import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from informer_bot.db import Database

log = logging.getLogger(__name__)

GREETING = "Hi, I'm informer. Use /list to pick channels to follow."
DENIED = "Not allowed."


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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.debug("/start from user=%s", update.effective_user.id)
    await update.message.reply_text(GREETING)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    log.debug("/list from user=%s", update.effective_user.id)
    await update.message.reply_text(
        "Pick channels:",
        reply_markup=_user_keyboard(db, update.effective_user.id),
    )


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
