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
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from informer_bot import webapp
from informer_bot.db import Database
from informer_bot.modes import SubscriptionMode
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
    db.set_user_status(user_id=OWNER_ID, status="approved")
    db.add_pending_provider(user_id=OWNER_ID, session_path="data/informer.session")
    db.set_provider_status(user_id=OWNER_ID, status="approved")
    db.set_meta("owner_id", str(OWNER_ID))
    db.upsert_channel(channel_id=1, title="Alpha", username="alpha", about="about A")
    db.upsert_channel(channel_id=2, title="Beta", username="beta")
    db.set_provider_channels(provider_user_id=OWNER_ID, channel_ids={1, 2})
    db.set_user_status(user_id=USER_ID, status="approved")
    return db


@pytest.fixture
def notify_owner() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def send_dm() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
async def client(
    db: Database, notify_owner: AsyncMock, send_dm: AsyncMock,
) -> TestClient:
    app = build_app(
        db=db, bot_token=BOT_TOKEN, owner_id=OWNER_ID,
        notify_owner_provider_request=notify_owner,
        send_dm=send_dm,
    )
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
        json={"channel_id": 1, "mode": SubscriptionMode.ALL},
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
    db.add_usage(
        user_id=USER_ID, provider="anthropic",
        input_tokens=1000, output_tokens=200,
    )
    db.add_system_usage(provider="anthropic", input_tokens=500, output_tokens=100)
    db.add_embedding_usage(provider="openai", tokens=75)
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
    assert body["system"]["by_provider"][0]["provider"] == "anthropic"
    assert body["embeddings"]["by_provider"][0]["provider"] == "openai"


async def test_usage_for_non_owner_omits_admin_keys(
    client: TestClient, db: Database
) -> None:
    db.add_usage(
        user_id=USER_ID, provider="anthropic", input_tokens=10, output_tokens=2,
    )
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
    db.subscribe(user_id=USER_ID, channel_id=1, mode=SubscriptionMode.ALL)
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.post(
        "/api/subscription",
        headers={"X-Telegram-Init-Data": init_data},
        json={"channel_id": 1, "mode": SubscriptionMode.UNSUBSCRIBE},
    )
    assert resp.status == 200
    assert db.is_subscribed(user_id=USER_ID, channel_id=1) is False
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) is None


# ---------- /api/filter ----------

async def test_filter_null_clears_existing_prompt(
    client: TestClient, db: Database
) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode=SubscriptionMode.FILTERED)
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
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == SubscriptionMode.FILTERED


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
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == SubscriptionMode.FILTERED
    assert db.get_channel_filter(user_id=USER_ID, channel_id=1) == "only AI"


async def test_filter_on_off_explicit_row_auto_bumps_to_filtered(
    client: TestClient, db: Database
) -> None:
    db.subscribe(user_id=USER_ID, channel_id=1, mode=SubscriptionMode.OFF)
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.post(
        "/api/filter",
        headers={"X-Telegram-Init-Data": init_data},
        json={"channel_id": 1, "filter_prompt": "only AI"},
    )
    assert resp.status == 200
    assert db.get_subscription_mode(user_id=USER_ID, channel_id=1) == SubscriptionMode.FILTERED


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


# ---------- auto-delete ----------

async def test_state_returns_auto_delete_hours(
    client: TestClient, db: Database
) -> None:
    db.set_user_auto_delete_hours(USER_ID, 6)
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["auto_delete_hours"] == 6


async def test_state_returns_null_when_auto_delete_unset(
    client: TestClient,
) -> None:
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    body = await resp.json()
    assert body["auto_delete_hours"] is None


async def test_auto_delete_set_then_clear(
    client: TestClient, db: Database
) -> None:
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)}
    resp = await client.post("/api/auto_delete", headers=headers, json={"hours": 6})
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "auto_delete_hours": 6}
    assert db.get_user_auto_delete_hours(USER_ID) == 6

    resp = await client.post("/api/auto_delete", headers=headers, json={"hours": None})
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "auto_delete_hours": None}
    assert db.get_user_auto_delete_hours(USER_ID) is None


async def test_state_returns_dedup_debug_default_false(
    client: TestClient, db: Database
) -> None:
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    body = await resp.json()
    assert body["dedup_debug"] is False


