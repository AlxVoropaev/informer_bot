import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from informer_bot.db import Database
from informer_bot.summarizer import estimate_cost_usd

log = logging.getLogger(__name__)

GREETING = "Hi, I'm informer. Use /list to pick channels to follow."
DENIED = "Not allowed."
PENDING = "Your request has been sent to the administrator. Please wait."
STILL_PENDING = "Still waiting for the administrator's approval."
ACCESS_DENIED = "Sorry, you are not allowed to use this bot."
APPROVED_NOTICE = "You are approved! " + GREETING


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def _owner_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.bot_data["owner_id"]


def _user_keyboard(db: Database, user_id: int) -> InlineKeyboardMarkup:
    subs = set(db.list_user_subscriptions(user_id))
    rows = [
        [InlineKeyboardButton(
            text=f"{'✅' if c.id in subs else '⬜'} {c.title}",
            callback_data=f"toggle:{c.id}",
        )]
        for c in db.list_channels()
    ]
    rows.append([InlineKeyboardButton(text="Done", callback_data="done")])
    return InlineKeyboardMarkup(rows)


def _admin_keyboard(db: Database) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{'⛔' if c.blacklisted else '✅'} {c.title}",
            callback_data=f"bl:{c.id}",
        )]
        for c in db.list_channels(include_blacklisted=True)
    ]
    return InlineKeyboardMarkup(rows)


