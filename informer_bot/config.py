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
    catch_up_window_hours: int = 48
    embedding_provider: str = "auto"  # 'auto', 'openai', 'ollama', 'none'
    chat_provider: str = "anthropic"  # 'anthropic' or 'ollama'
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_chat_model: str = "qwen3.5:4b"
    ollama_embedding_model: str = "qwen3-embedding:4b"
    miniapp_url: str | None = None
    webapp_host: str = "0.0.0.0"
    webapp_port: int = 8085


def load_config() -> Config:
    load_dotenv("data/.env")
    chat_provider = os.environ.get("CHAT_PROVIDER", "anthropic").lower()
    if chat_provider not in {"anthropic", "ollama"}:
        raise SystemExit(
            f"CHAT_PROVIDER must be one of anthropic/ollama, got {chat_provider!r}"
        )
    if chat_provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY missing in .env")
    provider = os.environ.get("EMBEDDING_PROVIDER", "auto").lower()
    if provider not in {"auto", "openai", "ollama", "none"}:
        raise SystemExit(
            f"EMBEDDING_PROVIDER must be one of auto/openai/ollama/none, got {provider!r}"
        )
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
        catch_up_window_hours=int(os.environ.get("CATCH_UP_WINDOW_HOURS", "48")),
        embedding_provider=provider,
        chat_provider=chat_provider,
        ollama_base_url=os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434/v1"
        ),
        ollama_chat_model=os.environ.get("OLLAMA_CHAT_MODEL", "qwen3.5:4b"),
        ollama_embedding_model=os.environ.get(
            "OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b"
        ),
        miniapp_url=os.environ.get("MINIAPP_URL") or None,
        webapp_host=os.environ.get("WEBAPP_HOST", "0.0.0.0"),
        webapp_port=int(os.environ.get("WEBAPP_PORT", "8085")),
    )
