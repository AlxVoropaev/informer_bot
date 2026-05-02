from pathlib import Path

import pytest

from informer_bot.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def test_upsert_channel_inserts_then_updates_title(db: Database) -> None:
    db.upsert_channel(channel_id=100, title="Old")
    db.upsert_channel(channel_id=100, title="New")

    channels = db.list_channels()

    assert len(channels) == 1
    assert channels[0].id == 100
    assert channels[0].title == "New"
    assert channels[0].blacklisted is False


def test_upsert_channel_preserves_blacklisted_flag(db: Database) -> None:
    db.upsert_channel(channel_id=100, title="Foo")
    db.set_blacklisted(channel_id=100, blacklisted=True)
    db.upsert_channel(channel_id=100, title="Foo renamed")

    [channel] = db.list_channels(include_blacklisted=True)
    assert channel.blacklisted is True


def test_list_channels_excludes_blacklisted_by_default(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Visible")
    db.upsert_channel(channel_id=2, title="Hidden")
    db.set_blacklisted(channel_id=2, blacklisted=True)

    visible = db.list_channels()
    all_ = db.list_channels(include_blacklisted=True)

    assert [c.id for c in visible] == [1]
    assert sorted(c.id for c in all_) == [1, 2]


def test_subscribe_is_idempotent(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")

    db.subscribe(user_id=42, channel_id=1)
    db.subscribe(user_id=42, channel_id=1)

    assert db.is_subscribed(user_id=42, channel_id=1) is True
    assert db.list_user_subscriptions(user_id=42) == [1]


def test_unsubscribe(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1)

    db.unsubscribe(user_id=42, channel_id=1)

    assert db.is_subscribed(user_id=42, channel_id=1) is False
    assert db.list_user_subscriptions(user_id=42) == []


def test_subscribers_for_channel_skips_blacklisted_channel(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Open")
    db.upsert_channel(channel_id=2, title="Banned")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=10, channel_id=2)
    db.subscribe(user_id=20, channel_id=1)
    db.set_blacklisted(channel_id=2, blacklisted=True)

    assert sorted(db.subscribers_for_channel(channel_id=1)) == [10, 20]
    assert db.subscribers_for_channel(channel_id=2) == []


def test_mark_seen_returns_true_only_first_time(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")

    assert db.mark_seen(channel_id=1, message_id=555) is True
    assert db.mark_seen(channel_id=1, message_id=555) is False
    assert db.mark_seen(channel_id=1, message_id=556) is True
