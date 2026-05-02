import asyncio
import contextlib
import logging
import signal

from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler
from telethon import TelegramClient

from informer_bot.album import AlbumBuffer
from informer_bot.bot import (
    cmd_blacklist,
    cmd_filter,
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
    on_language,
    on_toggle,
)
from informer_bot.client import fetch_subscribed_channels, register_new_post_handler
from informer_bot.config import load_config
from informer_bot.db import Database
from informer_bot.pipeline import handle_new_post, refresh_channels
from informer_bot.summarizer import is_relevant, summarize

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
    app.add_handler(CommandHandler("filter", cmd_filter))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CallbackQueryHandler(on_toggle, pattern=r"^toggle:"))
    app.add_handler(CallbackQueryHandler(on_done, pattern=r"^done$"))
    app.add_handler(CallbackQueryHandler(on_blacklist, pattern=r"^bl:"))
    app.add_handler(CallbackQueryHandler(on_blacklist_done, pattern=r"^bl_done$"))
    app.add_handler(CallbackQueryHandler(on_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(on_deny, pattern=r"^deny:"))
    app.add_handler(CallbackQueryHandler(on_language, pattern=r"^lang:"))

    async def send_dm(user_id: int, text: str, photo: bytes | None = None) -> None:
        try:
            if photo is not None:
                await app.bot.send_photo(
                    chat_id=user_id, photo=photo, caption=text, parse_mode="HTML"
                )
                log.debug("DM (photo) sent to %s (%d cap chars)", user_id, len(text))
            else:
                await app.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML"
                )
                log.debug("DM sent to %s (%d chars)", user_id, len(text))
        except Exception:
            log.exception("send_dm to %s failed", user_id)

    async def on_post(
        channel_id: int, message_id: int, text: str, link: str, photo: bytes | None,
    ) -> None:
        await handle_new_post(
            channel_id=channel_id, message_id=message_id, text=text, link=link,
            db=db, summarize_fn=summarize, is_relevant_fn=is_relevant, send_dm=send_dm,
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
