"""Tests for the Mini App aiohttp server.

Builds a real `web.Application` via `informer_bot.webapp.build_app`, drives it
with an `aiohttp.test_utils.TestClient`, and forges signed `initData` headers
using the same HMAC algorithm Telegram uses, so the auth middleware is
exercised end-to-end against a real `Database`.
"""
import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from informer_bot import webapp
from informer_bot.db import Database
from informer_bot.webapp import build_app

BOT_TOKEN = "123456:test-bot-token"
OWNER_ID = 999
USER_ID = 42


def _make_init_data(
    *,
    bot_token: str = BOT_TOKEN,
    user_id: int = USER_ID,
    auth_date: int | None = None,
    valid_hash: bool = True,
    user_first_name: str = "Tester",
) -> str:
    """Forge a Telegram Mini App initData query string."""
    if auth_date is None:
        auth_date = int(time.time())
    pairs: dict[str, str] = {
        "user": json.dumps({"id": user_id, "first_name": user_first_name}),
    }
    if auth_date is not None:
        pairs["auth_date"] = str(auth_date)
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not valid_hash:
        sig = "0" * 64
    pairs["hash"] = sig
    return urlencode(pairs)


def _make_init_data_no_auth_date(*, user_id: int = USER_ID) -> str:
    """Forge initData WITHOUT an auth_date field (regression guard)."""
    pairs: dict[str, str] = {
        "user": json.dumps({"id": user_id, "first_name": "T"}),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    pairs["hash"] = sig
    return urlencode(pairs)


@pytest.fixture(autouse=True)
def _reset_rate_state() -> Iterator[None]:
    """The rate-limit deque is module-global; clear it between tests."""
    webapp._rate_state.clear()
    yield
    webapp._rate_state.clear()


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "webapp.db")
    db.upsert_channel(channel_id=1, title="Alpha", username="alpha", about="about A")
    db.upsert_channel(channel_id=2, title="Beta", username="beta")
    db.set_user_status(user_id=USER_ID, status="approved")
    db.set_user_status(user_id=OWNER_ID, status="approved")
    return db


@pytest.fixture
async def client(db: Database) -> TestClient:
    app = build_app(db=db, bot_token=BOT_TOKEN, owner_id=OWNER_ID)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


# ---------- auth: HMAC, freshness, missing fields ----------

async def test_state_returns_200_with_valid_init_data(
    client: TestClient, db: Database
) -> None:
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["user_id"] == USER_ID
    assert body["is_owner"] is False
    assert body["language"] == "en"
    titles = sorted(c["title"] for c in body["channels"])
    assert titles == ["Alpha", "Beta"]


async def test_invalid_hmac_rejected_with_401(client: TestClient) -> None:
    init_data = _make_init_data(valid_hash=False)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 401
    body = await resp.json()
    assert body["error"] == "invalid_init_data"


async def test_stale_auth_date_rejected_with_401(client: TestClient) -> None:
    twenty_five_hours_ago = int(time.time()) - 25 * 3600
    init_data = _make_init_data(auth_date=twenty_five_hours_ago)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 401
    body = await resp.json()
    assert body["error"] == "invalid_init_data"


async def test_missing_auth_date_rejected_with_401(client: TestClient) -> None:
    """Regression guard for S1: initData without auth_date must be rejected
    even when its HMAC validates."""
    init_data = _make_init_data_no_auth_date()
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 401
    body = await resp.json()
    assert body["error"] == "invalid_init_data"


# ---------- approval gate (was C8) ----------

async def test_pending_user_blocked_on_every_endpoint(
    client: TestClient, db: Database
) -> None:
    pending_id = 555
    db.add_pending_user(user_id=pending_id, username="bob")
    init_data = _make_init_data(user_id=pending_id)
    headers = {"X-Telegram-Init-Data": init_data}

    state_resp = await client.get("/api/state", headers=headers)
    assert state_resp.status == 403

    sub_resp = await client.post(
        "/api/subscription",
        headers=headers,
        json={"channel_id": 1, "mode": "all"},
    )
    assert sub_resp.status == 403

    filter_resp = await client.post(
        "/api/filter",
        headers=headers,
        json={"channel_id": 1, "filter_prompt": "x"},
    )
    assert filter_resp.status == 403

    lang_resp = await client.post(
        "/api/language", headers=headers, json={"language": "ru"}
    )
    assert lang_resp.status == 403

    usage_resp = await client.get("/api/usage", headers=headers)
    assert usage_resp.status == 403