async def test_dedup_debug_set_then_clear(
    client: TestClient, db: Database
) -> None:
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)}
    resp = await client.post(
        "/api/dedup_debug", headers=headers, json={"enabled": True}
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "dedup_debug": True}
    assert db.get_dedup_debug(USER_ID) is True

    resp = await client.post(
        "/api/dedup_debug", headers=headers, json={"enabled": False}
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "dedup_debug": False}
    assert db.get_dedup_debug(USER_ID) is False

    state = await (await client.get(
        "/api/state", headers=headers
    )).json()
    assert state["dedup_debug"] is False


# ---------- summary prompt (owner-only) ----------

async def test_state_includes_summary_prompt_for_owner(
    client: TestClient, db: Database
) -> None:
    from informer_bot.summarizer import SYSTEM_PROMPT

    init_data = _make_init_data(user_id=OWNER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    body = await resp.json()
    assert body["summary_prompt"] is None
    assert body["summary_prompt_default"] == SYSTEM_PROMPT


async def test_state_returns_custom_summary_prompt_for_owner(
    client: TestClient, db: Database
) -> None:
    from informer_bot.summarizer import SYSTEM_PROMPT

    db.set_meta("summary_prompt", "CUSTOM")
    init_data = _make_init_data(user_id=OWNER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    body = await resp.json()
    assert body["summary_prompt"] == "CUSTOM"
    assert body["summary_prompt_default"] == SYSTEM_PROMPT


async def test_state_omits_summary_prompt_for_non_owner(
    client: TestClient,
) -> None:
    init_data = _make_init_data(user_id=USER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    body = await resp.json()
    assert "summary_prompt" not in body
    assert "summary_prompt_default" not in body


async def test_summary_prompt_set_then_reset(
    client: TestClient, db: Database
) -> None:
    from informer_bot.summarizer import SYSTEM_PROMPT

    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)}
    resp = await client.post(
        "/api/summary_prompt", headers=headers, json={"prompt": "CUSTOM"}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["summary_prompt"] == "CUSTOM"
    assert body["summary_prompt_default"] == SYSTEM_PROMPT
    assert db.get_meta("summary_prompt") == "CUSTOM"

    resp = await client.post(
        "/api/summary_prompt", headers=headers, json={"prompt": None}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["summary_prompt"] is None
    assert body["summary_prompt_default"] == SYSTEM_PROMPT
    assert db.get_meta("summary_prompt") == ""


async def test_summary_prompt_empty_resets(
    client: TestClient, db: Database
) -> None:
    db.set_meta("summary_prompt", "CUSTOM")
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)}
    resp = await client.post(
        "/api/summary_prompt", headers=headers, json={"prompt": "   "}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["summary_prompt"] is None
    assert db.get_meta("summary_prompt") == ""


async def test_summary_prompt_strips_whitespace(
    client: TestClient, db: Database
) -> None:
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)}
    resp = await client.post(
        "/api/summary_prompt", headers=headers, json={"prompt": "  CUSTOM  "}
    )
    assert resp.status == 200
    assert db.get_meta("summary_prompt") == "CUSTOM"


async def test_summary_prompt_non_owner_forbidden(
    client: TestClient, db: Database
) -> None:
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)}
    resp = await client.post(
        "/api/summary_prompt", headers=headers, json={"prompt": "CUSTOM"}
    )
    assert resp.status == 403
    body = await resp.json()
    assert body["error"] == "not_owner"
    assert db.get_meta("summary_prompt") is None


@pytest.mark.parametrize("bad", [0, -1, 721, "abc"])
async def test_auto_delete_rejects_bad_values(
    client: TestClient, db: Database, bad
) -> None:
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)}
    if bad == 0:
        # 0 is treated as "clear", returns ok with null
        resp = await client.post("/api/auto_delete", headers=headers, json={"hours": 0})
        assert resp.status == 200
        return
    resp = await client.post("/api/auto_delete", headers=headers, json={"hours": bad})
    assert resp.status == 400
    assert (await resp.json())["error"] == "bad_hours"


async def test_summary_prompt_too_long_rejected(
    client: TestClient, db: Database
) -> None:
    db.set_meta("summary_prompt", "PRIOR")
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)}
    resp = await client.post(
        "/api/summary_prompt", headers=headers, json={"prompt": "x" * 5000}
    )
    assert resp.status == 400
    assert (await resp.json())["error"] == "prompt_too_long"
    assert db.get_meta("summary_prompt") == "PRIOR"


