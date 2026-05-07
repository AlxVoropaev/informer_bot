import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.remote_processor import (
    RemoteProcessorClient,
    RemoteProcessorError,
    RemoteProcessorTimeout,
    _RateLimiter,
)
from shared.protocol import (
    EmbedReply,
    ErrorReply,
    IsRelevantReply,
    SummarizeReply,
    encode_reply,
)


def _make_client_mock() -> SimpleNamespace:
    sent: list[SimpleNamespace] = []
    next_msg_id = [1000]

    async def send_message(chat_id: int, text: str) -> SimpleNamespace:
        next_msg_id[0] += 1
        msg = SimpleNamespace(id=next_msg_id[0], text=text, chat_id=chat_id)
        sent.append(msg)
        return msg

    handlers: list = []

    def add_event_handler(handler, event_filter) -> None:
        handlers.append((handler, event_filter))

    return SimpleNamespace(
        send_message=AsyncMock(side_effect=send_message),
        delete_messages=AsyncMock(return_value=None),
        add_event_handler=add_event_handler,
        _sent=sent,
        _handlers=handlers,
    )


def _make_event(text: str, msg_id: int = 9999) -> SimpleNamespace:
    return SimpleNamespace(
        message=SimpleNamespace(text=text, id=msg_id, document=None),
    )


async def _fire_reply(client_mock, text: str, msg_id: int = 9999) -> None:
    handler, _filter = client_mock._handlers[0]
    await handler(_make_event(text, msg_id))


@pytest.fixture
def remote() -> tuple[RemoteProcessorClient, SimpleNamespace]:
    client_mock = _make_client_mock()
    rp = RemoteProcessorClient(
        telethon_client=client_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
    )
    return rp, client_mock


