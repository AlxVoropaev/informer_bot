"""HTTP server for the Telegram Mini App.

Serves a static SPA from `webapp/` plus a JSON API. Every API call must include
an `X-Telegram-Init-Data` header containing the raw `Telegram.WebApp.initData`
query string; we verify its HMAC against the bot token (Telegram Mini App spec)
and extract the caller's user_id from the `user` field.
"""
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from informer_bot.db import Database, format_user_label
from informer_bot.i18n import LANGUAGES
from informer_bot.summarizer import estimate_cost_usd, estimate_embedding_cost_usd

log = logging.getLogger(__name__)

_INITDATA_MAX_AGE = 24 * 3600  # reject initData older than 24h
_STATIC_DIR = Path(__file__).resolve().parent.parent / "webapp"

# Per-user token bucket: 30 requests / 60s sliding window.
_RATE_LIMIT_REQUESTS = 30
_RATE_LIMIT_WINDOW = 60.0
_rate_state: dict[int, deque[float]] = defaultdict(deque)

DB_KEY: web.AppKey[Database] = web.AppKey("db", Database)
BOT_TOKEN_KEY: web.AppKey[str] = web.AppKey("bot_token", str)
OWNER_ID_KEY: web.AppKey[int] = web.AppKey("owner_id", int)


