"""Tests for `informer_bot.config.load_config` validation and defaults.

`load_config` raises `SystemExit` for unknown EMBEDDING_PROVIDER /
LOCAL_EMBEDDING_DEVICE values, and falls back to documented defaults when
optional vars are absent. Uses `monkeypatch.setenv` / `monkeypatch.delenv`
to drive the loader without touching process state permanently.

`load_dotenv` doesn't overwrite values already set in the process
environment by default, so `monkeypatch.setenv` reliably wins over any
`data/.env` file the developer might have on disk.
"""
import pytest

from informer_bot.config import load_config
from informer_bot.summarizer import LOCAL_EMBED_MODEL_DEFAULT


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_API_ID", "111")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OWNER_ID", "999")


def _clear_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every optional var so we read the genuine defaults in load_config."""
    for key in (
        "EMBEDDING_PROVIDER",
        "LOCAL_EMBEDDING_DEVICE",
        "LOCAL_EMBEDDING_MODEL",
        "OPENAI_API_KEY",
        "DEDUP_THRESHOLD",
        "DEDUP_WINDOW_HOURS",
        "CATCH_UP_WINDOW_HOURS",
        "MINIAPP_URL",
        "MINIAPP_URL_FILE",
        "WEBAPP_HOST",
        "WEBAPP_PORT",
        "SESSION_PATH",
        "DB_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_invalid_embedding_provider_raises_systemexit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "invalid_value")

    with pytest.raises(SystemExit) as excinfo:
        load_config()

    assert "EMBEDDING_PROVIDER" in str(excinfo.value)


def test_invalid_local_embedding_device_raises_systemexit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("LOCAL_EMBEDDING_DEVICE", "invalid_value")

    with pytest.raises(SystemExit) as excinfo:
        load_config()

    assert "LOCAL_EMBEDDING_DEVICE" in str(excinfo.value)


def test_defaults_are_applied_when_optional_vars_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)

    cfg = load_config()

    assert cfg.embedding_provider == "auto"
    assert cfg.local_embedding_model == LOCAL_EMBED_MODEL_DEFAULT
    assert cfg.local_embedding_device == "cpu"
    assert cfg.dedup_threshold == 0.85
    assert cfg.dedup_window_hours == 48
    assert cfg.catch_up_window_hours == 48
    assert cfg.webapp_host == "0.0.0.0"
    assert cfg.webapp_port == 8085
    assert cfg.miniapp_url is None
    assert cfg.openai_api_key is None
    assert cfg.log_level == "INFO"
    # Required values were parsed correctly.
    assert cfg.telegram_api_id == 111
    assert cfg.telegram_api_hash == "deadbeef"
    assert cfg.telegram_bot_token == "123:abc"
    assert cfg.owner_id == 999


@pytest.mark.parametrize("provider", ["auto", "openai", "local", "none"])
def test_valid_embedding_providers_accepted(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("EMBEDDING_PROVIDER", provider)

    cfg = load_config()

    assert cfg.embedding_provider == provider


def test_embedding_provider_is_lowercased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "OpenAI")

    cfg = load_config()

    assert cfg.embedding_provider == "openai"
