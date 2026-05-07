import asyncio
import logging

from openai import AsyncOpenAI
from telethon import TelegramClient

from processor_bot.bot import RateLimiter, register_handler
from processor_bot.config import load_config

log = logging.getLogger(__name__)


async def main() -> None:
    cfg = load_config()
    logging.getLogger().setLevel(cfg.log_level)
    log.info(
        "starting processor_bot (log_level=%s, bus=%s, chat=%s, embed=%s)",
        cfg.log_level, cfg.bus_group_id,
        cfg.ollama_chat_model, cfg.ollama_embedding_model,
    )
    ollama_client = AsyncOpenAI(base_url=cfg.ollama_base_url, api_key="ollama")
    tg = TelegramClient(cfg.session_path, cfg.telegram_api_id, cfg.telegram_api_hash)
    await tg.start(bot_token=cfg.processor_bot_token)
    limiter = RateLimiter(min_interval=1.0)
    register_handler(tg, cfg=cfg, ollama_client=ollama_client, limiter=limiter)
    log.info("processor_bot is running. Ctrl+C to stop.")
    await tg.run_until_disconnected()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
