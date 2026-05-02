from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from informer_bot.db import Database
from informer_bot.pipeline import handle_new_post, refresh_channels


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "p.db")


# ---------- handle_new_post ----------

async def test_handle_new_post_skips_empty_text(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    summarize = AsyncMock()
    send_dm = AsyncMock()

    await handle_new_post(
        channel_id=1, message_id=100, text="   ",
        link="https://t.me/a/100", db=db, summarize_fn=summarize, send_dm=send_dm,
    )

    summarize.assert_not_called()
    send_dm.assert_not_called()


async def test_handle_new_post_summarises_and_dms_subscribers(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=20, channel_id=1)
    summarize = AsyncMock(return_value="Brief.")
    send_dm = AsyncMock()

    await handle_new_post(
        channel_id=1, message_id=100, text="Long post body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize, send_dm=send_dm,
    )

    summarize.assert_awaited_once_with("Long post body")
    assert send_dm.await_count == 2
    sent = {call.args[0]: call.args[1] for call in send_dm.await_args_list}
    assert sent[10] == "Brief.\n\nhttps://t.me/a/100"
    assert sent[20] == "Brief.\n\nhttps://t.me/a/100"


async def test_handle_new_post_is_idempotent_per_message(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    summarize = AsyncMock(return_value="Brief.")
    send_dm = AsyncMock()

    for _ in range(2):
        await handle_new_post(
            channel_id=1, message_id=100, text="body",
            link="https://t.me/a/100", db=db, summarize_fn=summarize, send_dm=send_dm,
        )

    summarize.assert_awaited_once()
    send_dm.assert_awaited_once()


async def test_handle_new_post_silent_when_channel_blacklisted(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    db.set_blacklisted(channel_id=1, blacklisted=True)
    summarize = AsyncMock(return_value="Brief.")
    send_dm = AsyncMock()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize, send_dm=send_dm,
    )

    send_dm.assert_not_called()


# ---------- refresh_channels ----------

async def test_refresh_upserts_new_channels(db: Database) -> None:
    fetch = AsyncMock(return_value=[(1, "Alpha"), (2, "Beta")])
    send_dm = AsyncMock()

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    titles = {c.id: c.title for c in db.list_channels(include_blacklisted=True)}
    assert titles == {1: "Alpha", 2: "Beta"}
    send_dm.assert_not_called()


async def test_refresh_notifies_subscribers_when_channel_disappears(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha")
    db.upsert_channel(channel_id=2, title="Gone")
    db.subscribe(user_id=10, channel_id=2)
    db.subscribe(user_id=20, channel_id=2)

    fetch = AsyncMock(return_value=[(1, "Alpha")])
    send_dm = AsyncMock()

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    assert send_dm.await_count == 2
    for call in send_dm.await_args_list:
        user_id, text = call.args
        assert user_id in {10, 20}
        assert "Gone" in text and "no longer available" in text.lower()
    assert {c.id for c in db.list_channels(include_blacklisted=True)} == {1}


async def test_refresh_silent_for_disappeared_blacklisted_channels(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha")
    db.upsert_channel(channel_id=2, title="WasBanned")
    db.subscribe(user_id=10, channel_id=2)
    db.set_blacklisted(channel_id=2, blacklisted=True)

    fetch = AsyncMock(return_value=[(1, "Alpha")])
    send_dm = AsyncMock()

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    send_dm.assert_not_called()
    assert {c.id for c in db.list_channels(include_blacklisted=True)} == {1}
