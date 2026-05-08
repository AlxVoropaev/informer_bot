"""Multi-session Telethon orchestrator.

One `TelegramClient` per approved provider whose `.session` file exists.
All clients share a single `AlbumBuffer` / pipeline callback. Source-side
dedup (multiple providers receiving the same channel post) is enforced by
a process-local in-flight claim set, layered on top of the persistent
`db.mark_seen` call inside `pipeline.handle_new_post`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient

from informer_bot.album import AlbumBuffer
from informer_bot.client import register_new_post_handler
from informer_bot.db import Database

log = logging.getLogger(__name__)


@dataclass
class ProviderClient:
    user_id: int
    tg: TelegramClient
    session_path: str


# Process-local set of (channel_id, message_id) pairs currently in flight.
# Used by `register_new_post_handler` (via the `claim` callback wired here)
# to drop duplicate posts arriving on a second provider's client before they
# enter the pipeline. The persistent `db.mark_seen` in `handle_new_post`
# still owns crash-safe restart-time dedup.
_InFlight = set[tuple[int, int]]


def make_source_dedup_claim(
    inflight: _InFlight,
) -> Callable[[int, int], bool]:
    """Return a `claim(channel_id, message_id) -> bool` checker.

    Returns True iff this caller is the first to claim the (channel, message)
    pair. False means another provider's client already claimed it.
    """

    def claim(channel_id: int, message_id: int) -> bool:
        key = (channel_id, message_id)
        if key in inflight:
            return False
        inflight.add(key)
        return True

    return claim


async def start_all(
    *,
    db: Database,
    api_id: int,
    api_hash: str,
    buffer: AlbumBuffer,
    inflight: _InFlight | None = None,
    client_factory: Callable[[str, int, str], TelegramClient] | None = None,
) -> list[ProviderClient]:
    """Start one Telethon client per approved provider with an existing session.

    Skips approved providers whose session file is missing (warns) — the
    provider hasn't run the CLI session-creation tool yet.
    """
    if inflight is None:
        inflight = set()
    factory = client_factory or (
        lambda path, aid, ah: TelegramClient(path, aid, ah)
    )
    claim = make_source_dedup_claim(inflight)
    started: list[ProviderClient] = []
    for provider in db.list_providers(status="approved"):
        if not os.path.exists(provider.session_path):
            log.warning(
                "provider user=%s session_path=%r missing on disk; skipping",
                provider.user_id, provider.session_path,
            )
            continue
        tg = factory(provider.session_path, api_id, api_hash)
        try:
            await tg.connect()
            if not await tg.is_user_authorized():
                log.warning(
                    "provider user=%s not authorized at session_path=%r; "
                    "skipping (provider must re-run the login CLI)",
                    provider.user_id, provider.session_path,
                )
                await tg.disconnect()
                continue
        except Exception:
            log.exception(
                "provider user=%s start failed (session_path=%r)",
                provider.user_id, provider.session_path,
            )
            continue
        register_new_post_handler(tg, buffer, claim=claim)
        started.append(ProviderClient(
            user_id=provider.user_id, tg=tg, session_path=provider.session_path,
        ))
        log.info(
            "provider user=%s started (session_path=%r)",
            provider.user_id, provider.session_path,
        )
    return started


async def stop_all(clients: list[ProviderClient]) -> None:
    for pc in clients:
        try:
            await pc.tg.disconnect()
        except Exception:
            log.exception(
                "provider user=%s disconnect failed", pc.user_id,
            )


def session_exists(session_path: str) -> bool:
    """A `.session` file is what Telethon expects on disk."""
    return Path(session_path).exists()
