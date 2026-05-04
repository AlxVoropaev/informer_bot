import logging
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from informer_bot.db import Database
from informer_bot.i18n import t
from informer_bot.pipeline import (
    AnnounceNewChannelFn,
    FetchChannelsFn,
    SendDmFn,
    refresh_channels,
)
from informer_bot.summarizer import estimate_cost_usd, estimate_embedding_cost_usd

log = logging.getLogger(__name__)


@dataclass
class BotState:
    """All long-lived deps the PTB handlers need from main.py.

    Stored in `app.bot_data["state"]` to keep handler signatures clean.
    """

    db: Database
    owner_id: int
    miniapp_url: str | None
    fetch_channels: FetchChannelsFn
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


def _user_label(user) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return f"{user.first_name} ({user.id})"
    return str(user.id)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log.debug("/help from user=%s", user_id)
    lang = _lang(context, user_id)
    text = t(lang, "user_help")
    if user_id == _owner_id(context):
        text += t(lang, "owner_help_extra")
    await update.message.reply_text(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user = update.effective_user
    log.debug("/start from user=%s", user.id)
    status = db.get_user_status(user.id)
    lang = db.get_language(user.id)

    if status == "approved":
        await update.message.reply_text(t(lang, "greeting"))
        return
    if status == "pending":
        await update.message.reply_text(t(lang, "still_pending"))
        return
    if status == "denied":
        await update.message.reply_text(t(lang, "access_denied"))
        return

    db.add_pending_user(
        user_id=user.id, username=user.username, first_name=user.first_name
    )
    log.info("new access request from user=%s (%s)", user.id, _user_label(user))
    await update.message.reply_text(t(lang, "pending"))
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
    user_id = update.effective_user.id
    lang = _lang(context, user_id)
    if _db(context).get_user_status(user_id) != "approved":
        await update.message.reply_text(t(lang, "denied"))
        return
    url = _state(context).miniapp_url
    if not url:
        await update.message.reply_text(t(lang, "miniapp_unconfigured"))
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
        text=t(lang, "open_miniapp_button"), web_app=WebAppInfo(url=url),
    )]])
    await update.message.reply_text(t(lang, "miniapp_intro"), reply_markup=keyboard)


def _format_usage_line(label: str, input_tokens: int, output_tokens: int) -> str:
    cost = estimate_cost_usd(input_tokens, output_tokens)
    return f"{label}: in={input_tokens:,} out={output_tokens:,} ≈ ${cost:.4f}"


async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    log.debug("/usage from user=%s", user_id)
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(t(lang, "denied"))
        return

    if user_id == _owner_id(context):
        rows = db.list_all_usage()
        sys_in, sys_out = db.get_system_usage()
        emb_tokens = db.get_embedding_usage()
        lines = [t(lang, "usage_admin_header")]
        if rows:
            for _uid, label, inp, out in rows:
                lines.append(_format_usage_line(label, inp, out))
        else:
            lines.append(t(lang, "usage_admin_none"))
        lines.append("")
        lines.append(_format_usage_line(t(lang, "usage_admin_system_label"), sys_in, sys_out))
        lines.append(t(
            lang, "usage_admin_embedding_line",
            label=t(lang, "usage_admin_embedding_label"),
            tokens=emb_tokens,
            cost=estimate_embedding_cost_usd(emb_tokens),
        ))
        await update.message.reply_text("\n".join(lines))
        return

    inp, out = db.get_usage(user_id)
    cost = estimate_cost_usd(inp, out)
    await update.message.reply_text(
        t(lang, "usage_user_block", inp=inp, out=out, cost=cost)
    )


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = _lang(context, user_id)
    if user_id != _owner_id(context):
        log.info("/update denied for user=%s", user_id)
        await update.message.reply_text(t(lang, "denied"))
        return
    log.info("/update from owner=%s", user_id)
    await update.message.reply_text(t(lang, "refreshing"))
    state = _state(context)
    try:
        await refresh_channels(
            fetch_fn=state.fetch_channels,
            db=state.db,
            send_dm=state.send_dm,
            announce_new_channel=state.announce_new_channel,
        )
    except Exception:
        log.exception("/update refresh failed")
        await update.message.reply_text(t(lang, "refresh_failed"))
        return
    await update.message.reply_text(t(lang, "refresh_done"))


async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = _lang(context, user_id)
    if user_id != _owner_id(context):
        log.info("/blacklist denied for user=%s", user_id)
        await update.message.reply_text(t(lang, "denied"))
        return
    log.debug("/blacklist from owner=%s", user_id)
    context.user_data["bl_page"] = 0
    await update.message.reply_text(
        t(lang, "admin_pick_blacklist"),
        reply_markup=_admin_keyboard(_db(context), lang, page=0),
    )


async def on_blacklist_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = _lang(context, user_id)
    if user_id != _owner_id(context):
        log.info("blacklist done denied for user=%s", user_id)
        await update.callback_query.answer(t(lang, "denied"))
        return
    log.debug("/blacklist done by owner=%s", user_id)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(t(lang, "blacklist_closed"))


async def on_blacklist_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    if user_id != _owner_id(context):
        await update.callback_query.answer(t(lang, "denied"))
        return
    page = int(update.callback_query.data.split(":", 1)[1])
    context.user_data["bl_page"] = page
    await update.callback_query.answer()
    await update.callback_query.edit_message_reply_markup(
        reply_markup=_admin_keyboard(db, lang, page=page),
    )


async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    actor_id = update.effective_user.id
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("approve denied for user=%s", actor_id)
        await update.callback_query.answer(t(actor_lang, "denied"))
        return

    target_id = int(update.callback_query.data.split(":", 1)[1])
    db.set_user_status(user_id=target_id, status="approved")
    log.info("user=%s approved by owner", target_id)

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        t(actor_lang, "user_allowed", target=target_id)
    )
    target_lang = db.get_language(target_id)
    await context.bot.send_message(
        chat_id=target_id, text=t(target_lang, "approved_notice")
    )


async def on_deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    actor_id = update.effective_user.id
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("deny denied for user=%s", actor_id)
        await update.callback_query.answer(t(actor_lang, "denied"))
        return

    target_id = int(update.callback_query.data.split(":", 1)[1])
    db.set_user_status(user_id=target_id, status="denied")
    log.info("user=%s denied by owner", target_id)

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        t(actor_lang, "user_denied_msg", target=target_id)
    )
    target_lang = db.get_language(target_id)
    await context.bot.send_message(
        chat_id=target_id, text=t(target_lang, "access_denied")
    )


async def on_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    actor_id = update.effective_user.id
    actor_lang = db.get_language(actor_id)
    if actor_id != _owner_id(context):
        log.info("blacklist toggle denied for user=%s", actor_id)
        await update.callback_query.answer(t(actor_lang, "denied"))
        return

    channel_id = int(update.callback_query.data.split(":", 1)[1])
    channel = db.get_channel(channel_id)
    if channel is None:
        await update.callback_query.answer(t(actor_lang, "channel_unavailable"))
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

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        t(actor_lang, "admin_pick_blacklist"),
        reply_markup=_admin_keyboard(
            db, actor_lang, page=context.user_data.get("bl_page", 0)
        ),
    )


async def on_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
