from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.bot import (
    cmd_blacklist,
    cmd_help,
    cmd_language,
    cmd_list,
    cmd_start,
    cmd_usage,
    on_approve,
    on_blacklist,
    on_blacklist_done,
    on_blacklist_page,
    on_deny,
    on_filter_delete,
    on_filter_edit,
    on_filter_text,
    on_language,
    on_list_back,
    on_list_info,
    on_list_page,
    on_noop,
    on_toggle,
)
from informer_bot.db import Database

OWNER_ID = 999
USER_ID = 42


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.upsert_channel(channel_id=1, title="Alpha")
    db.upsert_channel(channel_id=2, title="Beta")
    db.upsert_channel(channel_id=3, title="BannedChan")
    db.set_blacklisted(channel_id=3, blacklisted=True)
    db.set_user_status(user_id=USER_ID, status="approved")
    db.set_user_status(user_id=OWNER_ID, status="approved")
    return db


def _ctx(db: Database) -> SimpleNamespace:
    return SimpleNamespace(
        bot_data={"db": db, "owner_id": OWNER_ID},
        bot=SimpleNamespace(send_message=AsyncMock()),
        user_data={},
    )


def _msg_update(
    user_id: int, username: str | None = None, text: str = ""
) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username=username, first_name=None),
        effective_chat=SimpleNamespace(id=user_id),
        message=SimpleNamespace(reply_text=AsyncMock(), text=text),
    )


def _cb_update(user_id: int, data: str) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        callback_query=SimpleNamespace(
            data=data,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
        ),
    )


def _kb_rows(reply_kwargs: dict) -> list[list[tuple[str, str]]]:
    """Extract [[(button_text, callback_data), ...], ...] from an InlineKeyboardMarkup kwarg."""
    markup = reply_kwargs["reply_markup"]
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


# ---------- /help ----------

