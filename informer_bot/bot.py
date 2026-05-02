import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from informer_bot.db import Database
from informer_bot.i18n import LANGUAGE_NAMES, LANGUAGES, t
from informer_bot.pipeline import refresh_channels
from informer_bot.summarizer import estimate_cost_usd

log = logging.getLogger(__name__)


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def _owner_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.bot_data["owner_id"]


def _lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    return _db(context).get_language(user_id)


_MODE_EMOJI = {None: "⬜", "filtered": "🔀", "all": "✅"}
_NEXT_MODE = {None: "filtered", "filtered": "all", "all": None}


def _user_keyboard(db: Database, user_id: int, lang: str) -> InlineKeyboardMarkup:
    modes = db.list_user_subscription_modes(user_id)
    rows = [
        [InlineKeyboardButton(
            text=f"{_MODE_EMOJI[modes.get(c.id)]} {c.title}",
            callback_data=f"toggle:{c.id}",
        )]
        for c in db.list_channels()
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "done_button"), callback_data="done")])
    return InlineKeyboardMarkup(rows)


def _admin_keyboard(db: Database, lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{'⛔' if c.blacklisted else '✅'} {c.title}",
            callback_data=f"bl:{c.id}",
        )]
        for c in db.list_channels(include_blacklisted=True)
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "done_button"), callback_data="bl_done")])
    return InlineKeyboardMarkup(rows)


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text=LANGUAGE_NAMES[code], callback_data=f"lang:{code}")]
        for code in LANGUAGES
    ])


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


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    log.debug("/list from user=%s", user_id)
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(t(lang, "denied"))
        return
    await update.message.reply_text(
        t(lang, "pick_channels"),
        reply_markup=_user_keyboard(db, user_id, lang),
    )


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
        lines = [t(lang, "usage_admin_header")]
        if rows:
            for _uid, label, inp, out in rows:
                lines.append(_format_usage_line(label, inp, out))
        else:
            lines.append(t(lang, "usage_admin_none"))
        lines.append("")
        lines.append(_format_usage_line(t(lang, "usage_admin_system_label"), sys_in, sys_out))
        await update.message.reply_text("\n".join(lines))
        return

    inp, out = db.get_usage(user_id)
    cost = estimate_cost_usd(inp, out)
    await update.message.reply_text(
        t(lang, "usage_user_block", inp=inp, out=out, cost=cost)
    )


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    log.debug("/filter from user=%s", user_id)
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(t(lang, "denied"))
        return

    args_text = (update.message.text or "").split(maxsplit=1)
    filter_help = t(lang, "filter_help")
    if len(args_text) < 2:
        current = db.get_filter(user_id=user_id)
        if current:
            await update.message.reply_text(
                t(lang, "filter_current", filter=current, help=filter_help)
            )
        else:
            await update.message.reply_text(t(lang, "filter_none", help=filter_help))
        return

    payload = args_text[1].strip()
    if payload.lower() == "clear":
        db.set_filter(user_id=user_id, filter_prompt=None)
        log.info("user=%s cleared filter", user_id)
        await update.message.reply_text(t(lang, "filter_cleared"))
        return

    db.set_filter(user_id=user_id, filter_prompt=payload)
    log.info("user=%s updated filter (%d chars)", user_id, len(payload))
    await update.message.reply_text(t(lang, "filter_saved", filter=payload))


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log.debug("/language from user=%s", user_id)
    lang = _lang(context, user_id)
    await update.message.reply_text(
        t(lang, "language_prompt", current=LANGUAGE_NAMES[lang]),
        reply_markup=_language_keyboard(),
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
    try:
        await refresh_channels(
            fetch_fn=context.bot_data["fetch_channels"],
            db=_db(context),
            send_dm=context.bot_data["send_dm"],
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
    await update.message.reply_text(
        t(lang, "admin_pick_blacklist"),
        reply_markup=_admin_keyboard(_db(context), lang),
    )


async def on_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    channel_id = int(update.callback_query.data.split(":", 1)[1])

    if db.get_user_status(user_id) != "approved":
        log.info("toggle rejected: user=%s not approved", user_id)
        await update.callback_query.answer(t(lang, "denied"))
        return

    visible_ids = {c.id for c in db.list_channels()}
    if channel_id not in visible_ids:
        log.info("toggle rejected: user=%s channel=%s unavailable", user_id, channel_id)
        await update.callback_query.answer(t(lang, "channel_unavailable"))
        return

    current = db.get_subscription_mode(user_id, channel_id)
    next_mode = _NEXT_MODE[current]
    if next_mode is None:
        db.unsubscribe(user_id, channel_id)
    else:
        db.subscribe(user_id, channel_id, mode=next_mode)
    log.info("user=%s channel=%s mode %s -> %s", user_id, channel_id, current, next_mode)

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        t(lang, "pick_channels"),
        reply_markup=_user_keyboard(db, user_id, lang),
    )


async def on_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log.debug("/list done by user=%s", user_id)
    lang = _lang(context, user_id)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(t(lang, "selection_saved"))


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
    [channel] = [c for c in db.list_channels(include_blacklisted=True) if c.id == channel_id]
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
        reply_markup=_admin_keyboard(db, actor_lang),
    )


async def on_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    code = update.callback_query.data.split(":", 1)[1]
    if code not in LANGUAGES:
        await update.callback_query.answer()
        return
    db.set_language(user_id=user_id, language=code)
    log.info("user=%s language -> %s", user_id, code)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        t(code, "language_prompt", current=LANGUAGE_NAMES[code])
    )
