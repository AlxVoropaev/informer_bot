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
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from informer_bot.db import Database
from informer_bot.i18n import LANGUAGES

log = logging.getLogger(__name__)

_INITDATA_MAX_AGE = 24 * 3600  # reject initData older than 24h
_STATIC_DIR = Path(__file__).resolve().parent.parent / "webapp"


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
    if auth_date and int(auth_date) + _INITDATA_MAX_AGE < int(time.time()):
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


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    bot_token: str = request.app["bot_token"]
    parsed = verify_init_data(init_data, bot_token)
    if parsed is None:
        return web.json_response({"error": "invalid_init_data"}, status=401)
    user = _user_from_init(parsed)
    if user is None or "id" not in user:
        return web.json_response({"error": "no_user"}, status=401)
    request["user_id"] = int(user["id"])
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
    db: Database = request.app["db"]
    owner_id: int = request.app["owner_id"]
    user_id: int = request["user_id"]
    if db.get_user_status(user_id) != "approved":
        return web.json_response({"error": "not_approved"}, status=403)
    return web.json_response({
        "user_id": user_id,
        "language": db.get_language(user_id),
        "is_owner": user_id == owner_id,
        "channels": _channel_payload(db, user_id),
    })


async def _subscription(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    user_id: int = request["user_id"]
    if db.get_user_status(user_id) != "approved":
        return web.json_response({"error": "not_approved"}, status=403)
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
    db: Database = request.app["db"]
    user_id: int = request["user_id"]
    if db.get_user_status(user_id) != "approved":
        return web.json_response({"error": "not_approved"}, status=403)
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


async def _language(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
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
    app["db"] = db
    app["bot_token"] = bot_token
    app["owner_id"] = owner_id
    app.router.add_get("/api/state", _state)
    app.router.add_post("/api/subscription", _subscription)
    app.router.add_post("/api/filter", _filter)
    app.router.add_post("/api/language", _language)

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
