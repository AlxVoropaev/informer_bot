from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.bot import (
    cmd_admin_list,
    cmd_filter,
    cmd_help,
    cmd_list,
    cmd_start,
    cmd_usage,
    on_approve,
    on_blacklist,
    on_deny,
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
    for cmd in ("/start", "/list", "/filter", "/usage", "/help"):
        assert cmd in text
    assert "/admin_list" not in text
    assert "/update" not in text


async def test_help_for_owner_includes_admin_commands(db: Database) -> None:
    update = _msg_update(OWNER_ID)
    await cmd_help(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    for cmd in ("/list", "/filter", "/admin_list", "/update"):
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
    titles = [text for text, _ in flat]
    assert "BannedChan" not in " ".join(titles)
    assert any("Alpha" in t and t.startswith("⬜") for t in titles)
    assert any("Beta" in t and t.startswith("⬜") for t in titles)
    toggles = [(text, data) for text, data in flat if data.startswith("toggle:")]
    assert len(toggles) == len(flat) - 1
    assert flat[-1] == ("Done", "done")


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

async def test_toggle_cycles_disabled_filtered_all_disabled(db: Database) -> None:
    ctx = _ctx(db)

    upd1 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd1, ctx)
    assert db.get_subscription_mode(USER_ID, 1) == "filtered"
    upd1.callback_query.answer.assert_awaited()
    upd1.callback_query.edit_message_text.assert_awaited()

    upd2 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd2, ctx)
    assert db.get_subscription_mode(USER_ID, 1) == "all"

    upd3 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd3, ctx)
    assert db.get_subscription_mode(USER_ID, 1) is None
    assert db.is_subscribed(USER_ID, 1) is False


async def test_toggle_refuses_blacklisted_channel(db: Database) -> None:
    upd = _cb_update(USER_ID, "toggle:3")
    await on_toggle(upd, _ctx(db))

    assert db.is_subscribed(USER_ID, 3) is False
    upd.callback_query.answer.assert_awaited()


# ---------- /admin_list ----------

async def test_admin_list_denies_non_owner(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_admin_list(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text or "forbidden" in text


async def test_admin_list_shows_all_channels_with_blacklist_marker(db: Database) -> None:
    update = _msg_update(OWNER_ID)
    await cmd_admin_list(update, _ctx(db))

    flat = [btn for row in _kb_rows(update.message.reply_text.await_args.kwargs) for btn in row]
    titles = [t for t, _ in flat]
    assert any("Alpha" in t for t in titles)
    assert any("Beta" in t for t in titles)
    banned = next(t for t in titles if "BannedChan" in t)
    assert banned.startswith("⛔")
    assert all(data.startswith("bl:") for _, data in flat)


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
        assert "Alpha" in text and "no longer available" in text.lower()


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


# ---------- /filter ----------

async def test_filter_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    update = _msg_update(new_user, text="/filter only AI")

    await cmd_filter(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text
    assert db.get_filter(user_id=new_user) is None


async def test_filter_bare_shows_no_filter_message_when_unset(db: Database) -> None:
    update = _msg_update(USER_ID, text="/filter")

    await cmd_filter(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "No filter" in text or "no filter" in text.lower()


async def test_filter_set_saves_payload(db: Database) -> None:
    update = _msg_update(USER_ID, text="/filter only AI news, no crypto")

    await cmd_filter(update, _ctx(db))

    assert db.get_filter(user_id=USER_ID) == "only AI news, no crypto"
    text = update.message.reply_text.await_args.args[0]
    assert "only AI news, no crypto" in text


async def test_filter_bare_shows_current_filter_when_set(db: Database) -> None:
    db.set_filter(user_id=USER_ID, filter_prompt="only AI news")
    update = _msg_update(USER_ID, text="/filter")

    await cmd_filter(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "only AI news" in text


async def test_filter_clear_removes_filter(db: Database) -> None:
    db.set_filter(user_id=USER_ID, filter_prompt="only AI news")
    update = _msg_update(USER_ID, text="/filter clear")

    await cmd_filter(update, _ctx(db))

    assert db.get_filter(user_id=USER_ID) is None
    text = update.message.reply_text.await_args.args[0].lower()
    assert "clear" in text or "everything" in text