async def test_help_for_regular_user_lists_user_commands_only(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_help(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    for cmd in ("/start", "/list", "/usage", "/help"):
        assert cmd in text
    assert "/blacklist" not in text
    assert "/update" not in text


async def test_help_for_owner_includes_admin_commands(db: Database) -> None:
    update = _msg_update(OWNER_ID)
    await cmd_help(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    for cmd in ("/list", "/blacklist", "/update"):
        assert cmd in text


async def test_help_works_for_unapproved_user(db: Database) -> None:
    unknown = 777
    update = _msg_update(unknown)
    await cmd_help(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "/start" in text


# ---------- /start ----------

async def test_start_for_approved_user_replies_with_greeting(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_start(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "/list" in text


async def test_start_for_unknown_user_creates_pending_and_dms_admin(db: Database) -> None:
    new_user = 555
    ctx = _ctx(db)
    update = _msg_update(new_user, username="bob")

    await cmd_start(update, ctx)

    assert db.get_user_status(new_user) == "pending"
    update.message.reply_text.assert_awaited_once()
    user_text = update.message.reply_text.await_args.args[0].lower()
    assert "wait" in user_text or "request" in user_text

    ctx.bot.send_message.assert_awaited_once()
    admin_call = ctx.bot.send_message.await_args
    assert admin_call.kwargs["chat_id"] == OWNER_ID
    markup = admin_call.kwargs["reply_markup"]
    rows = [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]
    flat = [btn for row in rows for btn in row]
    assert any(data == f"approve:{new_user}" for _, data in flat)
    assert any(data == f"deny:{new_user}" for _, data in flat)


async def test_start_for_pending_user_does_not_re_dm_admin(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    update = _msg_update(new_user, username="bob")

    await cmd_start(update, ctx)

    ctx.bot.send_message.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "wait" in text or "approval" in text


async def test_start_for_denied_user_replies_denied_and_no_admin_dm(db: Database) -> None:
    new_user = 555
    db.set_user_status(user_id=new_user, status="denied")
    ctx = _ctx(db)
    update = _msg_update(new_user)

    await cmd_start(update, ctx)

    ctx.bot.send_message.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text or "denied" in text


# ---------- approve / deny callbacks ----------

async def test_approve_sets_status_and_greets_user(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, f"approve:{new_user}")

    await on_approve(upd, ctx)

    assert db.get_user_status(new_user) == "approved"
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_awaited()
    ctx.bot.send_message.assert_awaited_once()
    assert ctx.bot.send_message.await_args.kwargs["chat_id"] == new_user


async def test_deny_sets_status_and_notifies_user(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, f"deny:{new_user}")

    await on_deny(upd, ctx)

    assert db.get_user_status(new_user) == "denied"
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_awaited()
    ctx.bot.send_message.assert_awaited_once()
    assert ctx.bot.send_message.await_args.kwargs["chat_id"] == new_user
    text = ctx.bot.send_message.await_args.kwargs["text"].lower()
    assert "not allowed" in text or "denied" in text


async def test_approve_denies_non_owner(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, f"approve:{new_user}")

    await on_approve(upd, ctx)

    assert db.get_user_status(new_user) == "pending"
    ctx.bot.send_message.assert_not_called()


async def test_deny_denies_non_owner(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, f"deny:{new_user}")

    await on_deny(upd, ctx)

    assert db.get_user_status(new_user) == "pending"
    ctx.bot.send_message.assert_not_called()


# ---------- gating of /list and toggle ----------

async def test_list_blocks_non_approved_user(db: Database) -> None:
    new_user = 555  # not approved
    update = _msg_update(new_user)

    await cmd_list(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text or "approval" in text


async def test_toggle_blocks_non_approved_user(db: Database) -> None:
    new_user = 555  # not approved
    upd = _cb_update(new_user, "toggle:1")

    await on_toggle(upd, _ctx(db))

    assert db.is_subscribed(new_user, 1) is False
    upd.callback_query.answer.assert_awaited()


# ---------- /list ----------

async def test_list_shows_only_non_blacklisted_with_unchecked_marker(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    rows = _kb_rows(update.message.reply_text.await_args.kwargs)
    flat = [btn for row in rows for btn in row]
    toggle_titles = [text for text, data in flat if data.startswith("toggle:")]
    assert "BannedChan" not in " ".join(toggle_titles)
    assert any("Alpha" in t and t.startswith("⬜") for t in toggle_titles)
    assert any("Beta" in t and t.startswith("⬜") for t in toggle_titles)
    toggles = [d for _, d in flat if d.startswith("toggle:")]
    infos = [d for _, d in flat if d.startswith("linfo:")]
    fedits = [d for _, d in flat if d.startswith("fedit:")]
    fdels = [d for _, d in flat if d.startswith("fdel:")]
    assert len(toggles) == 2
    assert len(infos) == 2
    assert len(fedits) == 2
    assert len(fdels) == 0
    assert flat[-1] == ("Done", "done")


async def test_list_shows_delete_button_only_when_filter_exists(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="filtered")
    db.set_channel_filter(user_id=USER_ID, channel_id=1, filter_prompt="for A")
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    rows = _kb_rows(update.message.reply_text.await_args.kwargs)
    flat = [btn for row in rows for btn in row]
    fdels = [d for _, d in flat if d.startswith("fdel:")]
    assert fdels == ["fdel:1"]


async def test_list_marks_filtered_and_all_modes_distinctly(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="filtered")
    db.subscribe(user_id=USER_ID, channel_id=2, mode="all")
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    flat = [btn for row in _kb_rows(update.message.reply_text.await_args.kwargs) for btn in row]
    alpha = next(t for t, _ in flat if "Alpha" in t)
    beta = next(t for t, _ in flat if "Beta" in t)
    assert alpha.startswith("🔀")
    assert beta.startswith("✅")


# ---------- toggle callback ----------

async def test_toggle_cycles_disabled_filtered_debug_all_disabled(db: Database) -> None:
    ctx = _ctx(db)

    upd1 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd1, ctx)
    assert db.get_subscription_mode(USER_ID, 1) == "filtered"
    upd1.callback_query.answer.assert_awaited()
    upd1.callback_query.edit_message_text.assert_awaited()

    upd2 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd2, ctx)
    assert db.get_subscription_mode(USER_ID, 1) == "debug"

    upd3 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd3, ctx)
    assert db.get_subscription_mode(USER_ID, 1) == "all"

    upd4 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd4, ctx)
    assert db.get_subscription_mode(USER_ID, 1) is None
    assert db.is_subscribed(USER_ID, 1) is False


async def test_toggle_off_preserves_row_when_filter_set(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="all")
    db.set_channel_filter(user_id=USER_ID, channel_id=1, filter_prompt="keep me")
    ctx = _ctx(db)

    upd = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd, ctx)

    assert db.get_subscription_mode(USER_ID, 1) == "off"
    assert db.get_channel_filter(USER_ID, 1) == "keep me"


async def test_toggle_refuses_blacklisted_channel(db: Database) -> None:
    upd = _cb_update(USER_ID, "toggle:3")
    await on_toggle(upd, _ctx(db))

    assert db.is_subscribed(USER_ID, 3) is False
    upd.callback_query.answer.assert_awaited()


# ---------- /blacklist ----------

async def test_blacklist_denies_non_owner(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_blacklist(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text or "forbidden" in text


async def test_blacklist_shows_all_channels_with_blacklist_marker(db: Database) -> None:
    update = _msg_update(OWNER_ID)
    await cmd_blacklist(update, _ctx(db))

    flat = [btn for row in _kb_rows(update.message.reply_text.await_args.kwargs) for btn in row]
    titles = [t for t, _ in flat]
    assert any("Alpha" in t for t in titles)
    assert any("Beta" in t for t in titles)
    banned = next(t for t in titles if "BannedChan" in t)
    assert banned.startswith("⛔")
    toggles = [(text, data) for text, data in flat if data.startswith("bl:")]
    assert len(toggles) == len(flat) - 1
    assert flat[-1] == ("Done", "bl_done")


# ---------- blacklist callback ----------

async def test_blacklist_toggle_flips_flag_for_owner(db: Database) -> None:
    upd = _cb_update(OWNER_ID, "bl:1")
    await on_blacklist(upd, _ctx(db))

    [alpha] = [c for c in db.list_channels(include_blacklisted=True) if c.id == 1]
    assert alpha.blacklisted is True

    upd2 = _cb_update(OWNER_ID, "bl:1")
    await on_blacklist(upd2, _ctx(db))
    [alpha] = [c for c in db.list_channels(include_blacklisted=True) if c.id == 1]
    assert alpha.blacklisted is False


async def test_blacklist_toggling_on_dms_existing_subscribers(db: Database) -> None:
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=20, channel_id=1)
    ctx = _ctx(db)

    upd = _cb_update(OWNER_ID, "bl:1")
    await on_blacklist(upd, ctx)

    [alpha] = [c for c in db.list_channels(include_blacklisted=True) if c.id == 1]
    assert alpha.blacklisted is True
    assert ctx.bot.send_message.await_count == 2
    sent = {call.kwargs["chat_id"]: call.kwargs["text"] for call in ctx.bot.send_message.await_args_list}
    assert set(sent.keys()) == {10, 20}
    for text in sent.values():
        assert "Alpha" in text and "admin blocked" in text.lower()


async def test_blacklist_toggling_off_does_not_dm(db: Database) -> None:
    db.subscribe(user_id=10, channel_id=3)  # channel 3 is already blacklisted in fixture
    ctx = _ctx(db)

    upd = _cb_update(OWNER_ID, "bl:3")
    await on_blacklist(upd, ctx)

    [banned] = [c for c in db.list_channels(include_blacklisted=True) if c.id == 3]
    assert banned.blacklisted is False
    ctx.bot.send_message.assert_not_called()


async def test_blacklist_callback_denies_non_owner(db: Database) -> None:
    upd = _cb_update(USER_ID, "bl:1")
    await on_blacklist(upd, _ctx(db))

    [alpha] = [c for c in db.list_channels(include_blacklisted=True) if c.id == 1]
    assert alpha.blacklisted is False
    upd.callback_query.answer.assert_awaited()


async def test_blacklist_done_closes_keyboard_for_owner(db: Database) -> None:
    upd = _cb_update(OWNER_ID, "bl_done")
    await on_blacklist_done(upd, _ctx(db))

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_awaited_once()
    text = upd.callback_query.edit_message_text.await_args.args[0]
    assert "blacklist" in text.lower() or "done" in text.lower() or "closed" in text.lower()


async def test_blacklist_done_denies_non_owner(db: Database) -> None:
    upd = _cb_update(USER_ID, "bl_done")
    await on_blacklist_done(upd, _ctx(db))

    upd.callback_query.edit_message_text.assert_not_awaited()


# ---------- /usage ----------

async def test_usage_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    update = _msg_update(new_user)

    await cmd_usage(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text


async def test_usage_for_regular_user_shows_own_totals_and_cost(db: Database) -> None:
    db.add_usage(user_id=USER_ID, input_tokens=1_000_000, output_tokens=200_000)
    update = _msg_update(USER_ID)

    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "1,000,000" in text or "1000000" in text
    assert "200,000" in text or "200000" in text
    assert "$" in text


async def test_usage_for_admin_shows_per_user_breakdown_and_system_total(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice", first_name="Alice")
    db.add_pending_user(user_id=20, username=None, first_name="Bob")
    db.set_user_status(user_id=10, status="approved")
    db.set_user_status(user_id=20, status="approved")
    db.add_usage(user_id=10, input_tokens=100, output_tokens=20)
    db.add_usage(user_id=20, input_tokens=50, output_tokens=10)
    db.add_system_usage(input_tokens=75, output_tokens=15)

    update = _msg_update(OWNER_ID)
    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "@alice (10)" in text
    assert "Bob (20)" in text
    assert "100" in text and "20" in text
    assert "50" in text and "10" in text
    assert "system" in text.lower() or "total" in text.lower()
    assert "75" in text and "15" in text


# ---------- per-channel filter (edit/delete/text) ----------

async def test_filter_edit_dms_prompt_and_queues_pending(db: Database) -> None:
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "fedit:1")

    await on_filter_edit(upd, ctx)

    assert ctx.user_data["awaiting_filter_for"] == 1
    upd.callback_query.answer.assert_awaited()
    ctx.bot.send_message.assert_awaited()
    last = ctx.bot.send_message.await_args_list[-1]
    assert last.kwargs["chat_id"] == USER_ID
    body = last.kwargs["text"]
    assert "Alpha" in body or "Tips" in body or "tips" in body.lower()


async def test_filter_edit_includes_existing_filter_when_set(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1)
    db.set_channel_filter(user_id=USER_ID, channel_id=1, filter_prompt="only AI")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "fedit:1")

    await on_filter_edit(upd, ctx)

    sent = [c.kwargs["text"] for c in ctx.bot.send_message.await_args_list]
    assert any("only AI" in t for t in sent)


async def test_filter_edit_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    ctx = _ctx(db)
    upd = _cb_update(new_user, "fedit:1")

    await on_filter_edit(upd, ctx)

    assert "awaiting_filter_for" not in ctx.user_data
    ctx.bot.send_message.assert_not_called()


async def test_filter_text_saves_prompt_and_activates_filtered(db: Database) -> None:
    ctx = _ctx(db)
    ctx.user_data["awaiting_filter_for"] = 1
    update = _msg_update(USER_ID, text="only AI news")

    await on_filter_text(update, ctx)

    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) == "only AI news"
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == "filtered"
    assert "awaiting_filter_for" not in ctx.user_data
    text = update.message.reply_text.await_args.args[0]
    assert "only AI news" in text


async def test_filter_text_preserves_all_mode(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="all")
    ctx = _ctx(db)
    ctx.user_data["awaiting_filter_for"] = 1
    update = _msg_update(USER_ID, text="only AI")

    await on_filter_text(update, ctx)

    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) == "only AI"
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == "all"


async def test_filter_text_no_pending_does_nothing(db: Database) -> None:
    ctx = _ctx(db)
    update = _msg_update(USER_ID, text="random message")

    await on_filter_text(update, ctx)

    update.message.reply_text.assert_not_called()
    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) is None


async def test_filter_delete_removes_prompt_and_refreshes_keyboard(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="filtered")
    db.set_channel_filter(user_id=USER_ID, channel_id=1, filter_prompt="kill me")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "fdel:1")

    await on_filter_delete(upd, ctx)

    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) is None
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == "filtered"
    upd.callback_query.edit_message_text.assert_awaited()


