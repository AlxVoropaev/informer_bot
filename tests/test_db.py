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
    assert db.list_user_subscription_modes(user_id=42) == {1: "filtered"}


def test_subscribe_default_mode_is_filtered(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1)

    assert db.get_subscription_mode(user_id=42, channel_id=1) == "filtered"


def test_subscribe_with_mode_all(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1, mode="all")

    assert db.get_subscription_mode(user_id=42, channel_id=1) == "all"


def test_subscribe_updates_existing_mode(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1, mode="filtered")
    db.subscribe(user_id=42, channel_id=1, mode="all")

    assert db.get_subscription_mode(user_id=42, channel_id=1) == "all"


def test_get_subscription_mode_returns_none_when_not_subscribed(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    assert db.get_subscription_mode(user_id=42, channel_id=1) is None


def test_unsubscribe(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1)

    db.unsubscribe(user_id=42, channel_id=1)

    assert db.is_subscribed(user_id=42, channel_id=1) is False
    assert db.list_user_subscription_modes(user_id=42) == {}


def test_subscribers_for_channel_skips_blacklisted_channel(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Open")
    db.upsert_channel(channel_id=2, title="Banned")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.subscribe(user_id=10, channel_id=2)
    db.subscribe(user_id=20, channel_id=1)
    db.set_blacklisted(channel_id=2, blacklisted=True)

    assert sorted(db.subscribers_for_channel(channel_id=1)) == [(10, "all"), (20, "filtered")]
    assert db.subscribers_for_channel(channel_id=2) == []


def test_mark_seen_returns_true_only_first_time(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")

    assert db.mark_seen(channel_id=1, message_id=555) is True
    assert db.mark_seen(channel_id=1, message_id=555) is False
    assert db.mark_seen(channel_id=1, message_id=556) is True


def test_get_user_status_returns_none_for_unknown_user(db: Database) -> None:
    assert db.get_user_status(user_id=42) is None


def test_add_pending_user_sets_status_and_username(db: Database) -> None:
    db.add_pending_user(user_id=42, username="alice")

    assert db.get_user_status(user_id=42) == "pending"


def test_add_pending_user_is_idempotent_does_not_overwrite_status(db: Database) -> None:
    db.add_pending_user(user_id=42, username="alice")
    db.set_user_status(user_id=42, status="approved")
    db.add_pending_user(user_id=42, username="alice")

    assert db.get_user_status(user_id=42) == "approved"


def test_set_user_status_updates_existing(db: Database) -> None:
    db.add_pending_user(user_id=42, username="alice")
    db.set_user_status(user_id=42, status="denied")

    assert db.get_user_status(user_id=42) == "denied"


def test_delete_channel_removes_channel_and_subscriptions(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=10, channel_id=2)
    db.subscribe(user_id=20, channel_id=1)

    db.delete_channel(channel_id=1)

    assert [c.id for c in db.list_channels(include_blacklisted=True)] == [2]
    assert db.list_user_subscription_modes(user_id=10) == {2: "filtered"}
    assert db.list_user_subscription_modes(user_id=20) == {}


# ---------- usage tracking ----------

def test_get_usage_returns_zero_for_unknown_user(db: Database) -> None:
    assert db.get_usage(user_id=42) == (0, 0)


def test_add_usage_accumulates(db: Database) -> None:
    db.add_usage(user_id=42, input_tokens=100, output_tokens=20)
    db.add_usage(user_id=42, input_tokens=50, output_tokens=10)

    assert db.get_usage(user_id=42) == (150, 30)


def test_add_usage_separate_users(db: Database) -> None:
    db.add_usage(user_id=10, input_tokens=100, output_tokens=20)
    db.add_usage(user_id=20, input_tokens=200, output_tokens=40)

    assert db.get_usage(user_id=10) == (100, 20)
    assert db.get_usage(user_id=20) == (200, 40)


def test_get_system_usage_starts_at_zero(db: Database) -> None:
    assert db.get_system_usage() == (0, 0)


def test_add_system_usage_accumulates(db: Database) -> None:
    db.add_system_usage(input_tokens=100, output_tokens=20)
    db.add_system_usage(input_tokens=50, output_tokens=10)

    assert db.get_system_usage() == (150, 30)


def test_list_all_usage_returns_label_and_tokens(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice", first_name="Alice")
    db.add_pending_user(user_id=20, username=None, first_name="Bob")
    db.add_pending_user(user_id=30, username=None, first_name=None)
    db.add_usage(user_id=10, input_tokens=100, output_tokens=20)
    db.add_usage(user_id=20, input_tokens=50, output_tokens=10)
    db.add_usage(user_id=30, input_tokens=25, output_tokens=5)

    rows = {uid: (label, inp, out) for uid, label, inp, out in db.list_all_usage()}

    assert rows[10] == ("@alice (10)", 100, 20)
    assert rows[20] == ("Bob (20)", 50, 10)
    assert rows[30] == ("(30)", 25, 5)


def test_list_all_usage_includes_users_without_user_row(db: Database) -> None:
    db.add_usage(user_id=99, input_tokens=10, output_tokens=2)

    rows = {uid: (label, inp, out) for uid, label, inp, out in db.list_all_usage()}
    assert rows[99] == ("(99)", 10, 2)


def test_add_pending_user_stores_first_name(db: Database) -> None:
    db.add_pending_user(user_id=42, username="alice", first_name="Alice")

    assert db.get_user_label(user_id=42) == "@alice (42)"


def test_get_user_label_falls_back_to_first_name_then_id(db: Database) -> None:
    db.add_pending_user(user_id=10, username=None, first_name="Bob")
    db.add_pending_user(user_id=20, username=None, first_name=None)

    assert db.get_user_label(user_id=10) == "Bob (10)"
    assert db.get_user_label(user_id=20) == "(20)"
    assert db.get_user_label(user_id=999) == "(999)"


def test_list_user_ids(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice")
    db.add_pending_user(user_id=20, username="bob")

    assert db.list_user_ids() == [10, 20]


def test_update_user_name_overwrites_username_and_first_name(db: Database) -> None:
    db.add_pending_user(user_id=10, username="old", first_name="Old")

    db.update_user_name(user_id=10, username="new", first_name="New")

    assert db.get_user_label(user_id=10) == "@new (10)"


def test_get_channel_filter_returns_none_when_unset(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    assert db.get_channel_filter(user_id=10, channel_id=1) is None
    assert db.get_channel_filter(user_id=999, channel_id=1) is None


def test_set_channel_filter_round_trips(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")

    assert db.get_channel_filter(user_id=10, channel_id=1) == "only AI"


def test_set_channel_filter_clear_removes_prompt(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="x")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt=None)

    assert db.get_channel_filter(user_id=10, channel_id=1) is None


def test_set_channel_filter_creates_off_subscription_if_missing(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")

    assert db.get_channel_filter(user_id=10, channel_id=1) == "only AI"
    assert db.get_subscription_mode(user_id=10, channel_id=1) == "off"


def test_set_channel_filter_preserves_existing_mode(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="x")

    assert db.get_subscription_mode(user_id=10, channel_id=1) == "all"


def test_filter_per_channel_is_isolated(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=10, channel_id=2)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="for A")
    db.set_channel_filter(user_id=10, channel_id=2, filter_prompt="for B")

    assert db.get_channel_filter(user_id=10, channel_id=1) == "for A"
    assert db.get_channel_filter(user_id=10, channel_id=2) == "for B"


def test_subscribers_for_channel_skips_off_mode(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="filtered")
    db.subscribe(user_id=20, channel_id=1, mode="off")
    db.subscribe(user_id=30, channel_id=1, mode="all")

    subs = sorted(db.subscribers_for_channel(channel_id=1))
    assert subs == [(10, "filtered"), (30, "all")]


def test_off_mode_preserves_filter_prompt(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="filtered")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="keep me")
    db.subscribe(user_id=10, channel_id=1, mode="off")

    assert db.get_channel_filter(user_id=10, channel_id=1) == "keep me"

    db.subscribe(user_id=10, channel_id=1, mode="filtered")
    assert db.get_channel_filter(user_id=10, channel_id=1) == "keep me"


def test_list_user_subscription_filters(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=10, channel_id=2)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="for A")

    assert db.list_user_subscription_filters(user_id=10) == {1: "for A", 2: None}


def test_get_language_defaults_to_en(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice")
    assert db.get_language(user_id=10) == "en"
    assert db.get_language(user_id=999) == "en"


def test_set_language_round_trips_and_overwrites(db: Database) -> None:
    db.set_language(user_id=10, language="ru")
    assert db.get_language(user_id=10) == "ru"
    db.set_language(user_id=10, language="en")
    assert db.get_language(user_id=10) == "en"


def test_update_user_name_can_clear_username(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice", first_name="Alice")

    db.update_user_name(user_id=10, username=None, first_name="Alice")

    assert db.get_user_label(user_id=10) == "Alice (10)"
