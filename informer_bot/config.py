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
    embedding_provider: str = "auto"  # 'auto', 'openai', 'ollama', 'remote', 'none'
    chat_provider: str = "anthropic"  # 'anthropic', 'ollama', or 'remote'
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_chat_model: str = "qwen3.5:4b"
    ollama_embedding_model: str = "qwen3-embedding:4b"
    bus_group_id: int | None = None
    processor_bot_user_id: int | None = None
    processor_timeout_seconds: float = 60.0
    health_check_interval_seconds: float = 60.0
    chat_provider_fallback: str = "anthropic"  # 'anthropic' or 'ollama'
    embedding_provider_fallback: str = "openai"  # 'openai', 'ollama', or 'none'
    miniapp_url: str | None = None
    miniapp_tg_deeplink: str | None = None
    # Loopback by default; compose.yaml overrides to 0.0.0.0 so Caddy can reach it.
    webapp_host: str = "127.0.0.1"
    webapp_port: int = 8085


def load_config() -> Config:
    load_dotenv("data/.env")
    chat_provider = os.environ.get("CHAT_PROVIDER", "anthropic").lower()
    if chat_provider not in {"anthropic", "ollama", "remote"}:
        raise SystemExit(
            f"CHAT_PROVIDER must be one of anthropic/ollama/remote, got {chat_provider!r}"
        )
    if chat_provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY missing in .env")
    provider = os.environ.get("EMBEDDING_PROVIDER", "auto").lower()
    if provider not in {"auto", "openai", "ollama", "remote", "none"}:
        raise SystemExit(
            f"EMBEDDING_PROVIDER must be one of auto/openai/ollama/remote/none, got {provider!r}"
        )
    bus_group_id_raw = os.environ.get("BUS_GROUP_ID")
    processor_user_id_raw = os.environ.get("PROCESSOR_BOT_USER_ID")
    if chat_provider == "remote" or provider == "remote":
        if not bus_group_id_raw or not processor_user_id_raw:
            raise SystemExit(
                "CHAT_PROVIDER/EMBEDDING_PROVIDER=remote requires "
                "BUS_GROUP_ID and PROCESSOR_BOT_USER_ID in .env"
            )
    health_interval = float(os.environ.get("HEALTH_CHECK_INTERVAL_SECONDS", "60.0"))
    if health_interval <= 0:
        raise SystemExit(
            f"HEALTH_CHECK_INTERVAL_SECONDS must be > 0, got {health_interval}"
        )
    chat_fallback = os.environ.get("CHAT_PROVIDER_FALLBACK", "anthropic").lower()
    if chat_fallback not in {"anthropic", "ollama"}:
        raise SystemExit(
            f"CHAT_PROVIDER_FALLBACK must be one of anthropic/ollama, got {chat_fallback!r}"
        )
    embed_fallback = os.environ.get("EMBEDDING_PROVIDER_FALLBACK", "openai").lower()
    if embed_fallback not in {"openai", "ollama", "none"}:
        raise SystemExit(
            f"EMBEDDING_PROVIDER_FALLBACK must be one of openai/ollama/none, "
            f"got {embed_fallback!r}"
        )
    if (
        chat_provider == "remote"
        and chat_fallback == "anthropic"
        and not os.environ.get("ANTHROPIC_API_KEY")
    ):
        raise SystemExit(
            "CHAT_PROVIDER=remote with CHAT_PROVIDER_FALLBACK=anthropic "
            "requires ANTHROPIC_API_KEY in .env"
        )
    if (
        provider == "remote"
        and embed_fallback == "openai"
        and not os.environ.get("OPENAI_API_KEY")
    ):
        raise SystemExit(
            "EMBEDDING_PROVIDER=remote with EMBEDDING_PROVIDER_FALLBACK=openai "
            "requires OPENAI_API_KEY in .env"
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
        bus_group_id=int(bus_group_id_raw) if bus_group_id_raw else None,
        processor_bot_user_id=(
            int(processor_user_id_raw) if processor_user_id_raw else None
        ),
        processor_timeout_seconds=float(
            os.environ.get("PROCESSOR_TIMEOUT_SECONDS", "60.0")
        ),
        health_check_interval_seconds=health_interval,
        chat_provider_fallback=chat_fallback,
        embedding_provider_fallback=embed_fallback,
        miniapp_url=os.environ.get("MINIAPP_URL") or None,
        miniapp_tg_deeplink=os.environ.get("MINIAPP_TG_DEEPLINK") or None,
        webapp_host=os.environ.get("WEBAPP_HOST", "127.0.0.1"),
        webapp_port=int(os.environ.get("WEBAPP_PORT", "8085")),
    )
