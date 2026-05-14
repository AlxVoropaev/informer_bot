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


def _make_app_mock() -> SimpleNamespace:
    sent: list[SimpleNamespace] = []
    files: dict[str, bytes] = {}
    next_msg_id = [1000]
    next_file_id = [0]

    async def send_document(*, chat_id, document, **_kwargs):
        next_msg_id[0] += 1
        next_file_id[0] += 1
        file_id = f"f{next_file_id[0]}"
        # InputFile exposes input_file_content with the bytes payload.
        content = getattr(document, "input_file_content", None)
        if content is None:
            stream = getattr(document, "stream", None) or document
            stream.seek(0)
            content = stream.read()
        files[file_id] = content
        msg = SimpleNamespace(
            message_id=next_msg_id[0],
            chat_id=chat_id,
            document=SimpleNamespace(file_id=file_id),
        )
        sent.append(msg)
        return msg

    async def get_file(file_id: str):
        content = files[file_id]

        async def download_to_memory(*, out) -> None:
            out.write(content)

        return SimpleNamespace(download_to_memory=download_to_memory)

    bot = SimpleNamespace(
        send_document=AsyncMock(side_effect=send_document),
        delete_messages=AsyncMock(return_value=None),
        get_file=AsyncMock(side_effect=get_file),
    )

    handlers: list = []

    def add_handler(handler) -> None:
        handlers.append(handler)

    return SimpleNamespace(
        bot=bot,
        add_handler=add_handler,
        _sent=sent,
        _handlers=handlers,
        _files=files,
        _next_msg_id=next_msg_id,
        _next_file_id=next_file_id,
    )


async def _request_payload(app_mock: SimpleNamespace) -> str:
    sent_msg = app_mock._sent[-1]
    file_id = sent_msg.document.file_id
    return app_mock._files[file_id].decode("utf-8")


async def _fire_reply(
    rp: RemoteProcessorClient,
    app_mock: SimpleNamespace,
    payload: str,
    msg_id: int = 9999,
) -> None:
    app_mock._next_file_id[0] += 1
    file_id = f"reply_{app_mock._next_file_id[0]}"
    app_mock._files[file_id] = payload.encode("utf-8")
    document = SimpleNamespace(file_id=file_id)
    message = SimpleNamespace(message_id=msg_id, document=document)
    update = SimpleNamespace(effective_message=message)
    context = SimpleNamespace(bot=app_mock.bot)
    await rp._on_reply(update, context)


@pytest.fixture
def remote() -> tuple[RemoteProcessorClient, SimpleNamespace]:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
    )
    return rp, app_mock


