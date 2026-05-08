"""Tests for `processor_bot.config.load_config` validation and defaults.

Mirrors `tests/test_config.py`: drive the loader with `monkeypatch` so
`data/.env` on disk can't influence the result.
"""
import pytest

from processor_bot.config import load_config


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROCESSOR_BOT_TOKEN", "999:tok")
    monkeypatch.setenv("BUS_GROUP_ID", "-100123")
    monkeypatch.setenv("INFORMER_BOT_USER_ID", "42")


def _clear_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OLLAMA_BASE_URL",
        "OLLAMA_CHAT_MODEL",
        "OLLAMA_EMBEDDING_MODEL",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_required_env_vars_produce_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)

    cfg = load_config()

    assert cfg.processor_bot_token == "999:tok"
    assert cfg.bus_group_id == -100123
    assert cfg.informer_bot_user_id == 42


def test_missing_processor_bot_token_raises_systemexit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.delenv("PROCESSOR_BOT_TOKEN", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        load_config()

    assert "PROCESSOR_BOT_TOKEN" in str(excinfo.value)


def test_defaults_are_applied_when_optional_vars_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)

    cfg = load_config()

    assert cfg.ollama_base_url == "http://localhost:11434/v1"
    assert cfg.ollama_chat_model == "qwen3.5:4b"
    assert cfg.ollama_embedding_model == "qwen3-embedding:4b"
    assert cfg.log_level == "INFO"


def test_optional_overrides_are_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    _clear_optional(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu:11434/v1")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen-x")
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "embed-x")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    cfg = load_config()

    assert cfg.ollama_base_url == "http://gpu:11434/v1"
    assert cfg.ollama_chat_model == "qwen-x"
    assert cfg.ollama_embedding_model == "embed-x"
    # Loader uppercases LOG_LEVEL to match informer_bot semantics.
    assert cfg.log_level == "DEBUG"
