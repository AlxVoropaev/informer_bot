# Mini App (primary user surface)

The Mini App is the only place regular users manage subscriptions, filters, or
language — there are no `/list` or `/language` Telegram commands. The bot
keeps `/start`, `/app`, `/help`, `/usage` for users, plus admin `/blacklist`
and `/update`. `/help` tells users to open the Mini App for everything else.

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

- `GET /api/state` → `{user_id, language, is_owner, auto_delete_hours, dedup_debug, channels: [...]}` — owner payload also includes `summary_prompt` (the saved custom override, or `null` when no override is active and the hardcoded default is in use) and `summary_prompt_default` (the hardcoded default).
- `POST /api/subscription` `{channel_id, mode}` (`mode` ∈ `off|filtered|debug|all|unsubscribe`)
- `POST /api/filter` `{channel_id, filter_prompt}` (null/empty clears)
- `POST /api/language` `{language}`
- `POST /api/auto_delete` `{hours}` — integer 1..720 enables, `null`/`0`/`""` disables
- `POST /api/dedup_debug` `{enabled}` — user-level toggle for the dedup-debug delivery path (see [behaviour.md](behaviour.md) and [dedup.md](dedup.md))
- `GET /api/usage` → `{is_owner, user: {input_tokens, output_tokens, cost_usd}}` — owner payload also includes `per_user[]`, `system`, `embeddings`.
- `POST /api/summary_prompt` `{prompt}` — owner-only (non-owners get 403 `not_owner`). Saves a custom system prompt for post summarization. `null`/missing/empty/whitespace resets to the hardcoded default. Prompts longer than 4096 characters are rejected with 400 `prompt_too_long`. Returns `{ok, summary_prompt, summary_prompt_default}` where `summary_prompt` is `null` when no override is active. The custom prompt is stored in the `meta` table under `summary_prompt` and applied to every summarize backend (Anthropic, Ollama, remote processor) via the `SummarizeRequest.system_prompt` field.

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
`https://$MINIAPP_DOMAIN:8443` → `bot:8085`, with TLS certs auto-fetched/renewed
from Let's Encrypt. Caddyfile at the repo root is `{$MINIAPP_DOMAIN}:8443 {
reverse_proxy bot:8085 }`; the domain comes from `data/.env` via
`env_file`. Required env vars: `MINIAPP_DOMAIN` (used by Caddy) and
`MINIAPP_URL=https://<same-domain>:8443` (used by the bot for the WebApp
button). Caddy listens on host ports 80 (ACME HTTP-01) and 8443 (HTTPS).
We use 8443 instead of 443 because the deployment host has MTProto VPN
already on 443; Telegram Mini Apps accept non-443 HTTPS URLs. The Caddy
service mounts named volumes `caddy_data` (cert storage) and
`caddy_config`. We chose Caddy over Cloudflare's quick tunnel because
Russian mobile carriers DPI-block `*.trycloudflare.com` while Telegram's
in-app WebView inherits the app's bypass-tunnel routing — a plain VPS IP
behind a regular domain bypasses both issues.
