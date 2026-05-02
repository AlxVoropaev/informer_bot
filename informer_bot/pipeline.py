import html
import logging
from collections.abc import Awaitable, Callable

from informer_bot.db import Database
from informer_bot.i18n import t
from informer_bot.summarizer import RelevanceCheck, Summary

log = logging.getLogger(__name__)

SummarizeFn = Callable[[str], Awaitable[Summary]]
IsRelevantFn = Callable[[str, str], Awaitable[RelevanceCheck]]
SendDmFn = Callable[..., Awaitable[None]]
FetchChannelsFn = Callable[[], Awaitable[list[tuple[int, str]]]]


def _format_post(channel_title: str, summary: str, link: str) -> str:
    return f'<a href="{html.escape(link, quote=True)}">{html.escape(channel_title)}</a>\n{html.escape(summary)}'


async def handle_new_post(
    *,
    channel_id: int,
    message_id: int,
    text: str,
    link: str,
    db: Database,
    summarize_fn: SummarizeFn,
    is_relevant_fn: IsRelevantFn,
    send_dm: SendDmFn,
    photo: bytes | None = None,
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

    recipients: list[int] = []
    for user_id, mode in subscribers:
        if mode == "all":
            recipients.append(user_id)
            continue
        filter_prompt = db.get_filter(user_id=user_id)
        if not filter_prompt:
            recipients.append(user_id)
            continue
        check = await is_relevant_fn(text, filter_prompt)
        db.add_system_usage(
            input_tokens=check.input_tokens, output_tokens=check.output_tokens
        )
        db.add_usage(
            user_id=user_id,
            input_tokens=check.input_tokens,
            output_tokens=check.output_tokens,
        )
        if check.relevant:
            recipients.append(user_id)
        else:
            log.debug("filter excluded user=%s for post %s/%s", user_id, channel_id, message_id)

    if not recipients:
        log.info(
            "post %s/%s: no recipients passed filter (of %d subscriber(s))",
            channel_id, message_id, len(subscribers),
        )
        return

    log.info(
        "handling post %s/%s for %d/%d recipient(s) (%d chars)",
        channel_id, message_id, len(recipients), len(subscribers), len(text),
    )
    summary = await summarize_fn(text)
    db.add_system_usage(
        input_tokens=summary.input_tokens, output_tokens=summary.output_tokens
    )
    channel_title = db.get_channel_title(channel_id) or ""
    body = _format_post(channel_title, summary.text, link)
    for user_id in recipients:
        await send_dm(user_id, body, photo)
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
            for user_id, _mode in subs:
                lang = db.get_language(user_id)
                await send_dm(
                    user_id,
                    t(lang, "channel_gone", title=channel.title),
                )
            notified += len(subs)
        db.delete_channel(channel_id=channel.id)
        removed += 1
    log.info(
        "refresh done: %d known, %d removed, %d subscriber(s) notified",
        len(fresh), removed, notified,
    )
