from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.tl.types import Channel

from informer_bot.client import (
    _download_photo,
    catch_up,
    fetch_subscribed_channels,
    register_new_post_handler,
)
from informer_bot.db import Database
from informer_bot.modes import SubscriptionMode


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
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
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
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
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
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
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
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.OFF)
    db.subscribe(user_id=10, channel_id=2, mode=SubscriptionMode.ALL)
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


async def test_catch_up_continues_after_get_entity_raises(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Bad")
    db.upsert_channel(channel_id=2, title="Good")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
    db.subscribe(user_id=10, channel_id=2, mode=SubscriptionMode.ALL)
    db.mark_seen(channel_id=1, message_id=50)
    db.mark_seen(channel_id=2, message_id=50)
    now = 1_000_000

    async def fake_get_entity(channel_id: int):
        if channel_id == 1:
            raise RuntimeError("boom")
        return _entity(2, "good")

    messages = [_msg(101, now - 60, text="hi")]
    tg = MagicMock()
    tg.get_entity = AsyncMock(side_effect=fake_get_entity)
    tg.iter_messages = MagicMock(return_value=_AsyncIter(messages))
    buffer = MagicMock()
    buffer.add = AsyncMock()

    await catch_up(tg, db, buffer, max_age_seconds=48 * 3600, now=now)

    # get_entity called for both channels; iter_messages only ran for channel 2.
    assert tg.get_entity.await_count == 2
    assert buffer.add.await_count == 1
    assert buffer.add.await_args.kwargs["channel_id"] == 2


async def test_catch_up_skips_non_broadcast_entity(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
    db.mark_seen(channel_id=1, message_id=50)

    private = MagicMock(spec=Channel)
    private.id = 1
    private.broadcast = False
    private.username = "priv"

    tg = MagicMock()
    tg.get_entity = AsyncMock(return_value=private)
    tg.iter_messages = MagicMock()
    buffer = MagicMock()
    buffer.add = AsyncMock()

    await catch_up(tg, db, buffer, max_age_seconds=48 * 3600, now=1_000_000)

    tg.iter_messages.assert_not_called()
    buffer.add.assert_not_called()


async def test_catch_up_skips_entity_without_username(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
    db.mark_seen(channel_id=1, message_id=50)

    private = MagicMock(spec=Channel)
    private.id = 1
    private.broadcast = True
    private.username = None  # private channel, no public link

    tg = MagicMock()
    tg.get_entity = AsyncMock(return_value=private)
    tg.iter_messages = MagicMock()
    buffer = MagicMock()
    buffer.add = AsyncMock()

    await catch_up(tg, db, buffer, max_age_seconds=48 * 3600, now=1_000_000)

    tg.iter_messages.assert_not_called()
    buffer.add.assert_not_called()


# ---------- fetch_subscribed_channels: GetFullChannelRequest failure ----------

async def test_fetch_subscribed_channels_silent_failure_returns_about_none() -> None:
    """When GetFullChannelRequest raises, the channel is still returned with
    `about=None` instead of crashing the whole fetch."""
    entity = _entity(123, "alphachan")
    entity.title = "Alpha"
    dialog = SimpleNamespace(entity=entity)

    async def _raising_call(*_args, **_kwargs):
        raise RuntimeError("flood")

    tg = MagicMock(side_effect=_raising_call)
    tg.iter_dialogs = MagicMock(return_value=_AsyncIter([dialog]))

    out = await fetch_subscribed_channels(tg)

    assert out == [(123, "Alpha", "alphachan", None)]


# ---------- _download_photo failure ----------

async def test_download_photo_returns_none_on_exception() -> None:
    """download_media raising should return None, not propagate."""
    msg = SimpleNamespace(
        id=42,
        photo=object(),  # truthy, so we go into the try branch
        download_media=AsyncMock(side_effect=RuntimeError("net down")),
    )
    result = await _download_photo(msg)
    assert result is None


async def test_download_photo_returns_none_when_no_photo() -> None:
    """No photo on the message -> early-return None without calling download."""
    msg = SimpleNamespace(id=42, photo=None, download_media=AsyncMock())
    result = await _download_photo(msg)
    assert result is None
    msg.download_media.assert_not_awaited()


# ---------- register_new_post_handler: early drop ----------

def _capture_handler(tg: MagicMock):
    """Capture the handler registered via @tg.on(events.NewMessage())."""
    captured: list = []

    def on_decorator(_event_filter):
        def decorator(fn):
            captured.append(fn)
            return fn

        return decorator

    tg.on = MagicMock(side_effect=on_decorator)
    return captured


async def test_register_new_post_handler_drops_non_broadcast_chat() -> None:
    tg = MagicMock()
    captured = _capture_handler(tg)
    buffer = MagicMock()
    buffer.add = AsyncMock()
    register_new_post_handler(tg, buffer)
    assert len(captured) == 1
    handler = captured[0]

    chat = MagicMock(spec=Channel)
    chat.id = 1
    chat.broadcast = False
    chat.username = "x"
    event = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        message=SimpleNamespace(id=10, message="hi", grouped_id=None, photo=None),
    )

    await handler(event)

    buffer.add.assert_not_called()


async def test_register_new_post_handler_drops_chat_without_username() -> None:
    tg = MagicMock()
    captured = _capture_handler(tg)
    buffer = MagicMock()
    buffer.add = AsyncMock()
    register_new_post_handler(tg, buffer)
    handler = captured[0]

    chat = MagicMock(spec=Channel)
    chat.id = 1
    chat.broadcast = True
    chat.username = None
    event = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        message=SimpleNamespace(id=10, message="hi", grouped_id=None, photo=None),
    )

    await handler(event)

    buffer.add.assert_not_called()


async def test_register_new_post_handler_forwards_broadcast_with_username() -> None:
    tg = MagicMock()
    captured = _capture_handler(tg)
    buffer = MagicMock()
    buffer.add = AsyncMock()
    register_new_post_handler(tg, buffer)
    handler = captured[0]

    chat = _entity(7, "newschan")
    event = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        message=SimpleNamespace(
            id=10, message="hello", grouped_id=None, photo=None
        ),
    )

    await handler(event)

    buffer.add.assert_awaited_once()
    kwargs = buffer.add.await_args.kwargs
    assert kwargs["channel_id"] == 7
    assert kwargs["channel_username"] == "newschan"
    assert kwargs["text"] == "hello"
