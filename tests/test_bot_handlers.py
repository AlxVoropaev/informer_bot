from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.bot import (
    BotState,
    cmd_app,
    cmd_blacklist,
    cmd_help,
    cmd_start,
    cmd_update,
    cmd_usage,
    on_approve,
    on_blacklist,
    on_blacklist_done,
    on_blacklist_page,
    on_deny,
    on_noop,
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


def _ctx(db: Database, miniapp_url: str | None = None) -> SimpleNamespace:
    state = BotState(
        db=db,
        owner_id=OWNER_ID,
        miniapp_url=miniapp_url,
        fetch_channels=AsyncMock(),
        send_dm=AsyncMock(),
        announce_new_channel=None,
    )
    return SimpleNamespace(
        bot_data={"state": state},
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
    for cmd in ("/start", "/app", "/usage", "/help"):
        assert cmd in text
    assert "Mini App" in text
    assert "/blacklist" not in text
    assert "/update" not in text


async def test_help_for_owner_includes_admin_commands(db: Database) -> None:
    update = _msg_update(OWNER_ID)
    await cmd_help(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    for cmd in ("/app", "/blacklist", "/update"):
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
    assert "Mini App" in text


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


# ---------- /app ----------

async def test_app_offers_miniapp_button_for_approved_user(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_app(update, _ctx(db, miniapp_url="https://app.example.com/"))

    update.message.reply_text.assert_awaited_once()
    markup = update.message.reply_text.await_args.kwargs["reply_markup"]
    flat = [b for row in markup.inline_keyboard for b in row]
    web_app_btns = [b for b in flat if getattr(b, "web_app", None) is not None]
    assert len(web_app_btns) == 1
    assert web_app_btns[0].web_app.url == "https://app.example.com/"


async def test_app_replies_unconfigured_when_url_missing(db: Database) -> None:
    update = _msg_update(USER_ID)
    await cmd_app(update, _ctx(db, miniapp_url=None))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "MINIAPP_URL" in text or "not configured" in text.lower()


async def test_app_blocks_non_approved_user(db: Database) -> None:
    update = _msg_update(555)
    await cmd_app(update, _ctx(db, miniapp_url="https://app.example.com/"))

    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text


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


# ---------- pagination (blacklist only) ----------

def _seed_many_channels(db: Database, count: int, prefix: str = "Ch") -> None:
    for i in range(count):
        db.upsert_channel(channel_id=1000 + i, title=f"{prefix}{i:02d}")


async def test_blacklist_paginates_for_owner(db: Database) -> None:
    _seed_many_channels(db, 18)
    update = _msg_update(OWNER_ID)
    await cmd_blacklist(update, _ctx(db))

    rows = _kb_rows(update.message.reply_text.await_args.kwargs)
    bl_toggles = [d for row in rows for _, d in row if d.startswith("bl:")]
    assert len(bl_toggles) == 15
    flat = [btn for row in rows for btn in row]
    nav_pairs = [(t, d) for t, d in flat if d == "noop" or d.startswith("blpage:")]
    assert nav_pairs == [("1/2", "noop"), ("▶", "blpage:1")]


async def test_blacklist_page_callback_advances_for_owner(db: Database) -> None:
    _seed_many_channels(db, 18)
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, "blpage:1")

    await on_blacklist_page(upd, ctx)

    assert ctx.user_data["bl_page"] == 1
    upd.callback_query.edit_message_reply_markup.assert_awaited_once()


async def test_blacklist_page_callback_denies_non_owner(db: Database) -> None:
    _seed_many_channels(db, 18)
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


# ---------- /update ----------

async def test_update_denies_non_owner(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh = AsyncMock()
    monkeypatch.setattr("informer_bot.bot.refresh_channels", refresh)

    update = _msg_update(USER_ID)
    await cmd_update(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text or "denied" in text
    refresh.assert_not_called()


async def test_update_for_owner_calls_refresh_channels_with_state_deps(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh = AsyncMock()
    monkeypatch.setattr("informer_bot.bot.refresh_channels", refresh)

    ctx = _ctx(db)
    state: BotState = ctx.bot_data["state"]
    update = _msg_update(OWNER_ID)

    await cmd_update(update, ctx)

    refresh.assert_awaited_once()
    kwargs = refresh.await_args.kwargs
    assert kwargs["fetch_fn"] is state.fetch_channels
    assert kwargs["db"] is state.db
    assert kwargs["send_dm"] is state.send_dm
    assert kwargs["announce_new_channel"] is state.announce_new_channel

    # Two replies on the happy path: "refreshing..." and "refresh_done".
    assert update.message.reply_text.await_count == 2
    final_text = update.message.reply_text.await_args.args[0].lower()
    assert "fail" not in final_text


async def test_update_swallows_refresh_exception_and_replies_failure(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("informer_bot.bot.refresh_channels", refresh)

    update = _msg_update(OWNER_ID)
    # The handler is expected to swallow the exception, not re-raise.
    await cmd_update(update, _ctx(db))

    refresh.assert_awaited_once()
    # First reply was the "refreshing..." one; the failure reply must be the last.
    assert update.message.reply_text.await_count == 2
    final_text = update.message.reply_text.await_args.args[0].lower()
    assert "fail" in final_text or "log" in final_text


# ---------- save toggle (auto-delete) ----------

def _save_cb_update(user_id: int, bot_msg_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        callback_query=SimpleNamespace(
            data="save",
            message=SimpleNamespace(message_id=bot_msg_id, chat=SimpleNamespace(id=user_id)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
        ),
    )


async def test_on_save_marks_saved_and_relabels_button(db: Database) -> None:
    from informer_bot.bot import on_save
    db.set_user_auto_delete_hours(USER_ID, 6)
    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=100, bot_message_id=777,
        is_photo=False, body="b", now=1000, delete_at=1000 + 6 * 3600,
    )

    update = _save_cb_update(USER_ID, 777)
    await on_save(update, _ctx(db))

    state = db.get_delivered_save_state(
        user_id=USER_ID, channel_id=1, message_id=100,
    )
    assert state == (True, None)
    update.callback_query.edit_message_reply_markup.assert_awaited_once()
    kw = update.callback_query.edit_message_reply_markup.await_args.kwargs
    [[btn]] = [
        [(b.text, b.callback_data) for b in row]
        for row in kw["reply_markup"].inline_keyboard
    ]
    assert btn[1] == "save"
    assert "Saved" in btn[0]


async def test_on_save_toggles_back_resets_delete_at(db: Database) -> None:
    from informer_bot.bot import on_save
    db.set_user_auto_delete_hours(USER_ID, 6)
    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=100, bot_message_id=777,
        is_photo=False, body="b", now=1000, delete_at=1000 + 6 * 3600,
    )
    db.set_delivered_saved(
        user_id=USER_ID, channel_id=1, message_id=100,
        saved=True, delete_at=None,
    )

    update = _save_cb_update(USER_ID, 777)
    await on_save(update, _ctx(db))

    saved, delete_at = db.get_delivered_save_state(
        user_id=USER_ID, channel_id=1, message_id=100,
    )
    assert saved is False
    assert delete_at is not None and delete_at > int(__import__("time").time())


async def test_on_save_preserves_dup_link_buttons(db: Database) -> None:
    from informer_bot.bot import on_save
    db.set_user_auto_delete_hours(USER_ID, 6)
    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=100, bot_message_id=777,
        is_photo=False, body="b", now=1000, delete_at=1000 + 6 * 3600,
    )
    db.set_delivered_dup_links(
        user_id=USER_ID, channel_id=1, message_id=100,
        dup_links=[("Channel B", "https://t.me/b/1")],
    )

    update = _save_cb_update(USER_ID, 777)
    await on_save(update, _ctx(db))

    kw = update.callback_query.edit_message_reply_markup.await_args.kwargs
    rows = [
        [(b.text, b.callback_data, getattr(b, "url", None)) for b in row]
        for row in kw["reply_markup"].inline_keyboard
    ]
    assert len(rows) == 2
    assert rows[0][0][2] == "https://t.me/b/1"
    assert rows[1][0][1] == "save"


async def test_on_save_silently_ignores_unknown_message(db: Database) -> None:
    from informer_bot.bot import on_save
    update = _save_cb_update(USER_ID, 12345)
    await on_save(update, _ctx(db))
    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_reply_markup.assert_not_called()


# ---------- sweeper ----------

async def test_sweep_due_deletions_deletes_due_rows_and_skips_saved(
    db: Database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from informer_bot.main import sweep_due_deletions

    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=1, delete_at=1,
    )
    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=101, bot_message_id=2,
        is_photo=False, body="b", now=1, delete_at=10**12,  # far future
    )
    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=102, bot_message_id=3,
        is_photo=False, body="b", now=1, delete_at=1,
    )
    db.set_delivered_saved(
        user_id=USER_ID, channel_id=1, message_id=102,
        saved=True, delete_at=None,
    )

    bot = SimpleNamespace(delete_message=AsyncMock())
    app = SimpleNamespace(bot=bot)

    # Pause after first iteration so we can inspect the DB.
    async def fake_sleep(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("informer_bot.main.asyncio.sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await sweep_due_deletions(app, db)

    deleted = sorted(c.kwargs["message_id"] for c in bot.delete_message.await_args_list)
    assert deleted == [1]
    # Row 100 gone, 101 untouched, 102 still saved.
    assert db.get_delivered_save_state(
        user_id=USER_ID, channel_id=1, message_id=100,
    ) is None
    assert db.get_delivered_save_state(
        user_id=USER_ID, channel_id=1, message_id=101,
    ) is not None
    assert db.get_delivered_save_state(
        user_id=USER_ID, channel_id=1, message_id=102,
    ) == (True, None)
