import logging

from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import (
    AIORateLimiter,
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from processor_bot.bot import make_handler_callback
from processor_bot.config import load_config

log = logging.getLogger(__name__)


def main() -> None:
    cfg = load_config()
    logging.getLogger().setLevel(cfg.log_level)
    log.info(
        "starting processor_bot (log_level=%s, bus=%s, chat=%s, embed=%s)",
        cfg.log_level, cfg.bus_group_id,
        cfg.ollama_chat_model, cfg.ollama_embedding_model,
    )
    ollama_client = AsyncOpenAI(base_url=cfg.ollama_base_url, api_key="ollama")
    application = (
        Application.builder()
        .token(cfg.processor_bot_token)
        .rate_limiter(
            AIORateLimiter(overall_max_rate=1, overall_time_period=1.0)
        )
        .build()
    )

    async def _start(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return
        await message.reply_text("Nobody home")

    application.add_handler(CommandHandler("start", _start))
    callback = make_handler_callback(cfg=cfg, ollama_client=ollama_client)
    application.add_handler(
        MessageHandler(
            filters.Chat(cfg.bus_group_id)
            & filters.User(cfg.informer_bot_user_id)
            & filters.Document.FileExtension("json"),
            callback,
        )
    )
    log.info("processor_bot is running. Ctrl+C to stop.")
    application.run_polling()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
