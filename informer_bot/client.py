from telethon import TelegramClient, events
from telethon.tl.types import Channel

from informer_bot.album import AlbumBuffer


async def fetch_subscribed_channels(tg: TelegramClient) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    async for dialog in tg.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel) and entity.broadcast and entity.username:
            out.append((entity.id, entity.title))
    return out


def register_new_post_handler(tg: TelegramClient, buffer: AlbumBuffer) -> None:
    @tg.on(events.NewMessage())
    async def _handler(event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        if not (isinstance(chat, Channel) and chat.broadcast and chat.username):
            return
        await buffer.add(
            channel_id=chat.id,
            channel_username=chat.username,
            message_id=event.message.id,
            grouped_id=event.message.grouped_id,
            text=event.message.message or "",
        )
