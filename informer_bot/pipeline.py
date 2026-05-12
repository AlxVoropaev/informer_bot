import asyncio
import html
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from informer_bot.db import Database
from informer_bot.dedup import find_duplicate
from informer_bot.i18n import t
from informer_bot.modes import SubscriptionMode
from informer_bot.remote_processor import RemoteProcessorError, RemoteProcessorTimeout
from informer_bot.summarizer import Embedding, RelevanceCheck, Summary

log = logging.getLogger(__name__)


class SummarizeFn(Protocol):
    async def __call__(
        self, text: str, *, system_prompt: str | None = None,
    ) -> Summary: ...


IsRelevantFn = Callable[[str, str], Awaitable[RelevanceCheck]]
SendDmFn = Callable[..., Awaitable[int | None]]
EditDmFn = Callable[..., Awaitable[None]]
EmbedFn = Callable[[str], Awaitable[Embedding]]
FetchChannelsFn = Callable[[], Awaitable[list[tuple[int, str, str, str | None]]]]
FetchChannelsForFn = Callable[
    [int], Awaitable[list[tuple[int, str, str, str | None]]]
]
AnnounceNewChannelFn = Callable[[int, int, str], Awaitable[None]]


def _format_post(
    channel_title: str,
    summary: str,
    link: str,
    marker: str | None = None,
    tail: str | None = None,
    settings_url: str | None = None,
    settings_label: str | None = None,
) -> str:
    title_html = (
        f'<a href="{html.escape(link, quote=True)}">{html.escape(channel_title)}</a>'
    )
    if settings_url and settings_label:
        title_html = (
            f'{title_html} '
            f'<a href="{html.escape(settings_url, quote=True)}">'
            f'{html.escape(settings_label)}</a>'
        )
    body = f'{title_html}\n{html.escape(summary)}'
    if marker:
        body = f"{html.escape(marker)}\n{body}"
    if tail:
        body = f"{body}\n{tail}"
    return body


def _original_link_html(label: str, title: str, url: str) -> str:
    return (
        f'↳ {html.escape(label)}: '
        f'<a href="{html.escape(url, quote=True)}">{html.escape(title)}</a>'
    )


def _channel_settings_url(deeplink: str | None, channel_id: int) -> str | None:
    if not deeplink:
        return None
    sep = "&" if "?" in deeplink else "?"
    return f"{deeplink}{sep}startapp=channel_{channel_id}"


