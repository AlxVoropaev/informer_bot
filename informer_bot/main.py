import asyncio
import contextlib
import functools
import logging
import signal
import time
from urllib.parse import quote

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
)
from telethon import TelegramClient

from informer_bot.album import AlbumBuffer
from informer_bot.bot import (
    BotState,
    build_dm_keyboard,
    cmd_app,
    cmd_blacklist,
    cmd_help,
    cmd_start,
    cmd_update,
    cmd_usage,
    on_approve,
    on_blacklist,
    on_blacklist_done,
    on_blacklist_page,
    on_deny,
    on_noop,
    on_save,
)
from informer_bot.client import (
    catch_up,
    fetch_subscribed_channels,
    register_new_post_handler,
)
from informer_bot.config import Config, load_config
from informer_bot.db import Database
from informer_bot.i18n import t
from informer_bot.pipeline import (
    AnnounceNewChannelFn,
    EditDmFn,
    EmbedFn,
    FetchChannelsFn,
    SendDmFn,
    handle_new_post,
)
from informer_bot.summarizer import (
    EMBED_DIMENSIONS,
    EMBED_MODEL,
    LOCAL_EMBED_DIMENSIONS,
    LocalEmbedder,
    embed_summary,
    is_relevant,
    summarize,
)
from informer_bot.webapp import start_server as start_webapp_server

log = logging.getLogger(__name__)


def setup_embedder(
    cfg: Config, db: Database
) -> tuple[EmbedFn | None, str | None]:
    """Pick an embedding provider, return (embed_fn, embedding_id).

    embed_fn is None when dedup is disabled. embedding_id is a stable string
    used to detect provider/model switches across restarts.
    """
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
        local = LocalEmbedder(
            model_name=cfg.local_embedding_model,
            device=cfg.local_embedding_device,
        )
        embed_fn = local.embed
        embedding_id = f"local:{cfg.local_embedding_model}:{LOCAL_EMBED_DIMENSIONS}"
        log.info(
            "embedding provider: local (%s on %s, ~%d dims)",
            cfg.local_embedding_model, cfg.local_embedding_device, LOCAL_EMBED_DIMENSIONS,
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

    return embed_fn, embedding_id


def _make_send_dm(app: Application) -> SendDmFn:
    async def send_dm(
        user_id: int,
        text: str,
        photo: bytes | None = None,
        save_button: str | None = None,
    ) -> int | None:
        keyboard = build_dm_keyboard([], save_button)
        try:
            if photo is not None:
                msg = await app.bot.send_photo(
                    chat_id=user_id, photo=photo, caption=text,
                    parse_mode="HTML", reply_markup=keyboard,
                )
                log.info(
                    "outgoing: DM (photo) user=%s msg=%s cap_chars=%d",
                    user_id, msg.message_id, len(text),
                )
            else:
                msg = await app.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML",
                    reply_markup=keyboard,
                )
                log.info(
                    "outgoing: DM user=%s msg=%s chars=%d",
                    user_id, msg.message_id, len(text),
                )
            return msg.message_id
        except Exception:
            log.exception("send_dm to %s failed", user_id)
            return None

    return send_dm


def _make_edit_dm(app: Application) -> EditDmFn:
    async def edit_dm(
        user_id: int,
        bot_message_id: int,
        dup_links: list[tuple[str, str]],
        save_button: str | None = None,
    ) -> None:
        keyboard = build_dm_keyboard(dup_links, save_button)
        try:
            await app.bot.edit_message_reply_markup(
                chat_id=user_id, message_id=bot_message_id, reply_markup=keyboard,
            )
            log.info(
                "outgoing: DM buttons updated user=%s msg=%s links=%d save=%s",
                user_id, bot_message_id, len(dup_links), save_button is not None,
            )
        except Exception:
            log.exception(
                "edit_dm failed for user=%s msg=%s", user_id, bot_message_id
            )

    return edit_dm


async def sweep_due_deletions(app: Application, db: Database) -> None:
    """Background task: every 60s, delete DM messages whose timer has expired."""
    while True:
        try:
            now = int(time.time())
            due = db.list_due_deletions(now=now)
            for user_id, channel_id, message_id, bot_msg_id, _is_photo in due:
                try:
                    await app.bot.delete_message(
                        chat_id=user_id, message_id=bot_msg_id,
                    )
                    log.info(
                        "auto-delete: removed user=%s msg=%s", user_id, bot_msg_id,
                    )
                except Exception as exc:
                    log.warning(
                        "auto-delete: telegram delete failed user=%s msg=%s: %s",
                        user_id, bot_msg_id, exc,
                    )
                db.delete_delivered_row(
                    user_id=user_id, channel_id=channel_id, message_id=message_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("auto-delete sweeper iteration failed")
        await asyncio.sleep(60)


def _make_announce_new_channel(
    app: Application, db: Database, miniapp_url: str | None
) -> AnnounceNewChannelFn:
    async def announce_new_channel(
        user_id: int, channel_id: int, channel_title: str
    ) -> None:
        lang = db.get_language(user_id)
        keyboard = None
        if miniapp_url:
            sep = "&" if "?" in miniapp_url else "?"
            url = f"{miniapp_url}{sep}channel={quote(str(channel_id))}"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
                text=t(lang, "channel_new_open_button"),
                web_app=WebAppInfo(url=url),
            )]])
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=t(lang, "channel_new", title=channel_title),
                reply_markup=keyboard,
            )
            log.info(
                "outgoing: new-channel announce user=%s channel=%s",
                user_id, channel_id,
            )
        except Exception:
            log.exception(
                "announce_new_channel to user=%s channel=%s failed",
                user_id, channel_id,
            )

    return announce_new_channel


