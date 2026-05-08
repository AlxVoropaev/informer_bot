import json
import logging
import os
import sqlite3
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from informer_bot.modes import SubscriptionMode

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Channel:
    id: int
    title: str
    blacklisted: bool
    username: str | None = None
    about: str | None = None


@dataclass(frozen=True)
class Provider:
    user_id: int
    status: str
    session_path: str
    requested_at: int
    approved_at: int | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    username    TEXT,
    about       TEXT
);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id       INTEGER NOT NULL,
    channel_id    INTEGER NOT NULL,
    mode          TEXT NOT NULL DEFAULT 'filtered' CHECK(mode IN ('off','filtered','debug','all')),
    filter_prompt TEXT,
    PRIMARY KEY (user_id, channel_id),
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);
CREATE TABLE IF NOT EXISTS seen (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (channel_id, message_id)
);
CREATE TABLE IF NOT EXISTS users (
    user_id           INTEGER PRIMARY KEY,
    status            TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
    username          TEXT,
    first_name        TEXT,
    language          TEXT NOT NULL DEFAULT 'en' CHECK(language IN ('en','ru')),
    auto_delete_hours INTEGER,
    dedup_debug       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS usage (
    user_id       INTEGER NOT NULL,
    provider      TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, provider)
);
CREATE TABLE IF NOT EXISTS system_usage (
    provider      TEXT PRIMARY KEY,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS post_embeddings (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    embedding  BLOB NOT NULL,
    summary    TEXT NOT NULL,
    link       TEXT NOT NULL,
    PRIMARY KEY (channel_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_post_embeddings_created_at ON post_embeddings(created_at);
CREATE TABLE IF NOT EXISTS delivered (
    user_id        INTEGER NOT NULL,
    channel_id     INTEGER NOT NULL,
    message_id     INTEGER NOT NULL,
    bot_message_id INTEGER NOT NULL,
    is_photo       INTEGER NOT NULL,
    body           TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    dup_links_json TEXT NOT NULL DEFAULT '[]',
    saved          INTEGER NOT NULL DEFAULT 0,
    delete_at      INTEGER,
    PRIMARY KEY (user_id, channel_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_delivered_user_created ON delivered(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_delivered_user_botmsg ON delivered(user_id, bot_message_id);
CREATE TABLE IF NOT EXISTS embedding_usage (
    provider TEXT PRIMARY KEY,
    tokens   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS providers (
    user_id      INTEGER PRIMARY KEY,
    status       TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
    session_path TEXT NOT NULL,
    requested_at INTEGER NOT NULL,
    approved_at  INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE TABLE IF NOT EXISTS channel_blacklist (
    provider_user_id INTEGER NOT NULL,
    channel_id       INTEGER NOT NULL,
    PRIMARY KEY (provider_user_id, channel_id),
    FOREIGN KEY (provider_user_id) REFERENCES providers(user_id) ON DELETE CASCADE,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS provider_channels (
    provider_user_id INTEGER NOT NULL,
    channel_id       INTEGER NOT NULL,
    PRIMARY KEY (provider_user_id, channel_id),
    FOREIGN KEY (provider_user_id) REFERENCES providers(user_id) ON DELETE CASCADE,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
);
"""


# Ordered list of schema migrations. Each entry is SQL that bumps the schema
# from version N (its index) to N+1. New migrations append to the end; never
# rewrite an existing one. _SCHEMA above always produces the latest schema, so
# fresh DBs skip the migration loop entirely (their schema_version is set to
# len(_MIGRATIONS) on first open).
_MIGRATIONS: list[str] = [
    # 0 -> 1: users.first_name
    "ALTER TABLE users ADD COLUMN first_name TEXT",
    # 1 -> 2: users.language
    "ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en'",
    # 2 -> 3: subscriptions: add mode + filter_prompt + debug check (table rebuild)
    """
    CREATE TABLE subscriptions_new (
        user_id       INTEGER NOT NULL,
        channel_id    INTEGER NOT NULL,
        mode          TEXT NOT NULL DEFAULT 'filtered' CHECK(mode IN ('off','filtered','debug','all')),
        filter_prompt TEXT,
        PRIMARY KEY (user_id, channel_id),
        FOREIGN KEY (channel_id) REFERENCES channels(id)
    );
    INSERT INTO subscriptions_new (user_id, channel_id, mode, filter_prompt)
        SELECT user_id, channel_id,
               COALESCE(mode, 'filtered'),
               NULL
        FROM subscriptions;
    DROP TABLE subscriptions;
    ALTER TABLE subscriptions_new RENAME TO subscriptions;
    """,
    # 3 -> 4: delivered.dup_links_json
    "ALTER TABLE delivered ADD COLUMN dup_links_json TEXT NOT NULL DEFAULT '[]'",
    # 4 -> 5: channels.username
    "ALTER TABLE channels ADD COLUMN username TEXT",
    # 5 -> 6: channels.about
    "ALTER TABLE channels ADD COLUMN about TEXT",
    # 6 -> 7: users.auto_delete_hours
    "ALTER TABLE users ADD COLUMN auto_delete_hours INTEGER",
    # 7 -> 8: delivered.saved
    "ALTER TABLE delivered ADD COLUMN saved INTEGER NOT NULL DEFAULT 0",
    # 8 -> 9: delivered.delete_at + bot_message_id lookup index
    """
    ALTER TABLE delivered ADD COLUMN delete_at INTEGER;
    CREATE INDEX IF NOT EXISTS idx_delivered_user_botmsg
        ON delivered(user_id, bot_message_id);
    """,
    # 9 -> 10: users.dedup_debug
    "ALTER TABLE users ADD COLUMN dedup_debug INTEGER NOT NULL DEFAULT 0",
    # 10 -> 11: per-provider usage tables (rebuild usage / system_usage /
    # embedding_usage with a `provider` column, preserving old totals under
    # provider='unknown').
    """
    CREATE TABLE usage_new (
        user_id       INTEGER NOT NULL,
        provider      TEXT NOT NULL,
        input_tokens  INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, provider)
    );
    INSERT INTO usage_new (user_id, provider, input_tokens, output_tokens)
        SELECT user_id, 'unknown', input_tokens, output_tokens FROM usage;
    DROP TABLE usage;
    ALTER TABLE usage_new RENAME TO usage;

    CREATE TABLE system_usage_new (
        provider      TEXT PRIMARY KEY,
        input_tokens  INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO system_usage_new (provider, input_tokens, output_tokens)
        SELECT 'unknown', input_tokens, output_tokens FROM system_usage WHERE id = 1;
    DROP TABLE system_usage;
    ALTER TABLE system_usage_new RENAME TO system_usage;

    CREATE TABLE embedding_usage_new (
        provider TEXT PRIMARY KEY,
        tokens   INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO embedding_usage_new (provider, tokens)
        SELECT 'unknown', tokens FROM embedding_usage WHERE id = 1;
    DROP TABLE embedding_usage;
    ALTER TABLE embedding_usage_new RENAME TO embedding_usage;
    """,
    # 11 -> 12: multi-provider — providers table, per-provider blacklist,
    # drop channels.blacklisted (legacy global blacklist becomes the
    # owner's personal blacklist). Owner is read from OWNER_ID env.
    # The sentinel value is replaced at runtime with the actual SQL by
    # _migrate(); this migration needs runtime values (env, epoch) so it
    # cannot be a static string.
    "__PROGRAMMATIC_MULTI_PROVIDER__",
    # 12 -> 13: provider_channels — explicit provider→channel mapping. The
    # `_SCHEMA` block above creates the table via IF NOT EXISTS, so this
    # migration only needs to seed it: every existing `channels` row was
    # owner-contributed under the old single-provider model.
    "__PROGRAMMATIC_PROVIDER_CHANNELS_SEED__",
]


def pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def format_user_label(
    user_id: int, username: str | None, first_name: str | None
) -> str:
    if username:
        return f"@{username} ({user_id})"
    if first_name:
        return f"{first_name} ({user_id})"
    return f"({user_id})"


class Database:
    def __init__(self, path: Path | str) -> None:
        # RLock so transaction() can hold the lock while mutating methods
        # re-acquire it on the same thread.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._in_transaction = False
        self._owner_id_cached: int | None = None
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        log.debug("opened sqlite at %s", path)

    def _commit(self) -> None:
        # Defer to transaction() when one is active so multi-step
        # business operations stay atomic.
        if not self._in_transaction:
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run multiple mutating methods atomically.

        Nested calls are flat (the inner `with` reuses the outer transaction).
        On exception the whole block is rolled back.
        """
        with self._lock:
            if self._in_transaction:
                yield
                return
            self._in_transaction = True
            try:
                yield
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            finally:
                self._in_transaction = False

    def _bootstrap_schema_version(self) -> int:
        """Detect how far the schema has already been migrated for legacy DBs
        that pre-date the schema_version pin. Returns the index of the next
        pending migration."""
        users = {r[1] for r in self._conn.execute("PRAGMA table_info(users)")}
        subs = {r[1] for r in self._conn.execute("PRAGMA table_info(subscriptions)")}
        delivered = {r[1] for r in self._conn.execute("PRAGMA table_info(delivered)")}
        channels = {r[1] for r in self._conn.execute("PRAGMA table_info(channels)")}
        sub_sql_row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='subscriptions'"
        ).fetchone()
        sub_has_debug = bool(sub_sql_row and "'debug'" in sub_sql_row[0])

        if "first_name" not in users:
            return 0
        if "language" not in users:
            return 1
        if (
            "mode" not in subs
            or "filter_prompt" not in subs
            or not sub_has_debug
        ):
            return 2
        # delivered may not exist yet on very old DBs, but _SCHEMA just created
        # it with dup_links_json, so this check is only meaningful on legacy DBs
        # that already had `delivered` from an older _SCHEMA without that column.
        if delivered and "dup_links_json" not in delivered:
            return 3
        if "username" not in channels:
            return 4
        if "about" not in channels:
            return 5
        if "auto_delete_hours" not in users:
            return 6
        if delivered and "saved" not in delivered:
            return 7
        if delivered and "delete_at" not in delivered:
            return 8
        if "dedup_debug" not in users:
            return 9
        # Versions 10/11 still have `channels.blacklisted`; fresh DBs created
        # via `_SCHEMA` (post-12) do not. If the column is still present we
        # have not yet applied the multi-provider migration. (`providers` and
        # `channel_blacklist` always exist here because `_SCHEMA` ran first
        # via `IF NOT EXISTS`, so they're not a useful probe.)
        if "blacklisted" in channels:
            return len(_MIGRATIONS) - 2
        # Version 12 had the multi-provider tables but no `provider_channels`.
        # Probe legacy DBs by checking whether `provider_channels` had any
        # rows seeded for the owner — fresh DBs won't get here because
        # `meta.schema_version` is set explicitly.
        pc_seeded = self._conn.execute(
            "SELECT 1 FROM provider_channels LIMIT 1"
        ).fetchone()
        owner_row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'owner_id'"
        ).fetchone()
        chan_row = self._conn.execute(
            "SELECT 1 FROM channels LIMIT 1"
        ).fetchone()
        # If we have channels and an owner but provider_channels is empty,
        # the seed migration hasn't run.
        if owner_row is not None and chan_row is not None and pc_seeded is None:
            return len(_MIGRATIONS) - 1
        return len(_MIGRATIONS)

    def _migrate(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        version = int(row[0]) if row else self._bootstrap_schema_version()
        for i in range(version, len(_MIGRATIONS)):
            log.info("applying schema migration %d -> %d", i, i + 1)
            sql = _MIGRATIONS[i]
            if sql == "__PROGRAMMATIC_MULTI_PROVIDER__":
                self._migrate_multi_provider()
            elif sql == "__PROGRAMMATIC_PROVIDER_CHANNELS_SEED__":
                self._migrate_provider_channels_seed()
            else:
                self._conn.executescript(sql)
        if version < len(_MIGRATIONS) or row is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(len(_MIGRATIONS)),),
            )

    def _migrate_multi_provider(self) -> None:
        """Migration 11 -> 12.

        Seeds the OWNER_ID env user as the first approved provider, copies
        legacy `channels.blacklisted` rows into the owner's blacklist, and
        drops the `channels.blacklisted` column via table-rebuild.

        The `providers` and `channel_blacklist` tables themselves are created
        by `_SCHEMA` (with IF NOT EXISTS) which runs before `_migrate()` —
        so this routine only needs to populate them.
        """
        owner_raw = os.environ.get("OWNER_ID")
        if not owner_raw:
            raise RuntimeError(
                "OWNER_ID env var required to migrate to multi-provider schema"
            )
        owner_id = int(owner_raw)
        now = int(time.time())

        c = self._conn
        # Owner's users row may not exist on legacy DBs; seed it.
        c.execute(
            "INSERT OR IGNORE INTO users (user_id, status) VALUES (?, 'approved')",
            (owner_id,),
        )
        c.execute(
            "INSERT INTO providers "
            "(user_id, status, session_path, requested_at, approved_at) "
            "VALUES (?, 'approved', 'data/informer.session', ?, ?)",
            (owner_id, now, now),
        )
        # Copy legacy global blacklist into owner's per-provider blacklist.
        c.execute(
            "INSERT INTO channel_blacklist (provider_user_id, channel_id) "
            "SELECT ?, id FROM channels WHERE blacklisted = 1",
            (owner_id,),
        )
        # Rebuild `channels` without the `blacklisted` column.
        # SQLite recommends turning FK off during a column-removing rebuild
        # because subscriptions(channel_id) FKs reference channels(id). We
        # execute a fresh PRAGMA pair around the rebuild; PRAGMA foreign_keys
        # is allowed inside executescript() because executescript COMMITs any
        # pending transaction first.
        self._conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE channels_new (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                username TEXT,
                about TEXT
            );
            INSERT INTO channels_new (id, title, username, about)
                SELECT id, title, username, about FROM channels;
            DROP TABLE channels;
            ALTER TABLE channels_new RENAME TO channels;
            PRAGMA foreign_keys = ON;
            """
        )
        bad = self._conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(
                f"foreign_key_check failed during multi-provider migration: {bad!r}"
            )
        c.execute(
            "INSERT INTO meta (key, value) VALUES ('owner_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(owner_id),),
        )
        self._owner_id_cached = owner_id

    def _migrate_provider_channels_seed(self) -> None:
        """Migration 12 -> 13.

        Seed `provider_channels` with `(owner_id, channel_id)` for every
        existing channel — under the legacy single-provider model the owner
        was the source of every channel in `channels`. The table itself is
        created by `_SCHEMA` (with IF NOT EXISTS).
        """
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'owner_id'"
        ).fetchone()
        if row is None:
            # No owner means there's nothing to seed (e.g. fresh DB before
            # the multi-provider migration ran). Skip silently.
            return
        owner_id = int(row[0])
        self._conn.execute(
            "INSERT OR IGNORE INTO provider_channels (provider_user_id, channel_id) "
            "SELECT ?, id FROM channels",
            (owner_id,),
        )

    def _owner_id(self) -> int | None:
        """Return the legacy 'owner' provider id from `meta.owner_id` or None.

        Used by the legacy single-blacklist shims. Cached on first access;
        a new migration that writes `meta.owner_id` invalidates the cache
        directly.
        """
        if self._owner_id_cached is not None:
            return self._owner_id_cached
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'owner_id'"
        ).fetchone()
        if row is None:
            return None
        self._owner_id_cached = int(row[0])
        return self._owner_id_cached

    def upsert_channel(
        self,
        channel_id: int,
        title: str,
        username: str | None = None,
        about: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO channels (id, title, username, about) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title = excluded.title, "
                "username = COALESCE(excluded.username, channels.username), "
                "about = COALESCE(excluded.about, channels.about)",
                (channel_id, title, username, about),
            )
            self._commit()
        log.debug(
            "upsert_channel id=%s title=%r username=%r about_chars=%s",
            channel_id, title, username, len(about) if about else 0,
        )

    def set_blacklisted(self, channel_id: int, blacklisted: bool) -> None:
        """Legacy single-blacklist shim — routes through the owner provider's
        per-provider blacklist. Subagent C will replace callers with
        `set_provider_channel_blacklisted` directly."""
        owner_id = self._owner_id()
        if owner_id is None:
            raise RuntimeError(
                "owner_id not set; cannot use legacy set_blacklisted shim"
            )
        self.set_provider_channel_blacklisted(
            provider_user_id=owner_id, channel_id=channel_id, blacklisted=blacklisted,
        )
        log.debug("set_blacklisted id=%s blacklisted=%s", channel_id, blacklisted)

    def get_channel_title(self, channel_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT title FROM channels WHERE id = ?", (channel_id,)
            ).fetchone()
        return row[0] if row else None

    def get_channel(self, channel_id: int) -> Channel | None:
        owner_id = self._owner_id()
        with self._lock:
            row = self._conn.execute(
                "SELECT c.id, c.title, c.username, c.about, "
                "       EXISTS (SELECT 1 FROM channel_blacklist b "
                "               WHERE b.provider_user_id = ? AND b.channel_id = c.id) "
                "FROM channels c WHERE c.id = ?",
                (owner_id if owner_id is not None else -1, channel_id),
            ).fetchone()
        if row is None:
            return None
        return Channel(
            id=row[0], title=row[1], username=row[2], about=row[3],
            blacklisted=bool(row[4]),
        )

    def list_channels(self, include_blacklisted: bool = False) -> list[Channel]:
        owner_id = self._owner_id()
        owner_param = owner_id if owner_id is not None else -1
        sql = (
            "SELECT c.id, c.title, c.username, c.about, "
            "       EXISTS (SELECT 1 FROM channel_blacklist b "
            "               WHERE b.provider_user_id = ? AND b.channel_id = c.id) "
            "FROM channels c"
        )
        params: list[object] = [owner_param]
        if not include_blacklisted:
            sql += (
                " WHERE NOT EXISTS (SELECT 1 FROM channel_blacklist b2 "
                "                   WHERE b2.provider_user_id = ? "
                "                     AND b2.channel_id = c.id)"
            )
            params.append(owner_param)
        sql += " ORDER BY c.title"
        with self._lock:
            return [
                Channel(
                    id=r[0], title=r[1], username=r[2], about=r[3],
                    blacklisted=bool(r[4]),
                )
                for r in self._conn.execute(sql, params)
            ]

    def subscribe(
        self,
        user_id: int,
        channel_id: int,
        mode: SubscriptionMode | str = SubscriptionMode.FILTERED,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO subscriptions (user_id, channel_id, mode) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, channel_id) DO UPDATE SET mode = excluded.mode",
                (user_id, channel_id, mode),
            )
            self._commit()

    def unsubscribe(self, user_id: int, channel_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM subscriptions WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            )
            self._commit()

    def is_subscribed(self, user_id: int, channel_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM subscriptions WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            ).fetchone()
        return row is not None

    def get_subscription_mode(self, user_id: int, channel_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT mode FROM subscriptions WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            ).fetchone()
        return row[0] if row else None

    def list_user_subscription_modes(self, user_id: int) -> dict[int, str]:
        with self._lock:
            return {
                r[0]: r[1]
                for r in self._conn.execute(
                    "SELECT channel_id, mode FROM subscriptions WHERE user_id = ?",
                    (user_id,),
                )
            }

    def subscribers_for_channel(self, channel_id: int) -> list[tuple[int, str]]:
        owner_id = self._owner_id()
        owner_param = owner_id if owner_id is not None else -1
        with self._lock:
            return [
                (r[0], r[1])
                for r in self._conn.execute(
                    "SELECT s.user_id, s.mode FROM subscriptions s "
                    "JOIN channels c ON c.id = s.channel_id "
                    "WHERE s.channel_id = ? AND s.mode != 'off' "
                    "  AND NOT EXISTS (SELECT 1 FROM channel_blacklist b "
                    "                  WHERE b.provider_user_id = ? "
                    "                    AND b.channel_id = c.id)",
                    (channel_id, owner_param),
                )
            ]

    def delete_channel(self, channel_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM subscriptions WHERE channel_id = ?", (channel_id,))
            self._conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            self._commit()
        log.debug("delete_channel id=%s", channel_id)

    def get_user_status(self, user_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row[0] if row else None

    def add_pending_user(
        self, user_id: int, username: str | None, first_name: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (user_id, status, username, first_name) "
                "VALUES (?, 'pending', ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "username = excluded.username, "
                "first_name = COALESCE(excluded.first_name, users.first_name)",
                (user_id, username, first_name),
            )
            self._commit()
        log.debug(
            "add_pending_user user=%s username=%r first_name=%r",
            user_id, username, first_name,
        )

    def set_user_status(self, user_id: int, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (user_id, status) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET status = excluded.status",
                (user_id, status),
            )
            self._commit()
        log.debug("set_user_status user=%s status=%s", user_id, status)

    def list_user_ids(self) -> list[int]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT user_id FROM users ORDER BY user_id")]

    def list_approved_user_ids(self) -> list[int]:
        with self._lock:
            return [
                r[0]
                for r in self._conn.execute(
                    "SELECT user_id FROM users WHERE status = 'approved' ORDER BY user_id"
                )
            ]

    def update_user_name(
        self, user_id: int, username: str | None, first_name: str | None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (username, first_name, user_id),
            )
            self._commit()
        log.debug(
            "update_user_name user=%s username=%r first_name=%r",
            user_id, username, first_name,
        )

    def get_user_label(self, user_id: int) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT username, first_name FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        username = row[0] if row else None
        first_name = row[1] if row else None
        return format_user_label(user_id, username, first_name)

    def get_channel_filter(self, user_id: int, channel_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT filter_prompt FROM subscriptions WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            ).fetchone()
        return row[0] if row and row[0] else None

    def set_channel_filter(
        self, user_id: int, channel_id: int, filter_prompt: str | None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO subscriptions (user_id, channel_id, mode, filter_prompt) "
                "VALUES (?, ?, 'off', ?) "
                "ON CONFLICT(user_id, channel_id) DO UPDATE SET filter_prompt = excluded.filter_prompt",
                (user_id, channel_id, filter_prompt),
            )
            self._commit()
        log.debug(
            "set_channel_filter user=%s channel=%s len=%s",
            user_id, channel_id, len(filter_prompt) if filter_prompt else 0,
        )

    def list_user_subscription_filters(self, user_id: int) -> dict[int, str | None]:
        with self._lock:
            return {
                r[0]: r[1]
                for r in self._conn.execute(
                    "SELECT channel_id, filter_prompt FROM subscriptions WHERE user_id = ?",
                    (user_id,),
                )
            }

    def get_language(self, user_id: int) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT language FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row[0] if row and row[0] else "en"

    def get_user_auto_delete_hours(self, user_id: int) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT auto_delete_hours FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row[0] if row else None

    def set_user_auto_delete_hours(
        self, user_id: int, hours: int | None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (user_id, status, auto_delete_hours) "
                "VALUES (?, 'pending', ?) "
                "ON CONFLICT(user_id) DO UPDATE SET auto_delete_hours = excluded.auto_delete_hours",
                (user_id, hours),
            )
            self._commit()
        log.debug("set_user_auto_delete_hours user=%s hours=%s", user_id, hours)

    def get_dedup_debug(self, user_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT dedup_debug FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return bool(row[0]) if row else False

    def set_dedup_debug(self, user_id: int, enabled: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (user_id, status, dedup_debug) "
                "VALUES (?, 'pending', ?) "
                "ON CONFLICT(user_id) DO UPDATE SET dedup_debug = excluded.dedup_debug",
                (user_id, 1 if enabled else 0),
            )
            self._commit()
        log.debug("set_dedup_debug user=%s enabled=%s", user_id, enabled)

    def set_language(self, user_id: int, language: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (user_id, status, language) VALUES (?, 'pending', ?) "
                "ON CONFLICT(user_id) DO UPDATE SET language = excluded.language",
                (user_id, language),
            )
            self._commit()
        log.debug("set_language user=%s language=%s", user_id, language)

    def add_usage(
        self,
        user_id: int,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage (user_id, provider, input_tokens, output_tokens) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, provider) DO UPDATE SET "
                "input_tokens = usage.input_tokens + excluded.input_tokens, "
                "output_tokens = usage.output_tokens + excluded.output_tokens",
                (user_id, provider, input_tokens, output_tokens),
            )
            self._commit()

    def get_usage(self, user_id: int) -> list[tuple[str, int, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT provider, input_tokens, output_tokens FROM usage "
                "WHERE user_id = ? ORDER BY provider",
                (user_id,),
            ).fetchall()
        return [(p, i, o) for p, i, o in rows]

    def list_all_usage(
        self,
    ) -> list[tuple[int, str | None, str | None, str, int, int]]:
        """Return raw `(user_id, username, first_name, provider, input_tokens,
        output_tokens)` rows ordered by user_id then provider. Use
        `format_user_label` to render a display label."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT u.user_id, usr.username, usr.first_name, u.provider, "
                "       u.input_tokens, u.output_tokens "
                "FROM usage u LEFT JOIN users usr ON usr.user_id = u.user_id "
                "ORDER BY u.user_id, u.provider"
            ).fetchall()
        return [
            (user_id, username, first_name, provider, inp, output)
            for user_id, username, first_name, provider, inp, output in rows
        ]

    def add_system_usage(
        self, provider: str, input_tokens: int, output_tokens: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO system_usage (provider, input_tokens, output_tokens) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(provider) DO UPDATE SET "
                "input_tokens = system_usage.input_tokens + excluded.input_tokens, "
                "output_tokens = system_usage.output_tokens + excluded.output_tokens",
                (provider, input_tokens, output_tokens),
            )
            self._commit()

    def get_system_usage(self) -> list[tuple[str, int, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT provider, input_tokens, output_tokens FROM system_usage "
                "ORDER BY provider"
            ).fetchall()
        return [(p, i, o) for p, i, o in rows]

    def mark_seen(self, channel_id: int, message_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO seen (channel_id, message_id) VALUES (?, ?)",
                (channel_id, message_id),
            )
            self._commit()
            return cursor.rowcount == 1

    def max_seen_message_id(self, channel_id: int) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(message_id) FROM seen WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    def channels_with_active_subscribers(self) -> list[int]:
        owner_id = self._owner_id()
        owner_param = owner_id if owner_id is not None else -1
        with self._lock:
            return [
                r[0]
                for r in self._conn.execute(
                    "SELECT DISTINCT s.channel_id FROM subscriptions s "
                    "JOIN channels c ON c.id = s.channel_id "
                    "WHERE s.mode != 'off' "
                    "  AND NOT EXISTS (SELECT 1 FROM channel_blacklist b "
                    "                  WHERE b.provider_user_id = ? "
                    "                    AND b.channel_id = c.id)",
                    (owner_param,),
                )
            ]

    # ---------- dedup ----------

    def store_post_embedding(
        self,
        *,
        channel_id: int,
        message_id: int,
        embedding: list[float],
        summary: str,
        link: str,
        now: int | None = None,
    ) -> None:
        ts = int(time.time()) if now is None else now
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO post_embeddings "
                "(channel_id, message_id, created_at, embedding, summary, link) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (channel_id, message_id, ts, pack_vector(embedding), summary, link),
            )
            self._commit()

    def record_delivered(
        self,
        *,
        user_id: int,
        channel_id: int,
        message_id: int,
        bot_message_id: int,
        is_photo: bool,
        body: str,
        now: int | None = None,
        delete_at: int | None = None,
    ) -> None:
        ts = int(time.time()) if now is None else now
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO delivered "
                "(user_id, channel_id, message_id, bot_message_id, is_photo, body, "
                " created_at, delete_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, channel_id, message_id, bot_message_id,
                 1 if is_photo else 0, body, ts, delete_at),
            )
            self._commit()

    def get_delivered_save_state(
        self, *, user_id: int, channel_id: int, message_id: int
    ) -> tuple[bool, int | None] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT saved, delete_at FROM delivered "
                "WHERE user_id = ? AND channel_id = ? AND message_id = ?",
                (user_id, channel_id, message_id),
            ).fetchone()
        if row is None:
            return None
        return (bool(row[0]), row[1])

    def set_delivered_saved(
        self,
        *,
        user_id: int,
        channel_id: int,
        message_id: int,
        saved: bool,
        delete_at: int | None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE delivered SET saved = ?, delete_at = ? "
                "WHERE user_id = ? AND channel_id = ? AND message_id = ?",
                (1 if saved else 0, delete_at, user_id, channel_id, message_id),
            )
            self._commit()

    def extend_delivered_delete_at(
        self,
        *,
        user_id: int,
        channel_id: int,
        message_id: int,
        delete_at: int,
    ) -> None:
        """Bump delete_at — only when the row is unsaved.

        Saved rows must keep their NULL delete_at so the user's "save" survives
        a follow-up duplicate.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE delivered SET delete_at = ? "
                "WHERE user_id = ? AND channel_id = ? AND message_id = ? "
                "  AND saved = 0",
                (delete_at, user_id, channel_id, message_id),
            )
            self._commit()

    def get_delivered_by_bot_msg(
        self, *, user_id: int, bot_message_id: int
    ) -> tuple[int, int, bool, bool, int | None] | None:
        """Return (channel_id, message_id, is_photo, saved, delete_at) or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT channel_id, message_id, is_photo, saved, delete_at "
                "FROM delivered WHERE user_id = ? AND bot_message_id = ?",
                (user_id, bot_message_id),
            ).fetchone()
        if row is None:
            return None
        return (row[0], row[1], bool(row[2]), bool(row[3]), row[4])

    def list_due_deletions(
        self, *, now: int
    ) -> list[tuple[int, int, int, int, bool]]:
        """Return (user_id, channel_id, message_id, bot_message_id, is_photo)
        for unsaved rows whose delete_at has passed."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, channel_id, message_id, bot_message_id, is_photo "
                "FROM delivered "
                "WHERE saved = 0 AND delete_at IS NOT NULL AND delete_at <= ?",
                (now,),
            ).fetchall()
        return [(uid, cid, mid, bmid, bool(is_p)) for uid, cid, mid, bmid, is_p in rows]

    def delete_delivered_row(
        self, *, user_id: int, channel_id: int, message_id: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM delivered "
                "WHERE user_id = ? AND channel_id = ? AND message_id = ?",
                (user_id, channel_id, message_id),
            )
            self._commit()

    def get_delivered_dup_links(
        self, *, user_id: int, channel_id: int, message_id: int
    ) -> list[tuple[str, str]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT dup_links_json FROM delivered "
                "WHERE user_id = ? AND channel_id = ? AND message_id = ?",
                (user_id, channel_id, message_id),
            ).fetchone()
        if not row or not row[0]:
            return []
        return [tuple(item) for item in json.loads(row[0])]

    def set_delivered_dup_links(
        self,
        *,
        user_id: int,
        channel_id: int,
        message_id: int,
        dup_links: list[tuple[str, str]],
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE delivered SET dup_links_json = ? "
                "WHERE user_id = ? AND channel_id = ? AND message_id = ?",
                (json.dumps(dup_links), user_id, channel_id, message_id),
            )
            self._commit()

    def list_dedup_candidates(
        self, *, user_id: int, since: int
    ) -> list[tuple[int, int, int, bool, list[tuple[str, str]], list[float], str]]:
        """Return (channel_id, message_id, bot_message_id, is_photo, dup_links, vec, link)
        for delivered+embedded posts for this user newer than `since`."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT d.channel_id, d.message_id, d.bot_message_id, d.is_photo, "
                "       d.dup_links_json, p.embedding, p.link "
                "FROM delivered d "
                "JOIN post_embeddings p "
                "  ON p.channel_id = d.channel_id AND p.message_id = d.message_id "
                "WHERE d.user_id = ? AND d.created_at >= ?",
                (user_id, since),
            ).fetchall()
        return [
            (
                cid, mid, bmid, bool(is_p),
                [tuple(item) for item in json.loads(dup_json or "[]")],
                unpack_vector(blob), link,
            )
            for cid, mid, bmid, is_p, dup_json, blob, link in rows
        ]

    def purge_dedup_older_than(self, *, cutoff: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM delivered WHERE created_at < ?", (cutoff,))
            self._conn.execute("DELETE FROM post_embeddings WHERE created_at < ?", (cutoff,))
            self._commit()

    def purge_dedup_all(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM delivered")
            self._conn.execute("DELETE FROM post_embeddings")
            self._commit()
        log.info("purged all delivered + post_embeddings rows")

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._commit()
        if key == "owner_id":
            self._owner_id_cached = int(value)

    def add_embedding_usage(self, provider: str, tokens: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO embedding_usage (provider, tokens) VALUES (?, ?) "
                "ON CONFLICT(provider) DO UPDATE SET "
                "tokens = embedding_usage.tokens + excluded.tokens",
                (provider, tokens),
            )
            self._commit()

    def get_embedding_usage(self) -> list[tuple[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT provider, tokens FROM embedding_usage ORDER BY provider"
            ).fetchall()
        return [(p, t) for p, t in rows]

    # ---------- providers ----------

    def add_pending_provider(
        self, user_id: int, session_path: str, now: int | None = None,
    ) -> None:
        ts = int(time.time()) if now is None else now
        with self._lock:
            self._conn.execute(
                "INSERT INTO providers "
                "(user_id, status, session_path, requested_at, approved_at) "
                "VALUES (?, 'pending', ?, ?, NULL) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "status = 'pending', "
                "session_path = excluded.session_path, "
                "requested_at = excluded.requested_at, "
                "approved_at = NULL",
                (user_id, session_path, ts),
            )
            self._commit()
        log.debug(
            "add_pending_provider user=%s session_path=%r", user_id, session_path,
        )

    def set_provider_status(
        self, user_id: int, status: str, now: int | None = None,
    ) -> None:
        if status not in ("pending", "approved", "denied"):
            raise ValueError(f"invalid provider status: {status!r}")
        ts = int(time.time()) if now is None else now
        with self._lock:
            if status == "approved":
                self._conn.execute(
                    "UPDATE providers SET status = ?, approved_at = ? "
                    "WHERE user_id = ?",
                    (status, ts, user_id),
                )
            else:
                # Leave approved_at intact when denying so the historical
                # approval record survives.
                self._conn.execute(
                    "UPDATE providers SET status = ? WHERE user_id = ?",
                    (status, user_id),
                )
            self._commit()
        log.debug("set_provider_status user=%s status=%s", user_id, status)

    def get_provider(self, user_id: int) -> Provider | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, status, session_path, requested_at, approved_at "
                "FROM providers WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return Provider(
            user_id=row[0], status=row[1], session_path=row[2],
            requested_at=row[3], approved_at=row[4],
        )

    def list_providers(self, status: str | None = None) -> list[Provider]:
        with self._lock:
            if status is None:
                rows = self._conn.execute(
                    "SELECT user_id, status, session_path, requested_at, approved_at "
                    "FROM providers ORDER BY user_id"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT user_id, status, session_path, requested_at, approved_at "
                    "FROM providers WHERE status = ? ORDER BY user_id",
                    (status,),
                ).fetchall()
        return [
            Provider(
                user_id=r[0], status=r[1], session_path=r[2],
                requested_at=r[3], approved_at=r[4],
            )
            for r in rows
        ]

    def list_approved_provider_ids(self) -> list[int]:
        with self._lock:
            return [
                r[0]
                for r in self._conn.execute(
                    "SELECT user_id FROM providers WHERE status = 'approved' "
                    "ORDER BY user_id"
                )
            ]

    def delete_provider(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM providers WHERE user_id = ?", (user_id,)
            )
            self._commit()
        log.debug("delete_provider user=%s", user_id)

    # ---------- per-provider blacklist ----------

    def is_blacklisted(self, provider_user_id: int, channel_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM channel_blacklist "
                "WHERE provider_user_id = ? AND channel_id = ?",
                (provider_user_id, channel_id),
            ).fetchone()
        return row is not None

    def set_provider_channel_blacklisted(
        self, provider_user_id: int, channel_id: int, blacklisted: bool,
    ) -> None:
        with self._lock:
            if blacklisted:
                self._conn.execute(
                    "INSERT OR IGNORE INTO channel_blacklist "
                    "(provider_user_id, channel_id) VALUES (?, ?)",
                    (provider_user_id, channel_id),
                )
            else:
                self._conn.execute(
                    "DELETE FROM channel_blacklist "
                    "WHERE provider_user_id = ? AND channel_id = ?",
                    (provider_user_id, channel_id),
                )
            self._commit()

    def list_provider_blacklist(self, provider_user_id: int) -> set[int]:
        with self._lock:
            return {
                r[0]
                for r in self._conn.execute(
                    "SELECT channel_id FROM channel_blacklist "
                    "WHERE provider_user_id = ?",
                    (provider_user_id,),
                )
            }

    def list_visible_channels(self) -> list[Channel]:
        """Return channels visible to bot users — i.e. channels that at least
        one approved provider subscribes to and has NOT blacklisted. Returns
        an empty list when no providers contribute the channel.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.id, c.title, c.username, c.about FROM channels c "
                "WHERE EXISTS ("
                "  SELECT 1 FROM provider_channels pc "
                "  JOIN providers p ON p.user_id = pc.provider_user_id "
                "  WHERE pc.channel_id = c.id "
                "    AND p.status = 'approved' "
                "    AND NOT EXISTS ("
                "      SELECT 1 FROM channel_blacklist b "
                "      WHERE b.provider_user_id = pc.provider_user_id "
                "        AND b.channel_id = c.id"
                "    )"
                ") "
                "ORDER BY c.title"
            ).fetchall()
        owner_id = self._owner_id()
        owner_param = owner_id if owner_id is not None else -1
        # `Channel.blacklisted` is the legacy owner-centric flag for back-compat
        # rendering; `list_visible_channels` is multi-provider, so a channel
        # may be visible (some other provider has it) yet still be blacklisted
        # by the owner.
        with self._lock:
            owner_bl = {
                r[0]
                for r in self._conn.execute(
                    "SELECT channel_id FROM channel_blacklist "
                    "WHERE provider_user_id = ?",
                    (owner_param,),
                )
            }
        return [
            Channel(
                id=r[0], title=r[1], username=r[2], about=r[3],
                blacklisted=r[0] in owner_bl,
            )
            for r in rows
        ]

    def is_visible_channel(self, channel_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM channels c WHERE c.id = ? AND EXISTS ("
                "  SELECT 1 FROM provider_channels pc "
                "  JOIN providers p ON p.user_id = pc.provider_user_id "
                "  WHERE pc.channel_id = c.id "
                "    AND p.status = 'approved' "
                "    AND NOT EXISTS ("
                "      SELECT 1 FROM channel_blacklist b "
                "      WHERE b.provider_user_id = pc.provider_user_id "
                "        AND b.channel_id = c.id"
                "    )"
                ")",
                (channel_id,),
            ).fetchone()
        return row is not None

    # ---------- provider_channels ----------

    def set_provider_channels(
        self, provider_user_id: int, channel_ids: set[int],
    ) -> None:
        """Replace this provider's channel set with `channel_ids` atomically."""
        with self._lock, self.transaction():
            self._conn.execute(
                "DELETE FROM provider_channels WHERE provider_user_id = ?",
                (provider_user_id,),
            )
            self._conn.executemany(
                "INSERT INTO provider_channels (provider_user_id, channel_id) "
                "VALUES (?, ?)",
                [(provider_user_id, cid) for cid in channel_ids],
            )

    def add_provider_channel(
        self, provider_user_id: int, channel_id: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO provider_channels "
                "(provider_user_id, channel_id) VALUES (?, ?)",
                (provider_user_id, channel_id),
            )
            self._commit()

    def remove_provider_channel(
        self, provider_user_id: int, channel_id: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM provider_channels "
                "WHERE provider_user_id = ? AND channel_id = ?",
                (provider_user_id, channel_id),
            )
            self._commit()

    def list_provider_channels(self, provider_user_id: int) -> set[int]:
        with self._lock:
            return {
                r[0]
                for r in self._conn.execute(
                    "SELECT channel_id FROM provider_channels "
                    "WHERE provider_user_id = ?",
                    (provider_user_id,),
                )
            }

    def channels_with_no_provider(self) -> list[int]:
        """Return channel ids in `channels` that have no row in
        `provider_channels`. Used to detect orphans after a refresh."""
        with self._lock:
            return [
                r[0]
                for r in self._conn.execute(
                    "SELECT c.id FROM channels c "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM provider_channels pc "
                    "  WHERE pc.channel_id = c.id"
                    ") "
                    "ORDER BY c.id"
                )
            ]