def _user_label(user) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return f"{user.first_name} ({user.id})"
    return str(user.id)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user = update.effective_user
    log.debug("/start from user=%s", user.id)
    status = db.get_user_status(user.id)

    if status == "approved":
        await update.message.reply_text(GREETING)
        return
    if status == "pending":
        await update.message.reply_text(STILL_PENDING)
        return
    if status == "denied":
        await update.message.reply_text(ACCESS_DENIED)
        return

    db.add_pending_user(
        user_id=user.id, username=user.username, first_name=user.first_name
    )
    log.info("new access request from user=%s (%s)", user.id, _user_label(user))
    await update.message.reply_text(PENDING)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(text="✅ Allow", callback_data=f"approve:{user.id}"),
        InlineKeyboardButton(text="⛔ Deny", callback_data=f"deny:{user.id}"),
    ]])
    await context.bot.send_message(
        chat_id=_owner_id(context),
        text=f"Access request from {_user_label(user)}",
        reply_markup=keyboard,
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    log.debug("/list from user=%s", user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(DENIED)
        return
    await update.message.reply_text(
        "Pick channels:",
        reply_markup=_user_keyboard(db, user_id),
    )


def _format_usage_line(label: str, input_tokens: int, output_tokens: int) -> str:
    cost = estimate_cost_usd(input_tokens, output_tokens)
    return f"{label}: in={input_tokens:,} out={output_tokens:,} ≈ ${cost:.4f}"


async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    log.debug("/usage from user=%s", user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(DENIED)
        return

    if user_id == _owner_id(context):
        rows = db.list_all_usage()
        sys_in, sys_out = db.get_system_usage()
        lines = ["Usage by user (delivered):"]
        if rows:
            for _uid, label, inp, out in rows:
                lines.append(_format_usage_line(label, inp, out))
        else:
            lines.append("(none yet)")
        lines.append("")
        lines.append(_format_usage_line("System total (actual API spend)", sys_in, sys_out))
        await update.message.reply_text("\n".join(lines))
        return

    inp, out = db.get_usage(user_id)
    cost = estimate_cost_usd(inp, out)
    await update.message.reply_text(
        f"Your usage:\n"
        f"Input tokens: {inp:,}\n"
        f"Output tokens: {out:,}\n"
        f"Estimated cost: ${cost:.4f}"
    )


FILTER_HELP = (
    "Send /filter <text> to set what you want to read. "
    "Send /filter clear to remove your filter (deliver everything). "
    "Send /filter alone to see your current filter."
)


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    log.debug("/filter from user=%s", user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(DENIED)
        return

    args_text = (update.message.text or "").split(maxsplit=1)
    if len(args_text) < 2:
        current = db.get_filter(user_id=user_id)
        if current:
            await update.message.reply_text(f"Your filter:\n{current}\n\n{FILTER_HELP}")
        else:
            await update.message.reply_text(f"No filter set — you receive everything.\n\n{FILTER_HELP}")
        return

    payload = args_text[1].strip()
    if payload.lower() == "clear":
        db.set_filter(user_id=user_id, filter_prompt=None)
        log.info("user=%s cleared filter", user_id)
        await update.message.reply_text("Filter cleared. You will receive everything.")
        return

    db.set_filter(user_id=user_id, filter_prompt=payload)
    log.info("user=%s updated filter (%d chars)", user_id, len(payload))
    await update.message.reply_text(f"Filter saved:\n{payload}")


async def cmd_admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != _owner_id(context):
        log.info("/admin_list denied for user=%s", update.effective_user.id)
        await update.message.reply_text(DENIED)
        return
    log.debug("/admin_list from owner=%s", update.effective_user.id)
    await update.message.reply_text(
        "Admin: tap to toggle blacklist.",
        reply_markup=_admin_keyboard(_db(context)),
    )


async def on_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    channel_id = int(update.callback_query.data.split(":", 1)[1])

    if db.get_user_status(user_id) != "approved":
        log.info("toggle rejected: user=%s not approved", user_id)
        await update.callback_query.answer(DENIED)
        return

    visible_ids = {c.id for c in db.list_channels()}
    if channel_id not in visible_ids:
        log.info("toggle rejected: user=%s channel=%s unavailable", user_id, channel_id)
        await update.callback_query.answer("Channel unavailable.")
        return

    if db.is_subscribed(user_id, channel_id):
        db.unsubscribe(user_id, channel_id)
        log.info("user=%s unsubscribed from channel=%s", user_id, channel_id)
    else:
        db.subscribe(user_id, channel_id)
        log.info("user=%s subscribed to channel=%s", user_id, channel_id)

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Pick channels:",
        reply_markup=_user_keyboard(db, user_id),
    )


async def on_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.debug("/list done by user=%s", update.effective_user.id)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Channel selection saved.")


async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != _owner_id(context):
        log.info("approve denied for user=%s", update.effective_user.id)
        await update.callback_query.answer(DENIED)
        return

    db = _db(context)
    target_id = int(update.callback_query.data.split(":", 1)[1])
    db.set_user_status(user_id=target_id, status="approved")
    log.info("user=%s approved by owner", target_id)

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(f"Allowed user {target_id}.")
    await context.bot.send_message(chat_id=target_id, text=APPROVED_NOTICE)


async def on_deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != _owner_id(context):
        log.info("deny denied for user=%s", update.effective_user.id)
        await update.callback_query.answer(DENIED)
        return

    db = _db(context)
    target_id = int(update.callback_query.data.split(":", 1)[1])
    db.set_user_status(user_id=target_id, status="denied")
    log.info("user=%s denied by owner", target_id)

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(f"Denied user {target_id}.")
    await context.bot.send_message(chat_id=target_id, text=ACCESS_DENIED)


async def on_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != _owner_id(context):
        log.info("blacklist toggle denied for user=%s", update.effective_user.id)
        await update.callback_query.answer(DENIED)
        return

    db = _db(context)
    channel_id = int(update.callback_query.data.split(":", 1)[1])
    [channel] = [c for c in db.list_channels(include_blacklisted=True) if c.id == channel_id]
    will_blacklist = not channel.blacklisted

    if will_blacklist:
        subs = db.subscribers_for_channel(channel_id=channel_id)
        for user_id in subs:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Channel '{channel.title}' is no longer available.",
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
        "Admin: tap to toggle blacklist.",
        reply_markup=_admin_keyboard(db),
    )
