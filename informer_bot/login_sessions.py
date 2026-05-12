"""In-memory state for in-progress Mini App provider logins.

Each entry holds the live Telethon `TelegramClient`, the phone number, the
phone_code_hash (returned by `send_code_request`), the next expected step,
and a `last_activity` monotonic timestamp. Entries idle longer than
``IDLE_TTL_SECONDS`` are evicted on access.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

IDLE_TTL_SECONDS = 600


@dataclass
class Entry:
    client: Any
    step: str = "phone"
    phone: str | None = None
    phone_code_hash: str | None = None
    last_activity: float = field(default_factory=time.monotonic)
    temp_session_path: str | None = None
    live_session_path: str | None = None


class LoginSessions:
    def __init__(self) -> None:
        self._entries: dict[int, Entry] = {}

    def _touch(self, entry: Entry) -> None:
        entry.last_activity = time.monotonic()

    def _expired(self, entry: Entry) -> bool:
        return (time.monotonic() - entry.last_activity) > IDLE_TTL_SECONDS

    def get(self, user_id: int) -> Entry | None:
        entry = self._entries.get(user_id)
        if entry is None:
            return None
        if self._expired(entry):
            self._entries.pop(user_id, None)
            try:
                coro = entry.client.disconnect()
                if asyncio.iscoroutine(coro):
                    asyncio.create_task(coro)
            except Exception:  # noqa: BLE001
                log.exception("login_sessions: disconnect on evict failed")
            return None
        return entry

    def start(self, user_id: int, client: Any) -> Entry:
        existing = self._entries.pop(user_id, None)
        if existing is not None:
            try:
                coro = existing.client.disconnect()
                if asyncio.iscoroutine(coro):
                    asyncio.create_task(coro)
            except Exception:  # noqa: BLE001
                log.exception("login_sessions: disconnect on replace failed")
        entry = Entry(client=client)
        self._entries[user_id] = entry
        return entry

    def set_phone(
        self, user_id: int, phone: str, phone_code_hash: str
    ) -> None:
        entry = self._entries[user_id]
        entry.phone = phone
        entry.phone_code_hash = phone_code_hash
        entry.step = "code"
        self._touch(entry)

    def require_password(self, user_id: int) -> None:
        entry = self._entries[user_id]
        entry.step = "password"
        self._touch(entry)

    def pop(self, user_id: int) -> Entry | None:
        return self._entries.pop(user_id, None)

    def active_user_ids(self) -> set[int]:
        return {
            uid for uid, entry in self._entries.items() if not self._expired(entry)
        }
