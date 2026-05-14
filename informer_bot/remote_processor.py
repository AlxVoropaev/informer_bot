import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from telegram import InputFile, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from informer_bot.summarizer import Embedding, RelevanceCheck, Summary
from shared.protocol import (
    REQUEST_FILENAME,
    EmbedReply,
    EmbedRequest,
    ErrorReply,
    IsRelevantReply,
    IsRelevantRequest,
    Op,
    PingReply,
    PingRequest,
    ProtocolError,
    Reply,
    Request,
    SummarizeReply,
    SummarizeRequest,
    decode_reply,
    encode_request,
)

log = logging.getLogger(__name__)


class RemoteProcessorError(Exception):
    pass


class RemoteProcessorTimeout(Exception):
    pass


@dataclass
class _Pending:
    op: Op
    future: asyncio.Future[tuple[Reply, int | None]]
    request_msg_id: int | None = None


class _RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_send = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._last_send + self._min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_send = time.monotonic()


class RemoteProcessorClient:
    def __init__(
        self,
        *,
        application: Application,
        bus_group_id: int,
        processor_bot_user_id: int,
        timeout_seconds: float,
        min_send_interval_seconds: float = 1.0,
        unhealthy_grace_seconds: float = 0.0,
    ) -> None:
        self._app = application
        self._bus_group_id = bus_group_id
        self._processor_bot_user_id = processor_bot_user_id
        self._timeout_seconds = timeout_seconds
        self._pending: dict[str, _Pending] = {}
        self._limiter = _RateLimiter(min_send_interval_seconds)
        self._healthy: bool = True
        self._on_state_change: Callable[[bool], Awaitable[None]] | None = None
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._grace_seconds = unhealthy_grace_seconds
        self._grace_event: asyncio.Event | None = None
        self._grace_outcome: Literal["recovered", "unhealthy"] | None = None
        self._grace_task: asyncio.Task[None] | None = None
        self._last_chat_model: str | None = None
        self._last_embed_model: str | None = None

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def last_chat_model(self) -> str | None:
        return self._last_chat_model

    @property
    def last_embed_model(self) -> str | None:
        return self._last_embed_model

    def set_state_change_callback(
        self, callback: Callable[[bool], Awaitable[None]] | None
    ) -> None:
        self._on_state_change = callback

    async def _set_healthy(self, healthy: bool) -> None:
        if self._healthy == healthy:
            return
        self._healthy = healthy
        log.info("remote: health state -> %s", "healthy" if healthy else "unhealthy")
        callback = self._on_state_change
        if callback is None:
            return
        try:
            await callback(healthy)
        except Exception:
            log.exception("remote: state-change callback failed")

    def _grace_active(self) -> bool:
        return self._grace_event is not None and self._grace_outcome is None

    async def _arm_grace(self) -> None:
        if self._grace_seconds <= 0:
            await self._set_healthy(False)
            return
        if self._grace_active():
            return
        self._grace_event = asyncio.Event()
        self._grace_outcome = None
        log.info("remote: grace period armed (%.0fs)", self._grace_seconds)
        self._grace_task = asyncio.create_task(
            self._grace_expire(self._grace_seconds)
        )

    async def _grace_expire(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        await self._resolve_grace("unhealthy")

    async def _resolve_grace(
        self, outcome: Literal["recovered", "unhealthy"]
    ) -> None:
        if self._grace_outcome is not None or self._grace_event is None:
            return
        self._grace_outcome = outcome
        self._grace_event.set()
        if outcome == "unhealthy":
            await self._set_healthy(False)
        else:
            task = self._grace_task
            if task is not None and not task.done():
                task.cancel()

    async def await_health_decision(self) -> Literal["recovered", "unhealthy"]:
        if self._grace_event is None:
            return "recovered" if self._healthy else "unhealthy"
        await self._grace_event.wait()
        outcome = self._grace_outcome
        assert outcome is not None
        return outcome

    async def run_health_check_loop(
        self, interval_seconds: float, stop_event: asyncio.Event
    ) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self.ping()
            except RemoteProcessorTimeout as exc:
                log.warning("remote: health ping timed out: %s", exc)
                await self._arm_grace()
            except Exception as exc:
                log.warning("remote: health ping failed: %s", exc)
                await self._arm_grace()
            else:
                if self._grace_active():
                    await self._resolve_grace("recovered")
                await self._set_healthy(True)

    def start(self) -> None:
        self._app.add_handler(
            MessageHandler(
                filters.Chat(self._bus_group_id)
                & filters.User(self._processor_bot_user_id)
                & filters.Document.FileExtension("json"),
                self._on_reply,
            )
        )

    async def summarize(
        self, text: str, *, system_prompt: str | None = None,
    ) -> Summary:
        if self._grace_active():
            raise RemoteProcessorTimeout("processor in grace period")
        req = SummarizeRequest.new(text, system_prompt=system_prompt)
        try:
            reply = await self._send_and_wait(req, Op.summarize)
        except RemoteProcessorTimeout:
            await self._arm_grace()
            raise
        if not isinstance(reply, SummarizeReply):
            raise RemoteProcessorError(
                f"unexpected reply type for summarize: {type(reply).__name__}"
            )
        self._last_chat_model = reply.model or None
        return Summary(
            text=reply.text,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            provider="remote",
        )

    async def is_relevant(self, text: str, filter_prompt: str) -> RelevanceCheck:
        if self._grace_active():
            raise RemoteProcessorTimeout("processor in grace period")
        req = IsRelevantRequest.new(text, filter_prompt)
        try:
            reply = await self._send_and_wait(req, Op.is_relevant)
        except RemoteProcessorTimeout:
            await self._arm_grace()
            raise
        if not isinstance(reply, IsRelevantReply):
            raise RemoteProcessorError(
                f"unexpected reply type for is_relevant: {type(reply).__name__}"
            )
        return RelevanceCheck(
            relevant=reply.relevant,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            provider="remote",
        )

    async def embed(self, text: str) -> Embedding:
        from informer_bot.summarizer import EMBED_DIMENSIONS

        if self._grace_active():
            raise RemoteProcessorTimeout("processor in grace period")
        req = EmbedRequest.new(text, EMBED_DIMENSIONS)
        try:
            reply = await self._send_and_wait(req, Op.embed)
        except RemoteProcessorTimeout:
            await self._arm_grace()
            raise
        if not isinstance(reply, EmbedReply):
            raise RemoteProcessorError(
                f"unexpected reply type for embed: {type(reply).__name__}"
            )
        self._last_embed_model = reply.model or None
        return Embedding(
            vector=list(reply.vector),
            tokens=reply.tokens,
            provider="remote",
            model=reply.model,
        )

    async def ping(self) -> None:
        req = PingRequest.new()
        reply = await self._send_and_wait(req, Op.ping)
        if not isinstance(reply, PingReply):
            raise RemoteProcessorError(
                f"unexpected reply type for ping: {type(reply).__name__}"
            )
        if reply.chat_model:
            self._last_chat_model = reply.chat_model
        if reply.embed_model:
            self._last_embed_model = reply.embed_model

    async def _send_and_wait(self, req: Request, op: Op) -> Reply:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[Reply, int | None]] = loop.create_future()
        pending = _Pending(op=op, future=future)
        self._pending[req.id] = pending
        try:
            await self._limiter.acquire()
            payload = encode_request(req).encode("utf-8")
            req_msg = await self._app.bot.send_document(
                chat_id=self._bus_group_id,
                document=InputFile(BytesIO(payload), filename=REQUEST_FILENAME),
                caption=f"op: {op.value}",
            )
            pending.request_msg_id = getattr(req_msg, "message_id", None)
            try:
                reply, reply_msg_id = await asyncio.wait_for(
                    future, timeout=self._timeout_seconds
                )
            except asyncio.TimeoutError as e:
                raise RemoteProcessorTimeout(
                    f"no reply for {op.value} (id={req.id}) within "
                    f"{self._timeout_seconds}s"
                ) from e
        finally:
            self._pending.pop(req.id, None)
        self._schedule_delete(pending.request_msg_id, reply_msg_id)
        if isinstance(reply, ErrorReply):
            raise RemoteProcessorError(reply.error)
        return reply

    def _schedule_delete(
        self, request_msg_id: int | None, reply_msg_id: int | None
    ) -> None:
        ids = [i for i in (request_msg_id, reply_msg_id) if i is not None]
        if not ids:
            return
        task = asyncio.create_task(self._delete_messages(ids))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def close(self) -> None:
        tasks = list(self._cleanup_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._cleanup_tasks.clear()
        grace_task = self._grace_task
        if grace_task is not None and not grace_task.done():
            grace_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await grace_task

    async def _delete_messages(self, ids: list[int]) -> None:
        try:
            await self._app.bot.delete_messages(
                chat_id=self._bus_group_id, message_ids=ids
            )
        except Exception as exc:
            log.warning("remote: delete_messages failed for %s: %s", ids, exc)

    async def _on_reply(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None or message.document is None:
            return
        try:
            tg_file = await context.bot.get_file(message.document.file_id)
            buf = BytesIO()
            await tg_file.download_to_memory(out=buf)
            text = buf.getvalue().decode("utf-8")
        except Exception as exc:
            log.warning("remote: failed to download reply: %s", exc)
            return
        try:
            reply_id = self._peek_id(text)
        except ProtocolError as e:
            log.warning("remote: bad reply payload: %s", e)
            return
        pending = self._pending.get(reply_id)
        if pending is None:
            log.warning("remote: reply for unknown id=%s", reply_id)
            return
        try:
            reply = decode_reply(text, pending.op)
        except ProtocolError as e:
            log.warning("remote: bad reply id=%s: %s", reply_id, e)
            return
        self._resolve(pending, reply, message.message_id)

    @staticmethod
    def _peek_id(text: str) -> str:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProtocolError(f"malformed JSON: {e}") from e
        if not isinstance(data, dict) or "id" not in data:
            raise ProtocolError("reply missing 'id'")
        return str(data["id"])

    @staticmethod
    def _resolve(pending: _Pending, reply: Reply, reply_msg_id: int | None) -> None:
        # Freshness invariant: stale replies for already-cleared requests are
        # filtered earlier in _on_reply via the self._pending dict (the entry
        # is popped in _send_and_wait's finally on timeout). This done()-guard
        # only catches the narrow race where _on_reply reads `pending` before
        # the timeout's finally runs but `wait_for` has already cancelled the
        # future. In that case we drop the late reply silently.
        if pending.future.done():
            return
        pending.future.set_result((reply, reply_msg_id))
