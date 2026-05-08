"""Smoke tests for `processor_bot.main`.

Patches `Application.builder()` and `run_polling` so we exercise the
wiring (config load, handler registration, polling kick-off) without
touching a real Telegram client.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROCESSOR_BOT_TOKEN", "999:tok")
    monkeypatch.setenv("BUS_GROUP_ID", "-100123")
    monkeypatch.setenv("INFORMER_BOT_USER_ID", "42")
    for key in (
        "OLLAMA_BASE_URL",
        "OLLAMA_CHAT_MODEL",
        "OLLAMA_EMBEDDING_MODEL",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)


def _builder_chain() -> tuple[MagicMock, MagicMock]:
    """Return (builder, application) so tests can introspect wiring."""
    application = MagicMock()
    application.add_handler = MagicMock()
    application.run_polling = MagicMock()
    builder = MagicMock()
    builder.token.return_value = builder
    builder.rate_limiter.return_value = builder
    builder.build.return_value = application
    return builder, application


def test_main_loads_config_and_starts_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)
    builder, application = _builder_chain()

    with patch(
        "processor_bot.main.Application.builder", return_value=builder
    ):
        from processor_bot.main import main
        main()

    builder.token.assert_called_once_with("999:tok")
    builder.build.assert_called_once()
    # Two handlers registered: /start command + bus message handler.
    assert application.add_handler.call_count == 2
    application.run_polling.assert_called_once()


async def test_start_handler_replies_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)
    builder, application = _builder_chain()

    with patch(
        "processor_bot.main.Application.builder", return_value=builder
    ):
        from processor_bot.main import main
        main()

    # The /start CommandHandler is registered first.
    start_handler = application.add_handler.call_args_list[0].args[0]
    callback = start_handler.callback

    reply_text = AsyncMock()
    update = SimpleNamespace(
        effective_message=SimpleNamespace(reply_text=reply_text)
    )
    await callback(update, SimpleNamespace())

    reply_text.assert_awaited_once_with("Nobody home")


async def test_start_handler_skips_if_no_effective_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)
    builder, application = _builder_chain()

    with patch(
        "processor_bot.main.Application.builder", return_value=builder
    ):
        from processor_bot.main import main
        main()

    start_handler = application.add_handler.call_args_list[0].args[0]
    callback = start_handler.callback

    update = SimpleNamespace(effective_message=None)
    # Must not raise AttributeError.
    await callback(update, SimpleNamespace())
