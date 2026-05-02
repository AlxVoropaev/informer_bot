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


def register_new_post_handler(tg: TelegramClient, buffer: AlbumBuffer) -> None:
    @tg.on(events.NewMessage())
    async def _handler(event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        if not (isinstance(chat, Channel) and chat.broadcast and chat.username):
            log.debug("ignoring message from non-broadcast chat")
            return
        log.debug(
            "new message: channel=%s msg=%s grouped=%s",
            chat.id, event.message.id, event.message.grouped_id,
        )
        await buffer.add(
            channel_id=chat.id,
            channel_username=chat.username,
            message_id=event.message.id,
            grouped_id=event.message.grouped_id,
            text=event.message.message or "",
        )
