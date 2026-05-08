"""Smoke tests for `processor_bot.bot.make_handler_callback`.

Mirror of `informer_bot.remote_processor._on_reply` but on the request
side: handler decodes a Telegram document into a Request, dispatches to
`handle_request`, and replies via `bot.send_document`.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from processor_bot.bot import make_handler_callback
from processor_bot.config import Config
from shared.protocol import (
    REPLY_FILENAME,
    PingReply,
    SummarizeRequest,
    encode_request,
)


@pytest.fixture
def cfg() -> Config:
    return Config(
        processor_bot_token="t",
        bus_group_id=-100123,
        informer_bot_user_id=42,
    )


def _make_update_with_document(
    payload: bytes,
    *,
    sender_id: int = 42,
    chat_id: int = -100123,
    file_id: str = "f1",
    message_id: int = 7,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """Build (update, context) where context.bot serves the document body."""
    document = SimpleNamespace(file_id=file_id)
    message = SimpleNamespace(
        chat_id=chat_id,
        message_id=message_id,
        document=document,
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=sender_id),
    )

    async def download_to_memory(*, out) -> None:
        out.write(payload)

    tg_file = SimpleNamespace(download_to_memory=download_to_memory)
    bot = SimpleNamespace(
        get_file=AsyncMock(return_value=tg_file),
        send_document=AsyncMock(),
    )
    context = SimpleNamespace(bot=bot)
    return update, context


async def test_valid_request_dispatches_and_sends_reply_document(
    cfg: Config,
) -> None:
    req = SummarizeRequest.new("hello")
    payload = encode_request(req).encode("utf-8")
    update, context = _make_update_with_document(payload)
    reply = PingReply(id=req.id)

    with patch(
        "processor_bot.bot.handle_request",
        new=AsyncMock(return_value=reply),
    ) as mock_handle:
        callback = make_handler_callback(cfg=cfg, ollama_client=AsyncMock())
        await callback(update, context)

    mock_handle.assert_awaited_once()
    # Verify the reply was sent as a document on the bus group.
    context.bot.send_document.assert_awaited_once()
    kwargs = context.bot.send_document.await_args.kwargs
    assert kwargs["chat_id"] == cfg.bus_group_id
    assert kwargs["document"].filename == REPLY_FILENAME
    # Caption announces the op so the informer side can route it.
    assert kwargs["caption"] == "op: summarize"


async def test_handle_request_exception_sends_error_reply(
    cfg: Config,
) -> None:
    req = SummarizeRequest.new("hello")
    payload = encode_request(req).encode("utf-8")
    update, context = _make_update_with_document(payload)

    with patch(
        "processor_bot.bot.handle_request",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        callback = make_handler_callback(cfg=cfg, ollama_client=AsyncMock())
        await callback(update, context)

    context.bot.send_document.assert_awaited_once()
    sent_doc = context.bot.send_document.await_args.kwargs["document"]
    body = sent_doc.input_file_content.decode("utf-8")
    parsed = json.loads(body)
    assert parsed["ok"] is False
    assert parsed["id"] == req.id
    assert "boom" in parsed["error"]


async def test_non_document_message_returns_silently(cfg: Config) -> None:
    message = SimpleNamespace(chat_id=-100123, message_id=1, document=None)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_document=AsyncMock()))

    callback = make_handler_callback(cfg=cfg, ollama_client=AsyncMock())
    await callback(update, context)

    context.bot.send_document.assert_not_awaited()


async def test_malformed_json_logs_and_returns_silently(cfg: Config) -> None:
    update, context = _make_update_with_document(b"not json {{{")

    callback = make_handler_callback(cfg=cfg, ollama_client=AsyncMock())
    await callback(update, context)

    # Bad payload: handler swallows the ProtocolError, never replies.
    context.bot.send_document.assert_not_awaited()


async def test_no_effective_message_returns_silently(cfg: Config) -> None:
    update = SimpleNamespace(
        effective_message=None,
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_document=AsyncMock()))

    callback = make_handler_callback(cfg=cfg, ollama_client=AsyncMock())
    await callback(update, context)

    context.bot.send_document.assert_not_awaited()


async def test_wrong_sender_is_dropped(cfg: Config) -> None:
    req = SummarizeRequest.new("hello")
    payload = encode_request(req).encode("utf-8")
    update, context = _make_update_with_document(payload, sender_id=999)

    with patch(
        "processor_bot.bot.handle_request", new=AsyncMock()
    ) as mock_handle:
        callback = make_handler_callback(cfg=cfg, ollama_client=AsyncMock())
        await callback(update, context)

    mock_handle.assert_not_awaited()
    context.bot.send_document.assert_not_awaited()
