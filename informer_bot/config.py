import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str
    owner_id: int
    openai_api_key: str | None = None
    session_path: str = "data/informer"
    db_path: str = "data/informer.db"
    log_level: str = "INFO"
    dedup_threshold: float = 0.85
    dedup_window_hours: int = 48


def load_config() -> Config:
    load_dotenv("data/.env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY missing in .env")
    return Config(
        telegram_api_id=int(os.environ["TELEGRAM_API_ID"]),
        telegram_api_hash=os.environ["TELEGRAM_API_HASH"],
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        owner_id=int(os.environ["OWNER_ID"]),
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        session_path=os.environ.get("SESSION_PATH", "data/informer"),
        db_path=os.environ.get("DB_PATH", "data/informer.db"),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        dedup_threshold=float(os.environ.get("DEDUP_THRESHOLD", "0.85")),
        dedup_window_hours=int(os.environ.get("DEDUP_WINDOW_HOURS", "48")),
    )
