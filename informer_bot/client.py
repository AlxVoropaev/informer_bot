import logging
import time

from telethon import TelegramClient, events
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel

from informer_bot.album import AlbumBuffer
from informer_bot.db import Database
from informer_bot.throttle import cheap_limiter, expensive_limiter

log = logging.getLogger(__name__)


async def fetch_subscribed_channels(
    tg: TelegramClient,
) -> list[tuple[int, str, str, str | None]]:
    out: list[tuple[int, str, str, str | None]] = []
    async for dialog in tg.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel) and entity.broadcast and entity.username:
            try:
                async with expensive_limiter:
                    full = await tg(GetFullChannelRequest(entity))
                about = full.full_chat.about or None
            except Exception:
                log.exception("fetch about failed for channel=%s", entity.id)
                about = None
            out.append((entity.id, entity.title, entity.username, about))
            log.debug(
                "subscribed channel: id=%s @%s '%s' about_chars=%s",
                entity.id, entity.username, entity.title, len(about) if about else 0,
            )
    log.info("fetched %d subscribed channel(s) from telethon", len(out))
    return out


async def _download_photo(message) -> bytes | None:
    if not getattr(message, "photo", None):
        return None
    try:
        async with cheap_limiter:
            return await message.download_media(file=bytes)
    except Exception:
        log.exception("photo download failed for msg=%s", getattr(message, "id", "?"))
        return None


async def catch_up(
    tg: TelegramClient,
    db: Database,
    buffer: AlbumBuffer,
    *,
    max_age_seconds: int,
    now: int | None = None,
) -> None:
    """Replay posts that arrived during downtime.

    For each subscribed channel with prior `seen` history, fetch messages with
    id > MAX(seen.message_id) and date >= now - max_age_seconds, then feed them
    through the same album buffer the live handler uses. Channels with no prior
    seen rows are skipped (no full-history backfill on first run).
    """
    cutoff_ts = (int(time.time()) if now is None else now) - max_age_seconds
    channel_ids = db.channels_with_active_subscribers()
    total = 0
    for channel_id in channel_ids:
        max_id = db.max_seen_message_id(channel_id)
        if max_id is None:
            log.debug("catch_up: channel=%s has no prior seen history, skip", channel_id)
            continue
        try:
            async with expensive_limiter:
                entity = await tg.get_entity(channel_id)
        except Exception:
            log.exception("catch_up: get_entity failed for channel=%s", channel_id)
            continue
        if not (isinstance(entity, Channel) and entity.broadcast and entity.username):
            log.debug("catch_up: channel=%s no longer broadcast/public, skip", channel_id)
            continue

        n = 0
        # Acquire once before the paginating async generator starts.
        async with cheap_limiter:
            iterator = tg.iter_messages(entity, min_id=max_id, reverse=True)
        async for message in iterator:
            if message.date is not None and message.date.timestamp() < cutoff_ts:
                continue
            photo = await _download_photo(message)
            await buffer.add(
                channel_id=entity.id,
                channel_username=entity.username,
                message_id=message.id,
                grouped_id=message.grouped_id,
                text=message.message or "",
                photo=photo,
            )
            n += 1
        total += n
        log.info(
            "catch_up: channel=%s @%s replayed %d post(s) (since msg=%s)",
            entity.id, entity.username, n, max_id,
        )
    log.info(
        "catch_up done: %d post(s) replayed across %d channel(s)",
        total, len(channel_ids),
    )


def register_new_post_handler(tg: TelegramClient, buffer: AlbumBuffer) -> None:
    @tg.on(events.NewMessage())
    async def _handler(event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        if not (isinstance(chat, Channel) and chat.broadcast and chat.username):
            log.info(
                "incoming dropped: chat=%s msg=%s type=%s broadcast=%s username=%s",
                getattr(chat, "id", "?"), event.message.id,
                type(chat).__name__,
                getattr(chat, "broadcast", None),
                getattr(chat, "username", None),
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
