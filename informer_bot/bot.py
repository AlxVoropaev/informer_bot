import logging
import os
import time
from dataclasses import dataclass

from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
    WebAppInfo,
)
from telegram.ext import ContextTypes

from informer_bot.db import Database, format_user_label
from informer_bot.i18n import t
from informer_bot.pipeline import (
    AnnounceNewChannelFn,
    FetchChannelsForFn,
    SendDmFn,
    refresh_channels,
)
from informer_bot.summarizer import estimate_cost_usd, estimate_embedding_cost_usd

log = logging.getLogger(__name__)


# PTB types `effective_user`/`message`/`callback_query` as Optional, but every
# handler here is registered behind a filter that guarantees they're set —
# these helpers narrow the type for mypy without scattering asserts.
def _user(update: Update) -> User:
    assert update.effective_user is not None
    return update.effective_user


def _message(update: Update) -> Message:
    assert update.message is not None
    return update.message


def _query(update: Update) -> CallbackQuery:
    assert update.callback_query is not None
    return update.callback_query


@dataclass
class BotState:
    """All long-lived deps the PTB handlers need from main.py.

    Stored in `app.bot_data["state"]` to keep handler signatures clean.
    """

    db: Database
    owner_id: int
    miniapp_url: str | None
    fetch_channels_for: FetchChannelsForFn
    provider_user_ids: list[int]
    send_dm: SendDmFn
    announce_new_channel: AnnounceNewChannelFn | None


def _state(context: ContextTypes.DEFAULT_TYPE) -> BotState:
    return context.bot_data["state"]


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return _state(context).db


def _owner_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return _state(context).owner_id


def _lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    return _db(context).get_language(user_id)


_PAGE_SIZE = 15


def _paginate(items: list, page: int) -> tuple[list, int, int]:
    total_pages = max(1, (len(items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * _PAGE_SIZE
    return items[start:start + _PAGE_SIZE], page, total_pages


def _nav_row(page: int, total_pages: int, prefix: str) -> list[InlineKeyboardButton] | None:
    if total_pages <= 1:
        return None
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton(text="◀", callback_data=f"{prefix}:{page - 1}"))
    row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text="▶", callback_data=f"{prefix}:{page + 1}"))
    return row


def _admin_keyboard(
    db: Database, lang: str, page: int = 0
) -> InlineKeyboardMarkup:
    page_items, _page, total_pages = _paginate(
        db.list_channels(include_blacklisted=True), page
    )
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text=f"{'⛔' if c.blacklisted else '✅'} {c.title}",
            callback_data=f"bl:{c.id}",
        )]
        for c in page_items
    ]
    nav = _nav_row(_page, total_pages, "blpage")
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=t(lang, "done_button"), callback_data="bl_done")])
    return InlineKeyboardMarkup(rows)


def _user_label(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return f"{user.first_name} ({user.id})"
    return str(user.id)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _user(update).id
    log.debug("/help from user=%s", user_id)
    lang = _lang(context, user_id)
    text = t(lang, "user_help")
    if user_id == _owner_id(context):
        text += t(lang, "owner_help_extra")
    await _message(update).reply_text(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user = _user(update)
    message = _message(update)
    log.debug("/start from user=%s", user.id)
    status = db.get_user_status(user.id)
    lang = db.get_language(user.id)

    if status == "approved":
        await message.reply_text(t(lang, "greeting"))
        return
    if status == "pending":
        await message.reply_text(t(lang, "still_pending"))
        return
    if status == "denied":
        await message.reply_text(t(lang, "access_denied"))
        return

    db.add_pending_user(
        user_id=user.id, username=user.username, first_name=user.first_name
    )
    log.info("new access request from user=%s (%s)", user.id, _user_label(user))
    await message.reply_text(t(lang, "pending"))
    owner_lang = db.get_language(_owner_id(context))
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(text=t(owner_lang, "approve_button"), callback_data=f"approve:{user.id}"),
        InlineKeyboardButton(text=t(owner_lang, "deny_button"), callback_data=f"deny:{user.id}"),
    ]])
    await context.bot.send_message(
        chat_id=_owner_id(context),
        text=t(owner_lang, "access_request", label=_user_label(user)),
        reply_markup=keyboard,
    )


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _user(update).id
    message = _message(update)
    lang = _lang(context, user_id)
    if _db(context).get_user_status(user_id) != "approved":
        await message.reply_text(t(lang, "denied"))
        return
    url = _state(context).miniapp_url
    if not url:
        await message.reply_text(t(lang, "miniapp_unconfigured"))
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
        text=t(lang, "open_miniapp_button"), web_app=WebAppInfo(url=url),
    )]])
    await message.reply_text(t(lang, "miniapp_intro"), reply_markup=keyboard)


