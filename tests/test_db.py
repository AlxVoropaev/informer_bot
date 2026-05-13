import sqlite3
from pathlib import Path

import pytest

from informer_bot.db import Database, format_user_label
from informer_bot.modes import SubscriptionMode


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _seed_owner(db: Database, owner_id: int = 1) -> None:
    """Set up the legacy 'owner' provider so `set_blacklisted` & friends
    can route through `channel_blacklist(owner_id, ...)`. The multi-provider
    schema removed `channels.blacklisted`; tests that exercise the legacy
    blacklist API need an owner to write against."""
    db.set_user_status(user_id=owner_id, status="approved")
    db.add_pending_provider(user_id=owner_id, session_path="data/informer.session")
    db.set_provider_status(user_id=owner_id, status="approved")
    db.set_meta("owner_id", str(owner_id))


def test_upsert_channel_inserts_then_updates_title(db: Database) -> None:
    db.upsert_channel(channel_id=100, title="Old")
    db.upsert_channel(channel_id=100, title="New")

    channels = db.list_channels()

    assert len(channels) == 1
    assert channels[0].id == 100
    assert channels[0].title == "New"
    assert channels[0].blacklisted is False


def test_upsert_channel_preserves_blacklisted_flag(db: Database) -> None:
    # Multi-provider schema moved blacklisted out of `channels` into
    # `channel_blacklist`; upsert_channel never touched the new table so the
    # flag survives an upsert trivially. Test still exercises the original
    # intent: an upsert mustn't clear a prior blacklist.
    _seed_owner(db)
    db.upsert_channel(channel_id=100, title="Foo")
    db.set_blacklisted(channel_id=100, blacklisted=True)
    db.upsert_channel(channel_id=100, title="Foo renamed")

    [channel] = db.list_channels(include_blacklisted=True)
    assert channel.blacklisted is True


def test_list_channels_excludes_blacklisted_by_default(db: Database) -> None:
    _seed_owner(db)
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
    assert db.list_user_subscription_modes(user_id=42) == {1: SubscriptionMode.FILTERED}


def test_subscribe_default_mode_is_filtered(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1)

    assert db.get_subscription_mode(user_id=42, channel_id=1) == SubscriptionMode.FILTERED


def test_subscribe_with_mode_all(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1, mode=SubscriptionMode.ALL)

    assert db.get_subscription_mode(user_id=42, channel_id=1) == SubscriptionMode.ALL


def test_subscribe_with_mode_debug(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1, mode=SubscriptionMode.DEBUG)

    assert db.get_subscription_mode(user_id=42, channel_id=1) == SubscriptionMode.DEBUG


def test_dedup_debug_default_false(db: Database) -> None:
    assert db.get_dedup_debug(user_id=42) is False


def test_set_dedup_debug_creates_user_row(db: Database) -> None:
    db.set_dedup_debug(user_id=42, enabled=True)

    assert db.get_dedup_debug(user_id=42) is True
    assert db.get_user_status(user_id=42) == "pending"


def test_set_dedup_debug_toggles(db: Database) -> None:
    db.add_pending_user(user_id=42, username="alice")
    db.set_dedup_debug(user_id=42, enabled=True)
    db.set_dedup_debug(user_id=42, enabled=False)

    assert db.get_dedup_debug(user_id=42) is False


def test_subscribe_updates_existing_mode(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=42, channel_id=1, mode=SubscriptionMode.FILTERED)
    db.subscribe(user_id=42, channel_id=1, mode=SubscriptionMode.ALL)

    assert db.get_subscription_mode(user_id=42, channel_id=1) == SubscriptionMode.ALL


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
    _seed_owner(db)
    db.upsert_channel(channel_id=1, title="Open")
    db.upsert_channel(channel_id=2, title="Banned")
    db.set_provider_channels(provider_user_id=1, channel_ids={1, 2})
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
    db.subscribe(user_id=10, channel_id=2)
    db.subscribe(user_id=20, channel_id=1)
    db.set_blacklisted(channel_id=2, blacklisted=True)

    assert sorted(db.subscribers_for_channel(channel_id=1)) == [
        (10, SubscriptionMode.ALL),
        (20, SubscriptionMode.FILTERED),
    ]
    assert db.subscribers_for_channel(channel_id=2) == []


