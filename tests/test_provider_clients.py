from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from informer_bot.db import Database
from informer_bot.provider_clients import (
    ProviderClient,
    make_source_dedup_claim,
    start_all,
    stop_all,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "p.db")


def _seed_provider(db: Database, user_id: int, session_path: str) -> None:
    db.set_user_status(user_id=user_id, status="approved")
    db.add_pending_provider(user_id=user_id, session_path=session_path)
    db.set_provider_status(user_id=user_id, status="approved")


def _fake_factory(authorized: bool = True):
    """Return a `(session_path, api_id, api_hash) -> MagicMock` factory.

    The returned client mocks `connect`, `is_user_authorized`, `disconnect`,
    and `on` (used by `register_new_post_handler`).
    """
    def factory(session_path: str, api_id: int, api_hash: str) -> MagicMock:
        client = MagicMock()
        client.connect = AsyncMock()
        client.is_user_authorized = AsyncMock(return_value=authorized)
        client.disconnect = AsyncMock()
        # `register_new_post_handler` registers via @tg.on(events.NewMessage()).
        client.on = MagicMock(side_effect=lambda _flt: lambda fn: fn)
        return client
    return factory


async def test_start_all_skips_provider_with_missing_session(
    db: Database, tmp_path: Path,
) -> None:
    missing = tmp_path / "absent.session"
    _seed_provider(db, user_id=10, session_path=str(missing))

    buffer = MagicMock()
    clients = await start_all(
        db=db, api_id=1, api_hash="h", buffer=buffer,
        client_factory=_fake_factory(),
    )

    assert clients == []


async def test_start_all_returns_one_client_per_present_session(
    db: Database, tmp_path: Path,
) -> None:
    s1 = tmp_path / "p1.session"
    s1.write_text("x")
    s2 = tmp_path / "p2.session"
    s2.write_text("x")
    s_missing = tmp_path / "missing.session"

    _seed_provider(db, user_id=10, session_path=str(s1))
    _seed_provider(db, user_id=20, session_path=str(s2))
    _seed_provider(db, user_id=30, session_path=str(s_missing))

    buffer = MagicMock()
    factory = _fake_factory()
    clients = await start_all(
        db=db, api_id=1, api_hash="h", buffer=buffer,
        client_factory=factory,
    )

    assert sorted(c.user_id for c in clients) == [10, 20]
    for c in clients:
        c.tg.connect.assert_awaited_once()
        c.tg.is_user_authorized.assert_awaited_once()
        c.tg.on.assert_called()  # NewMessage handler registered.


async def test_start_all_skips_unauthorized_session(
    db: Database, tmp_path: Path,
) -> None:
    s = tmp_path / "p.session"
    s.write_text("x")
    _seed_provider(db, user_id=10, session_path=str(s))

    factory = _fake_factory(authorized=False)
    clients = await start_all(
        db=db, api_id=1, api_hash="h", buffer=MagicMock(),
        client_factory=factory,
    )

    assert clients == []


async def test_stop_all_disconnects_each_client() -> None:
    pcs = [
        ProviderClient(
            user_id=10,
            tg=MagicMock(disconnect=AsyncMock()),
            session_path="a",
        ),
        ProviderClient(
            user_id=20,
            tg=MagicMock(disconnect=AsyncMock()),
            session_path="b",
        ),
    ]
    await stop_all(pcs)
    for pc in pcs:
        pc.tg.disconnect.assert_awaited_once()


def test_source_dedup_claim_first_caller_wins() -> None:
    inflight: set[tuple[int, int]] = set()
    claim = make_source_dedup_claim(inflight)

    assert claim(1, 100) is True
    assert claim(1, 100) is False
    assert claim(1, 101) is True
    assert claim(2, 100) is True