def verify_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram Mini App initData. Returns parsed fields on success.

    Algorithm per https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app:
      secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
      data_check_string = "\\n".join(sorted(f"{k}={v}" for k, v in fields if k != "hash"))
      expected = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()
    """
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None
    auth_date = pairs.get("auth_date")
    if not auth_date:
        return None
    if int(auth_date) + _INITDATA_MAX_AGE < int(time.time()):
        return None
    return pairs


def _user_from_init(parsed: dict) -> dict | None:
    raw = parsed.get("user")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _allow_request(user_id: int, *, now: float | None = None) -> bool:
    """Sliding-window rate limit: True if request fits, False if over limit."""
    ts = time.monotonic() if now is None else now
    window_start = ts - _RATE_LIMIT_WINDOW
    bucket = _rate_state[user_id]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_REQUESTS:
        return False
    bucket.append(ts)
    return True


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    bot_token = request.app[BOT_TOKEN_KEY]
    parsed = verify_init_data(init_data, bot_token)
    if parsed is None:
        return web.json_response({"error": "invalid_init_data"}, status=401)
    user = _user_from_init(parsed)
    if user is None or "id" not in user:
        return web.json_response({"error": "no_user"}, status=401)
    user_id = int(user["id"])
    if not _allow_request(user_id):
        return web.json_response({"error": "rate_limited"}, status=429)
    db = request.app[DB_KEY]
    if db.get_user_status(user_id) != "approved":
        return web.json_response({"error": "not_approved"}, status=403)
    request["user_id"] = user_id
    request["tg_user"] = user
    return await handler(request)


def _channel_payload(db: Database, user_id: int) -> list[dict]:
    modes = db.list_user_subscription_modes(user_id)
    filters = db.list_user_subscription_filters(user_id)
    return [
        {
            "id": c.id,
            "title": c.title,
            "username": c.username,
            "about": c.about,
            "blacklisted": c.blacklisted,
            "mode": modes.get(c.id) or "off",
            "filter_prompt": filters.get(c.id),
        }
        for c in db.list_channels(include_blacklisted=False)
    ]


async def _state(request: web.Request) -> web.Response:
    db = request.app[DB_KEY]
    owner_id = request.app[OWNER_ID_KEY]
    user_id: int = request["user_id"]
    return web.json_response({
        "user_id": user_id,
        "language": db.get_language(user_id),
        "is_owner": user_id == owner_id,
        "auto_delete_hours": db.get_user_auto_delete_hours(user_id),
        "dedup_debug": db.get_dedup_debug(user_id),
        "channels": _channel_payload(db, user_id),
    })


_AUTO_DELETE_MAX_HOURS = 720  # 30 days


async def _auto_delete(request: web.Request) -> web.Response:
    db = request.app[DB_KEY]
    user_id: int = request["user_id"]
    body = await request.json()
    raw = body.get("hours")
    if raw is None or raw == 0 or raw == "":
        hours: int | None = None
    else:
        try:
            hours = int(raw)
        except (TypeError, ValueError):
            return web.json_response({"error": "bad_hours"}, status=400)
        if hours < 1 or hours > _AUTO_DELETE_MAX_HOURS:
            return web.json_response({"error": "bad_hours"}, status=400)
    db.set_user_auto_delete_hours(user_id, hours)
    log.info("miniapp: user=%s auto_delete -> %s", user_id, hours)
    return web.json_response({"ok": True, "auto_delete_hours": hours})


async def _subscription(request: web.Request) -> web.Response:
    db = request.app[DB_KEY]
    user_id: int = request["user_id"]
    body = await request.json()
    channel_id = int(body["channel_id"])
    mode = body["mode"]
    if mode not in ("off", "filtered", "debug", "all", "unsubscribe"):
        return web.json_response({"error": "bad_mode"}, status=400)
    if db.get_channel(channel_id) is None:
        return web.json_response({"error": "no_channel"}, status=404)
    if mode == "unsubscribe":
        db.unsubscribe(user_id, channel_id)
    else:
        db.subscribe(user_id, channel_id, mode=mode)
    log.info("miniapp: user=%s channel=%s mode -> %s", user_id, channel_id, mode)
    return web.json_response({"ok": True, "channels": _channel_payload(db, user_id)})


async def _filter(request: web.Request) -> web.Response:
    db = request.app[DB_KEY]
    user_id: int = request["user_id"]
    body = await request.json()
    channel_id = int(body["channel_id"])
    prompt = body.get("filter_prompt")
    if prompt is not None:
        prompt = str(prompt).strip() or None
    if db.get_channel(channel_id) is None:
        return web.json_response({"error": "no_channel"}, status=404)
    current_mode = db.get_subscription_mode(user_id, channel_id)
    db.set_channel_filter(user_id=user_id, channel_id=channel_id, filter_prompt=prompt)
    if prompt is not None and current_mode in (None, "off"):
        db.subscribe(user_id, channel_id, mode="filtered")
    log.info(
        "miniapp: user=%s channel=%s filter %s",
        user_id, channel_id, "set" if prompt else "cleared",
    )
    return web.json_response({"ok": True, "channels": _channel_payload(db, user_id)})


async def _usage(request: web.Request) -> web.Response:
    db = request.app[DB_KEY]
    owner_id = request.app[OWNER_ID_KEY]
    user_id: int = request["user_id"]
    inp, out = db.get_usage(user_id)
    payload: dict = {
        "is_owner": user_id == owner_id,
        "user": {
            "input_tokens": inp,
            "output_tokens": out,
            "cost_usd": estimate_cost_usd(inp, out),
        },
    }
    if user_id == owner_id:
        sys_in, sys_out = db.get_system_usage()
        emb_tokens = db.get_embedding_usage()
        payload["per_user"] = [
            {
                "user_id": uid,
                "label": format_user_label(uid, username, first_name),
                "input_tokens": ui,
                "output_tokens": uo,
                "cost_usd": estimate_cost_usd(ui, uo),
            }
            for uid, username, first_name, ui, uo in db.list_all_usage()
        ]
        payload["system"] = {
            "input_tokens": sys_in,
            "output_tokens": sys_out,
            "cost_usd": estimate_cost_usd(sys_in, sys_out),
        }
        payload["embeddings"] = {
            "tokens": emb_tokens,
            "cost_usd": estimate_embedding_cost_usd(emb_tokens),
        }
    return web.json_response(payload)


async def _dedup_debug(request: web.Request) -> web.Response:
    db = request.app[DB_KEY]
    user_id: int = request["user_id"]
    body = await request.json()
    enabled = bool(body.get("enabled"))
    db.set_dedup_debug(user_id, enabled)
    log.info("miniapp: user=%s dedup_debug -> %s", user_id, enabled)
    return web.json_response({"ok": True, "dedup_debug": enabled})


async def _language(request: web.Request) -> web.Response:
    db = request.app[DB_KEY]
    user_id: int = request["user_id"]
    body = await request.json()
    code = body.get("language")
    if code not in LANGUAGES:
        return web.json_response({"error": "bad_language"}, status=400)
    db.set_language(user_id=user_id, language=code)
    log.info("miniapp: user=%s language -> %s", user_id, code)
    return web.json_response({"ok": True, "language": code})


def build_app(*, db: Database, bot_token: str, owner_id: int) -> web.Application:
    app = web.Application(middlewares=[_auth_middleware])
    app[DB_KEY] = db
    app[BOT_TOKEN_KEY] = bot_token
    app[OWNER_ID_KEY] = owner_id
    app.router.add_get("/api/state", _state)
    app.router.add_post("/api/subscription", _subscription)
    app.router.add_post("/api/filter", _filter)
    app.router.add_post("/api/language", _language)
    app.router.add_post("/api/auto_delete", _auto_delete)
    app.router.add_post("/api/dedup_debug", _dedup_debug)
    app.router.add_get("/api/usage", _usage)

    async def index(_req: web.Request) -> web.FileResponse:
        return web.FileResponse(_STATIC_DIR / "index.html")

    app.router.add_get("/", index)
    app.router.add_static("/static/", _STATIC_DIR)
    return app


async def start_server(
    *, db: Database, bot_token: str, owner_id: int, host: str, port: int
) -> web.AppRunner:
    app = build_app(db=db, bot_token=bot_token, owner_id=owner_id)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("miniapp server listening on %s:%s", host, port)
    return runner
