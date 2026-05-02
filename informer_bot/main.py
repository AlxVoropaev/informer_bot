import asyncio
import logging

from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler
from telethon import TelegramClient

from informer_bot.album import AlbumBuffer
from informer_bot.bot import (
    cmd_admin_list,
    cmd_list,
    cmd_start,
    on_blacklist,
    on_toggle,
)
from informer_bot.client import fetch_subscribed_channels, register_new_post_handler
from informer_bot.config import load_config
from informer_bot.db import Database
from informer_bot.pipeline import handle_new_post, refresh_channels
from informer_bot.summarizer import summarize

log = logging.getLogger(__name__)


async def main() -> None:
    cfg = load_config()
    logging.getLogger().setLevel(cfg.log_level)
    log.info("starting informer_bot (log_level=%s, db=%s)", cfg.log_level, cfg.db_path)
    db = Database(cfg.db_path)

    tg = TelegramClient(cfg.session_path, cfg.telegram_api_id, cfg.telegram_api_hash)
    await tg.connect()
    if not await tg.is_user_authorized():
        raise SystemExit("No Telethon session. Run: uv run python login.py")
    log.info("telethon authorized")

    app = ApplicationBuilder().token(cfg.telegram_bot_token).build()
    app.bot_data["db"] = db
    app.bot_data["owner_id"] = cfg.owner_id
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("admin_list", cmd_admin_list))
    app.add_handler(CallbackQueryHandler(on_toggle, pattern=r"^toggle:"))
    app.add_handler(CallbackQueryHandler(on_blacklist, pattern=r"^bl:"))

    async def send_dm(user_id: int, text: str) -> None:
        try:
            await app.bot.send_message(chat_id=user_id, text=text)
            log.debug("DM sent to %s (%d chars)", user_id, len(text))
        except Exception:
            log.exception("send_dm to %s failed", user_id)

    async def on_post(channel_id: int, message_id: int, text: str, link: str) -> None:
        await handle_new_post(
            channel_id=channel_id, message_id=message_id, text=text, link=link,
            db=db, summarize_fn=summarize, send_dm=send_dm,
        )

    buffer = AlbumBuffer(on_flush=on_post, delay=1.5)
    register_new_post_handler(tg, buffer)

    async def fetch() -> list[tuple[int, str]]:
        return await fetch_subscribed_channels(tg)

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    async def refresh_loop() -> None:
        while True:
            await asyncio.sleep(cfg.refresh_interval_seconds)
            try:
                await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)
            except Exception:
                log.exception("refresh failed")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    refresh_task = asyncio.create_task(refresh_loop())

    log.info("informer_bot is running. Ctrl+C to stop.")
    try:
        await tg.run_until_disconnected()
    finally:
        refresh_task.cancel()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await tg.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
