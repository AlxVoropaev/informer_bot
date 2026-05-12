from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.bot import (
    BotState,
    cmd_app,
    cmd_become_provider,
    cmd_help,
    cmd_revoke_provider,
    cmd_start,
    cmd_update,
    cmd_usage,
    on_approve,
    on_become_provider_self,
    on_deny,
    on_provider_approve,
    on_provider_deny,
)
from informer_bot.db import Database

OWNER_ID = 999
USER_ID = 42


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.set_user_status(user_id=OWNER_ID, status="approved")
    db.add_pending_provider(user_id=OWNER_ID, session_path="data/informer.session")
    db.set_provider_status(user_id=OWNER_ID, status="approved")
    db.set_meta("owner_id", str(OWNER_ID))
    db.upsert_channel(channel_id=1, title="Alpha")
    db.upsert_channel(channel_id=2, title="Beta")
    db.set_user_status(user_id=USER_ID, status="approved")
    return db


def _ctx(db: Database, miniapp_url: str | None = None) -> SimpleNamespace:
    state = BotState(
        db=db,
        owner_id=OWNER_ID,
        miniapp_url=miniapp_url,
        fetch_channels_for=AsyncMock(),
        provider_user_ids=[OWNER_ID],
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
    for cmd in ("/app", "/update"):
        assert cmd in text
    assert "/blacklist" not in text


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


async def test_approve_attaches_become_provider_button(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, f"approve:{new_user}")

    await on_approve(upd, ctx)

    ctx.bot.send_message.assert_awaited_once()
    kw = ctx.bot.send_message.await_args.kwargs
    assert kw["chat_id"] == new_user
    markup = kw["reply_markup"]
    assert markup is not None
    flat = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "provider_self" in flat


async def test_approve_omits_become_provider_button_for_existing_provider(
    db: Database,
) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    db.add_pending_provider(
        user_id=new_user, session_path=f"data/sessions/{new_user}.session",
    )
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, f"approve:{new_user}")

    await on_approve(upd, ctx)

    ctx.bot.send_message.assert_awaited_once()
    kw = ctx.bot.send_message.await_args.kwargs
    markup = kw["reply_markup"]
    if markup is not None:
        flat = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "provider_self" not in flat


async def test_deny_denies_non_owner(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, f"deny:{new_user}")

    await on_deny(upd, ctx)

    assert db.get_user_status(new_user) == "pending"
    ctx.bot.send_message.assert_not_called()


async def test_approve_handles_malformed_callback(db: Database) -> None:
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, "approve")

    await on_approve(upd, ctx)

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_not_awaited()
    ctx.bot.send_message.assert_not_called()


async def test_deny_handles_malformed_callback(db: Database) -> None:
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, "deny:abc")

    await on_deny(upd, ctx)

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_not_awaited()
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


# ---------- /usage ----------

