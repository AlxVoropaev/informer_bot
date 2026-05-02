import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Channel:
    id: int
    title: str
    blacklisted: bool


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    blacklisted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id    INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, channel_id),
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);
CREATE TABLE IF NOT EXISTS seen (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (channel_id, message_id)
);
CREATE TABLE IF NOT EXISTS users (
    user_id  INTEGER PRIMARY KEY,
    status   TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
    username TEXT
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        log.debug("opened sqlite at %s", path)

    def upsert_channel(self, channel_id: int, title: str) -> None:
        self._conn.execute(
            "INSERT INTO channels (id, title) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title = excluded.title",
            (channel_id, title),
        )
        self._conn.commit()
        log.debug("upsert_channel id=%s title=%r", channel_id, title)

    def set_blacklisted(self, channel_id: int, blacklisted: bool) -> None:
        self._conn.execute(
            "UPDATE channels SET blacklisted = ? WHERE id = ?",
            (1 if blacklisted else 0, channel_id),
        )
        self._conn.commit()
        log.debug("set_blacklisted id=%s blacklisted=%s", channel_id, blacklisted)

    def list_channels(self, include_blacklisted: bool = False) -> list[Channel]:
        sql = "SELECT id, title, blacklisted FROM channels"
        if not include_blacklisted:
            sql += " WHERE blacklisted = 0"
        sql += " ORDER BY title"
        return [Channel(id=r[0], title=r[1], blacklisted=bool(r[2])) for r in self._conn.execute(sql)]

    def subscribe(self, user_id: int, channel_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO subscriptions (user_id, channel_id) VALUES (?, ?)",
            (user_id, channel_id),
        )
        self._conn.commit()

    def unsubscribe(self, user_id: int, channel_id: int) -> None:
        self._conn.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )
        self._conn.commit()

    def is_subscribed(self, user_id: int, channel_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        ).fetchone()
        return row is not None

    def list_user_subscriptions(self, user_id: int) -> list[int]:
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT channel_id FROM subscriptions WHERE user_id = ? ORDER BY channel_id",
                (user_id,),
            )
        ]

    def subscribers_for_channel(self, channel_id: int) -> list[int]:
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT s.user_id FROM subscriptions s "
                "JOIN channels c ON c.id = s.channel_id "
                "WHERE s.channel_id = ? AND c.blacklisted = 0",
                (channel_id,),
            )
        ]

    def delete_channel(self, channel_id: int) -> None:
        self._conn.execute("DELETE FROM subscriptions WHERE channel_id = ?", (channel_id,))
        self._conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        self._conn.commit()
        log.debug("delete_channel id=%s", channel_id)

    def get_user_status(self, user_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row else None

    def add_pending_user(self, user_id: int, username: str | None) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO users (user_id, status, username) VALUES (?, 'pending', ?)",
            (user_id, username),
        )
        self._conn.commit()
        log.debug("add_pending_user user=%s username=%r", user_id, username)

    def set_user_status(self, user_id: int, status: str) -> None:
        self._conn.execute(
            "INSERT INTO users (user_id, status) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET status = excluded.status",
            (user_id, status),
        )
        self._conn.commit()
        log.debug("set_user_status user=%s status=%s", user_id, status)

    def mark_seen(self, channel_id: int, message_id: int) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO seen (channel_id, message_id) VALUES (?, ?)",
            (channel_id, message_id),
        )
        self._conn.commit()
        return cursor.rowcount == 1
