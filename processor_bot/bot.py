import logging
from collections.abc import Callable, Coroutine
from io import BytesIO
from typing import Any

from openai import APIConnectionError, AsyncOpenAI
from telegram import InputFile, ReplyParameters, Update
from telegram.ext import ContextTypes

from processor_bot.config import Config
from processor_bot.handlers import handle_request
from shared.protocol import (
    REPLY_FILENAME,
    EmbedRequest,
    ErrorReply,
    IsRelevantRequest,
    ProtocolError,
    Reply,
    Request,
    SummarizeReply,
    SummarizeRequest,
    decode_request,
    encode_reply,
    request_op,
)

log = logging.getLogger(__name__)

HandlerCallback = Callable[
    [Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]
]

_LOG_TEXT_LIMIT = 500


def _short(s: str) -> str:
    if len(s) <= _LOG_TEXT_LIMIT:
        return s
    return f"{s[:_LOG_TEXT_LIMIT]}…[+{len(s) - _LOG_TEXT_LIMIT} chars]"


def _request_text(req: Request) -> str | None:
    if isinstance(req, (SummarizeRequest, IsRelevantRequest, EmbedRequest)):
        return req.text
    return None


def _reply_text(reply: Reply) -> str | None:
    if isinstance(reply, SummarizeReply):
        return reply.text
    return None


def make_handler_callback(
    *, cfg: Config, ollama_client: AsyncOpenAI
) -> HandlerCallback:
    async def _on_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        log.info(
            "incoming: chat=%s user=%s msg=%s",
            message.chat_id if message else None,
            update.effective_user.id if update.effective_user else None,
            message.message_id if message else None,
        )
        if message is None or message.document is None:
            return
        # Sender check is enforced by filters at registration; keep a defensive
        # log in case the handler is invoked outside the expected filter.
        sender = update.effective_user
        if sender is None or sender.id != cfg.informer_bot_user_id:
            log.debug(
                "drop: sender=%s not informer", sender.id if sender else None,
            )
            return
        try:
            tg_file = await context.bot.get_file(message.document.file_id)
            buf = BytesIO()
            await tg_file.download_to_memory(out=buf)
            body = buf.getvalue().decode("utf-8")
        except Exception as e:
            log.warning("download failed: %s", e)
            return
        try:
            req = decode_request(body)
        except ProtocolError as e:
            log.warning("decode failed: %s", e)
            return
        log.info("request: op=%s id=%s", type(req).__name__, req.id)
        in_text = _request_text(req)
        if in_text is not None:
            log.debug(
                "request text: op=%s id=%s len=%d body=%r",
                type(req).__name__, req.id, len(in_text), _short(in_text),
            )
        try:
            reply = await handle_request(
                req,
                client=ollama_client,
                chat_model=cfg.ollama_chat_model,
                embedding_model=cfg.ollama_embedding_model,
            )
        except APIConnectionError as e:
            log.warning(
                "ollama unreachable for id=%s op=%s: %s",
                req.id, type(req).__name__, e,
            )
            reply = ErrorReply(id=req.id, error=str(e))
        except Exception as e:
            log.exception("handler failed for id=%s", req.id)
            reply = ErrorReply(id=req.id, error=str(e))

        encoded = encode_reply(reply)
        op = request_op(req)
        await context.bot.send_document(
            chat_id=cfg.bus_group_id,
            document=InputFile(
                BytesIO(encoded.encode("utf-8")),
                filename=REPLY_FILENAME,
            ),
            caption=f"op: {op.value}",
            reply_parameters=ReplyParameters(message_id=message.message_id),
        )
        log.info("reply: op=%s id=%s", type(reply).__name__, reply.id)
        out_text = _reply_text(reply)
        if out_text is not None:
            log.debug(
                "reply text: op=%s id=%s len=%d body=%r",
                type(reply).__name__, reply.id, len(out_text), _short(out_text),
            )

    return _on_message