async def test_summarize_round_trip(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, app_mock = remote
    rp.start()

    assert rp.last_chat_model is None

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        reply = encode_reply(SummarizeReply(
            id=req["id"], text="brief", input_tokens=10, output_tokens=3,
            model="qwen2.5:7b",
        ))
        await _fire_reply(rp, app_mock, reply)

    asyncio.create_task(replier())
    result = await rp.summarize("hello")

    assert result.text == "brief"
    assert result.input_tokens == 10
    assert result.output_tokens == 3
    assert rp.last_chat_model == "qwen2.5:7b"
    # Wait briefly for fire-and-forget delete to run.
    await asyncio.sleep(0.01)
    app_mock.bot.delete_messages.assert_awaited()


async def test_is_relevant_round_trip(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, app_mock = remote
    rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        reply = encode_reply(IsRelevantReply(
            id=req["id"], relevant=True, input_tokens=20, output_tokens=1,
        ))
        await _fire_reply(rp, app_mock, reply)

    asyncio.create_task(replier())
    result = await rp.is_relevant("post", "interest")

    assert result.relevant is True
    assert result.input_tokens == 20


async def test_summarize_timeout() -> None:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.1,
        min_send_interval_seconds=0.0,
    )
    rp.start()

    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("never replied")


async def test_error_reply_raises(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, app_mock = remote
    rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        reply = encode_reply(ErrorReply(id=req["id"], error="model crashed"))
        await _fire_reply(rp, app_mock, reply)

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
    rp, app_mock = remote
    rp.start()

    # Reply for an id we never sent — handler must not raise.
    stray = encode_reply(SummarizeReply(
        id="not-a-real-id", text="x", input_tokens=1, output_tokens=1,
    ))
    await _fire_reply(rp, app_mock, stray)


async def test_embed_round_trip(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, app_mock = remote
    rp.start()

    assert rp.last_embed_model is None

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        payload = encode_reply(EmbedReply(
            id=req["id"], vector=[0.1, 0.2, 0.3], tokens=5,
            model="qwen3-embedding:4b",
        ))
        await _fire_reply(rp, app_mock, payload)

    asyncio.create_task(replier())
    result = await rp.embed("text")

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.tokens == 5
    assert result.model == "qwen3-embedding:4b"
    assert result.provider == "remote"
    assert rp.last_embed_model == "qwen3-embedding:4b"


async def test_request_is_sent_as_json_document(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, app_mock = remote
    rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        reply = encode_reply(SummarizeReply(
            id=req["id"], text="ok", input_tokens=1, output_tokens=1,
        ))
        await _fire_reply(rp, app_mock, reply)

    asyncio.create_task(replier())
    await rp.summarize("hi")

    # The request was sent via send_document (not send_message); a payload
    # file lookup must succeed and parse as JSON.
    assert app_mock.bot.send_document.await_count == 1
    body = await _request_payload(app_mock)
    parsed = json.loads(body)
    assert parsed["op"] == "summarize"
    assert parsed["text"] == "hi"


async def test_summarize_forwards_system_prompt_on_wire(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, app_mock = remote
    rp.start()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        reply = encode_reply(SummarizeReply(
            id=req["id"], text="ok", input_tokens=1, output_tokens=1,
        ))
        await _fire_reply(rp, app_mock, reply)

    asyncio.create_task(replier())
    await rp.summarize("hi", system_prompt="CUSTOM")

    body = await _request_payload(app_mock)
    parsed = json.loads(body)
    assert parsed["system_prompt"] == "CUSTOM"


async def test_summarize_timeout_marks_unhealthy_and_calls_callback() -> None:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.1,
        min_send_interval_seconds=0.0,
    )
    rp.start()

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
    from shared.protocol import PingReply

    app_mock = _make_app_mock()
    pending_replies: list[asyncio.Task] = []

    real_send_document = app_mock.bot.send_document.side_effect

    async def auto_replier(*args, **kwargs):
        msg = await real_send_document(*args, **kwargs)
        body = app_mock._files[msg.document.file_id].decode("utf-8")
        req_id = json.loads(body)["id"]
        reply_text = encode_reply(PingReply(id=req_id))

        async def fire() -> None:
            await asyncio.sleep(0)
            await _fire_reply(rp, app_mock, reply_text)

        pending_replies.append(asyncio.create_task(fire()))
        return msg

    app_mock.bot.send_document = AsyncMock(side_effect=auto_replier)

    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
    )
    rp.start()
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
    assert app_mock.bot.send_document.await_count >= 1


async def test_ping_success_populates_last_models(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    from shared.protocol import PingReply

    rp, app_mock = remote
    rp.start()

    assert rp.last_chat_model is None
    assert rp.last_embed_model is None

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        reply = encode_reply(PingReply(
            id=req["id"], chat_model="qwen2.5:7b",
            embed_model="qwen3-embedding:4b",
        ))
        await _fire_reply(rp, app_mock, reply)

    asyncio.create_task(replier())
    await rp.ping()

    assert rp.last_chat_model == "qwen2.5:7b"
    assert rp.last_embed_model == "qwen3-embedding:4b"


async def test_ping_with_empty_models_preserves_existing(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    # Backward-compat: an old processor that hasn't been redeployed returns a
    # PingReply with empty defaults. Already-known model names must not be
    # clobbered.
    from shared.protocol import PingReply

    rp, app_mock = remote
    rp.start()
    rp._last_chat_model = "prev-chat"
    rp._last_embed_model = "prev-embed"

    async def replier() -> None:
        await asyncio.sleep(0.01)
        body = await _request_payload(app_mock)
        req = json.loads(body)
        reply = encode_reply(PingReply(id=req["id"]))
        await _fire_reply(rp, app_mock, reply)

    asyncio.create_task(replier())
    await rp.ping()

    assert rp.last_chat_model == "prev-chat"
    assert rp.last_embed_model == "prev-embed"


async def test_health_loop_ping_failure_flips_state() -> None:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.05,
        min_send_interval_seconds=0.0,
    )
    rp.start()
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
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
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
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
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


async def test_embed_raises_on_wrong_reply_type(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, _app_mock = remote
    rp.start()

    async def replier() -> None:
        # Wait for embed() to register its pending entry, then resolve the
        # future directly with a wrong-typed reply (bypassing decode_reply,
        # which would otherwise validate the payload against pending.op).
        for _ in range(100):
            if rp._pending:
                break
            await asyncio.sleep(0.005)
        assert rp._pending, "embed() never registered a pending request"
        req_id, pending = next(iter(rp._pending.items()))
        wrong_reply = SummarizeReply(
            id=req_id, text="x", input_tokens=1, output_tokens=1,
        )
        pending.future.set_result((wrong_reply, 9999))

    asyncio.create_task(replier())
    with pytest.raises(RemoteProcessorError, match="unexpected reply type for embed"):
        await rp.embed("text")


async def test_ping_raises_on_wrong_reply_type(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, _app_mock = remote
    rp.start()

    async def replier() -> None:
        for _ in range(100):
            if rp._pending:
                break
            await asyncio.sleep(0.005)
        assert rp._pending, "ping() never registered a pending request"
        req_id, pending = next(iter(rp._pending.items()))
        wrong_reply = SummarizeReply(
            id=req_id, text="x", input_tokens=1, output_tokens=1,
        )
        pending.future.set_result((wrong_reply, 9999))

    asyncio.create_task(replier())
    with pytest.raises(RemoteProcessorError, match="unexpected reply type for ping"):
        await rp.ping()


async def test_cleanup_tasks_tracked(
    remote: tuple[RemoteProcessorClient, SimpleNamespace],
) -> None:
    rp, _app_mock = remote

    rp._schedule_delete(1, 2)
    assert len(rp._cleanup_tasks) == 1

    task = next(iter(rp._cleanup_tasks))
    await task
    # Done-callback runs synchronously after the task completes; yield once
    # so any pending callbacks land before we check.
    await asyncio.sleep(0)

    assert len(rp._cleanup_tasks) == 0


async def test_grace_period_zero_preserves_immediate_unhealthy() -> None:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.05,
        min_send_interval_seconds=0.0,
        unhealthy_grace_seconds=0.0,
    )
    rp.start()
    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)

    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("never replied")

    assert rp.healthy is False
    assert states == [False]


async def test_call_timeout_arms_grace_without_flipping() -> None:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.05,
        min_send_interval_seconds=0.0,
        unhealthy_grace_seconds=5.0,
    )
    rp.start()
    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)

    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("never replied")

    assert rp.healthy is True
    assert states == []

    # await_health_decision must not return synchronously — it should block on
    # the event. Use a short wait_for to confirm.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(rp.await_health_decision(), timeout=0.05)

    await rp.close()


async def test_ping_success_during_grace_resolves_recovered() -> None:
    from shared.protocol import PingReply

    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
        unhealthy_grace_seconds=5.0,
    )
    rp.start()
    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)

    # Manually arm grace (skips wire round-trip for the arming step).
    await rp._arm_grace()
    assert rp._grace_event is not None
    assert rp.healthy is True

    # Now run a single health-check iteration that succeeds. Reuse the
    # auto-reply pattern from test_health_loop_ping_success_keeps_healthy.
    real_send_document = app_mock.bot.send_document.side_effect

    async def auto_replier(*args, **kwargs):
        msg = await real_send_document(*args, **kwargs)
        body = app_mock._files[msg.document.file_id].decode("utf-8")
        req_id = json.loads(body)["id"]
        reply_text = encode_reply(PingReply(id=req_id))

        async def fire() -> None:
            await asyncio.sleep(0)
            await _fire_reply(rp, app_mock, reply_text)

        asyncio.create_task(fire())
        return msg

    app_mock.bot.send_document = AsyncMock(side_effect=auto_replier)
    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.1)
        stop_event.set()

    asyncio.create_task(stopper())
    await rp.run_health_check_loop(interval_seconds=0.02, stop_event=stop_event)

    decision = await asyncio.wait_for(rp.await_health_decision(), timeout=0.5)
    assert decision == "recovered"
    assert rp.healthy is True
    # No state-change DM was fired — we never told the owner about the outage.
    assert states == []

    await rp.close()