def _format_chat_line(
    label: str, provider: str, input_tokens: int, output_tokens: int
) -> str:
    cost = estimate_cost_usd(provider, input_tokens, output_tokens)
    return (
        f"  {label}: in={input_tokens:,} out={output_tokens:,} ≈ ${cost:.4f}"
    )


def _format_embed_line(label: str, provider: str, tokens: int) -> str:
    cost = estimate_embedding_cost_usd(provider, tokens)
    return f"  {label}: tokens={tokens:,} ≈ ${cost:.4f}"


def _visible_chat_rows(
    rows: list[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    """Hide a zeroed-out 'unknown' bucket but keep nonzero legacy data."""
    return [
        (p, i, o) for p, i, o in rows
        if p != "unknown" or i != 0 or o != 0
    ]


def _visible_embed_rows(rows: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return [(p, t_) for p, t_ in rows if p != "unknown" or t_ != 0]


async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = _user(update).id
    message = _message(update)
    log.debug("/usage from user=%s", user_id)
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await message.reply_text(t(lang, "denied"))
        return

    if user_id == _owner_id(context):
        all_rows = db.list_all_usage()
        sys_rows = _visible_chat_rows(db.get_system_usage())
        emb_rows = _visible_embed_rows(db.get_embedding_usage())
        lines = [t(lang, "usage_admin_header")]
        if all_rows:
            current_uid: int | None = None
            for uid, username, first_name, provider, inp, out in all_rows:
                if provider == "unknown" and inp == 0 and out == 0:
                    continue
                if uid != current_uid:
                    current_uid = uid
                    lines.append(format_user_label(uid, username, first_name))
                lines.append(_format_chat_line(provider, provider, inp, out))
        else:
            lines.append(t(lang, "usage_admin_none"))
        lines.append("")
        lines.append(t(lang, "usage_admin_system_label"))
        if sys_rows:
            for provider, inp, out in sys_rows:
                lines.append(_format_chat_line(provider, provider, inp, out))
        else:
            lines.append(t(lang, "usage_admin_none"))
        lines.append("")
        lines.append(t(lang, "usage_admin_embedding_label"))
        if emb_rows:
            for provider, tokens in emb_rows:
                lines.append(_format_embed_line(provider, provider, tokens))
        else:
            lines.append(t(lang, "usage_admin_none"))
        await message.reply_text("\n".join(lines))
        return

    rows = _visible_chat_rows(db.get_usage(user_id))
    lines = [t(lang, "usage_user_header")]
    if rows:
        total_in = 0
        total_out = 0
        total_cost = 0.0
        for provider, inp, out in rows:
            lines.append(_format_chat_line(provider, provider, inp, out))
            total_in += inp
            total_out += out
            total_cost += estimate_cost_usd(provider, inp, out)
        lines.append(t(
            lang, "usage_user_total",
            inp=total_in, out=total_out, cost=total_cost,
        ))
    else:
        lines.append(t(lang, "usage_user_none"))
    await message.reply_text("\n".join(lines))


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _user(update).id
    message = _message(update)
    lang = _lang(context, user_id)
    if user_id != _owner_id(context):
        log.info("/update denied for user=%s", user_id)
        await message.reply_text(t(lang, "denied"))
        return
    log.info("/update from owner=%s", user_id)
    await message.reply_text(t(lang, "refreshing"))
    state = _state(context)
    try:
        await refresh_channels(
            fetch_fn_for=state.fetch_channels_for,
            provider_user_ids=state.provider_user_ids,
            db=state.db,
            send_dm=state.send_dm,
            announce_new_channel=state.announce_new_channel,
        )
    except Exception:
        log.exception("/update refresh failed")
        await message.reply_text(t(lang, "refresh_failed"))
        return
    await message.reply_text(t(lang, "refresh_done"))


async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _user(update).id
    message = _message(update)
    lang = _lang(context, user_id)
    if user_id != _owner_id(context):
        log.info("/blacklist denied for user=%s", user_id)
        await message.reply_text(t(lang, "denied"))
        return
    log.debug("/blacklist from owner=%s", user_id)
    assert context.user_data is not None
    context.user_data["bl_page"] = 0
    await message.reply_text(
        t(lang, "admin_pick_blacklist"),
        reply_markup=_admin_keyboard(_db(context), lang, page=0),
    )


async def on_blacklist_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _user(update).id
    query = _query(update)
    lang = _lang(context, user_id)
    if user_id != _owner_id(context):
        log.info("blacklist done denied for user=%s", user_id)
        await query.answer(t(lang, "denied"))
        return
    log.debug("/blacklist done by owner=%s", user_id)
    await query.answer()
    await query.edit_message_text(t(lang, "blacklist_closed"))


async def on_blacklist_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = _user(update).id
    query = _query(update)
    lang = db.get_language(user_id)
    if user_id != _owner_id(context):
        await query.answer(t(lang, "denied"))
        return
    assert isinstance(query.data, str)
    page = int(query.data.split(":", 1)[1])
    assert context.user_data is not None
    context.user_data["bl_page"] = page
    await query.answer()
    await query.edit_message_reply_markup(
        reply_markup=_admin_keyboard(db, lang, page=page),
    )


async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    actor_id = _user(update).id
    query = _query(update)
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("approve denied for user=%s", actor_id)
        await query.answer(t(actor_lang, "denied"))
        return

    assert isinstance(query.data, str)
    target_id = int(query.data.split(":", 1)[1])
    db.set_user_status(user_id=target_id, status="approved")
    log.info("user=%s approved by owner", target_id)

    await query.answer()
    await query.edit_message_text(
        t(actor_lang, "user_allowed", target=target_id)
    )
    target_lang = db.get_language(target_id)
    await context.bot.send_message(
        chat_id=target_id, text=t(target_lang, "approved_notice")
    )


async def on_deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    actor_id = _user(update).id
    query = _query(update)
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("deny denied for user=%s", actor_id)
        await query.answer(t(actor_lang, "denied"))
        return

    assert isinstance(query.data, str)
    target_id = int(query.data.split(":", 1)[1])
    db.set_user_status(user_id=target_id, status="denied")
    log.info("user=%s denied by owner", target_id)

    await query.answer()
    await query.edit_message_text(
        t(actor_lang, "user_denied_msg", target=target_id)
    )
    target_lang = db.get_language(target_id)
    await context.bot.send_message(
        chat_id=target_id, text=t(target_lang, "access_denied")
    )


async def on_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    actor_id = _user(update).id
    query = _query(update)
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("blacklist toggle denied for user=%s", actor_id)
        await query.answer(t(actor_lang, "denied"))
        return

    assert isinstance(query.data, str)
    channel_id = int(query.data.split(":", 1)[1])
    channel = db.get_channel(channel_id)
    if channel is None:
        await query.answer(t(actor_lang, "channel_unavailable"))
        return
    will_blacklist = not channel.blacklisted

    if will_blacklist:
        subs = db.subscribers_for_channel(channel_id=channel_id)
        for user_id, _mode in subs:
            sub_lang = db.get_language(user_id)
            await context.bot.send_message(
                chat_id=user_id,
                text=t(sub_lang, "channel_blocked", title=channel.title),
            )
        log.info(
            "blacklisting channel=%s '%s' (%d subscriber(s) notified)",
            channel_id, channel.title, len(subs),
        )
    else:
        log.info("un-blacklisting channel=%s '%s'", channel_id, channel.title)

    db.set_blacklisted(channel_id=channel_id, blacklisted=will_blacklist)

    await query.answer()
    page = (context.user_data or {}).get("bl_page", 0)
    await query.edit_message_text(
        t(actor_lang, "admin_pick_blacklist"),
        reply_markup=_admin_keyboard(db, actor_lang, page=page),
    )


async def on_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _query(update).answer()


def build_dm_keyboard(
    dup_links: list[tuple[str, str]],
    save_button_label: str | None,
) -> InlineKeyboardMarkup | None:
    """Compose the inline keyboard for a delivered DM.

    Order: one URL-button row per dup link, then the Save/Saved row when
    auto-delete is wired up for this message. Returns None when nothing
    should be attached so callers can pass it straight to PTB.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=title, url=link)] for title, link in dup_links
    ]
    if save_button_label is not None:
        rows.append([InlineKeyboardButton(
            text=save_button_label, callback_data="save",
        )])
    return InlineKeyboardMarkup(rows) if rows else None


async def on_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = _user(update).id
    query = _query(update)
    lang = db.get_language(user_id)
    msg = query.message
    if msg is None:
        await query.answer()
        return
    bot_message_id = msg.message_id
    row = db.get_delivered_by_bot_msg(
        user_id=user_id, bot_message_id=bot_message_id,
    )
    if row is None:
        # Message expired or never tracked — silently ack.
        await query.answer()
        return
    channel_id, message_id, _is_photo, saved, _delete_at = row
    new_saved = not saved
    if new_saved:
        new_delete_at: int | None = None
    else:
        hours = db.get_user_auto_delete_hours(user_id)
        new_delete_at = (
            int(time.time()) + hours * 3600 if hours is not None else None
        )
    db.set_delivered_saved(
        user_id=user_id, channel_id=channel_id, message_id=message_id,
        saved=new_saved, delete_at=new_delete_at,
    )
    label = t(lang, "saved_button" if new_saved else "save_button")
    dup_links = db.get_delivered_dup_links(
        user_id=user_id, channel_id=channel_id, message_id=message_id,
    )
    keyboard = build_dm_keyboard(dup_links, label)
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except Exception:
        log.exception(
            "save toggle: edit failed user=%s msg=%s", user_id, bot_message_id,
        )
    await query.answer()


# ---------- providers ----------

async def cmd_become_provider(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    db = _db(context)
    user_id = _user(update).id
    message = _message(update)
    lang = db.get_language(user_id)
    log.debug("/become_provider from user=%s", user_id)

    if db.get_user_status(user_id) != "approved":
        await message.reply_text(t(lang, "denied"))
        return

    if user_id == _owner_id(context):
        await message.reply_text(t(lang, "provider_owner_already"))
        return

    existing = db.get_provider(user_id)
    if existing is not None:
        if existing.status == "pending":
            await message.reply_text(t(lang, "provider_already_pending"))
            return
        if existing.status == "approved":
            await message.reply_text(t(lang, "provider_already_approved"))
            return
        if existing.status == "denied":
            await message.reply_text(t(lang, "provider_request_denied"))
            return

    session_path = f"data/sessions/{user_id}.session"
    db.add_pending_provider(user_id=user_id, session_path=session_path)
    log.info("provider request from user=%s", user_id)

    owner_id = _owner_id(context)
    owner_lang = db.get_language(owner_id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text=t(owner_lang, "provider_approve_button"),
            callback_data=f"provider_approve:{user_id}",
        ),
        InlineKeyboardButton(
            text=t(owner_lang, "provider_deny_button"),
            callback_data=f"provider_deny:{user_id}",
        ),
    ]])
    await context.bot.send_message(
        chat_id=owner_id,
        text=t(
            owner_lang, "provider_request_admin",
            user_label=db.get_user_label(user_id),
        ),
        reply_markup=keyboard,
    )
    await message.reply_text(t(lang, "provider_request_submitted"))


async def on_provider_approve(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    db = _db(context)
    actor_id = _user(update).id
    query = _query(update)
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("provider approve denied for user=%s", actor_id)
        await query.answer(t(actor_lang, "denied"))
        return

    assert isinstance(query.data, str)
    target_id = int(query.data.split(":", 1)[1])
    db.set_provider_status(user_id=target_id, status="approved")
    log.info("provider user=%s approved by owner", target_id)

    await query.answer()
    await query.edit_message_text(t(
        actor_lang, "provider_approved_owner",
        user_label=db.get_user_label(target_id),
    ))
    target_lang = db.get_language(target_id)
    await context.bot.send_message(
        chat_id=target_id, text=t(target_lang, "provider_approved_user"),
    )


async def on_provider_deny(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    db = _db(context)
    actor_id = _user(update).id
    query = _query(update)
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("provider deny denied for user=%s", actor_id)
        await query.answer(t(actor_lang, "denied"))
        return

    assert isinstance(query.data, str)
    target_id = int(query.data.split(":", 1)[1])
    db.set_provider_status(user_id=target_id, status="denied")
    log.info("provider user=%s denied by owner", target_id)

    await query.answer()
    await query.edit_message_text(t(
        actor_lang, "provider_denied_owner",
        user_label=db.get_user_label(target_id),
    ))
    target_lang = db.get_language(target_id)
    await context.bot.send_message(
        chat_id=target_id, text=t(target_lang, "provider_denied_user"),
    )


async def cmd_revoke_provider(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    db = _db(context)
    actor_id = _user(update).id
    message = _message(update)
    lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("/revoke_provider denied for user=%s", actor_id)
        await message.reply_text(t(lang, "denied"))
        return

    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.reply_text(t(lang, "revoke_invalid_id"))
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.reply_text(t(lang, "revoke_invalid_id"))
        return

    if target_id == _owner_id(context):
        await message.reply_text(t(lang, "revoke_cannot_revoke_owner"))
        return

    provider = db.get_provider(target_id)
    if provider is None:
        await message.reply_text(t(lang, "revoke_not_a_provider"))
        return

    target_label = db.get_user_label(target_id)
    db.delete_provider(target_id)
    try:
        os.unlink(provider.session_path)
        log.info(
            "revoked provider user=%s, removed session %s",
            target_id, provider.session_path,
        )
    except FileNotFoundError:
        log.info(
            "revoked provider user=%s, session file %s was already gone",
            target_id, provider.session_path,
        )
    except OSError:
        log.exception(
            "revoke_provider: failed to remove session %s for user=%s",
            provider.session_path, target_id,
        )

    # TODO(integration): once Subagent B lands `pipeline.prune_orphan_channels`,
    # call it here to drop channels that no remaining approved provider sees
    # and to DM affected subscribers.

    target_lang = db.get_language(target_id)
    try:
        await context.bot.send_message(
            chat_id=target_id, text=t(target_lang, "provider_revoked_user"),
        )
    except Exception:
        log.exception(
            "revoke_provider: failed to DM revoked user=%s", target_id,
        )
    await message.reply_text(t(
        lang, "provider_revoked_owner", user_label=target_label,
    ))
