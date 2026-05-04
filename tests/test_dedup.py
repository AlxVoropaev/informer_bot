from pathlib import Path

import pytest

from informer_bot.db import Database
from informer_bot.dedup import cosine, find_duplicate


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "d.db")


def test_cosine_identical_is_one() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_scale_invariant() -> None:
    assert cosine([1.0, 1.0], [2.0, 2.0]) == pytest.approx(1.0)


def test_cosine_zero_vector_returns_zero() -> None:
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        cosine([1.0], [1.0, 0.0])


def test_find_duplicate_returns_none_when_no_candidates(db: Database) -> None:
    match = find_duplicate(
        db=db, user_id=10, vec=[1.0, 0.0],
        threshold=0.85, window_seconds=3600, now=1000,
    )
    assert match is None


def test_find_duplicate_hits_above_threshold(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="s", link="L1", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=999,
        is_photo=False, body="orig", now=1000,
    )

    db.set_delivered_dup_links(
        user_id=10, channel_id=1, message_id=100,
        dup_links=[("X", "lx")],
    )

    match = find_duplicate(
        db=db, user_id=10, vec=[0.99, 0.01],
        threshold=0.85, window_seconds=3600, now=1500,
    )

    assert match is not None
    assert match.channel_id == 1
    assert match.message_id == 100
    assert match.bot_message_id == 999
    assert match.dup_links == [("X", "lx")]
    assert match.link == "L1"
    assert match.score >= 0.85


def test_find_duplicate_misses_below_threshold(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="s", link="l", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=1000,
    )

    match = find_duplicate(
        db=db, user_id=10, vec=[0.0, 1.0],
        threshold=0.85, window_seconds=3600, now=1500,
    )

    assert match is None


def test_find_duplicate_picks_best_score(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[0.9, 0.1],
        summary="s1", link="L1", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b1", now=1000,
    )
    db.store_post_embedding(
        channel_id=2, message_id=200, embedding=[1.0, 0.0],
        summary="s2", link="L2", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=2, message_id=200, bot_message_id=2,
        is_photo=False, body="b2", now=1000,
    )

    match = find_duplicate(
        db=db, user_id=10, vec=[1.0, 0.0],
        threshold=0.85, window_seconds=3600, now=1500,
    )

    assert match is not None
    assert match.bot_message_id == 2


def test_find_duplicate_excludes_outside_window(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="s", link="l", now=100,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=100,
    )

    match = find_duplicate(
        db=db, user_id=10, vec=[1.0, 0.0],
        threshold=0.85, window_seconds=60, now=10_000,
    )

    assert match is None


def test_find_duplicate_isolates_per_user(db: Database) -> None:
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="s", link="l", now=1000,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="b", now=1000,
    )

    match = find_duplicate(
        db=db, user_id=20, vec=[1.0, 0.0],
        threshold=0.85, window_seconds=3600, now=1500,
    )

    assert match is None