def test_subscribers_for_channel_skips_when_sole_provider_blacklisted(db: Database) -> None:
    # Provider A is the sole contributor and blacklists the channel themselves.
    # Even on a fresh install (no meta.owner_id), subscribers must NOT receive.
    # This is the production scenario captured on finka2 (May 2026).
    PROVIDER = 1
    db.set_user_status(user_id=PROVIDER, status="approved")
    db.add_pending_provider(user_id=PROVIDER, session_path="data/sessions/1.session")
    db.set_provider_status(user_id=PROVIDER, status="approved")
    db.upsert_channel(channel_id=100, title="Lepra")
    db.set_provider_channels(provider_user_id=PROVIDER, channel_ids={100})
    db.subscribe(user_id=PROVIDER, channel_id=100, mode=SubscriptionMode.ALL)
    db.subscribe(user_id=99, channel_id=100, mode=SubscriptionMode.FILTERED)
    db.set_provider_channel_blacklisted(
        provider_user_id=PROVIDER, channel_id=100, blacklisted=True,
    )
    # Note: meta.owner_id intentionally NOT set — this is the fresh-install case.

    assert db.subscribers_for_channel(channel_id=100) == []


def test_subscribers_for_channel_still_delivers_when_other_provider_contributes(
    db: Database,
) -> None:
    # Provider A blacklists, Provider B still contributes the same channel.
    # Channel stays visible → subscribers (including A) still receive.
    A, B = 1, 2
    for pid in (A, B):
        db.set_user_status(user_id=pid, status="approved")
        db.add_pending_provider(user_id=pid, session_path=f"data/sessions/{pid}.session")
        db.set_provider_status(user_id=pid, status="approved")
    db.upsert_channel(channel_id=100, title="Shared")
    db.set_provider_channels(provider_user_id=A, channel_ids={100})
    db.set_provider_channels(provider_user_id=B, channel_ids={100})
    db.subscribe(user_id=A, channel_id=100, mode=SubscriptionMode.ALL)
    db.subscribe(user_id=50, channel_id=100, mode=SubscriptionMode.FILTERED)
    db.set_provider_channel_blacklisted(
        provider_user_id=A, channel_id=100, blacklisted=True,
    )

    subs = sorted(db.subscribers_for_channel(channel_id=100))
    assert subs == [(A, SubscriptionMode.ALL), (50, SubscriptionMode.FILTERED)]