async def _send_and_record(
    *,
    db: Database,
    send_dm: SendDmFn,
    user_id: int,
    channel_id: int,
    message_id: int,
    body: str,
    photo: bytes | None,
    summary: Summary,
    delete_at: int | None,
    now_ts: int,
    send_kwargs: dict,
) -> None:
    bot_msg_id = await send_dm(user_id, body, photo, **send_kwargs)
    with db.transaction():
        if bot_msg_id is not None:
            db.record_delivered(
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                bot_message_id=bot_msg_id,
                is_photo=photo is not None,
                body=body,
                now=now_ts,
                delete_at=delete_at,
            )
        db.add_usage(
            user_id=user_id,
            provider=summary.provider,
            input_tokens=summary.input_tokens,
            output_tokens=summary.output_tokens,
        )


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
    embed_fn: EmbedFn | None = None,
    edit_dm: EditDmFn | None = None,
    photo: bytes | None = None,
    dedup_threshold: float = 0.85,
    dedup_window_seconds: int = 48 * 3600,
    miniapp_tg_deeplink: str | None = None,
    now: int | None = None,
) -> None:
    if not text.strip():
        log.info("skip post %s/%s: empty text", channel_id, message_id)
        return
    if not db.mark_seen(channel_id=channel_id, message_id=message_id):
        log.info("skip post %s/%s: already seen", channel_id, message_id)
        return
    subscribers = db.subscribers_for_channel(channel_id=channel_id)
    if not subscribers:
        log.info("skip post %s/%s: no subscribers", channel_id, message_id)
        return

    recipients: list[tuple[int, str, bool]] = []
    for user_id, mode in subscribers:
        if mode == SubscriptionMode.ALL:
            recipients.append((user_id, mode, False))
            continue
        filter_prompt = db.get_channel_filter(user_id=user_id, channel_id=channel_id)
        if not filter_prompt:
            recipients.append((user_id, mode, False))
            continue
        check = await is_relevant_fn(text, filter_prompt)
        db.add_system_usage(
            provider=check.provider,
            input_tokens=check.input_tokens,
            output_tokens=check.output_tokens,
        )
        db.add_usage(
            user_id=user_id,
            provider=check.provider,
            input_tokens=check.input_tokens,
            output_tokens=check.output_tokens,
        )
        if check.relevant:
            recipients.append((user_id, mode, False))
        elif mode == SubscriptionMode.DEBUG:
            recipients.append((user_id, mode, True))
        else:
            log.info("filter excluded user=%s for post %s/%s", user_id, channel_id, message_id)

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
        provider=summary.provider,
        input_tokens=summary.input_tokens,
        output_tokens=summary.output_tokens,
    )
    if not summary.text.strip():
        log.warning(
            "skip post %s/%s: empty summary (provider=%s in=%d out=%d) — "
            "model produced no text",
            channel_id, message_id, summary.provider,
            summary.input_tokens, summary.output_tokens,
        )
        return

    emb: Embedding | None = None
    if embed_fn is not None:
        try:
            emb = await embed_fn(summary.text)
        except (RemoteProcessorError, RemoteProcessorTimeout) as exc:
            log.warning(
                "embed unavailable for post %s/%s, skipping dedup: %s",
                channel_id, message_id, exc,
            )
        else:
            db.add_embedding_usage(provider=emb.provider, tokens=emb.tokens)

    now_ts = int(time.time()) if now is None else now
    channel_title = db.get_channel_title(channel_id) or ""
    settings_url = _channel_settings_url(miniapp_tg_deeplink, channel_id)

    for user_id, mode, marked_filter in recipients:
        lang = db.get_language(user_id)
        marker = t(lang, "debug_filtered_marker") if marked_filter else None
        settings_label = (
            t(lang, "channel_settings_link") if settings_url else None
        )
        body = _format_post(
            channel_title, summary.text, link, marker,
            settings_url=settings_url, settings_label=settings_label,
        )
        auto_hours = db.get_user_auto_delete_hours(user_id)
        save_label = t(lang, "save_button") if auto_hours is not None else None
        send_delete_at = (
            now_ts + auto_hours * 3600 if auto_hours is not None else None
        )

        duplicate = (
            find_duplicate(
                db=db,
                user_id=user_id,
                vec=emb.vector,
                threshold=dedup_threshold,
                window_seconds=dedup_window_seconds,
                now=now_ts,
            )
            if emb is not None
            else None
        )

        send_kwargs = {"save_button": save_label} if save_label is not None else {}

        dedup_debug = duplicate is not None and db.get_dedup_debug(user_id)

        if duplicate is not None and dedup_debug:
            dup_marker = t(lang, "debug_duplicate_marker")
            orig_title = db.get_channel_title(duplicate.channel_id) or ""
            tail_html = _original_link_html(
                t(lang, "original_label"), orig_title, duplicate.link,
            )
            body = _format_post(
                channel_title, summary.text, link, dup_marker, tail=tail_html,
                settings_url=settings_url, settings_label=settings_label,
            )
            await _send_and_record(
                db=db, send_dm=send_dm, user_id=user_id,
                channel_id=channel_id, message_id=message_id,
                body=body, photo=photo, summary=summary,
                delete_at=send_delete_at, now_ts=now_ts,
                send_kwargs=send_kwargs,
            )
        elif duplicate is not None and edit_dm is not None:
            new_dup_links = duplicate.dup_links + [(channel_title, link)]
            prev_state = db.get_delivered_save_state(
                user_id=user_id,
                channel_id=duplicate.channel_id,
                message_id=duplicate.message_id,
            )
            prev_saved = prev_state[0] if prev_state else False
            had_button = prev_state is not None and (
                prev_saved or prev_state[1] is not None
            )
            chain_label = (
                t(lang, "saved_button") if prev_saved
                else t(lang, "save_button") if had_button
                else None
            )
            edit_kwargs = (
                {"save_button": chain_label} if chain_label is not None else {}
            )
            await edit_dm(
                user_id, duplicate.bot_message_id, new_dup_links, **edit_kwargs,
            )
            with db.transaction():
                db.set_delivered_dup_links(
                    user_id=user_id,
                    channel_id=duplicate.channel_id,
                    message_id=duplicate.message_id,
                    dup_links=new_dup_links,
                )
                if auto_hours is not None:
                    db.extend_delivered_delete_at(
                        user_id=user_id,
                        channel_id=duplicate.channel_id,
                        message_id=duplicate.message_id,
                        delete_at=now_ts + auto_hours * 3600,
                    )
                db.add_usage(
                    user_id=user_id,
                    provider=summary.provider,
                    input_tokens=summary.input_tokens,
                    output_tokens=summary.output_tokens,
                )
        else:
            await _send_and_record(
                db=db, send_dm=send_dm, user_id=user_id,
                channel_id=channel_id, message_id=message_id,
                body=body, photo=photo, summary=summary,
                delete_at=send_delete_at, now_ts=now_ts,
                send_kwargs=send_kwargs,
            )

    if emb is not None:
        db.store_post_embedding(
            channel_id=channel_id,
            message_id=message_id,
            embedding=emb.vector,
            summary=summary.text,
            link=link,
            now=now_ts,
        )