async def test_state_returns_null_summary_prompt_for_owner_when_unset(
    client: TestClient, db: Database
) -> None:
    from informer_bot.summarizer import SYSTEM_PROMPT

    init_data = _make_init_data(user_id=OWNER_ID)
    resp = await client.get(
        "/api/state", headers={"X-Telegram-Init-Data": init_data}
    )
    body = await resp.json()
    assert body["summary_prompt"] is None
    assert body["summary_prompt_default"] == SYSTEM_PROMPT


async def test_summary_prompt_returns_null_after_reset(
    client: TestClient, db: Database
) -> None:
    db.set_meta("summary_prompt", "CUSTOM")
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)}
    resp = await client.post(
        "/api/summary_prompt", headers=headers, json={"prompt": None}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["summary_prompt"] is None
    assert db.get_meta("summary_prompt") == ""


async def test_subscription_rejects_non_numeric_channel_id(
    client: TestClient,
) -> None:
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)}
    resp = await client.post(
        "/api/subscription",
        headers=headers,
        json={"channel_id": "abc", "mode": SubscriptionMode.ALL},
    )
    assert resp.status == 400
    assert (await resp.json())["error"] == "bad_channel_id"


async def test_filter_rejects_non_numeric_channel_id(
    client: TestClient,
) -> None:
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)}
    resp = await client.post(
        "/api/filter",
        headers=headers,
        json={"channel_id": "abc", "filter_prompt": "x"},
    )
    assert resp.status == 400
    assert (await resp.json())["error"] == "bad_channel_id"


# ---------- /api/state: provider fields ----------


async def test_state_owner_is_provider(client: TestClient) -> None:
    resp = await client.get(
        "/api/state",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)},
    )
    body = await resp.json()
    assert body["is_provider"] is True
    assert body["provider_status"] == "approved"
    assert body["provider_blacklist"] == []
    assert body["provider_channels"] == [1, 2]


async def test_state_non_provider_user(client: TestClient) -> None:
    resp = await client.get(
        "/api/state",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
    )
    body = await resp.json()
    assert body["is_provider"] is False
    assert body["provider_status"] is None
    assert "provider_blacklist" not in body
    assert "provider_channels" not in body


async def test_state_pending_provider(client: TestClient, db: Database) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    resp = await client.get(
        "/api/state",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
    )
    body = await resp.json()
    assert body["is_provider"] is False
    assert body["provider_status"] == "pending"
    assert "provider_blacklist" not in body


async def test_state_approved_extra_provider(
    client: TestClient, db: Database
) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    db.set_provider_status(user_id=USER_ID, status="approved")
    db.upsert_channel(channel_id=10, title="Gamma")
    db.set_provider_channels(provider_user_id=USER_ID, channel_ids={10})
    db.set_provider_channel_blacklisted(
        provider_user_id=USER_ID, channel_id=10, blacklisted=True,
    )
    resp = await client.get(
        "/api/state",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
    )
    body = await resp.json()
    assert body["is_provider"] is True
    assert body["provider_status"] == "approved"
    assert body["provider_blacklist"] == [10]
    assert body["provider_channels"] == [10]


# ---------- /api/become_provider ----------


async def test_become_provider_creates_pending_and_dms_owner(
    client: TestClient, db: Database, notify_owner: AsyncMock,
) -> None:
    resp = await client.post(
        "/api/become_provider",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
        json={},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "status": "pending"}
    provider = db.get_provider(USER_ID)
    assert provider is not None
    assert provider.status == "pending"
    assert provider.session_path == f"data/sessions/{USER_ID}.session"
    notify_owner.assert_awaited_once_with(USER_ID)


async def test_become_provider_owner_rejected(
    client: TestClient, notify_owner: AsyncMock,
) -> None:
    resp = await client.post(
        "/api/become_provider",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)},
        json={},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": False, "reason": "owner"}
    notify_owner.assert_not_called()


