import os
from dataclasses import dataclass

from dotenv import load_dotenv

from informer_bot.summarizer import LOCAL_EMBED_MODEL_DEFAULT


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
    embedding_provider: str = "auto"  # 'auto', 'openai', 'local', 'none'
    local_embedding_model: str = LOCAL_EMBED_MODEL_DEFAULT
    local_embedding_device: str = "cpu"  # 'cpu' or 'cuda' (needs fastembed-gpu)
    miniapp_url: str | None = None
    miniapp_url_file: str | None = None
    webapp_host: str = "0.0.0.0"
    webapp_port: int = 8080


def load_config() -> Config:
    load_dotenv("data/.env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY missing in .env")
    provider = os.environ.get("EMBEDDING_PROVIDER", "auto").lower()
    if provider not in {"auto", "openai", "local", "none"}:
        raise SystemExit(
            f"EMBEDDING_PROVIDER must be one of auto/openai/local/none, got {provider!r}"
        )
    device = os.environ.get("LOCAL_EMBEDDING_DEVICE", "cpu").lower()
    if device not in {"cpu", "cuda"}:
        raise SystemExit(
            f"LOCAL_EMBEDDING_DEVICE must be cpu or cuda, got {device!r}"
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
        local_embedding_model=os.environ.get(
            "LOCAL_EMBEDDING_MODEL", LOCAL_EMBED_MODEL_DEFAULT
        ),
        local_embedding_device=device,
        miniapp_url=os.environ.get("MINIAPP_URL") or None,
        miniapp_url_file=os.environ.get("MINIAPP_URL_FILE") or None,
        webapp_host=os.environ.get("WEBAPP_HOST", "0.0.0.0"),
        webapp_port=int(os.environ.get("WEBAPP_PORT", "8080")),
    )
