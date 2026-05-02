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
    user_id       INTEGER PRIMARY KEY,
    status        TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
    username      TEXT,
    first_name    TEXT,
    filter_prompt TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    user_id       INTEGER PRIMARY KEY,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS system_usage (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO system_usage (id, input_tokens, output_tokens) VALUES (1, 0, 0);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(users)")}
        if "first_name" not in cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        if "filter_prompt" not in cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN filter_prompt TEXT")
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

    def add_pending_user(
        self, user_id: int, username: str | None, first_name: str | None = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO users (user_id, status, username, first_name) "
            "VALUES (?, 'pending', ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "username = excluded.username, "
            "first_name = COALESCE(excluded.first_name, users.first_name)",
            (user_id, username, first_name),
        )
        self._conn.commit()
        log.debug(
            "add_pending_user user=%s username=%r first_name=%r",
            user_id, username, first_name,
        )

    def set_user_status(self, user_id: int, status: str) -> None:
        self._conn.execute(
            "INSERT INTO users (user_id, status) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET status = excluded.status",
            (user_id, status),
        )
        self._conn.commit()
        log.debug("set_user_status user=%s status=%s", user_id, status)

    def list_user_ids(self) -> list[int]:
        return [r[0] for r in self._conn.execute("SELECT user_id FROM users ORDER BY user_id")]

    def update_user_name(
        self, user_id: int, username: str | None, first_name: str | None
    ) -> None:
        self._conn.execute(
            "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
            (username, first_name, user_id),
        )
        self._conn.commit()
        log.debug(
            "update_user_name user=%s username=%r first_name=%r",
            user_id, username, first_name,
        )

    def get_user_label(self, user_id: int) -> str:
        row = self._conn.execute(
            "SELECT username, first_name FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        username = row[0] if row else None
        first_name = row[1] if row else None
        if username:
            return f"@{username} ({user_id})"
        if first_name:
            return f"{first_name} ({user_id})"
        return f"({user_id})"

    def get_filter(self, user_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT filter_prompt FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row and row[0] else None

    def set_filter(self, user_id: int, filter_prompt: str | None) -> None:
        self._conn.execute(
            "UPDATE users SET filter_prompt = ? WHERE user_id = ?",
            (filter_prompt, user_id),
        )
        self._conn.commit()
        log.debug("set_filter user=%s len=%s", user_id, len(filter_prompt) if filter_prompt else 0)

    def add_usage(self, user_id: int, input_tokens: int, output_tokens: int) -> None:
        self._conn.execute(
            "INSERT INTO usage (user_id, input_tokens, output_tokens) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "input_tokens = usage.input_tokens + excluded.input_tokens, "
            "output_tokens = usage.output_tokens + excluded.output_tokens",
            (user_id, input_tokens, output_tokens),
        )
        self._conn.commit()

    def get_usage(self, user_id: int) -> tuple[int, int]:
        row = self._conn.execute(
            "SELECT input_tokens, output_tokens FROM usage WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def list_all_usage(self) -> list[tuple[int, str, int, int]]:
        rows = self._conn.execute(
            "SELECT u.user_id, usr.username, usr.first_name, u.input_tokens, u.output_tokens "
            "FROM usage u LEFT JOIN users usr ON usr.user_id = u.user_id "
            "ORDER BY u.user_id"
        ).fetchall()
        out: list[tuple[int, str, int, int]] = []
        for user_id, username, first_name, inp, output in rows:
            if username:
                label = f"@{username} ({user_id})"
            elif first_name:
                label = f"{first_name} ({user_id})"
            else:
                label = f"({user_id})"
            out.append((user_id, label, inp, output))
        return out

    def add_system_usage(self, input_tokens: int, output_tokens: int) -> None:
        self._conn.execute(
            "UPDATE system_usage SET "
            "input_tokens = input_tokens + ?, "
            "output_tokens = output_tokens + ? "
            "WHERE id = 1",
            (input_tokens, output_tokens),
        )
        self._conn.commit()

    def get_system_usage(self) -> tuple[int, int]:
        row = self._conn.execute(
            "SELECT input_tokens, output_tokens FROM system_usage WHERE id = 1"
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def mark_seen(self, channel_id: int, message_id: int) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO seen (channel_id, message_id) VALUES (?, ?)",
            (channel_id, message_id),
        )
        self._conn.commit()
        return cursor.rowcount == 1
