import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from informer_bot.db import Database
from informer_bot.i18n import LANGUAGE_NAMES, LANGUAGES, t
from informer_bot.pipeline import refresh_channels
from informer_bot.summarizer import estimate_cost_usd, estimate_embedding_cost_usd

log = logging.getLogger(__name__)


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def _owner_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.bot_data["owner_id"]


def _lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    return _db(context).get_language(user_id)


_MODE_EMOJI = {None: "⬜", "off": "⬜", "filtered": "🔀", "debug": "🐞", "all": "✅"}

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


def _user_keyboard(
    db: Database, user_id: int, lang: str, page: int = 0
) -> InlineKeyboardMarkup:
    modes = db.list_user_subscription_modes(user_id)
    filters = db.list_user_subscription_filters(user_id)
    page_items, _page, total_pages = _paginate(db.list_channels(), page)
    rows: list[list[InlineKeyboardButton]] = []
    for c in page_items:
        rows.append([InlineKeyboardButton(
            text=f"{_MODE_EMOJI[modes.get(c.id)]} {c.title}",
            callback_data=f"toggle:{c.id}",
        )])
        icon_row = [
            InlineKeyboardButton(text="ℹ️", callback_data=f"linfo:{c.id}"),
        ]
        if c.username:
            icon_row.append(InlineKeyboardButton(
                text="🔗", url=f"https://t.me/{c.username}",
            ))
        icon_row.append(InlineKeyboardButton(text="✏️", callback_data=f"fedit:{c.id}"))
        if filters.get(c.id):
            icon_row.append(InlineKeyboardButton(text="🗑", callback_data=f"fdel:{c.id}"))
        rows.append(icon_row)
    nav = _nav_row(_page, total_pages, "lpage")
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=t(lang, "done_button"), callback_data="done")])
    return InlineKeyboardMarkup(rows)


_DETAILS_TOGGLE_KEY = {
    None: "channel_details_toggle_off",
    "off": "channel_details_toggle_off",
    "filtered": "channel_details_toggle_filtered",
    "debug": "channel_details_toggle_debug",
    "all": "channel_details_toggle_all",
}


def _details_view(
    db: Database, user_id: int, lang: str, channel_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    channel = db.get_channel(channel_id)
    title = channel.title if channel else ""
    username = channel.username if channel else None
    about = channel.about if channel else None
    mode = db.get_subscription_mode(user_id, channel_id)
    has_filter = bool(db.get_channel_filter(user_id, channel_id))

    title_html = f"<b>{html.escape(title)}</b>"
    description = html.escape(about) if about else t(lang, "channel_details_no_description")
    text = f"{title_html}\n\n{description}"

    rows: list[list[InlineKeyboardButton]] = []
    if username:
        rows.append([InlineKeyboardButton(
            text=t(lang, "channel_details_open_button"),
            url=f"https://t.me/{username}",
        )])
    rows.append([InlineKeyboardButton(
        text=t(lang, _DETAILS_TOGGLE_KEY[mode]),
        callback_data=f"toggle:{channel_id}",
    )])
    edit_row = [InlineKeyboardButton(
        text=t(lang, "channel_details_edit_filter_button"),
        callback_data=f"fedit:{channel_id}",
    )]
    if has_filter:
        edit_row.append(InlineKeyboardButton(
            text=t(lang, "channel_details_delete_filter_button"),
            callback_data=f"fdel:{channel_id}",
        ))
    rows.append(edit_row)
    rows.append([InlineKeyboardButton(
        text=t(lang, "channel_details_back_button"),
        callback_data="lback",
    )])
    return text, InlineKeyboardMarkup(rows)


async def _rerender_list_or_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    user_id: int,
    lang: str,
) -> None:
    view = context.user_data.get("list_view", "list")
    if isinstance(view, tuple) and view[0] == "details":
        text, kb = _details_view(db, user_id, lang, view[1])
        await update.callback_query.edit_message_text(
            text, reply_markup=kb,
            parse_mode="HTML", disable_web_page_preview=True,
        )
        return
    await update.callback_query.edit_message_text(
        t(lang, "pick_channels"),
        reply_markup=_user_keyboard(
            db, user_id, lang, page=context.user_data.get("list_page", 0)
        ),
    )


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


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = _lang(context, user_id)
    if _db(context).get_user_status(user_id) != "approved":
        await update.message.reply_text(t(lang, "denied"))
        return
    url = context.bot_data.get("miniapp_url")
    if not url:
        await update.message.reply_text(t(lang, "miniapp_unconfigured"))
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
        text=t(lang, "open_miniapp_button"), web_app=WebAppInfo(url=url),
    )]])
    await update.message.reply_text(t(lang, "miniapp_intro"), reply_markup=keyboard)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    log.debug("/list from user=%s", user_id)
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(t(lang, "denied"))
        return
    context.user_data["list_page"] = 0
    context.user_data["list_view"] = "list"
    await update.message.reply_text(
        t(lang, "pick_channels"),
        reply_markup=_user_keyboard(db, user_id, lang, page=0),
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
            announce_new_channel=context.bot_data.get("announce_new_channel"),
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
    if current in (None, "off"):
        next_mode: str | None = "filtered"
        db.subscribe(user_id, channel_id, mode="filtered")
    elif current == "filtered":
        next_mode = "debug"
        db.subscribe(user_id, channel_id, mode="debug")
    elif current == "debug":
        next_mode = "all"
        db.subscribe(user_id, channel_id, mode="all")
    else:
        if db.get_channel_filter(user_id, channel_id):
            next_mode = "off"
            db.subscribe(user_id, channel_id, mode="off")
        else:
            next_mode = None
            db.unsubscribe(user_id, channel_id)
    log.info("user=%s channel=%s mode %s -> %s", user_id, channel_id, current, next_mode)

    await update.callback_query.answer()
    await _rerender_list_or_details(update, context, db, user_id, lang)


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


async def on_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.callback_query.answer(t(lang, "denied"))
        return
    page = int(update.callback_query.data.split(":", 1)[1])
    context.user_data["list_page"] = page
    context.user_data["list_view"] = "list"
    await update.callback_query.answer()
    await update.callback_query.edit_message_reply_markup(
        reply_markup=_user_keyboard(db, user_id, lang, page=page),
    )


async def on_list_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.callback_query.answer(t(lang, "denied"))
        return
    channel_id = int(update.callback_query.data.split(":", 1)[1])
    if db.get_channel(channel_id) is None:
        await update.callback_query.answer(t(lang, "channel_unavailable"))
        return
    context.user_data["list_view"] = ("details", channel_id)
    text, kb = _details_view(db, user_id, lang, channel_id)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text, reply_markup=kb,
        parse_mode="HTML", disable_web_page_preview=True,
    )