def test_mark_seen_returns_true_only_first_time(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")

    assert db.mark_seen(channel_id=1, message_id=555) is True
    assert db.mark_seen(channel_id=1, message_id=555) is False
    assert db.mark_seen(channel_id=1, message_id=556) is True


def test_max_seen_message_id_returns_none_when_empty(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    assert db.max_seen_message_id(channel_id=1) is None


def test_max_seen_message_id_returns_highest(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.mark_seen(channel_id=1, message_id=10)
    db.mark_seen(channel_id=1, message_id=42)
    db.mark_seen(channel_id=1, message_id=33)
    db.mark_seen(channel_id=2, message_id=999)

    assert db.max_seen_message_id(channel_id=1) == 42
    assert db.max_seen_message_id(channel_id=2) == 999


def test_channels_with_active_subscribers_excludes_off_and_blacklisted(db: Database) -> None:
    _seed_owner(db)
    db.upsert_channel(channel_id=1, title="On")
    db.upsert_channel(channel_id=2, title="Off")
    db.upsert_channel(channel_id=3, title="Banned")
    db.upsert_channel(channel_id=4, title="NoSubs")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.FILTERED)
    db.subscribe(user_id=10, channel_id=2, mode=SubscriptionMode.OFF)
    db.subscribe(user_id=10, channel_id=3, mode=SubscriptionMode.ALL)
    db.set_blacklisted(channel_id=3, blacklisted=True)

    assert db.channels_with_active_subscribers() == [1]


def test_channels_with_active_subscribers_dedupes_across_users(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Shared")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
    db.subscribe(user_id=20, channel_id=1, mode=SubscriptionMode.FILTERED)

    assert db.channels_with_active_subscribers() == [1]


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
    assert db.list_user_subscription_modes(user_id=10) == {2: SubscriptionMode.FILTERED}
    assert db.list_user_subscription_modes(user_id=20) == {}


# ---------- usage tracking ----------

def test_get_usage_returns_empty_for_unknown_user(db: Database) -> None:
    assert db.get_usage(user_id=42) == []


def test_add_usage_accumulates(db: Database) -> None:
    db.add_usage(user_id=42, provider="anthropic", input_tokens=100, output_tokens=20)
    db.add_usage(user_id=42, provider="anthropic", input_tokens=50, output_tokens=10)

    assert db.get_usage(user_id=42) == [("anthropic", 150, 30)]


def test_add_usage_separate_users(db: Database) -> None:
    db.add_usage(user_id=10, provider="anthropic", input_tokens=100, output_tokens=20)
    db.add_usage(user_id=20, provider="anthropic", input_tokens=200, output_tokens=40)

    assert db.get_usage(user_id=10) == [("anthropic", 100, 20)]
    assert db.get_usage(user_id=20) == [("anthropic", 200, 40)]


def test_add_usage_separate_providers_for_same_user(db: Database) -> None:
    db.add_usage(user_id=10, provider="anthropic", input_tokens=100, output_tokens=20)
    db.add_usage(user_id=10, provider="remote", input_tokens=300, output_tokens=50)

    assert db.get_usage(user_id=10) == [
        ("anthropic", 100, 20),
        ("remote", 300, 50),
    ]


def test_get_system_usage_starts_empty(db: Database) -> None:
    assert db.get_system_usage() == []


def test_add_system_usage_accumulates(db: Database) -> None:
    db.add_system_usage(provider="anthropic", input_tokens=100, output_tokens=20)
    db.add_system_usage(provider="anthropic", input_tokens=50, output_tokens=10)

    assert db.get_system_usage() == [("anthropic", 150, 30)]


def test_add_system_usage_separate_providers(db: Database) -> None:
    db.add_system_usage(provider="anthropic", input_tokens=100, output_tokens=20)
    db.add_system_usage(provider="remote", input_tokens=300, output_tokens=50)

    assert db.get_system_usage() == [
        ("anthropic", 100, 20),
        ("remote", 300, 50),
    ]


def test_list_all_usage_returns_raw_fields(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice", first_name="Alice")
    db.add_pending_user(user_id=20, username=None, first_name="Bob")
    db.add_pending_user(user_id=30, username=None, first_name=None)
    db.add_usage(user_id=10, provider="anthropic", input_tokens=100, output_tokens=20)
    db.add_usage(user_id=20, provider="anthropic", input_tokens=50, output_tokens=10)
    db.add_usage(user_id=30, provider="anthropic", input_tokens=25, output_tokens=5)

    rows = db.list_all_usage()
    by_uid = {
        uid: (username, first_name, provider, inp, out)
        for uid, username, first_name, provider, inp, out in rows
    }

    assert by_uid[10] == ("alice", "Alice", "anthropic", 100, 20)
    assert by_uid[20] == (None, "Bob", "anthropic", 50, 10)
    assert by_uid[30] == (None, None, "anthropic", 25, 5)


def test_list_all_usage_includes_users_without_user_row(db: Database) -> None:
    db.add_usage(user_id=99, provider="anthropic", input_tokens=10, output_tokens=2)

    rows = {
        uid: (username, first_name, provider, inp, out)
        for uid, username, first_name, provider, inp, out in db.list_all_usage()
    }
    assert rows[99] == (None, None, "anthropic", 10, 2)


def test_list_all_usage_returns_one_row_per_user_provider(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice")
    db.add_usage(user_id=10, provider="anthropic", input_tokens=100, output_tokens=20)
    db.add_usage(user_id=10, provider="remote", input_tokens=300, output_tokens=50)

    rows = db.list_all_usage()
    providers = sorted(provider for _, _, _, provider, _, _ in rows)
    assert providers == ["anthropic", "remote"]


def test_format_user_label_renders_username_first_name_and_fallback() -> None:
    assert format_user_label(10, "alice", "Alice") == "@alice (10)"
    assert format_user_label(20, None, "Bob") == "Bob (20)"
    assert format_user_label(30, None, None) == "(30)"


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
    assert db.get_subscription_mode(user_id=10, channel_id=1) == SubscriptionMode.OFF


def test_set_channel_filter_preserves_existing_mode(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.ALL)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="x")

    assert db.get_subscription_mode(user_id=10, channel_id=1) == SubscriptionMode.ALL


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
    _seed_owner(db)
    db.upsert_channel(channel_id=1, title="A")
    db.set_provider_channels(provider_user_id=1, channel_ids={1})
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.FILTERED)
    db.subscribe(user_id=20, channel_id=1, mode=SubscriptionMode.OFF)
    db.subscribe(user_id=30, channel_id=1, mode=SubscriptionMode.ALL)

    subs = sorted(db.subscribers_for_channel(channel_id=1))
    assert subs == [(10, SubscriptionMode.FILTERED), (30, SubscriptionMode.ALL)]


def test_off_mode_preserves_filter_prompt(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.FILTERED)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="keep me")
    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.OFF)

    assert db.get_channel_filter(user_id=10, channel_id=1) == "keep me"

    db.subscribe(user_id=10, channel_id=1, mode=SubscriptionMode.FILTERED)
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


# ---------- dedup ----------

def test_store_and_list_dedup_candidates_round_trip(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[0.1, 0.2, 0.3],
        summary="s1", link="l1", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=999,
        is_photo=False, body="body1", now=1000,
    )

    rows = db.list_dedup_candidates(user_id=10, since=0)

    assert len(rows) == 1
    cid, mid, bmid, is_p, dup_links, vec, link = rows[0]
    assert (cid, mid, bmid, is_p, dup_links, link) == (1, 100, 999, False, [], "l1")
    assert vec == pytest.approx([0.1, 0.2, 0.3], rel=1e-5)


def test_list_dedup_candidates_filters_by_user(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="s", link="l", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b10", now=1000,
    )
    db.record_delivered(
        user_id=20, channel_id=1, message_id=100, bot_message_id=2,
        is_photo=True, body="b20", now=1000,
    )

    rows10 = db.list_dedup_candidates(user_id=10, since=0)
    rows20 = db.list_dedup_candidates(user_id=20, since=0)

    assert [r[2] for r in rows10] == [1]
    assert [r[2] for r in rows20] == [2]
    assert [r[3] for r in rows10] == [False]
    assert [r[3] for r in rows20] == [True]


def test_list_dedup_candidates_filters_by_since(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0],
        summary="old", link="l1", now=500,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b1", now=500,
    )
    db.store_post_embedding(
        channel_id=1, message_id=200, embedding=[1.0],
        summary="new", link="l2", now=2000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=200, bot_message_id=2,
        is_photo=False, body="b2", now=2000,
    )

    rows = db.list_dedup_candidates(user_id=10, since=1000)

    assert [r[1] for r in rows] == [200]


