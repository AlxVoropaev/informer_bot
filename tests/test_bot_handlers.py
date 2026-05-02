from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.bot import cmd_admin_list, cmd_list, cmd_start, on_blacklist, on_toggle
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
    return db


def _ctx(db: Database) -> SimpleNamespace:
    return SimpleNamespace(bot_data={"db": db, "owner_id": OWNER_ID})


def _msg_update(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        message=SimpleNamespace(reply_text=AsyncMock()),
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


# ---------- /start ----------

async def test_start_replies_with_greeting(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_start(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "/list" in text


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
    assert all(data.startswith("toggle:") for _, data in flat)


async def test_list_marks_subscribed_channels_with_check(db: Database) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1)
    update = _msg_update(USER_ID)
    await cmd_list(update, _ctx(db))

    flat = [btn for row in _kb_rows(update.message.reply_text.await_args.kwargs) for btn in row]
    alpha = next(t for t, _ in flat if "Alpha" in t)
    beta = next(t for t, _ in flat if "Beta" in t)
    assert alpha.startswith("✅")
    assert beta.startswith("⬜")


# ---------- toggle callback ----------

async def test_toggle_subscribes_then_unsubscribes(db: Database) -> None:
    ctx = _ctx(db)

    upd1 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd1, ctx)
    assert db.is_subscribed(USER_ID, 1) is True
    upd1.callback_query.answer.assert_awaited()
    upd1.callback_query.edit_message_text.assert_awaited()

    upd2 = _cb_update(USER_ID, "toggle:1")
    await on_toggle(upd2, ctx)
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


async def test_blacklist_callback_denies_non_owner(db: Database) -> None:
    upd = _cb_update(USER_ID, "bl:1")
    await on_blacklist(upd, _ctx(db))

    [alpha] = [c for c in db.list_channels(include_blacklisted=True) if c.id == 1]
    assert alpha.blacklisted is False
    upd.callback_query.answer.assert_awaited()