async def test_become_provider_already_pending(
    client: TestClient, db: Database, notify_owner: AsyncMock,
) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    resp = await client.post(
        "/api/become_provider",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
        json={},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": False, "reason": "already_pending"}
    notify_owner.assert_not_called()


async def test_become_provider_already_approved(
    client: TestClient, db: Database, notify_owner: AsyncMock,
) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    db.set_provider_status(user_id=USER_ID, status="approved")
    resp = await client.post(
        "/api/become_provider",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
        json={},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": False, "reason": "already_approved"}
    notify_owner.assert_not_called()


async def test_become_provider_previously_denied(
    client: TestClient, db: Database, notify_owner: AsyncMock,
) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    db.set_provider_status(user_id=USER_ID, status="denied")
    resp = await client.post(
        "/api/become_provider",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
        json={},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": False, "reason": "denied"}
    notify_owner.assert_not_called()


# ---------- /api/blacklist ----------


async def test_blacklist_non_provider_forbidden(
    client: TestClient, send_dm: AsyncMock,
) -> None:
    resp = await client.post(
        "/api/blacklist",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
        json={"channel_id": 1, "blacklisted": True},
    )
    assert resp.status == 403
    assert (await resp.json())["error"] == "not_provider"
    send_dm.assert_not_called()


async def test_blacklist_pending_provider_forbidden(
    client: TestClient, db: Database,
) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    resp = await client.post(
        "/api/blacklist",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
        json={"channel_id": 1, "blacklisted": True},
    )
    assert resp.status == 403


async def test_blacklist_channel_not_owned_returns_400(
    client: TestClient, db: Database,
) -> None:
    db.add_pending_provider(
        user_id=USER_ID, session_path=f"data/sessions/{USER_ID}.session",
    )
    db.set_provider_status(user_id=USER_ID, status="approved")
    # USER_ID is approved but doesn't contribute channel 1.
    resp = await client.post(
        "/api/blacklist",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
        json={"channel_id": 1, "blacklisted": True},
    )
    assert resp.status == 400
    assert (await resp.json())["error"] == "channel_not_owned_by_provider"


async def test_blacklist_owner_toggles_own_channel(
    client: TestClient, db: Database, send_dm: AsyncMock,
) -> None:
    # Owner has a co-provider for channel 1 so blacklisting it doesn't orphan.
    co_provider = 7
    db.set_user_status(user_id=co_provider, status="approved")
    db.add_pending_provider(
        user_id=co_provider, session_path=f"data/sessions/{co_provider}.session",
    )
    db.set_provider_status(user_id=co_provider, status="approved")
    db.set_provider_channels(provider_user_id=co_provider, channel_ids={1})
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)}
    resp = await client.post(
        "/api/blacklist", headers=headers,
        json={"channel_id": 1, "blacklisted": True},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "blacklist": [1]}
    assert db.list_provider_blacklist(OWNER_ID) == {1}
    send_dm.assert_not_called()  # channel still has co_provider, no orphan

    resp = await client.post(
        "/api/blacklist", headers=headers,
        json={"channel_id": 1, "blacklisted": False},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "blacklist": []}
    assert db.list_provider_blacklist(OWNER_ID) == set()


async def test_blacklist_runs_orphan_sweep(
    client: TestClient, db: Database, send_dm: AsyncMock,
) -> None:
    """Toggling blacklist always runs `prune_orphan_channels`. A channel
    with no `provider_channels` row gets deleted and its subscribers DM'd."""
    SUBSCRIBER = 7777
    db.set_user_status(user_id=SUBSCRIBER, status="approved")
    # Seed an unrelated orphan channel (no provider_channels rows).
    db.upsert_channel(channel_id=99, title="Orphan")
    db.subscribe(user_id=SUBSCRIBER, channel_id=99)
    headers = {"X-Telegram-Init-Data": _make_init_data(user_id=OWNER_ID)}
    resp = await client.post(
        "/api/blacklist", headers=headers,
        json={"channel_id": 1, "blacklisted": True},
    )
    assert resp.status == 200
    # The orphan got swept regardless of which channel was blacklisted.
    assert db.get_channel(99) is None
    send_dm.assert_awaited_once()
    dm_user_id, dm_text = send_dm.await_args.args
    assert dm_user_id == SUBSCRIBER
    assert "Orphan" in dm_text and "no longer available" in dm_text.lower()


# ---------- /api/state: channels payload no longer carries 'blacklisted' ----------


async def test_state_channel_payload_omits_blacklisted_field(
    client: TestClient,
) -> None:
    resp = await client.get(
        "/api/state",
        headers={"X-Telegram-Init-Data": _make_init_data(user_id=USER_ID)},
    )
    body = await resp.json()
    for c in body["channels"]:
        assert "blacklisted" not in c