async def test_usage_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    update = _msg_update(new_user)

    await cmd_usage(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text


async def test_usage_for_regular_user_shows_own_totals_and_cost(db: Database) -> None:
    db.add_usage(
        user_id=USER_ID, provider="anthropic",
        input_tokens=1_000_000, output_tokens=200_000,
    )
    update = _msg_update(USER_ID)

    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "1,000,000" in text or "1000000" in text
    assert "200,000" in text or "200000" in text
    assert "$" in text
    assert "anthropic" in text


async def test_usage_for_regular_user_shows_each_provider_and_total(
    db: Database,
) -> None:
    db.add_usage(
        user_id=USER_ID, provider="anthropic",
        input_tokens=1_000, output_tokens=200,
    )
    db.add_usage(
        user_id=USER_ID, provider="remote",
        input_tokens=4_000, output_tokens=800,
    )
    update = _msg_update(USER_ID)

    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "anthropic" in text
    assert "remote" in text
    # Total line aggregates all providers.
    assert "5,000" in text or "5000" in text
    assert "1,000" in text or "1000" in text


async def test_usage_for_regular_user_hides_zero_unknown_bucket(
    db: Database,
) -> None:
    # No data at all: the "unknown" provider must not appear, just the empty
    # placeholder.
    update = _msg_update(USER_ID)

    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "unknown" not in text


async def test_usage_for_regular_user_shows_legacy_unknown_when_nonzero(
    db: Database,
) -> None:
    db.add_usage(
        user_id=USER_ID, provider="unknown",
        input_tokens=100, output_tokens=20,
    )
    update = _msg_update(USER_ID)

    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "unknown" in text


async def test_usage_for_admin_shows_per_user_breakdown_and_system_total(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice", first_name="Alice")
    db.add_pending_user(user_id=20, username=None, first_name="Bob")
    db.set_user_status(user_id=10, status="approved")
    db.set_user_status(user_id=20, status="approved")
    db.add_usage(
        user_id=10, provider="anthropic", input_tokens=100, output_tokens=20,
    )
    db.add_usage(
        user_id=20, provider="anthropic", input_tokens=50, output_tokens=10,
    )
    db.add_system_usage(provider="anthropic", input_tokens=75, output_tokens=15)

    update = _msg_update(OWNER_ID)
    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "@alice (10)" in text
    assert "Bob (20)" in text
    assert "100" in text and "20" in text
    assert "50" in text and "10" in text
    assert "system" in text.lower() or "total" in text.lower()
    assert "75" in text and "15" in text


async def test_usage_for_admin_breaks_out_user_by_provider(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.add_usage(
        user_id=10, provider="anthropic", input_tokens=100, output_tokens=20,
    )
    db.add_usage(
        user_id=10, provider="remote", input_tokens=4000, output_tokens=800,
    )

    update = _msg_update(OWNER_ID)
    await cmd_usage(update, _ctx(db))

    text = update.message.reply_text.await_args.args[0]
    assert "anthropic" in text
    assert "remote" in text
    # User label appears once before its per-provider sub-rows.
    assert text.count("@alice (10)") == 1


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
    assert kwargs["fetch_fn_for"] is state.fetch_channels_for
    assert kwargs["provider_user_ids"] is state.provider_user_ids
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


async def test_sweep_due_keeps_row_when_telegram_delete_fails(
    db: Database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from informer_bot.main import sweep_due_deletions

    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=200, bot_message_id=10,
        is_photo=False, body="b", now=1, delete_at=1,
    )
    db.record_delivered(
        user_id=USER_ID, channel_id=1, message_id=201, bot_message_id=11,
        is_photo=False, body="b", now=1, delete_at=1,
    )

    bot = SimpleNamespace(
        delete_message=AsyncMock(side_effect=[None, RuntimeError("boom")]),
    )
    app = SimpleNamespace(bot=bot)

    async def fake_sleep(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("informer_bot.main.asyncio.sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await sweep_due_deletions(app, db)

    assert db.get_delivered_save_state(
        user_id=USER_ID, channel_id=1, message_id=200,
    ) is None
    assert db.get_delivered_save_state(
        user_id=USER_ID, channel_id=1, message_id=201,
    ) is not None


# ---------- /become_provider ----------

async def test_become_provider_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    update = _msg_update(new_user)

    await cmd_become_provider(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text
    assert db.get_provider(new_user) is None


async def test_become_provider_owner_already_message(db: Database) -> None:
    update = _msg_update(OWNER_ID)
    ctx = _ctx(db)

    await cmd_become_provider(update, ctx)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "primary provider" in text or "already" in text
    ctx.bot.send_message.assert_not_called()


async def test_become_provider_creates_pending_and_dms_owner(db: Database) -> None:
    ctx = _ctx(db)
    update = _msg_update(USER_ID, username="bob")

    await cmd_become_provider(update, ctx)

    provider = db.get_provider(USER_ID)
    assert provider is not None
    assert provider.status == "pending"
    assert provider.session_path == f"data/sessions/{USER_ID}.session"

    ctx.bot.send_message.assert_awaited_once()
    admin_call = ctx.bot.send_message.await_args
    assert admin_call.kwargs["chat_id"] == OWNER_ID
    rows = [
        [(b.text, b.callback_data) for b in row]
        for row in admin_call.kwargs["reply_markup"].inline_keyboard
    ]
    flat = [btn for row in rows for btn in row]
    assert any(data == f"provider_approve:{USER_ID}" for _, data in flat)
    assert any(data == f"provider_deny:{USER_ID}" for _, data in flat)

    update.message.reply_text.assert_awaited_once()
    user_text = update.message.reply_text.await_args.args[0].lower()
    assert "submitted" in user_text or "request" in user_text


async def test_become_provider_already_pending(db: Database) -> None:
    db.add_pending_provider(user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session")
    ctx = _ctx(db)
    update = _msg_update(USER_ID)

    await cmd_become_provider(update, ctx)

    ctx.bot.send_message.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "pending" in text


async def test_become_provider_already_approved(db: Database) -> None:
    db.add_pending_provider(user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session")
    db.set_provider_status(user_id=USER_ID, status="approved")
    ctx = _ctx(db)
    update = _msg_update(USER_ID)

    await cmd_become_provider(update, ctx)

    ctx.bot.send_message.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "approved" in text


async def test_become_provider_previously_denied(db: Database) -> None:
    db.add_pending_provider(user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session")
    db.set_provider_status(user_id=USER_ID, status="denied")
    ctx = _ctx(db)
    update = _msg_update(USER_ID)

    await cmd_become_provider(update, ctx)

    ctx.bot.send_message.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "denied" in text
    # Status must remain denied (no auto-resubmit).
    assert db.get_provider(USER_ID).status == "denied"


# ---------- provider self-onboard from approval DM ----------

async def test_provider_self_creates_approved_provider(db: Database) -> None:
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "provider_self")

    await on_become_provider_self(upd, ctx)

    provider = db.get_provider(USER_ID)
    assert provider is not None
    assert provider.status == "approved"
    assert provider.session_path == f"data/sessions/{USER_ID}.session"
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_reply_markup.assert_awaited_once()
    chats = [c.kwargs["chat_id"] for c in ctx.bot.send_message.await_args_list]
    assert USER_ID in chats
    assert OWNER_ID in chats


async def test_provider_self_blocks_non_approved_user(db: Database) -> None:
    new_user = 555
    db.add_pending_user(user_id=new_user, username="bob")
    ctx = _ctx(db)
    upd = _cb_update(new_user, "provider_self")

    await on_become_provider_self(upd, ctx)

    assert db.get_provider(new_user) is None
    ctx.bot.send_message.assert_not_called()
    upd.callback_query.answer.assert_awaited()


async def test_provider_self_idempotent_when_already_approved(db: Database) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    db.set_provider_status(user_id=USER_ID, status="approved")
    before = db.get_provider(USER_ID)
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, "provider_self")

    await on_become_provider_self(upd, ctx)

    after = db.get_provider(USER_ID)
    assert before == after
    ctx.bot.send_message.assert_not_called()


# ---------- provider approve / deny callbacks ----------

async def test_on_provider_approve_sets_status_and_dms_target(db: Database) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, f"provider_approve:{USER_ID}")

    await on_provider_approve(upd, ctx)

    provider = db.get_provider(USER_ID)
    assert provider is not None
    assert provider.status == "approved"
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_awaited()
    ctx.bot.send_message.assert_awaited_once()
    assert ctx.bot.send_message.await_args.kwargs["chat_id"] == USER_ID
    text = ctx.bot.send_message.await_args.kwargs["text"].lower()
    assert "login cli" in text or "approved" in text


async def test_on_provider_deny_sets_status_and_dms_target(db: Database) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, f"provider_deny:{USER_ID}")

    await on_provider_deny(upd, ctx)

    provider = db.get_provider(USER_ID)
    assert provider is not None
    assert provider.status == "denied"
    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_awaited()
    ctx.bot.send_message.assert_awaited_once()
    assert ctx.bot.send_message.await_args.kwargs["chat_id"] == USER_ID


async def test_on_provider_approve_denies_non_owner(db: Database) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, f"provider_approve:{USER_ID}")

    await on_provider_approve(upd, ctx)

    assert db.get_provider(USER_ID).status == "pending"
    ctx.bot.send_message.assert_not_called()
    upd.callback_query.edit_message_text.assert_not_awaited()


async def test_on_provider_deny_denies_non_owner(db: Database) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    ctx = _ctx(db)
    upd = _cb_update(USER_ID, f"provider_deny:{USER_ID}")

    await on_provider_deny(upd, ctx)

    assert db.get_provider(USER_ID).status == "pending"
    ctx.bot.send_message.assert_not_called()


async def test_on_provider_approve_handles_malformed_callback(db: Database) -> None:
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, "provider_approve")

    await on_provider_approve(upd, ctx)

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_not_awaited()
    ctx.bot.send_message.assert_not_called()


async def test_on_provider_deny_handles_malformed_callback(db: Database) -> None:
    ctx = _ctx(db)
    upd = _cb_update(OWNER_ID, "provider_deny:xyz")

    await on_provider_deny(upd, ctx)

    upd.callback_query.answer.assert_awaited()
    upd.callback_query.edit_message_text.assert_not_awaited()
    ctx.bot.send_message.assert_not_called()


# ---------- /revoke_provider ----------

async def test_revoke_provider_denies_non_owner(db: Database) -> None:
    update = _msg_update(USER_ID, text=f"/revoke_provider {USER_ID}")
    ctx = _ctx(db)

    await cmd_revoke_provider(update, ctx)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not allowed" in text or "denied" in text
    ctx.bot.send_message.assert_not_called()


async def test_revoke_provider_invalid_id(db: Database) -> None:
    update = _msg_update(OWNER_ID, text="/revoke_provider notanint")

    await cmd_revoke_provider(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "usage" in text


async def test_revoke_provider_no_arg(db: Database) -> None:
    update = _msg_update(OWNER_ID, text="/revoke_provider")

    await cmd_revoke_provider(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "usage" in text


async def test_revoke_provider_refuses_owner(db: Database) -> None:
    update = _msg_update(OWNER_ID, text=f"/revoke_provider {OWNER_ID}")

    await cmd_revoke_provider(update, _ctx(db))

    assert db.get_provider(OWNER_ID) is not None
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "primary" in text or "cannot" in text


async def test_revoke_provider_unknown_user(db: Database) -> None:
    update = _msg_update(OWNER_ID, text="/revoke_provider 12345")

    await cmd_revoke_provider(update, _ctx(db))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0].lower()
    assert "not a provider" in text


async def test_revoke_provider_removes_provider_and_session_file(
    db: Database, tmp_path: Path,
) -> None:
    session_file = tmp_path / f"{USER_ID}.session"
    session_file.write_text("dummy")
    db.add_pending_provider(user_id=USER_ID, session_path=str(session_file))
    db.set_provider_status(user_id=USER_ID, status="approved")
    # USER_ID is the SOLE provider of channel 100; revocation should orphan it.
    db.upsert_channel(channel_id=100, title="OnlyVia42")
    db.set_provider_channels(provider_user_id=USER_ID, channel_ids={100})
    SUBSCRIBER_ID = 7777
    db.set_user_status(user_id=SUBSCRIBER_ID, status="approved")
    db.subscribe(user_id=SUBSCRIBER_ID, channel_id=100)
    ctx = _ctx(db)
    update = _msg_update(OWNER_ID, text=f"/revoke_provider {USER_ID}")

    await cmd_revoke_provider(update, ctx)

    assert db.get_provider(USER_ID) is None
    assert not session_file.exists()
    ctx.bot.send_message.assert_awaited_once()
    assert ctx.bot.send_message.await_args.kwargs["chat_id"] == USER_ID
    update.message.reply_text.assert_awaited_once()
    owner_text = update.message.reply_text.await_args.args[0].lower()
    assert "revoked" in owner_text
    # Orphan pruning kicked in: channel 100 is gone and the subscriber got DM'd.
    assert db.get_channel(100) is None
    state_send_dm = ctx.bot_data["state"].send_dm
    state_send_dm.assert_awaited_once()
    dm_user_id, dm_text = state_send_dm.await_args.args
    assert dm_user_id == SUBSCRIBER_ID
    assert "OnlyVia42" in dm_text and "no longer available" in dm_text.lower()


async def test_revoke_provider_handles_missing_session_file(
    db: Database, tmp_path: Path,
) -> None:
    missing = tmp_path / f"{USER_ID}.session"
    db.add_pending_provider(user_id=USER_ID, session_path=str(missing))
    db.set_provider_status(user_id=USER_ID, status="approved")
    ctx = _ctx(db)
    update = _msg_update(OWNER_ID, text=f"/revoke_provider {USER_ID}")

    await cmd_revoke_provider(update, ctx)

    assert db.get_provider(USER_ID) is None
    ctx.bot.send_message.assert_awaited_once()
    update.message.reply_text.assert_awaited_once()