async def test_filter_delete_no_op_when_no_filter(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="filtered")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "fdel:1")

    await on_filter_delete(upd, ctx)

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_not_called()


async def test_filter_delete_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    ctx = _ctx(db)
    upd = _cb_update(new_user, "fdel:1")

    await on_filter_delete(upd, ctx)

    upd.callback_query.edit_message_text.assert_not_called()


# ---------- /language ----------

async def test_language_shows_current_and_keyboard(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_language(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "English" in text
    rows = _kb_rows(update.message.reply_text.await_args.kwargs)
    flat = [btn for row in rows for btn in row]
    datas = {data for _, data in flat}
    assert datas == {"lang:en", "lang:ru"}


async def test_language_callback_persists_choice_and_updates_message(db: Database) -> None:
    upd = _cb_update(USER_ID, "lang:ru")
    await on_language(upd, _ctx(db))

    assert db.get_language(user_id=USER_ID) == "ru"
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_awaited_once()
    text = upd.callback_query.edit_message_text.await_args.args[0]
    assert "Русский" in text


async def test_language_affects_subsequent_replies(db: Database) -> None:
    db.set_language(user_id=USER_ID, language="ru")
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert text == "Выбери каналы:"


# ---------- pagination ----------

def _seed_many_channels(db: Database, count: int, prefix: str = "Ch") -> None:
    for i in range(count):
        db.upsert_channel(channel_id=1000 + i, title=f"{prefix}{i:02d}")


async def test_list_first_page_caps_at_25_and_shows_next_only(db: Database) -> None:
    _seed_many_channels(db, 28)  # plus the 2 non-blacklisted from fixture = 30 visible
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    rows = _kb_rows(update.message.reply_text.await_args.kwargs)
    toggles = [d for row in rows for _, d in row if d.startswith("toggle:")]
    assert len(toggles) == 25
    flat = [btn for row in rows for btn in row]
    nav_pairs = [(t, d) for t, d in flat if d == "noop" or d.startswith("lpage:")]
    assert nav_pairs == [("1/2", "noop"), ("▶", "lpage:1")]


async def test_list_second_page_shows_remainder_and_prev_only(db: Database) -> None:
    _seed_many_channels(db, 28)
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "lpage:1")

    await on_list_page(upd, ctx)

    assert ctx.user_data["list_page"] == 1
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_reply_markup.assert_awaited_once()
    markup = upd.callback_query.edit_message_reply_markup.await_args.kwargs["reply_markup"]
    rows = [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]
    toggles = [d for row in rows for _, d in row if d.startswith("toggle:")]
    assert len(toggles) == 5  # 30 - 25
    flat = [btn for row in rows for btn in row]
    nav_pairs = [(t, d) for t, d in flat if d == "noop" or d.startswith("lpage:")]
    assert nav_pairs == [("◀", "lpage:0"), ("2/2", "noop")]


async def test_list_no_pagination_when_under_threshold(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    rows = _kb_rows(update.message.reply_text.await_args.kwargs)
    flat = [btn for row in rows for btn in row]
    assert not any(d.startswith("lpage:") or d == "noop" for _, d in flat)


async def test_list_page_blocks_non_approved_user(db: Database) -> None:
    _seed_many_channels(db, 28)
    new_user = 555
    ctx = _ctx(db)
    upd = _cb_update(new_user, "lpage:1")

    await on_list_page(upd, ctx)

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_reply_markup.assert_not_called()


async def test_toggle_preserves_page_position(db: Database) -> None:
    _seed_many_channels(db, 28)
    ctx = _ctx(db)
    ctx.user_data["list_page"] = 1
    target_id = 1025  # in fixture order, will be on page 2

    upd = _cb_update(USER_ID, f"toggle:{target_id}")
    await on_toggle(upd, ctx)

    markup = upd.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    rows = [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]
    flat = [btn for row in rows for btn in row]
    nav_pairs = [(t, d) for t, d in flat if d == "noop" or d.startswith("lpage:")]
    assert ("2/2", "noop") in nav_pairs


async def test_blacklist_paginates_for_owner(db: Database) -> None:
    _seed_many_channels(db, 28)
    update = _msg_update(OWNER_ID)
    await cmd_blacklist(update, _ctx(db))

    rows = _kb_rows(update.message.reply_text.await_args.kwargs)
    bl_toggles = [d for row in rows for _, d in row if d.startswith("bl:")]
    assert len(bl_toggles) == 25
    flat = [btn for row in rows for btn in row]
    nav_pairs = [(t, d) for t, d in flat if d == "noop" or d.startswith("blpage:")]
    assert nav_pairs == [("1/2", "noop"), ("▶", "blpage:1")]


async def test_blacklist_page_callback_advances_for_owner(db: Database) -> None:
    _seed_many_channels(db, 28)
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, "blpage:1")

    await on_blacklist_page(upd, ctx)

    assert ctx.user_data["bl_page"] == 1
    upd.callback_query.edit_message_reply_markup.assert_awaited_once()


async def test_blacklist_page_callback_denies_non_owner(db: Database) -> None:
    _seed_many_channels(db, 28)
    upd = _cb_update(USER_ID, "blpage:1")

    await on_blacklist_page(upd, _ctx(db))

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_reply_markup.assert_not_called()


async def test_noop_callback_just_answers(db: Database) -> None:
    upd = _cb_update(USER_ID, "noop")
    await on_noop(upd, _ctx(db))

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_not_called()
    upd.callback_query.edit_message_reply_markup.assert_not_called()


# ---------- channel details (info) ----------

async def test_list_info_renders_title_description_and_open_button(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", username="alpha_chan", about="Daily AI news.")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "linfo:1")

    await on_list_info(upd, ctx)

    assert ctx.user_data["list_view"] == ("details", 1)
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_awaited_once()
    text = upd.callback_query.edit_message_text.await_args.args[0]
    kwargs = upd.callback_query.edit_message_text.await_args.kwargs
    assert "<b>Alpha</b>" in text
    assert "Daily AI news." in text
    assert kwargs["parse_mode"] == "HTML"
    rows = [[(b.text, b.callback_data, getattr(b, "url", None)) for b in row]
            for row in kwargs["reply_markup"].inline_keyboard]
    flat = [btn for row in rows for btn in row]
    open_btn = next(b for b in flat if b[2] is not None)
    assert open_btn[2] == "https://t.me/alpha_chan"
    assert any(d == "lback" for _, d, _ in flat)
    toggle_btn = next(b for b in flat if b[1] == "toggle:1")
    assert "⬜" in toggle_btn[0]


async def test_list_info_uses_placeholder_when_no_description(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", username="alpha_chan")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "linfo:1")

    await on_list_info(upd, ctx)

    text = upd.callback_query.edit_message_text.await_args.args[0]
    assert "No description" in text


async def test_list_info_hides_open_button_when_no_username(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", about="x")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "linfo:1")

    await on_list_info(upd, ctx)

    kwargs = upd.callback_query.edit_message_text.await_args.kwargs
    rows = [[getattr(b, "url", None) for b in row]
            for row in kwargs["reply_markup"].inline_keyboard]
    urls = [u for row in rows for u in row if u is not None]
    assert urls == []


async def test_list_info_escapes_html_in_title_and_about(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A <b>x</b>", username="a", about="5 < 10")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "linfo:1")

    await on_list_info(upd, ctx)

    text = upd.callback_query.edit_message_text.await_args.args[0]
    assert "A &lt;b&gt;x&lt;/b&gt;" in text
    assert "5 &lt; 10" in text


async def test_list_info_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    ctx = _ctx(db)
    upd = _cb_update(new_user, "linfo:1")

    await on_list_info(upd, ctx)

    upd.callback_query.edit_message_text.assert_not_called()


async def test_list_info_shows_delete_filter_button_when_filter_set(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", username="a")
    db.subscribe(user_id=USER_ID, channel_id=1, mode="filtered")
    db.set_channel_filter(user_id=USER_ID, channel_id=1, filter_prompt="only AI")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "linfo:1")

    await on_list_info(upd, ctx)

    kwargs = upd.callback_query.edit_message_text.await_args.kwargs
    rows = [[(b.text, b.callback_data) for b in row]
            for row in kwargs["reply_markup"].inline_keyboard]
    callbacks = [d for row in rows for _, d in row]
    assert "fdel:1" in callbacks
    assert "fedit:1" in callbacks


async def test_list_info_hides_delete_filter_button_when_no_filter(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", username="a")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "linfo:1")

    await on_list_info(upd, ctx)

    kwargs = upd.callback_query.edit_message_text.await_args.kwargs
    rows = [[(b.text, b.callback_data) for b in row]
            for row in kwargs["reply_markup"].inline_keyboard]
    callbacks = [d for row in rows for _, d in row]
    assert "fdel:1" not in callbacks
    assert "fedit:1" in callbacks


async def test_list_back_returns_to_list_at_saved_page(db: Database) -> None:
    _seed_many_channels(db, 28)
    ctx = _ctx(db)
    ctx.user_data["list_page"] = 1
    ctx.user_data["list_view"] = ("details", 1000)
    upd = _cb_update(USER_ID, "lback")

    await on_list_back(upd, ctx)

    assert ctx.user_data["list_view"] == "list"
    upd.callback_query.edit_message_text.assert_awaited_once()
    markup = upd.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    rows = [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]
    flat = [btn for row in rows for btn in row]
    nav_pairs = [(t, d) for t, d in flat if d == "noop" or d.startswith("lpage:")]
    assert ("2/2", "noop") in nav_pairs


async def test_toggle_in_details_view_re_renders_details(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", username="a", about="x")
    ctx = _ctx(db)
    ctx.user_data["list_view"] = ("details", 1)
    upd = _cb_update(USER_ID, "toggle:1")

    await on_toggle(upd, ctx)

    assert db.get_subscription_mode(USER_ID, 1) == "filtered"
    upd.callback_query.edit_message_text.assert_awaited_once()
    text = upd.callback_query.edit_message_text.await_args.args[0]
    kwargs = upd.callback_query.edit_message_text.await_args.kwargs
    assert "<b>Alpha</b>" in text
    assert kwargs["parse_mode"] == "HTML"
    rows = [[(b.text, b.callback_data) for b in row]
            for row in kwargs["reply_markup"].inline_keyboard]
    callbacks = [d for row in rows for _, d in row]
    assert "lback" in callbacks


async def test_filter_delete_in_details_view_re_renders_details(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", username="a", about="x")
    db.subscribe(user_id=USER_ID, channel_id=1, mode="filtered")
    db.set_channel_filter(user_id=USER_ID, channel_id=1, filter_prompt="kill me")
    ctx = _ctx(db)
    ctx.user_data["list_view"] = ("details", 1)
    upd = _cb_update(USER_ID, "fdel:1")

    await on_filter_delete(upd, ctx)

    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) is None
    upd.callback_query.edit_message_text.assert_awaited_once()
    kwargs = upd.callback_query.edit_message_text.await_args.kwargs
    text = upd.callback_query.edit_message_text.await_args.args[0]
    assert "<b>Alpha</b>" in text
    assert kwargs["parse_mode"] == "HTML"


async def test_list_info_unknown_channel_replies_unavailable(db: Database) -> None:
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "linfo:9999")

    await on_list_info(upd, ctx)

    upd.callback_query.edit_message_text.assert_not_called()
    upd.callback_query.answer.assert_awaited()


async def test_list_renders_link_button_when_channel_has_username(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha", username="alpha_chan")
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    rows = update.message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    flat = [b for row in rows for b in row]
    link_btns = [b for b in flat if getattr(b, "url", None) == "https://t.me/alpha_chan"]
    assert len(link_btns) == 1
    assert link_btns[0].text == "🔗"


async def test_list_omits_link_button_when_channel_has_no_username(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    rows = update.message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    flat = [b for row in rows for b in row]
    urls = [getattr(b, "url", None) for b in flat]
    assert all(u is None for u in urls)


async def test_cmd_list_resets_list_view(db: Database) -> None:
    ctx = _ctx(db)
    ctx.user_data["list_view"] = ("details", 1)
    update = _msg_update(USER_ID)

    await cmd_list(update, ctx)

    assert ctx.user_data["list_view"] == "list"