async def test_summarize_round_trip(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, client_mock = remote
    await rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        sent = client_mock._sent[-1]
        req = json.loads(sent.text)
        reply = encode_reply(SummarizeReply(
            id=req["id"], text="brief", input_tokens=10, output_tokens=3,
        ))
        await _fire_reply(client_mock, reply)

    asyncio.create_task(replier())
    result = await rp.summarize("hello")

    assert result.text == "brief"
    assert result.input_tokens == 10
    assert result.output_tokens == 3
    # Wait briefly for fire-and-forget delete to run.
    await asyncio.sleep(0.01)
    client_mock.delete_messages.assert_awaited()


async def test_is_relevant_round_trip(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, client_mock = remote
    await rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        sent = client_mock._sent[-1]
        req = json.loads(sent.text)
        reply = encode_reply(IsRelevantReply(
            id=req["id"], relevant=True, input_tokens=20, output_tokens=1,
        ))
        await _fire_reply(client_mock, reply)

    asyncio.create_task(replier())
    result = await rp.is_relevant("post", "interest")

    assert result.relevant is True
    assert result.input_tokens == 20


async def test_summarize_timeout() -> None:
    client_mock = _make_client_mock()
    rp = RemoteProcessorClient(
        telethon_client=client_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.1,
        min_send_interval_seconds=0.0,
    )
    await rp.start()

    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("never replied")


async def test_error_reply_raises(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, client_mock = remote
    await rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        sent = client_mock._sent[-1]
        req = json.loads(sent.text)
        reply = encode_reply(ErrorReply(id=req["id"], error="model crashed"))
        await _fire_reply(client_mock, reply)

    asyncio.create_task(replier())
    with pytest.raises(RemoteProcessorError, match="model crashed"):
        await rp.summarize("anything")


async def test_rate_limiter_spaces_sends() -> None:
    limiter = _RateLimiter(min_interval_seconds=0.05)
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.05


async def test_unknown_id_is_ignored(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, client_mock = remote
    await rp.start()

    # Reply for an id we never sent — handler must not raise.
    stray = encode_reply(SummarizeReply(
        id="not-a-real-id", text="x", input_tokens=1, output_tokens=1,
    ))
    await _fire_reply(client_mock, stray)


async def test_embed_round_trip(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, client_mock = remote
    await rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        sent = client_mock._sent[-1]
        req = json.loads(sent.text)
        payload = encode_reply(EmbedReply(
            id=req["id"], vector=[0.1, 0.2, 0.3], tokens=5,
        ))

        async def download_media(file) -> None:
            file.write(payload.encode("utf-8"))

        # Embed reply arrives as a document with EMBED_REPLY_FILENAME.
        from shared.protocol import EMBED_REPLY_FILENAME
        from telethon.tl.types import DocumentAttributeFilename
        document = SimpleNamespace(
            attributes=[DocumentAttributeFilename(file_name=EMBED_REPLY_FILENAME)],
        )
        message = SimpleNamespace(
            text=None, id=8888, document=document,
            download_media=AsyncMock(side_effect=download_media),
        )
        handler, _filter = client_mock._handlers[0]
        await handler(SimpleNamespace(message=message))

    asyncio.create_task(replier())
    result = await rp.embed("text")

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.tokens == 5


async def test_summarize_timeout_marks_unhealthy_and_calls_callback() -> None:
    client_mock = _make_client_mock()
    rp = RemoteProcessorClient(
        telethon_client=client_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.1,
        min_send_interval_seconds=0.0,
    )
    await rp.start()

    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)
    assert rp.healthy is True

    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("never replied")

    assert rp.healthy is False
    assert states == [False]


async def test_health_loop_ping_success_keeps_healthy() -> None:
    # Auto-reply harness: every send triggers an immediate matching PingReply,
    # so the loop sees consecutive successful pings until we set stop_event.
    sent: list[SimpleNamespace] = []
    handlers: list = []
    next_msg_id = [1000]
    pending_replies: list[asyncio.Task] = []

    async def send_message(chat_id: int, text: str) -> SimpleNamespace:
        next_msg_id[0] += 1
        msg = SimpleNamespace(id=next_msg_id[0], text=text, chat_id=chat_id)
        sent.append(msg)
        from shared.protocol import PingReply
        req_id = json.loads(text)["id"]
        reply_text = encode_reply(PingReply(id=req_id))

        async def fire() -> None:
            await asyncio.sleep(0)
            handler, _ = handlers[0]
            await handler(_make_event(reply_text))

        pending_replies.append(asyncio.create_task(fire()))
        return msg

    client_mock = SimpleNamespace(
        send_message=AsyncMock(side_effect=send_message),
        delete_messages=AsyncMock(return_value=None),
        add_event_handler=lambda h, f: handlers.append((h, f)),
    )
    rp = RemoteProcessorClient(
        telethon_client=client_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
    )
    await rp.start()
    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)
    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.1)
        stop_event.set()

    asyncio.create_task(stopper())
    await rp.run_health_check_loop(interval_seconds=0.02, stop_event=stop_event)

    assert rp.healthy is True
    # No transitions: started healthy, stayed healthy.
    assert states == []
    # At least one ping was sent.
    assert len(sent) >= 1


async def test_health_loop_ping_failure_flips_state() -> None:
    client_mock = _make_client_mock()
    rp = RemoteProcessorClient(
        telethon_client=client_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.05,
        min_send_interval_seconds=0.0,
    )
    await rp.start()
    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)
    stop_event = asyncio.Event()

    async def stopper() -> None:
        # Allow one ping to time out, then exit the loop.
        await asyncio.sleep(0.2)
        stop_event.set()

    asyncio.create_task(stopper())
    await rp.run_health_check_loop(interval_seconds=0.02, stop_event=stop_event)

    assert rp.healthy is False
    assert states == [False]


async def test_state_change_callback_fires_only_on_transitions() -> None:
    client_mock = _make_client_mock()
    rp = RemoteProcessorClient(
        telethon_client=client_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
    )
    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)

    # Already healthy: setting healthy=True is a no-op.
    await rp._set_healthy(True)
    assert states == []

    # Transition to unhealthy.
    await rp._set_healthy(False)
    assert states == [False]

    # Repeating unhealthy is a no-op.
    await rp._set_healthy(False)
    assert states == [False]

    # Recover.
    await rp._set_healthy(True)
    assert states == [False, True]


async def test_health_loop_exits_when_stop_event_set() -> None:
    client_mock = _make_client_mock()
    rp = RemoteProcessorClient(
        telethon_client=client_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
    )
    stop_event = asyncio.Event()
    stop_event.set()

    # Returns immediately because stop_event is already set.
    await asyncio.wait_for(
        rp.run_health_check_loop(interval_seconds=10.0, stop_event=stop_event),
        timeout=1.0,
    )
