import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    processor_bot_token: str
    bus_group_id: int
    informer_bot_user_id: int
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_chat_model: str = "qwen3.5:4b"
    ollama_embedding_model: str = "qwen3-embedding:4b"
    log_level: str = "INFO"
    session_path: str = "data/processor"


def load_config() -> Config:
    load_dotenv("data/.env")
    if not os.environ.get("PROCESSOR_BOT_TOKEN"):
        raise SystemExit("PROCESSOR_BOT_TOKEN missing in .env")
    return Config(
        telegram_api_id=int(os.environ["TELEGRAM_API_ID"]),
        telegram_api_hash=os.environ["TELEGRAM_API_HASH"],
        processor_bot_token=os.environ["PROCESSOR_BOT_TOKEN"],
        bus_group_id=int(os.environ["BUS_GROUP_ID"]),
        informer_bot_user_id=int(os.environ["INFORMER_BOT_USER_ID"]),
        ollama_base_url=os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434/v1"
        ),
        ollama_chat_model=os.environ.get("OLLAMA_CHAT_MODEL", "qwen3.5:4b"),
        ollama_embedding_model=os.environ.get(
            "OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b"
        ),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        session_path=os.environ.get("SESSION_PATH", "data/processor"),
    )