async def test_grace_expiry_marks_unhealthy_and_fires_dm() -> None:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.05,
        min_send_interval_seconds=0.0,
        unhealthy_grace_seconds=0.05,
    )
    rp.start()
    states: list[bool] = []

    async def on_change(healthy: bool) -> None:
        states.append(healthy)

    rp.set_state_change_callback(on_change)

    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("never replied")

    # During grace, before expiry, still healthy.
    assert rp.healthy is True

    decision = await asyncio.wait_for(rp.await_health_decision(), timeout=0.5)
    assert decision == "unhealthy"
    assert rp.healthy is False
    assert states == [False]

    await rp.close()


async def test_new_call_during_grace_short_circuits() -> None:
    app_mock = _make_app_mock()
    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=0.05,
        min_send_interval_seconds=0.0,
        unhealthy_grace_seconds=5.0,
    )
    rp.start()

    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("never replied")

    sends_before = app_mock.bot.send_document.await_count
    start = time.monotonic()
    with pytest.raises(RemoteProcessorTimeout):
        await rp.summarize("second call")
    elapsed = time.monotonic() - start
    assert elapsed < 0.05
    assert app_mock.bot.send_document.await_count == sends_before

    await rp.close()


async def test_close_cancels_pending_cleanup_tasks() -> None:
    app_mock = _make_app_mock()
    hang = asyncio.Event()  # never set

    async def hang_forever(**_kwargs):
        await hang.wait()

    app_mock.bot.delete_messages = AsyncMock(side_effect=hang_forever)

    rp = RemoteProcessorClient(
        application=app_mock,  # type: ignore[arg-type]
        bus_group_id=-100123,
        processor_bot_user_id=42,
        timeout_seconds=2.0,
        min_send_interval_seconds=0.0,
    )

    rp._schedule_delete(1, 2)
    assert len(rp._cleanup_tasks) == 1

    await rp.close()

    assert len(rp._cleanup_tasks) == 0
