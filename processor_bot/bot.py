import logging
from collections.abc import Awaitable, Callable
from io import BytesIO

from openai import AsyncOpenAI
from telegram import InputFile, ReplyParameters, Update
from telegram.ext import ContextTypes

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

HandlerCallback = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def make_handler_callback(
    *, cfg: Config, ollama_client: AsyncOpenAI
) -> HandlerCallback:
    async def _on_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return
        # Sender check is enforced by filters at registration; keep a defensive
        # log in case the handler is invoked outside the expected filter.
        sender = update.effective_user
        if sender is None or sender.id != cfg.informer_bot_user_id:
            log.debug(
                "drop: sender=%s not informer", sender.id if sender else None,
            )
            return
        body = message.text or ""
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

        encoded = encode_reply(reply)
        if isinstance(reply, EmbedReply):
            await context.bot.send_document(
                chat_id=cfg.bus_group_id,
                document=InputFile(
                    BytesIO(encoded.encode("utf-8")),
                    filename=EMBED_REPLY_FILENAME,
                ),
                reply_parameters=ReplyParameters(message_id=message.message_id),
            )
        else:
            await context.bot.send_message(
                chat_id=cfg.bus_group_id,
                text=encoded,
                reply_parameters=ReplyParameters(message_id=message.message_id),
            )
        log.info("reply: op=%s id=%s", type(reply).__name__, reply.id)

    return _on_message
