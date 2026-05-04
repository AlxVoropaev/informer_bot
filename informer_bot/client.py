import logging

from telethon import TelegramClient, events
from telethon.tl.types import Channel

from informer_bot.album import AlbumBuffer

log = logging.getLogger(__name__)


async def fetch_subscribed_channels(tg: TelegramClient) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    async for dialog in tg.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel) and entity.broadcast and entity.username:
            out.append((entity.id, entity.title))
            log.debug("subscribed channel: id=%s @%s '%s'", entity.id, entity.username, entity.title)
    log.info("fetched %d subscribed channel(s) from telethon", len(out))
    return out


async def _download_photo(message) -> bytes | None:
    if not getattr(message, "photo", None):
        return None
    try:
        return await message.download_media(file=bytes)
    except Exception:
        log.exception("photo download failed for msg=%s", getattr(message, "id", "?"))
        return None


def register_new_post_handler(tg: TelegramClient, buffer: AlbumBuffer) -> None:
    @tg.on(events.NewMessage())
    async def _handler(event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        if not (isinstance(chat, Channel) and chat.broadcast and chat.username):
            log.info(
                "incoming dropped: non-broadcast/no-username chat=%s msg=%s",
                getattr(chat, "id", "?"), event.message.id,
            )
            return
        log.info(
            "incoming: channel=%s @%s msg=%s grouped=%s chars=%d",
            chat.id, chat.username, event.message.id, event.message.grouped_id,
            len(event.message.message or ""),
        )
        photo = await _download_photo(event.message)
        await buffer.add(
            channel_id=chat.id,
            channel_username=chat.username,
            message_id=event.message.id,
            grouped_id=event.message.grouped_id,
            text=event.message.message or "",
            photo=photo,
        )