async def on_list_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.callback_query.answer(t(lang, "denied"))
        return
    context.user_data["list_view"] = "list"
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        t(lang, "pick_channels"),
        reply_markup=_user_keyboard(
            db, user_id, lang, page=context.user_data.get("list_page", 0)
        ),
    )


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


async def on_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()


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
        reply_markup=_admin_keyboard(
            db, actor_lang, page=context.user_data.get("bl_page", 0)
        ),
    )


async def on_filter_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    channel_id = int(update.callback_query.data.split(":", 1)[1])

    if db.get_user_status(user_id) != "approved":
        log.info("filter edit rejected: user=%s not approved", user_id)
        await update.callback_query.answer(t(lang, "denied"))
        return

    title = db.get_channel_title(channel_id)
    if title is None:
        await update.callback_query.answer(t(lang, "channel_unavailable"))
        return

    context.user_data["awaiting_filter_for"] = channel_id
    log.info("user=%s queued filter edit for channel=%s", user_id, channel_id)
    await update.callback_query.answer()
    current = db.get_channel_filter(user_id, channel_id)
    tips = t(lang, "filter_tips")
    if current:
        await context.bot.send_message(
            chat_id=user_id,
            text=t(lang, "filter_ask_with_current", title=title),
        )
        await context.bot.send_message(chat_id=user_id, text=current)
        await context.bot.send_message(chat_id=user_id, text=tips)
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text=t(lang, "filter_ask", title=title, tips=tips),
        )


async def on_filter_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    channel_id = int(update.callback_query.data.split(":", 1)[1])

    if db.get_user_status(user_id) != "approved":
        log.info("filter delete rejected: user=%s not approved", user_id)
        await update.callback_query.answer(t(lang, "denied"))
        return

    title = db.get_channel_title(channel_id)
    if title is None:
        await update.callback_query.answer(t(lang, "channel_unavailable"))
        return

    if not db.get_channel_filter(user_id, channel_id):
        await update.callback_query.answer(t(lang, "filter_no_prompt_to_delete"))
        return

    db.set_channel_filter(user_id=user_id, channel_id=channel_id, filter_prompt=None)
    log.info("user=%s deleted filter for channel=%s", user_id, channel_id)
    await update.callback_query.answer(t(lang, "filter_deleted_for", title=title))
    await _rerender_list_or_details(update, context, db, user_id, lang)


async def on_filter_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channel_id = context.user_data.pop("awaiting_filter_for", None)
    if channel_id is None:
        return
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    if db.get_user_status(user_id) != "approved":
        await update.message.reply_text(t(lang, "denied"))
        return
    title = db.get_channel_title(channel_id)
    if title is None:
        await update.message.reply_text(t(lang, "channel_unavailable"))
        return
    payload = (update.message.text or "").strip()
    if not payload:
        await update.message.reply_text(t(lang, "filter_no_pending"))
        return
    current_mode = db.get_subscription_mode(user_id, channel_id)
    db.set_channel_filter(user_id=user_id, channel_id=channel_id, filter_prompt=payload)
    if current_mode in (None, "off"):
        db.subscribe(user_id, channel_id, mode="filtered")
    log.info(
        "user=%s set filter for channel=%s (%d chars)", user_id, channel_id, len(payload)
    )
    await update.message.reply_text(
        t(lang, "filter_saved_for", title=title, filter=payload)
    )


async def on_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    lang = db.get_language(user_id)
    _, raw_channel, mode = update.callback_query.data.split(":", 2)
    channel_id = int(raw_channel)

    if db.get_user_status(user_id) != "approved":
        log.info("subscribe rejected: user=%s not approved", user_id)
        await update.callback_query.answer(t(lang, "denied"))
        return
    if mode not in ("filtered", "debug", "all"):
        await update.callback_query.answer()
        return

    title = db.get_channel_title(channel_id)
    if title is None:
        await update.callback_query.answer(t(lang, "channel_unavailable"))
        return

    db.subscribe(user_id, channel_id, mode=mode)
    log.info("user=%s subscribed to channel=%s mode=%s", user_id, channel_id, mode)
    mode_label = t(lang, f"subscribe_{mode}_button")
    await update.callback_query.answer(
        t(lang, "subscribed_toast", title=title, mode=mode_label)
    )
    await update.callback_query.edit_message_reply_markup(reply_markup=None)


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
