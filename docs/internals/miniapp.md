# Mini App (primary user surface)

The Mini App is the only place regular users manage subscriptions, filters,
language, or (for approved providers) personal channel blacklists — there are
no `/list`, `/language`, or `/blacklist` Telegram commands. The bot keeps
`/start`, `/app`, `/help`, `/usage`, `/become_provider` for users, plus admin
`/update` and `/revoke_provider`. `/help` tells users to open the Mini App for
everything else.

When `MINIAPP_URL` is set, `main.py` boots an **aiohttp** server alongside the
PTB application (same asyncio loop, same SQLite, no separate process). The
server serves `webapp/index.html` at `/`, static assets at `/static/<file>`,
and a JSON API under `/api/`. Every API call validates the
`X-Telegram-Init-Data` header via `informer_bot.webapp.verify_init_data` —
HMAC-SHA256 with key `HMAC("WebAppData", bot_token)` over the sorted
`\n`-joined `key=value` pairs from `Telegram.WebApp.initData` — and rejects
data older than 24h. The caller's user_id is parsed from the `user` field and
checked against `users.status='approved'`.

## Endpoints

- `GET /api/state` → `{user_id, language, is_owner, auto_delete_hours, dedup_debug, is_provider, provider_status, channels: [...]}` — owner payload also includes `summary_prompt` (the saved custom override, or `null` when no override is active and the hardcoded default is in use) and `summary_prompt_default` (the hardcoded default). Approved providers (owner included) additionally get `provider_blacklist` (array of channel ids the caller has personally blacklisted) and `provider_channels` (array of channel ids the caller's user-account is currently contributing). Each entry in `channels` no longer has a per-row `blacklisted` field — frontend cross-references the top-level `provider_blacklist` instead.
- `POST /api/subscription` `{channel_id, mode}` (`mode` ∈ `off|filtered|debug|all|unsubscribe`)
- `POST /api/filter` `{channel_id, filter_prompt}` (null/empty clears)
- `POST /api/language` `{language}`
- `POST /api/auto_delete` `{hours}` — integer 1..720 enables, `null`/`0`/`""` disables
- `POST /api/dedup_debug` `{enabled}` — user-level toggle for the dedup-debug delivery path (see [behaviour.md](behaviour.md) and [dedup.md](dedup.md))
- `POST /api/become_provider` `{}` → `{ok, status}` on success or `{ok: false, reason}`. `reason` ∈ `owner` (caller is already the owner), `already_pending`, `already_approved`, `denied`. Mirrors the `/become_provider` Telegram command and DMs the owner an Allow/Deny inline keyboard for fresh requests.
- `POST /api/blacklist` `{channel_id, blacklisted}` → caller-as-provider blacklist toggle. `{ok, blacklist}` (200) on success; `{error: "not_provider"}` (403) when the caller isn't an approved provider; `{error: "channel_not_owned_by_provider"}` (400) when the channel isn't in the caller's `provider_channels`. `prune_orphan_channels` is invoked defensively after a successful toggle.
- `GET /api/usage` → `{is_owner, user: {input_tokens, output_tokens, cost_usd}}` — owner payload also includes `per_user[]`, `system`, `embeddings`.
- `POST /api/summary_prompt` `{prompt}` — owner-only (non-owners get 403 `not_owner`). Saves a custom system prompt for post summarization. `null`/missing/empty/whitespace resets to the hardcoded default. Prompts longer than 4096 characters are rejected with 400 `prompt_too_long`. Returns `{ok, summary_prompt, summary_prompt_default}` where `summary_prompt` is `null` when no override is active. The custom prompt is stored in the `meta` table under `summary_prompt` and applied to every summarize backend (Anthropic, Ollama, remote processor) via the `SummarizeRequest.system_prompt` field.
- Provider login (owner-only) — every endpoint below returns 403 `not_owner` for non-owner callers:
  - `GET /api/providers` → `{providers: [...]}` where each entry is `{user_id, label, status, has_session, session_path, login_step}`. `login_step ∈ null|"phone"|"code"|"password"` and reflects whether an in-progress Mini App login is currently held in memory for that provider.
  - `POST /api/provider_login/start` `{user_id, force}` → starts a fresh Telethon login for the named approved provider. Returns `{ok: true, step: "phone"}`. 404 `unknown_provider` if `user_id` isn't an approved provider; 409 `session_exists` if a session file already exists and `force` isn't true. When `force=true`, the new login writes to a temporary path `<session_path>.relogin` (the live session file is never touched), and the temp file is atomically swapped over the live path only on full login success.
  - `POST /api/provider_login/phone` `{user_id, phone}` → calls Telethon `send_code_request`. Returns `{ok, step: "code"}`, or 409 `no_login_in_progress` / `bad_step`.
  - `POST /api/provider_login/code` `{user_id, code}` → calls Telethon `sign_in(code=...)`. Returns `{ok, step: "password"}` when 2FA is required, `{ok, done: true, restart_required: <bool>}` on full success (session file written, chmod 600). `restart_required` is true when this completed a `force=true` re-login that swapped the live session — the bot must restart for the new session to take effect because the running provider client still holds the old SQLite handle. Telethon errors (e.g. invalid/expired code) return 400 `{error, detail}`.
  - `POST /api/provider_login/password` `{user_id, password}` → completes 2FA via `sign_in(password=...)`. Returns `{ok, done: true, restart_required: <bool>}`, or 400 `bad_password`.
  - `POST /api/provider_login/cancel` `{user_id}` → disconnects, discards in-progress login state, and deletes any temporary re-login session file. The live session file is never touched. Always `{ok: true}`.
  - `POST /api/provider_logout` `{user_id}` → owner-only clean logout. Disconnects the running Telethon provider client (if any), then deletes the session file at `provider.session_path` and its `-journal` sibling. 404 `unknown_provider` if `user_id` isn't an approved provider. Returns `{ok: true}`. Disconnecting the provider will trip the bot's main wait loop and cause it to exit gracefully — Docker (or the user) restarts it, and the bot then comes back up in degraded mode until the admin logs back in.

In-progress Telethon clients live in an in-memory map (`informer_bot.login_sessions.LoginSessions`) keyed by `user_id`, with a 10-minute idle TTL — so a bot restart drops any in-flight login and the admin restarts from `phone`. The `informer_bot.cli_login` CLI remains the fallback.

## Degraded mode

If no usable Telethon provider sessions are available at startup (every approved provider has either no session file or an unauthorized one), the bot no longer exits — it logs a warning and runs in degraded mode with only the PTB application and the Mini App. No channel posts will be ingested in this state. The admin can log a provider in via the Mini App (or run `uv run python login.py`) and restart the bot to restore full operation.

## Tabs

Approved providers (`is_provider === true`) see two top-level tabs: **Subscribe**
(the existing channel list, unchanged) and **Provide** (only the channels in the
caller's `provider_channels`, with an inline blacklist checkbox per row driven by
`provider_blacklist`; tapping the row body still opens the same details view).
Search is scoped to the active tab and the input resets on tab switch; default
tab is Subscribe. Non-providers see no tab UI — just the single subscribe list,
identical to before.

## Deep-linking

The new-channel announcement DM (sent on `/update`) attaches a
`web_app=WebAppInfo(url=f"{MINIAPP_URL}?channel=<id>")` button. On open,
`webapp/app.js` reads `?channel=<id>` (and falls back to
`tg.initDataUnsafe.start_param` matching `^channel_(-?\d+)$`) and auto-opens
that channel's details view.

When the optional `MINIAPP_TG_DEEPLINK` env var is set (e.g.
`https://t.me/MyBot/app` — requires a Web App short-name registered via
`/newapp` in @BotFather), every summary DM includes a small ⚙ link next to
the channel title. The URL is `<MINIAPP_TG_DEEPLINK>?startapp=channel_<id>`,
which Telegram clients intercept inside chats and open the Mini App on the
target channel's details view via `start_param`. Without the env var the
summary message is unchanged.

Subscription/filter behaviour mirrors the inline-keyboard handlers — setting a
filter on an `off`/no-row channel auto-bumps it to `filtered`, same as
`on_filter_text`. The frontend (`webapp/`) is vanilla HTML/CSS/JS using the
Telegram `--tg-theme-*` CSS variables for native theming. `/app` opens the
Mini App via `InlineKeyboardButton(web_app=WebAppInfo(url=MINIAPP_URL))` and
`main.py` also calls `set_chat_menu_button(MenuButtonWebApp(...))` so the
bot's burger menu launches it.

## Caddy reverse proxy

`compose.yaml` ships a `caddy` (caddy:2-alpine) sidecar that reverse-proxies
`https://$MINIAPP_DOMAIN:9443` → `bot:8085`, with TLS certs auto-fetched/renewed
from Let's Encrypt. Caddyfile at the repo root is `{$MINIAPP_DOMAIN}:9443 {
reverse_proxy bot:8085 }`; the domain comes from `data/.env` via
`env_file`. Required env vars: `MINIAPP_DOMAIN` (used by Caddy) and
`MINIAPP_URL=https://<same-domain>:9443` (used by the bot for the WebApp
button). Caddy listens on host ports 80 (ACME HTTP-01) and 9443 (HTTPS).
We use 9443 instead of 443 because the deployment host has MTProto VPN
already on 443; Telegram Mini Apps accept non-443 HTTPS URLs. The Caddy
service mounts named volumes `caddy_data` (cert storage) and
`caddy_config`. We chose Caddy over Cloudflare's quick tunnel because
Russian mobile carriers DPI-block `*.trycloudflare.com` while Telegram's
in-app WebView inherits the app's bypass-tunnel routing — a plain VPS IP
behind a regular domain bypasses both issues.