def test_list_dedup_candidates_skips_delivered_without_embedding(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=1000,
    )

    assert db.list_dedup_candidates(user_id=10, since=0) == []


def test_dup_links_default_empty_and_round_trip(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0],
        summary="s", link="l", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="orig", now=1000,
    )

    assert db.get_delivered_dup_links(
        user_id=10, channel_id=1, message_id=100
    ) == []

    db.set_delivered_dup_links(
        user_id=10, channel_id=1, message_id=100,
        dup_links=[("Channel B", "https://t.me/b/200")],
    )

    assert db.get_delivered_dup_links(
        user_id=10, channel_id=1, message_id=100
    ) == [("Channel B", "https://t.me/b/200")]

    [(_, _, _, _, dup_links, _, _)] = db.list_dedup_candidates(user_id=10, since=0)
    assert dup_links == [("Channel B", "https://t.me/b/200")]


def test_purge_dedup_older_than_cutoff(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0], summary="o", link="l", now=500,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=500,
    )
    db.store_post_embedding(
        channel_id=1, message_id=200, embedding=[1.0], summary="n", link="l", now=2000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=200, bot_message_id=2,
        is_photo=False, body="b", now=2000,
    )

    db.purge_dedup_older_than(cutoff=1000)

    rows = db.list_dedup_candidates(user_id=10, since=0)
    assert [r[1] for r in rows] == [200]


def test_get_embedding_usage_starts_empty(db: Database) -> None:
    assert db.get_embedding_usage() == []


def test_add_embedding_usage_accumulates(db: Database) -> None:
    db.add_embedding_usage(provider="openai", tokens=50)
    db.add_embedding_usage(provider="openai", tokens=25)

    assert db.get_embedding_usage() == [("openai", 75)]


def test_add_embedding_usage_separate_providers(db: Database) -> None:
    db.add_embedding_usage(provider="openai", tokens=50)
    db.add_embedding_usage(provider="remote", tokens=20)

    assert db.get_embedding_usage() == [("openai", 50), ("remote", 20)]


