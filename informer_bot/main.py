import asyncio
import contextlib
import functools
import logging
import signal
import time

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from telethon import TelegramClient

from informer_bot.album import AlbumBuffer
from informer_bot.bot import (
    cmd_blacklist,
    cmd_help,
    cmd_language,
    cmd_list,
    cmd_start,
    cmd_update,
    cmd_usage,
    on_approve,
    on_blacklist,
    on_blacklist_done,
    on_deny,
    on_done,
    on_filter_delete,
    on_filter_edit,
    on_filter_text,
    on_language,
    on_toggle,
)
from informer_bot.client import fetch_subscribed_channels, register_new_post_handler
from informer_bot.config import load_config
from informer_bot.db import Database
from informer_bot.i18n import t
from informer_bot.pipeline import EditDmFn, EmbedFn, handle_new_post, refresh_channels
from informer_bot.summarizer import (
    EMBED_DIMENSIONS,
    EMBED_MODEL,
    LOCAL_EMBED_DIMENSIONS,
    LocalEmbedder,
    embed_summary,
    is_relevant,
    summarize,
)

log = logging.getLogger(__name__)


async def main() -> None:
    cfg = load_config()
    logging.getLogger().setLevel(cfg.log_level)
    log.info("starting informer_bot (log_level=%s, db=%s)", cfg.log_level, cfg.db_path)
    db = Database(cfg.db_path)
    db.set_user_status(user_id=cfg.owner_id, status="approved")

    tg = TelegramClient(cfg.session_path, cfg.telegram_api_id, cfg.telegram_api_hash)
    await tg.connect()
    if not await tg.is_user_authorized():
        raise SystemExit("No Telethon session. Run: uv run python login.py")
    log.info("telethon authorized")

    app = ApplicationBuilder().token(cfg.telegram_bot_token).build()
    app.bot_data["db"] = db
    app.bot_data["owner_id"] = cfg.owner_id
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("blacklist", cmd_blacklist))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CallbackQueryHandler(on_toggle, pattern=r"^toggle:"))
    app.add_handler(CallbackQueryHandler(on_done, pattern=r"^done$"))
    app.add_handler(CallbackQueryHandler(on_filter_edit, pattern=r"^fedit:"))
    app.add_handler(CallbackQueryHandler(on_filter_delete, pattern=r"^fdel:"))
    app.add_handler(CallbackQueryHandler(on_blacklist, pattern=r"^bl:"))
    app.add_handler(CallbackQueryHandler(on_blacklist_done, pattern=r"^bl_done$"))
    app.add_handler(CallbackQueryHandler(on_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(on_deny, pattern=r"^deny:"))
    app.add_handler(CallbackQueryHandler(on_language, pattern=r"^lang:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_filter_text))

    embed_fn: EmbedFn | None = None
    embedding_id: str | None = None
    provider = cfg.embedding_provider
    if provider == "auto":
        provider = "openai" if cfg.openai_api_key else "none"

    if provider == "openai":
        if not cfg.openai_api_key:
            raise SystemExit("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is missing")
        openai_client = AsyncOpenAI(api_key=cfg.openai_api_key)
        embed_fn = functools.partial(embed_summary, client=openai_client)
        embedding_id = f"openai:{EMBED_MODEL}:{EMBED_DIMENSIONS}"
        log.info("embedding provider: openai (%s, %d dims)", EMBED_MODEL, EMBED_DIMENSIONS)
    elif provider == "local":
        local = LocalEmbedder(model_name=cfg.local_embedding_model)
        embed_fn = local.embed
        embedding_id = f"local:{cfg.local_embedding_model}:{LOCAL_EMBED_DIMENSIONS}"
        log.info(
            "embedding provider: local (%s, ~%d dims)",
            cfg.local_embedding_model, LOCAL_EMBED_DIMENSIONS,
        )
    else:
        log.warning("embedding provider: none — deduplication disabled")

    if embed_fn is not None and embedding_id is not None:
        prev = db.get_meta("embedding_id")
        if prev is not None and prev != embedding_id:
            log.warning(
                "embedding model changed (%s -> %s); dropping dedup index",
                prev, embedding_id,
            )
            db.purge_dedup_all()
        db.set_meta("embedding_id", embedding_id)
        db.purge_dedup_older_than(
            cutoff=int(time.time()) - cfg.dedup_window_hours * 3600
        )

    async def send_dm(
        user_id: int, text: str, photo: bytes | None = None
    ) -> int | None:
        try:
            if photo is not None:
                msg = await app.bot.send_photo(
                    chat_id=user_id, photo=photo, caption=text, parse_mode="HTML"
                )
                log.info(
                    "outgoing: DM (photo) user=%s msg=%s cap_chars=%d",
                    user_id, msg.message_id, len(text),
                )
            else:
                msg = await app.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML"
                )
                log.info(
                    "outgoing: DM user=%s msg=%s chars=%d",
                    user_id, msg.message_id, len(text),
                )
            return msg.message_id
        except Exception:
            log.exception("send_dm to %s failed", user_id)
            return None

    async def edit_dm(
        user_id: int, bot_message_id: int, dup_links: list[tuple[str, str]]
    ) -> None:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text=title, url=link)] for title, link in dup_links]
        )
        try:
            await app.bot.edit_message_reply_markup(
                chat_id=user_id, message_id=bot_message_id, reply_markup=keyboard,
            )
            log.info(
                "outgoing: DM buttons updated user=%s msg=%s links=%d",
                user_id, bot_message_id, len(dup_links),
            )
        except Exception:
            log.exception(
                "edit_dm failed for user=%s msg=%s", user_id, bot_message_id
            )

    edit_dm_fn: EditDmFn | None = edit_dm if embed_fn is not None else None

    async def on_post(
        channel_id: int, message_id: int, text: str, link: str, photo: bytes | None,
    ) -> None:
        await handle_new_post(
            channel_id=channel_id, message_id=message_id, text=text, link=link,
            db=db, summarize_fn=summarize, is_relevant_fn=is_relevant, send_dm=send_dm,
            embed_fn=embed_fn, edit_dm=edit_dm_fn,
            dedup_threshold=cfg.dedup_threshold,
            dedup_window_seconds=cfg.dedup_window_hours * 3600,
            photo=photo,
        )

    buffer = AlbumBuffer(on_flush=on_post, delay=1.5)
    register_new_post_handler(tg, buffer)

    async def fetch() -> list[tuple[int, str]]:
        return await fetch_subscribed_channels(tg)

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    app.bot_data["fetch_channels"] = fetch
    app.bot_data["send_dm"] = send_dm

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    for user_id in db.list_user_ids():
        try:
            chat = await app.bot.get_chat(chat_id=user_id)
        except Exception:
            log.debug("name refresh failed for user=%s", user_id)
            continue
        db.update_user_name(
            user_id=user_id, username=chat.username, first_name=chat.first_name
        )

    if embed_fn is None:
        await send_dm(
            cfg.owner_id,
            t(db.get_language(cfg.owner_id), "dedup_disabled_notice"),
        )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    log.info("informer_bot is running. Ctrl+C to stop.")
    disconnect_task = asyncio.create_task(tg.run_until_disconnected())
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        await asyncio.wait(
            {disconnect_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        log.info("shutting down")
        for task in (disconnect_task, stop_task):
            task.cancel()
        for task in (disconnect_task, stop_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await tg.disconnect()
        log.info("shutdown complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
