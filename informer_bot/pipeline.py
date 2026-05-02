import logging
from collections.abc import Awaitable, Callable

from informer_bot.db import Database
from informer_bot.summarizer import Summary

log = logging.getLogger(__name__)

SummarizeFn = Callable[[str], Awaitable[Summary]]
SendDmFn = Callable[[int, str], Awaitable[None]]
FetchChannelsFn = Callable[[], Awaitable[list[tuple[int, str]]]]


async def handle_new_post(
    *,
    channel_id: int,
    message_id: int,
    text: str,
    link: str,
    db: Database,
    summarize_fn: SummarizeFn,
    send_dm: SendDmFn,
) -> None:
    if not text.strip():
        log.debug("skip post %s/%s: empty text", channel_id, message_id)
        return
    if not db.mark_seen(channel_id=channel_id, message_id=message_id):
        log.debug("skip post %s/%s: already seen", channel_id, message_id)
        return
    subscribers = db.subscribers_for_channel(channel_id=channel_id)
    if not subscribers:
        log.debug("skip post %s/%s: no subscribers", channel_id, message_id)
        return
    log.info(
        "handling post %s/%s for %d subscriber(s) (%d chars)",
        channel_id, message_id, len(subscribers), len(text),
    )
    summary = await summarize_fn(text)
    db.add_system_usage(
        input_tokens=summary.input_tokens, output_tokens=summary.output_tokens
    )
    body = f"{summary.text}\n\n{link}"
    for user_id in subscribers:
        await send_dm(user_id, body)
        db.add_usage(
            user_id=user_id,
            input_tokens=summary.input_tokens,
            output_tokens=summary.output_tokens,
        )


async def refresh_channels(
    *,
    fetch_fn: FetchChannelsFn,
    db: Database,
    send_dm: SendDmFn,
) -> None:
    fresh = await fetch_fn()
    fresh_ids = {channel_id for channel_id, _ in fresh}
    log.debug("refresh: %d fresh channel(s) from telethon", len(fresh))

    for channel_id, title in fresh:
        db.upsert_channel(channel_id=channel_id, title=title)

    removed = 0
    notified = 0
    known = db.list_channels(include_blacklisted=True)
    for channel in known:
        if channel.id in fresh_ids:
            continue
        if not channel.blacklisted:
            subs = db.subscribers_for_channel(channel_id=channel.id)
            for user_id in subs:
                await send_dm(
                    user_id,
                    f"Channel '{channel.title}' is no longer available.",
                )
            notified += len(subs)
        db.delete_channel(channel_id=channel.id)
        removed += 1
    log.info(
        "refresh done: %d known, %d removed, %d subscriber(s) notified",
        len(fresh), removed, notified,
    )