def test_migration_v10_to_v11_preserves_old_usage_under_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-populate a v10-shape DB with the old singleton-row usage tables,
    then open it through Database and confirm the rows survive under
    provider='unknown'."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE channels (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            blacklisted INTEGER NOT NULL DEFAULT 0, username TEXT, about TEXT
        );
        CREATE TABLE subscriptions (
            user_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'filtered'
                CHECK(mode IN ('off','filtered','debug','all')),
            filter_prompt TEXT,
            PRIMARY KEY (user_id, channel_id),
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        );
        CREATE TABLE seen (
            channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            PRIMARY KEY (channel_id, message_id)
        );
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
            username TEXT, first_name TEXT,
            language TEXT NOT NULL DEFAULT 'en' CHECK(language IN ('en','ru')),
            auto_delete_hours INTEGER,
            dedup_debug INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE usage (
            user_id INTEGER PRIMARY KEY,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE system_usage (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE post_embeddings (
            channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL, embedding BLOB NOT NULL,
            summary TEXT NOT NULL, link TEXT NOT NULL,
            PRIMARY KEY (channel_id, message_id)
        );
        CREATE TABLE delivered (
            user_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL, bot_message_id INTEGER NOT NULL,
            is_photo INTEGER NOT NULL, body TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            dup_links_json TEXT NOT NULL DEFAULT '[]',
            saved INTEGER NOT NULL DEFAULT 0,
            delete_at INTEGER,
            PRIMARY KEY (user_id, channel_id, message_id)
        );
        CREATE TABLE embedding_usage (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            tokens INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO usage (user_id, input_tokens, output_tokens)
            VALUES (10, 123, 45), (20, 7, 1);
        INSERT INTO system_usage (id, input_tokens, output_tokens)
            VALUES (1, 999, 100);
        INSERT INTO embedding_usage (id, tokens) VALUES (1, 555);
        INSERT INTO meta (key, value) VALUES ('schema_version', '10');
        """
    )
    conn.commit()
    conn.close()

    # Migration 11 -> 12 needs OWNER_ID; this v10 test now also walks through
    # the multi-provider migration, so seed the env.
    monkeypatch.setenv("OWNER_ID", "1")
    db = Database(db_path)

    assert db.get_usage(user_id=10) == [("unknown", 123, 45)]
    assert db.get_usage(user_id=20) == [("unknown", 7, 1)]
    assert db.get_system_usage() == [("unknown", 999, 100)]
    assert db.get_embedding_usage() == [("unknown", 555)]


def test_purge_dedup_all_clears_both_tables(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0], summary="s", link="l", now=500,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=500,
    )

    db.purge_dedup_all()

    assert db.list_dedup_candidates(user_id=10, since=0) == []


def test_meta_get_returns_none_when_unset(db: Database) -> None:
    assert db.get_meta("anything") is None


def test_meta_set_then_get_roundtrips(db: Database) -> None:
    db.set_meta("embedding_id", "openai:text-embedding-3-small:512")
    assert db.get_meta("embedding_id") == "openai:text-embedding-3-small:512"


def test_meta_set_overwrites(db: Database) -> None:
    db.set_meta("embedding_id", "v1")
    db.set_meta("embedding_id", "v2")
    assert db.get_meta("embedding_id") == "v2"


# ---------- auto-delete ----------

def test_auto_delete_hours_default_none(db: Database) -> None:
    db.add_pending_user(user_id=10, username="a")
    assert db.get_user_auto_delete_hours(10) is None


def test_auto_delete_hours_round_trip(db: Database) -> None:
    db.add_pending_user(user_id=10, username="a")
    db.set_user_auto_delete_hours(10, 6)
    assert db.get_user_auto_delete_hours(10) == 6
    db.set_user_auto_delete_hours(10, None)
    assert db.get_user_auto_delete_hours(10) is None


def test_record_delivered_stores_delete_at_when_provided(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=999,
        is_photo=False, body="b", now=1000, delete_at=4600,
    )
    state = db.get_delivered_save_state(user_id=10, channel_id=1, message_id=100)
    assert state == (False, 4600)


def test_record_delivered_no_delete_at_when_omitted(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=999,
        is_photo=False, body="b", now=1000,
    )
    state = db.get_delivered_save_state(user_id=10, channel_id=1, message_id=100)
    assert state == (False, None)


def test_set_delivered_saved_toggles(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=999,
        is_photo=False, body="b", now=1000, delete_at=4600,
    )
    db.set_delivered_saved(
        user_id=10, channel_id=1, message_id=100, saved=True, delete_at=None,
    )
    assert db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=100,
    ) == (True, None)
    db.set_delivered_saved(
        user_id=10, channel_id=1, message_id=100, saved=False, delete_at=9999,
    )
    assert db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=100,
    ) == (False, 9999)


def test_extend_delete_at_skips_saved_rows(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=999,
        is_photo=False, body="b", now=1000, delete_at=2000,
    )
    db.set_delivered_saved(
        user_id=10, channel_id=1, message_id=100, saved=True, delete_at=None,
    )
    db.extend_delivered_delete_at(
        user_id=10, channel_id=1, message_id=100, delete_at=8000,
    )
    assert db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=100,
    ) == (True, None)


def test_extend_delete_at_updates_unsaved(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=999,
        is_photo=False, body="b", now=1000, delete_at=2000,
    )
    db.extend_delivered_delete_at(
        user_id=10, channel_id=1, message_id=100, delete_at=8000,
    )
    assert db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=100,
    ) == (False, 8000)


def test_get_delivered_by_bot_msg_returns_none_when_missing(db: Database) -> None:
    assert db.get_delivered_by_bot_msg(user_id=10, bot_message_id=999) is None


def test_get_delivered_by_bot_msg_returns_row(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=42, message_id=123, bot_message_id=777,
        is_photo=True, body="b", now=1000, delete_at=5000,
    )
    row = db.get_delivered_by_bot_msg(user_id=10, bot_message_id=777)
    assert row is not None
    assert row == (42, 123, True, False, 5000)  # channel_id, msg_id, is_photo, saved, delete_at


def test_list_due_deletions_returns_unsaved_rows_at_or_before_now(
    db: Database,
) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=1000, delete_at=2000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=101, bot_message_id=2,
        is_photo=False, body="b", now=1000, delete_at=3000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=102, bot_message_id=3,
        is_photo=False, body="b", now=1000, delete_at=2500,
    )
    db.set_delivered_saved(
        user_id=10, channel_id=1, message_id=102, saved=True, delete_at=None,
    )
    due = db.list_due_deletions(now=2500)
    assert sorted(due) == [(10, 1, 100, 1, False), (10, 1, 101, 2, False)] or \
        sorted(due) == [(10, 1, 100, 1, False)]
    # 101 has delete_at=3000 > 2500, so it shouldn't be due yet
    due = db.list_due_deletions(now=2500)
    assert (10, 1, 100, 1, False) in due
    assert (10, 1, 101, 2, False) not in due
    assert (10, 1, 102, 3, False) not in due


def test_delete_delivered_row_removes_only_that_row(db: Database) -> None:
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=1000, delete_at=2000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=101, bot_message_id=2,
        is_photo=False, body="b", now=1000, delete_at=2000,
    )
    db.delete_delivered_row(user_id=10, channel_id=1, message_id=100)
    assert db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=100,
    ) is None
    assert db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=101,
    ) == (False, 2000)


# ---------- transactions ----------

def test_transaction_commits_on_success(db: Database) -> None:
    db.add_pending_user(user_id=1, username="a")
    with db.transaction():
        db.add_usage(user_id=1, provider="anthropic", input_tokens=10, output_tokens=2)
        db.add_system_usage(provider="anthropic", input_tokens=10, output_tokens=2)

    assert db.get_usage(user_id=1) == [("anthropic", 10, 2)]
    assert db.get_system_usage() == [("anthropic", 10, 2)]


def test_transaction_rolls_back_on_exception(db: Database) -> None:
    db.add_pending_user(user_id=1, username="a")
    db.add_usage(user_id=1, provider="anthropic", input_tokens=5, output_tokens=1)
    db.add_system_usage(provider="anthropic", input_tokens=5, output_tokens=1)

    with pytest.raises(RuntimeError):
        with db.transaction():
            db.add_usage(user_id=1, provider="anthropic", input_tokens=100, output_tokens=20)
            db.add_system_usage(provider="anthropic", input_tokens=100, output_tokens=20)
            raise RuntimeError("boom")

    assert db.get_usage(user_id=1) == [("anthropic", 5, 1)]
    assert db.get_system_usage() == [("anthropic", 5, 1)]


def test_transaction_nested_flat(db: Database) -> None:
    db.add_pending_user(user_id=1, username="a")
    with db.transaction():
        db.add_usage(user_id=1, provider="anthropic", input_tokens=3, output_tokens=1)
        with db.transaction():
            db.add_system_usage(provider="anthropic", input_tokens=3, output_tokens=1)

    assert db.get_usage(user_id=1) == [("anthropic", 3, 1)]
    assert db.get_system_usage() == [("anthropic", 3, 1)]


# ---------- multi-provider migration & schema ----------


def _make_legacy_v11_db(path: Path) -> None:
    """Materialize a v11-shape DB on disk: schema BEFORE the multi-provider
    migration. Mirrors the pre-12 layout: `channels.blacklisted` lives on
    the row, `providers` and `channel_blacklist` don't exist."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE channels (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            blacklisted INTEGER NOT NULL DEFAULT 0,
            username TEXT, about TEXT
        );
        CREATE TABLE subscriptions (
            user_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'filtered'
                CHECK(mode IN ('off','filtered','debug','all')),
            filter_prompt TEXT,
            PRIMARY KEY (user_id, channel_id),
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        );
        CREATE TABLE seen (
            channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            PRIMARY KEY (channel_id, message_id)
        );
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
            username TEXT, first_name TEXT,
            language TEXT NOT NULL DEFAULT 'en' CHECK(language IN ('en','ru')),
            auto_delete_hours INTEGER,
            dedup_debug INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE usage (
            user_id INTEGER NOT NULL, provider TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, provider)
        );
        CREATE TABLE system_usage (
            provider TEXT PRIMARY KEY,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE post_embeddings (
            channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL, embedding BLOB NOT NULL,
            summary TEXT NOT NULL, link TEXT NOT NULL,
            PRIMARY KEY (channel_id, message_id)
        );
        CREATE TABLE delivered (
            user_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL, bot_message_id INTEGER NOT NULL,
            is_photo INTEGER NOT NULL, body TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            dup_links_json TEXT NOT NULL DEFAULT '[]',
            saved INTEGER NOT NULL DEFAULT 0,
            delete_at INTEGER,
            PRIMARY KEY (user_id, channel_id, message_id)
        );
        CREATE TABLE embedding_usage (
            provider TEXT PRIMARY KEY,
            tokens INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('schema_version', '11');
        """
    )
    conn.commit()
    conn.close()


def test_multi_provider_migration_seeds_owner_and_copies_blacklist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "legacy.db"
    _make_legacy_v11_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO channels (id, title, blacklisted) VALUES
            (1, 'Open', 0),
            (2, 'Banned', 1),
            (3, 'AlsoBanned', 1);
        INSERT INTO subscriptions (user_id, channel_id, mode) VALUES (10, 2, 'all');
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("OWNER_ID", "777")
    db = Database(db_path)

    # Column dropped
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(channels)")}
    assert cols == {"id", "title", "username", "about"}

    # Owner provider seeded
    owner = db.get_provider(user_id=777)
    assert owner is not None
    assert owner.status == "approved"
    assert owner.session_path == "data/informer.session"
    assert owner.approved_at is not None

    # Owner's user row was inserted (FK requirement)
    assert db.get_user_status(user_id=777) == "approved"

    # Legacy blacklist copied into channel_blacklist for the owner
    assert db.list_provider_blacklist(provider_user_id=777) == {2, 3}

    # meta.owner_id is set so the legacy shims can find the owner
    assert db.get_meta("owner_id") == "777"

    # FKs intact: subscriptions(channel_id) still resolves
    bad = db._conn.execute("PRAGMA foreign_key_check").fetchall()
    assert bad == []


def test_multi_provider_migration_requires_owner_id_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "legacy.db"
    _make_legacy_v11_db(db_path)

    monkeypatch.delenv("OWNER_ID", raising=False)
    with pytest.raises(RuntimeError, match="OWNER_ID"):
        Database(db_path)


def test_legacy_set_blacklisted_writes_into_owner_blacklist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "legacy.db"
    _make_legacy_v11_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "INSERT INTO channels (id, title, blacklisted) VALUES (1, 'A', 0);"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("OWNER_ID", "555")
    db = Database(db_path)

    # Compat shim: set_blacklisted routes through the new table for the owner.
    db.set_blacklisted(channel_id=1, blacklisted=True)
    assert db.list_provider_blacklist(provider_user_id=555) == {1}

    # And Channel.blacklisted reflects it via list_channels.
    [ch] = [c for c in db.list_channels(include_blacklisted=True) if c.id == 1]
    assert ch.blacklisted is True

    # Default list_channels (include_blacklisted=False) excludes it.
    assert db.list_channels() == []

    # Toggling off removes the row.
    db.set_blacklisted(channel_id=1, blacklisted=False)
    assert db.list_provider_blacklist(provider_user_id=555) == set()


def test_set_blacklisted_raises_when_owner_id_unset(db: Database) -> None:
    """Fresh DB has no owner provider; the legacy shim must fail loudly
    rather than silently no-op so callers know to seed the owner first."""
    db.upsert_channel(channel_id=1, title="A")
    with pytest.raises(RuntimeError, match="owner_id"):
        db.set_blacklisted(channel_id=1, blacklisted=True)


def test_list_channels_treats_unblacklisted_when_owner_unset(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    [a, b] = db.list_channels()
    assert a.blacklisted is False
    assert b.blacklisted is False


# ---------- providers API ----------


def test_add_pending_provider_inserts_pending_row(db: Database) -> None:
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="data/p10.session", now=1000)

    p = db.get_provider(user_id=10)
    assert p is not None
    assert p.user_id == 10
    assert p.status == "pending"
    assert p.session_path == "data/p10.session"
    assert p.requested_at == 1000
    assert p.approved_at is None


def test_add_pending_provider_resets_status_to_pending(db: Database) -> None:
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="old", now=100)
    db.set_provider_status(user_id=10, status="approved", now=200)
    db.add_pending_provider(user_id=10, session_path="new", now=300)

    p = db.get_provider(user_id=10)
    assert p is not None
    assert p.status == "pending"
    assert p.session_path == "new"
    assert p.requested_at == 300
    assert p.approved_at is None


def test_set_provider_status_approved_stamps_approved_at(db: Database) -> None:
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="s", now=100)
    db.set_provider_status(user_id=10, status="approved", now=500)

    p = db.get_provider(user_id=10)
    assert p is not None
    assert p.status == "approved"
    assert p.approved_at == 500


def test_set_provider_status_denied_keeps_approved_at(db: Database) -> None:
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="s", now=100)
    db.set_provider_status(user_id=10, status="approved", now=500)
    db.set_provider_status(user_id=10, status="denied", now=600)

    p = db.get_provider(user_id=10)
    assert p is not None
    assert p.status == "denied"
    # approved_at preserved as historical record
    assert p.approved_at == 500


def test_set_provider_status_rejects_invalid(db: Database) -> None:
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="s")
    with pytest.raises(ValueError):
        db.set_provider_status(user_id=10, status="bogus")


def test_list_providers_filter_by_status(db: Database) -> None:
    for uid in (10, 20, 30):
        db.set_user_status(user_id=uid, status="approved")
        db.add_pending_provider(user_id=uid, session_path=f"s{uid}")
    db.set_provider_status(user_id=20, status="approved")
    db.set_provider_status(user_id=30, status="denied")

    pending = db.list_providers(status="pending")
    approved = db.list_providers(status="approved")
    all_ = db.list_providers()

    assert [p.user_id for p in pending] == [10]
    assert [p.user_id for p in approved] == [20]
    assert [p.user_id for p in all_] == [10, 20, 30]


def test_list_approved_provider_ids(db: Database) -> None:
    for uid in (10, 20, 30):
        db.set_user_status(user_id=uid, status="approved")
        db.add_pending_provider(user_id=uid, session_path="s")
    db.set_provider_status(user_id=10, status="approved")
    db.set_provider_status(user_id=30, status="approved")
    assert db.list_approved_provider_ids() == [10, 30]


def test_delete_provider_cascades_blacklist(db: Database) -> None:
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="s")
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.set_provider_channel_blacklisted(provider_user_id=10, channel_id=1, blacklisted=True)
    db.set_provider_channel_blacklisted(provider_user_id=10, channel_id=2, blacklisted=True)
    assert db.list_provider_blacklist(provider_user_id=10) == {1, 2}

    db.delete_provider(user_id=10)

    assert db.get_provider(user_id=10) is None
    assert db.list_provider_blacklist(provider_user_id=10) == set()


# ---------- per-provider blacklist ----------


def test_set_provider_channel_blacklisted_idempotent(db: Database) -> None:
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="s")
    db.upsert_channel(channel_id=1, title="A")

    db.set_provider_channel_blacklisted(provider_user_id=10, channel_id=1, blacklisted=True)
    db.set_provider_channel_blacklisted(provider_user_id=10, channel_id=1, blacklisted=True)
    assert db.is_blacklisted(provider_user_id=10, channel_id=1) is True
    assert db.list_provider_blacklist(provider_user_id=10) == {1}

    db.set_provider_channel_blacklisted(provider_user_id=10, channel_id=1, blacklisted=False)
    assert db.is_blacklisted(provider_user_id=10, channel_id=1) is False
    assert db.list_provider_blacklist(provider_user_id=10) == set()


# ---------- list_visible_channels ----------


def test_list_visible_channels_empty_when_no_approved_providers(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    # Pending providers don't count.
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_provider(user_id=10, session_path="s")
    assert db.list_visible_channels() == []
    assert db.is_visible_channel(1) is False


def test_list_visible_channels_owner_only_unblacklisted(db: Database) -> None:
    _seed_owner(db, owner_id=1)
    db.upsert_channel(channel_id=1, title="Visible")
    db.upsert_channel(channel_id=2, title="Hidden")
    db.set_provider_channels(provider_user_id=1, channel_ids={1, 2})
    db.set_provider_channel_blacklisted(provider_user_id=1, channel_id=2, blacklisted=True)

    visible_ids = [c.id for c in db.list_visible_channels()]
    assert visible_ids == [1]
    assert db.is_visible_channel(1) is True
    assert db.is_visible_channel(2) is False


def test_list_visible_channels_two_providers_one_blacklists(db: Database) -> None:
    _seed_owner(db, owner_id=1)
    db.set_user_status(user_id=2, status="approved")
    db.add_pending_provider(user_id=2, session_path="b.session")
    db.set_provider_status(user_id=2, status="approved")
    db.upsert_channel(channel_id=10, title="Shared")
    db.set_provider_channels(provider_user_id=1, channel_ids={10})
    db.set_provider_channels(provider_user_id=2, channel_ids={10})
    # Owner blacklists; provider 2 does not -> still visible.
    db.set_provider_channel_blacklisted(provider_user_id=1, channel_id=10, blacklisted=True)

    assert [c.id for c in db.list_visible_channels()] == [10]
    assert db.is_visible_channel(10) is True


def test_list_visible_channels_hidden_when_all_providers_blacklist(db: Database) -> None:
    _seed_owner(db, owner_id=1)
    db.set_user_status(user_id=2, status="approved")
    db.add_pending_provider(user_id=2, session_path="b.session")
    db.set_provider_status(user_id=2, status="approved")
    db.upsert_channel(channel_id=10, title="Shared")
    db.set_provider_channels(provider_user_id=1, channel_ids={10})
    db.set_provider_channels(provider_user_id=2, channel_ids={10})
    db.set_provider_channel_blacklisted(provider_user_id=1, channel_id=10, blacklisted=True)
    db.set_provider_channel_blacklisted(provider_user_id=2, channel_id=10, blacklisted=True)

    assert db.list_visible_channels() == []
    assert db.is_visible_channel(10) is False