# ---------- /api/usage owner vs non-owner ----------

async def test_usage_for_owner_includes_per_user_system_embeddings(
    client: TestClient, db: Database
) -> None:
    db.add_usage(user_id=USER_ID, input_tokens=1000, output_tokens=200)
    db.add_system_usage(input_tokens=500, output_tokens=100)
    db.add_embedding_usage(75)
    init_data = _make_init_data(user_id=OWNER_ID)
    resp = await client.get(
        "/api/usage", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["is_owner"] is True
    assert "per_user" in body
    assert "system" in body
    assert "embeddings" in body
    assert body["system"]["input_tokens"] == 500
    assert body["embeddings"]["tokens"] == 75


async def test_usage_for_non_owner_omits_admin_keys(
    client: TestClient, db: Database
) -> None:
    db.add_usage(user_id=USER_ID, input_tokens=10, output_tokens=2)
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.get(
        "/api/usage", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["is_owner"] is False
    assert "user" in body
    assert "per_user" not in body
    assert "system" not in body
    assert "embeddings" not in body


# ---------- /api/subscription ----------

async def test_subscription_unsubscribe_deletes_row(
    client: TestClient, db: Database
) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="all")
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.post(
        "/api/subscription",
        headers={"X-Telegram-Init-Data": init_data},
        json={"channel_id": 1, "mode": "unsubscribe"},
    )
    assert resp.status == 200
    assert db.is_subscribed(user_id=USER_ID, channel_id=1) is False
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) is None


# ---------- /api/filter ----------

async def test_filter_null_clears_existing_prompt(
    client: TestClient, db: Database
) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="filtered")
    db.set_channel_filter(
        user_id=USER_ID, channel_id=1, filter_prompt="only AI"
    )
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.post(
        "/api/filter",
        headers={"X-Telegram-Init-Data": init_data},
        json={"channel_id": 1, "filter_prompt": None},
    )
    assert resp.status == 200
    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) is None
    # mode must NOT auto-bump when clearing.
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == "filtered"


async def test_filter_on_off_row_auto_bumps_to_filtered(
    client: TestClient, db: Database
) -> None:
    """Setting a filter on a no-row channel should auto-create a 'filtered'
    subscription (matches the on_filter_text legacy behaviour)."""
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.post(
        "/api/filter",
        headers={"X-Telegram-Init-Data": init_data},
        json={"channel_id": 1, "filter_prompt": "only AI"},
    )
    assert resp.status == 200
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == "filtered"
    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) == "only AI"


async def test_filter_on_off_explicit_row_auto_bumps_to_filtered(
    client: TestClient, db: Database
) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode="off")
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.post(
        "/api/filter",
        headers={"X-Telegram-Init-Data": init_data},
        json={"channel_id": 1, "filter_prompt": "only AI"},
    )
    assert resp.status == 200
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == "filtered"


# ---------- rate limit (S2) ----------

async def test_rate_limit_returns_429_after_burst(
    client: TestClient, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shrink the bucket so a burst of N+1 requests trips the limit. We patch
    the module-level config rather than relying on the real 30-request
    bucket — keeps the test fast and unambiguous."""
    monkeypatch.setattr(webapp, "_RATE_LIMIT_REQUESTS", 3)
    init_data = _make_init_data(user_id=USER_ID)
    headers = {"X-Telegram-Init-Data": init_data}

    statuses = []
    for _ in range(5):
        resp = await client.get("/api/state", headers=headers)
        statuses.append(resp.status)

    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]
    assert any(s == 429 for s in statuses)