async def prune_orphan_channels(
    *, db: Database, send_dm: SendDmFn,
) -> tuple[int, int]:
    """Delete channels with no remaining provider; DM their subscribers.

    Returns ``(removed_count, notified_count)``.
    """
    orphan_ids = db.channels_with_no_provider()
    removed = 0
    notified = 0
    for channel_id in orphan_ids:
        title = db.get_channel_title(channel_id) or ""
        subs = db.subscribers_for_channel(channel_id=channel_id)
        for user_id, _mode in subs:
            lang = db.get_language(user_id)
            await send_dm(
                user_id, t(lang, "channel_gone", title=title),
            )
        notified += len(subs)
        db.delete_channel(channel_id=channel_id)
        removed += 1
    return removed, notified


async def notify_subscribers_of_lost_visibility(
    *,
    db: Database,
    send_dm: SendDmFn,
    visible_before: set[int],
) -> int:
    """DM `channel_gone` to subscribers of channels that were visible
    before a blacklist action and aren't any more. Returns the number of
    DMs sent. Idempotent at the transition: only channels in
    `visible_before` but not in the current visible set are notified.
    Does not delete channels — they keep their `provider_channels` rows
    and can return when un-blacklisted.
    """
    visible_after = {c.id for c in db.list_visible_channels()}
    lost = visible_before - visible_after
    sent = 0
    for channel_id in lost:
        title = db.get_channel_title(channel_id) or ""
        subs = db.list_subscribed_users_for_channel(channel_id=channel_id)
        for user_id, _mode in subs:
            lang = db.get_language(user_id)
            await send_dm(
                user_id, t(lang, "channel_gone", title=title),
            )
        sent += len(subs)
    return sent


async def refresh_channels(
    *,
    fetch_fn_for: FetchChannelsForFn,
    provider_user_ids: list[int],
    db: Database,
    send_dm: SendDmFn,
    announce_new_channel: AnnounceNewChannelFn | None = None,
    inter_provider_sleep: float = 2.0,
) -> None:
    """Refresh the multi-provider channel index.

    For each approved provider:
      - fetch their subscribed channels via `fetch_fn_for(provider_id)`,
      - upsert each into `channels` (titles/usernames stay fresh),
      - replace `provider_channels(provider_id, *)` with the fetched ids.

    Then any channel left without a provider is deleted as an orphan (its
    subscribers are DM'd `channel_gone`). New channels — those that didn't
    exist on entry — are announced to all approved bot users via
    `announce_new_channel`. A short sleep between providers caps total RPS
    against Telegram from amplified flood-waits.
    """
    known_before_ids = {c.id for c in db.list_channels(include_blacklisted=True)}
    seen_titles: dict[int, str] = {}

    for idx, provider_id in enumerate(provider_user_ids):
        if idx > 0 and inter_provider_sleep > 0:
            await asyncio.sleep(inter_provider_sleep)
        try:
            fresh = await fetch_fn_for(provider_id)
        except Exception:
            log.exception(
                "refresh: fetch failed for provider=%s, skipping", provider_id,
            )
            continue
        log.debug(
            "refresh: provider=%s reported %d channel(s)", provider_id, len(fresh),
        )
        for channel_id, title, username, about in fresh:
            db.upsert_channel(
                channel_id=channel_id, title=title, username=username, about=about,
            )
            seen_titles[channel_id] = title
        db.set_provider_channels(
            provider_user_id=provider_id,
            channel_ids={tup[0] for tup in fresh},
        )

    # Orphans: channels left with no provider after every provider's set
    # was replaced.
    removed, notified = await prune_orphan_channels(db=db, send_dm=send_dm)

    announced = 0
    if announce_new_channel is not None and known_before_ids:
        new_ids = sorted(set(seen_titles) - known_before_ids)
        if new_ids:
            approved = db.list_approved_user_ids()
            for channel_id in new_ids:
                title = seen_titles[channel_id]
                for user_id in approved:
                    await announce_new_channel(user_id, channel_id, title)
                    announced += 1

    log.info(
        "refresh done: %d provider(s), %d removed, %d subscriber(s) notified, "
        "%d announcement(s) sent",
        len(provider_user_ids), removed, notified, announced,
    )
