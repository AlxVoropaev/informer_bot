from collections.abc import Awaitable, Callable

from informer_bot.db import Database

SummarizeFn = Callable[[str], Awaitable[str]]
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
        return
    if not db.mark_seen(channel_id=channel_id, message_id=message_id):
        return
    subscribers = db.subscribers_for_channel(channel_id=channel_id)
    if not subscribers:
        return
    brief = await summarize_fn(text)
    body = f"{brief}\n\n{link}"
    for user_id in subscribers:
        await send_dm(user_id, body)


async def refresh_channels(
    *,
    fetch_fn: FetchChannelsFn,
    db: Database,
    send_dm: SendDmFn,
) -> None:
    fresh = await fetch_fn()
    fresh_ids = {channel_id for channel_id, _ in fresh}

    for channel_id, title in fresh:
        db.upsert_channel(channel_id=channel_id, title=title)

    known = db.list_channels(include_blacklisted=True)
    for channel in known:
        if channel.id in fresh_ids:
            continue
        if not channel.blacklisted:
            for user_id in db.subscribers_for_channel(channel_id=channel.id):
                await send_dm(
                    user_id,
                    f"Channel '{channel.title}' is no longer available.",
                )
        db.delete_channel(channel_id=channel.id)
