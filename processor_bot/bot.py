import asyncio
import io
import logging
import time

from openai import AsyncOpenAI
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

from processor_bot.config import Config
from processor_bot.handlers import handle_request
from shared.protocol import (
    EMBED_REPLY_FILENAME,
    EmbedReply,
    ErrorReply,
    ProtocolError,
    decode_request,
    encode_reply,
)

log = logging.getLogger(__name__)


class RateLimiter:
    """Ensure at least `min_interval` seconds between acquisitions."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._next_at: float = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = time.monotonic() + self._min_interval


def register_handler(
    tg: TelegramClient,
    *,
    cfg: Config,
    ollama_client: AsyncOpenAI,
    limiter: RateLimiter,
) -> None:
    @tg.on(events.NewMessage(chats=[cfg.bus_group_id]))
    async def _on_message(event: events.NewMessage.Event) -> None:
        if event.sender_id != cfg.informer_bot_user_id:
            log.debug(
                "drop: sender=%s not informer", event.sender_id,
            )
            return
        body = event.message.message or ""
        try:
            req = decode_request(body)
        except ProtocolError as e:
            log.warning("decode failed: %s", e)
            return
        log.info("request: op=%s id=%s", type(req).__name__, req.id)
        try:
            reply = await handle_request(
                req,
                client=ollama_client,
                chat_model=cfg.ollama_chat_model,
                embedding_model=cfg.ollama_embedding_model,
            )
        except Exception as e:
            log.exception("handler failed for id=%s", req.id)
            reply = ErrorReply(id=req.id, error=str(e))

        await limiter.acquire()
        if isinstance(reply, EmbedReply):
            buf = io.BytesIO(encode_reply(reply).encode("utf-8"))
            buf.name = EMBED_REPLY_FILENAME
            await tg.send_file(
                cfg.bus_group_id,
                file=buf,
                reply_to=event.message.id,
                attributes=[DocumentAttributeFilename(EMBED_REPLY_FILENAME)],
            )
        else:
            await tg.send_message(
                cfg.bus_group_id,
                encode_reply(reply),
                reply_to=event.message.id,
            )
        log.info("reply: op=%s id=%s", type(reply).__name__, reply.id)
