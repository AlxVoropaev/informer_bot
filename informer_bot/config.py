import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str
    owner_id: int
    session_path: str = "informer"
    db_path: str = "informer.db"
    refresh_interval_seconds: int = 600
    log_level: str = "INFO"


def load_config() -> Config:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY missing in .env")
    return Config(
        telegram_api_id=int(os.environ["TELEGRAM_API_ID"]),
        telegram_api_hash=os.environ["TELEGRAM_API_HASH"],
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        owner_id=int(os.environ["OWNER_ID"]),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
