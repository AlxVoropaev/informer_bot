import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

from informer_bot.summarizer import Embedding, RelevanceCheck, Summary
from shared.protocol import (
    EMBED_REPLY_FILENAME,
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
        telethon_client: TelegramClient,
        bus_group_id: int,
        processor_bot_user_id: int,
        timeout_seconds: float,
        min_send_interval_seconds: float = 1.0,
    ) -> None:
        self._client = telethon_client
        self._bus_group_id = bus_group_id
        self._processor_bot_user_id = processor_bot_user_id
        self._timeout_seconds = timeout_seconds
        self._pending: dict[str, _Pending] = {}
        self._limiter = _RateLimiter(min_send_interval_seconds)
        self._healthy: bool = True
        self._on_state_change: Callable[[bool], Awaitable[None]] | None = None

    @property
    def healthy(self) -> bool:
        return self._healthy

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
                await self._set_healthy(False)
            except Exception as exc:
                log.warning("remote: health ping failed: %s", exc)
                await self._set_healthy(False)
            else:
                await self._set_healthy(True)

    async def start(self) -> None:
        self._client.add_event_handler(
            self._on_reply,
            events.NewMessage(
                chats=[self._bus_group_id],
                from_users=[self._processor_bot_user_id],
            ),
        )

    async def summarize(self, text: str) -> Summary:
        req = SummarizeRequest.new(text)
        try:
            reply = await self._send_and_wait(req, Op.summarize)
        except RemoteProcessorTimeout:
            await self._set_healthy(False)
            raise
        assert isinstance(reply, SummarizeReply)
        return Summary(
            text=reply.text,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            provider="remote",
        )

    async def is_relevant(self, text: str, filter_prompt: str) -> RelevanceCheck:
        req = IsRelevantRequest.new(text, filter_prompt)
        try:
            reply = await self._send_and_wait(req, Op.is_relevant)
        except RemoteProcessorTimeout:
            await self._set_healthy(False)
            raise
        assert isinstance(reply, IsRelevantReply)
        return RelevanceCheck(
            relevant=reply.relevant,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            provider="remote",
        )

    async def embed(self, text: str) -> Embedding:
        from informer_bot.summarizer import EMBED_DIMENSIONS

        req = EmbedRequest.new(text, EMBED_DIMENSIONS)
        try:
            reply = await self._send_and_wait(req, Op.embed)
        except RemoteProcessorTimeout:
            await self._set_healthy(False)
            raise
        assert isinstance(reply, EmbedReply)
        return Embedding(
            vector=list(reply.vector), tokens=reply.tokens, provider="remote",
        )

    async def ping(self) -> None:
        req = PingRequest.new()
        reply = await self._send_and_wait(req, Op.ping)
        assert isinstance(reply, PingReply)

    async def _send_and_wait(self, req: Request, op: Op) -> Reply:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[Reply, int | None]] = loop.create_future()
        pending = _Pending(op=op, future=future)
        self._pending[req.id] = pending
        try:
            await self._limiter.acquire()
            req_msg = await self._client.send_message(
                self._bus_group_id, encode_request(req)
            )
            pending.request_msg_id = getattr(req_msg, "id", None)
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
        asyncio.create_task(self._delete_messages(ids))

    async def _delete_messages(self, ids: list[int]) -> None:
        try:
            await self._client.delete_messages(self._bus_group_id, ids)
        except Exception as exc:
            log.warning("remote: delete_messages failed for %s: %s", ids, exc)

    async def _on_reply(self, event: events.NewMessage.Event) -> None:
        message = event.message
        document = getattr(message, "document", None)
        is_embed_file = False
        if document is not None:
            for attr in getattr(document, "attributes", None) or ():
                if (
                    isinstance(attr, DocumentAttributeFilename)
                    and attr.file_name == EMBED_REPLY_FILENAME
                ):
                    is_embed_file = True
                    break
        try:
            if is_embed_file:
                await self._handle_embed_file(message)
            else:
                self._handle_text_reply(message)
        except Exception as exc:
            log.warning("remote: failed to handle reply: %s", exc)

    async def _handle_embed_file(self, message: Any) -> None:
        buf = BytesIO()
        await message.download_media(file=buf)
        text = buf.getvalue().decode("utf-8")
        reply_id = self._peek_id(text)
        pending = self._pending.get(reply_id)
        if pending is None:
            log.warning("remote: embed reply for unknown id=%s", reply_id)
            return
        try:
            reply = decode_reply(text, pending.op)
        except ProtocolError as e:
            log.warning("remote: bad embed reply id=%s: %s", reply_id, e)
            return
        self._resolve(pending, reply, getattr(message, "id", None))

    def _handle_text_reply(self, message: Any) -> None:
        text = message.text or ""
        if not text:
            return
        reply_id = self._peek_id(text)
        pending = self._pending.get(reply_id)
        if pending is None:
            log.warning("remote: text reply for unknown id=%s", reply_id)
            return
        try:
            reply = decode_reply(text, pending.op)
        except ProtocolError as e:
            log.warning("remote: bad text reply id=%s: %s", reply_id, e)
            return
        self._resolve(pending, reply, getattr(message, "id", None))

    @staticmethod
    def _peek_id(text: str) -> str:
        data = json.loads(text)
        if not isinstance(data, dict) or "id" not in data:
            raise ProtocolError("reply missing 'id'")
        return str(data["id"])

    @staticmethod
    def _resolve(pending: _Pending, reply: Reply, reply_msg_id: int | None) -> None:
        if pending.future.done():
            return
        pending.future.set_result((reply, reply_msg_id))