async def main() -> None:
    cfg = load_config()
    logging.getLogger().setLevel(cfg.log_level)
    log.info("starting informer_bot (log_level=%s, db=%s)", cfg.log_level, cfg.db_path)
    db = Database(cfg.db_path)
    db.set_user_status(user_id=cfg.owner_id, status="approved")

    miniapp_url = cfg.miniapp_url

    tg = TelegramClient(cfg.session_path, cfg.telegram_api_id, cfg.telegram_api_hash)
    await tg.connect()
    if not await tg.is_user_authorized():
        raise SystemExit("No Telethon session. Run: uv run python login.py")
    log.info("telethon authorized")

    app = ApplicationBuilder().token(cfg.telegram_bot_token).build()
    for handler in (
        CommandHandler("start", cmd_start),
        CommandHandler("help", cmd_help),
        CommandHandler("app", cmd_app),
        CommandHandler("blacklist", cmd_blacklist),
        CommandHandler("usage", cmd_usage),
        CommandHandler("update", cmd_update),
        CallbackQueryHandler(on_blacklist, pattern=r"^bl:"),
        CallbackQueryHandler(on_blacklist_done, pattern=r"^bl_done$"),
        CallbackQueryHandler(on_blacklist_page, pattern=r"^blpage:"),
        CallbackQueryHandler(on_noop, pattern=r"^noop$"),
        CallbackQueryHandler(on_approve, pattern=r"^approve:"),
        CallbackQueryHandler(on_deny, pattern=r"^deny:"),
        CallbackQueryHandler(on_save, pattern=r"^save$"),
    ):
        app.add_handler(handler)

    embed_fn, _embedding_id = setup_embedder(cfg, db)
    send_dm = _make_send_dm(app)
    edit_dm: EditDmFn | None = _make_edit_dm(app) if embed_fn is not None else None
    announce_new_channel = _make_announce_new_channel(app, db, miniapp_url)

    async def on_post(
        channel_id: int, message_id: int, text: str, link: str, photo: bytes | None,
    ) -> None:
        await handle_new_post(
            channel_id=channel_id, message_id=message_id, text=text, link=link,
            db=db, summarize_fn=summarize, is_relevant_fn=is_relevant, send_dm=send_dm,
            embed_fn=embed_fn, edit_dm=edit_dm,
            dedup_threshold=cfg.dedup_threshold,
            dedup_window_seconds=cfg.dedup_window_hours * 3600,
            photo=photo,
        )

    buffer = AlbumBuffer(on_flush=on_post, delay=1.5)
    register_new_post_handler(tg, buffer)

    async def fetch() -> list[tuple[int, str, str, str | None]]:
        return await fetch_subscribed_channels(tg)

    fetch_channels: FetchChannelsFn = fetch
    app.bot_data["state"] = BotState(
        db=db,
        owner_id=cfg.owner_id,
        miniapp_url=miniapp_url,
        fetch_channels=fetch_channels,
        send_dm=send_dm,
        announce_new_channel=announce_new_channel,
    )

    await app.initialize()
    await app.start()
    assert app.updater is not None
    await app.updater.start_polling()

    webapp_runner = None
    if miniapp_url:
        webapp_runner = await start_webapp_server(
            db=db, bot_token=cfg.telegram_bot_token, owner_id=cfg.owner_id,
            host=cfg.webapp_host, port=cfg.webapp_port,
        )
        try:
            await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text=t(db.get_language(cfg.owner_id), "miniapp_menu_label"),
                web_app=WebAppInfo(url=miniapp_url),
            ))
            log.info("set chat menu button -> %s", miniapp_url)
        except Exception:
            log.exception("failed to set chat menu button")

    await catch_up(
        tg, db, buffer, max_age_seconds=cfg.catch_up_window_hours * 3600,
    )

    for user_id in db.list_user_ids():
        try:
            chat = await app.bot.get_chat(chat_id=user_id)
        except Exception:
            log.debug("name refresh failed for user=%s", user_id)
            continue
        db.update_user_name(
            user_id=user_id, username=chat.username, first_name=chat.first_name
        )
        # Throttle to ~20 RPS — well under Telegram's flood-wait threshold.
        await asyncio.sleep(0.05)

    if embed_fn is None:
        await send_dm(
            cfg.owner_id,
            t(db.get_language(cfg.owner_id), "dedup_disabled_notice"),
        )

    await send_dm(cfg.owner_id, t(db.get_language(cfg.owner_id), "startup_notice"))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    log.info("informer_bot is running. Ctrl+C to stop.")
    disconnect_task = asyncio.create_task(tg.run_until_disconnected())
    stop_task = asyncio.create_task(stop_event.wait())
    sweeper_task = asyncio.create_task(sweep_due_deletions(app, db))
    try:
        await asyncio.wait(
            {disconnect_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        await graceful_shutdown(
            app=app, tg=tg, db=db, cfg=cfg, send_dm=send_dm,
            tasks=(disconnect_task, stop_task, sweeper_task),
            webapp_runner=webapp_runner,
        )


async def graceful_shutdown(
    *,
    app: Application,
    tg: TelegramClient,
    db: Database,
    cfg: Config,
    send_dm: SendDmFn,
    tasks: tuple[asyncio.Task, ...],
    webapp_runner,
) -> None:
    log.info("shutting down")
    with contextlib.suppress(Exception):
        await send_dm(
            cfg.owner_id, t(db.get_language(cfg.owner_id), "shutdown_notice")
        )
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert app.updater is not None
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    if webapp_runner is not None:
        await webapp_runner.cleanup()
    await tg.disconnect()
    log.info("shutdown complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
