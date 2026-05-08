"""Tests for `informer_bot.cli_login.main`.

The Telethon client is stubbed with `FakeClient` so the CLI never reaches
the network. The fake writes a sentinel byte at the session path inside
`start()` to mirror Telethon's real behaviour of creating the SQLite
session file on disk.
"""
import stat
from pathlib import Path

import pytest

from informer_bot import cli_login
from informer_bot.db import Database


class FakeClient:
    """Stand-in for ``telethon.TelegramClient``.

    Stores constructor args on the class so tests can assert what the CLI
    passed in, and writes a sentinel file at ``session_path`` from
    ``start()`` to simulate Telethon writing the on-disk session.
    """

    last_init: tuple[str, int, str] | None = None
    started = False
    disconnected = False

    def __init__(self, session: str, api_id: int, api_hash: str) -> None:
        FakeClient.last_init = (session, api_id, api_hash)
        self._session = session

    async def start(self) -> "FakeClient":
        FakeClient.started = True
        Path(self._session).write_bytes(b"fake-session")
        return self

    async def disconnect(self) -> None:
        FakeClient.disconnected = True


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeClient.last_init = None
    FakeClient.started = False
    FakeClient.disconnected = False


@pytest.fixture
def env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Set up TELEGRAM_API_ID/HASH + a tmp DB_PATH and stub Telethon."""
    monkeypatch.setenv("TELEGRAM_API_ID", "111")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr(cli_login, "TelegramClient", FakeClient)
    return tmp_path


def _seed_provider(
    db_path: Path, user_id: int, status: str, session_path: Path,
) -> None:
    db = Database(db_path)
    # `providers.user_id` has an FK to `users.user_id`, so seed the user row
    # first.
    db.set_user_status(user_id=user_id, status="approved")
    db.add_pending_provider(user_id=user_id, session_path=str(session_path))
    if status != "pending":
        db.set_provider_status(user_id=user_id, status=status)


def test_missing_user_id_exits_2(
    env: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_login.main([])

    assert exc.value.code == 2
    assert "user-id" in capsys.readouterr().err


def test_unknown_user_exits_1(
    env: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli_login.main(["--user-id", "42"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "no provider request for user 42" in err
    assert "/become_provider" in err


def test_pending_provider_exits_1(
    env: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_provider(
        env / "test.db", user_id=42, status="pending",
        session_path=env / "sessions" / "p42.session",
    )

    rc = cli_login.main(["--user-id", "42"])

    assert rc == 1
    assert "pending owner approval" in capsys.readouterr().err
    assert FakeClient.started is False


def test_denied_provider_exits_1(
    env: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_provider(
        env / "test.db", user_id=42, status="denied",
        session_path=env / "sessions" / "p42.session",
    )

    rc = cli_login.main(["--user-id", "42"])

    assert rc == 1
    assert "denied" in capsys.readouterr().err
    assert FakeClient.started is False


def test_existing_session_without_force_exits_1(
    env: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = env / "sessions" / "p42.session"
    session_path.parent.mkdir(parents=True)
    session_path.write_bytes(b"old")
    _seed_provider(
        env / "test.db", user_id=42, status="approved",
        session_path=session_path,
    )

    rc = cli_login.main(["--user-id", "42"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "--force" in err
    # FakeClient must not have been started.
    assert FakeClient.started is False
    # File untouched.
    assert session_path.read_bytes() == b"old"


def test_approved_provider_writes_session_and_chmods(
    env: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = env / "sessions" / "p42.session"
    _seed_provider(
        env / "test.db", user_id=42, status="approved",
        session_path=session_path,
    )

    rc = cli_login.main(["--user-id", "42"])

    assert rc == 0
    assert FakeClient.started is True
    assert FakeClient.disconnected is True
    assert FakeClient.last_init == (str(session_path), 111, "deadbeef")
    assert session_path.read_bytes() == b"fake-session"
    # 0o600 on the session file (best-effort, but POSIX tmp_path supports it).
    mode = stat.S_IMODE(session_path.stat().st_mode)
    assert mode == 0o600
    out = capsys.readouterr().out
    assert "session written to" in out


def test_force_overwrites_existing_session(
    env: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = env / "sessions" / "p42.session"
    session_path.parent.mkdir(parents=True)
    session_path.write_bytes(b"old")
    _seed_provider(
        env / "test.db", user_id=42, status="approved",
        session_path=session_path,
    )

    rc = cli_login.main(["--user-id", "42", "--force"])

    assert rc == 0
    assert FakeClient.started is True
    assert session_path.read_bytes() == b"fake-session"
