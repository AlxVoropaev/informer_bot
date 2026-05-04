from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.tl.types import Channel

from informer_bot.client import catch_up
from informer_bot.db import Database


class _AsyncIter:
    def __init__(self, items: list) -> None:
        self._items = list(items)

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _msg(message_id: int, date_ts: int, text: str = "x", grouped_id: int | None = None):
    return SimpleNamespace(
        id=message_id,
        date=datetime.fromtimestamp(date_ts, tz=timezone.utc),
        message=text,
        grouped_id=grouped_id,
        photo=None,
    )


def _entity(channel_id: int, username: str) -> Channel:
    e = MagicMock(spec=Channel)
    e.id = channel_id
    e.broadcast = True
    e.username = username
    return e


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "c.db")


async def test_catch_up_skips_channels_with_no_prior_seen(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    tg = MagicMock()
    tg.get_entity = AsyncMock()
    tg.iter_messages = MagicMock()
    buffer = MagicMock()
    buffer.add = AsyncMock()

    await catch_up(tg, db, buffer, max_age_seconds=48 * 3600, now=1_000_000)

    tg.get_entity.assert_not_called()
    buffer.add.assert_not_called()


async def test_catch_up_replays_posts_newer_than_max_seen(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.mark_seen(channel_id=1, message_id=100)
    now = 1_000_000
    messages = [
        _msg(101, now - 3600, text="recent"),
        _msg(102, now - 7200, text="also recent", grouped_id=42),
    ]
    tg = MagicMock()
    tg.get_entity = AsyncMock(return_value=_entity(1, "chan"))
    tg.iter_messages = MagicMock(return_value=_AsyncIter(messages))
    buffer = MagicMock()
    buffer.add = AsyncMock()

    await catch_up(tg, db, buffer, max_age_seconds=48 * 3600, now=now)

    assert tg.iter_messages.call_args.kwargs == {"min_id": 100, "reverse": True}
    assert buffer.add.await_count == 2
    first_call = buffer.add.await_args_list[0].kwargs
    assert first_call["channel_id"] == 1
    assert first_call["channel_username"] == "chan"
    assert first_call["message_id"] == 101
    assert first_call["text"] == "recent"
    assert first_call["grouped_id"] is None
    assert buffer.add.await_args_list[1].kwargs["grouped_id"] == 42


async def test_catch_up_drops_posts_outside_window(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.mark_seen(channel_id=1, message_id=100)
    now = 1_000_000
    window = 48 * 3600
    messages = [
        _msg(101, now - window - 10, text="too old"),
        _msg(102, now - window + 10, text="just inside"),
    ]
    tg = MagicMock()
    tg.get_entity = AsyncMock(return_value=_entity(1, "chan"))
    tg.iter_messages = MagicMock(return_value=_AsyncIter(messages))
    buffer = MagicMock()
    buffer.add = AsyncMock()

    await catch_up(tg, db, buffer, max_age_seconds=window, now=now)

    assert buffer.add.await_count == 1
    assert buffer.add.await_args.kwargs["message_id"] == 102


async def test_catch_up_skips_off_and_blacklisted(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Off")
    db.upsert_channel(channel_id=2, title="Banned")
    db.subscribe(user_id=10, channel_id=1, mode="off")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.set_blacklisted(channel_id=2, blacklisted=True)
    db.mark_seen(channel_id=1, message_id=50)
    db.mark_seen(channel_id=2, message_id=50)
    tg = MagicMock()
    tg.get_entity = AsyncMock()
    tg.iter_messages = MagicMock()
    buffer = MagicMock()
    buffer.add = AsyncMock()

    await catch_up(tg, db, buffer, max_age_seconds=48 * 3600, now=1_000_000)

    tg.get_entity.assert_not_called()
    buffer.add.assert_not_called()
