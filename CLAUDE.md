
<!-- From https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md -->


# Informer bot


## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Worktree for Subagents Only

**Run code-changing subagents in an isolated git worktree. The main session
edits the working tree directly — no worktree needed.**

When spawning subagents via the Agent tool that will write or edit files, always
pass `isolation: "worktree"`. Read-only research/exploration agents don't need it.

## 5. Keep Docs Current

**After making changes, update CLAUDE.md or README.md if appropriate.**

If your changes affect anything documented in either file — stack, layout,
behaviour rules, required env vars, setup/run instructions, TODOs — update the
relevant section in the same change. CLAUDE.md = guidance for Claude;
README.md = user-facing setup and usage. If nothing documented is affected,
leave both alone.

## 6. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# Project context for development

## What this is

Telegram news aggregator. A Telethon **user-account client** (the admin's account) reads
posts from public channels the admin is subscribed to. A python-telegram-bot **bot**
exposes those channels to bot users; when a bot user has a channel enabled and a new
post lands, Claude summarises it and the bot DMs the user a 1–2-sentence brief plus a
link to the original.

One Python process runs both the client and the bot inside a single asyncio loop.

## Roles

- **Admin** (single, hard-coded `OWNER_ID`): owns the user-account session, owns the
  source-of-truth channel list, can blacklist channels.
- **Bot users** (many): subscribe via the bot, toggle channels on/off from the admin's
  (post-blacklist) list, receive DMs.

## Stack

- Python 3.12, managed with `uv` (`pyproject.toml`, `uv sync`, `uv run`).
- Telegram client: **Telethon** (MTProto user account, real-time `events.NewMessage`).
- Telegram bot: **python-telegram-bot** (v21+, asyncio).
- LLM: **anthropic** SDK, model `claude-haiku-4-5` (cheap & fast for summaries).
- Embeddings (dedup): pluggable. **OpenAI** `text-embedding-3-small` @ 512 dims
  (paid) or **fastembed** local CPU model (default
  `intfloat/multilingual-e5-large`, 1024 dims, ONNX, no PyTorch). Provider
  chosen via `EMBEDDING_PROVIDER`.
- Storage: **SQLite** (single file, `data/informer.db`) + Telethon
  `data/informer.session` file. The `data/` directory holds all mutable state
  and is bind-mounted into the Docker container.
- Config: **`.env`** (lives in `data/.env`) loaded via `python-dotenv`. Never
  commit `.env` or `*.session`.
- Container: **Dockerfile** + **compose.yaml** (`compose.yaml` not the legacy
  `docker-compose.yml`). Image is built as a non-root user matching host
  `HOST_UID`/`HOST_GID` so files written to `./data/` stay owned by you.
- Tests: **pytest** + **pytest-asyncio**. TDD — failing test before code.

## Required env vars (`data/.env`)

```
TELEGRAM_API_ID=...        # from my.telegram.org
TELEGRAM_API_HASH=...      # from my.telegram.org
TELEGRAM_BOT_TOKEN=...     # from @BotFather
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...         # optional — only consulted when EMBEDDING_PROVIDER picks openai
OWNER_ID=...               # admin's Telegram user id (numeric)
LOG_LEVEL=INFO             # optional, default INFO
EMBEDDING_PROVIDER=auto    # optional: auto|openai|local|none (auto picks openai if key set, else none)
LOCAL_EMBEDDING_MODEL=...  # optional, fastembed model name; default intfloat/multilingual-e5-large
DEDUP_THRESHOLD=0.85       # optional, cosine threshold for "same story"
DEDUP_WINDOW_HOURS=48      # optional, lookback window for dedup
CATCH_UP_WINDOW_HOURS=48   # optional, max age for restart catch-up replay
MINIAPP_URL=               # optional, public HTTPS URL of the Mini App; enables /app, the burger-menu launcher, and the in-process aiohttp server
WEBAPP_HOST=0.0.0.0        # optional, bind host for the Mini App server (default 0.0.0.0)
WEBAPP_PORT=8085           # optional, bind port for the Mini App server (default 8085)
```

## Mini App (primary user surface)

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

Endpoints:
- `GET /api/state` → `{user_id, language, is_owner, channels: [...]}`
- `POST /api/subscription` `{channel_id, mode}` (`mode` ∈ `off|filtered|debug|all|unsubscribe`)
- `POST /api/filter` `{channel_id, filter_prompt}` (null/empty clears)
- `POST /api/language` `{language}`
- `GET /api/usage` → `{is_owner, user: {input_tokens, output_tokens, cost_usd}}` — owner payload also includes `per_user[]`, `system`, `embeddings`.

Deep-linking: the new-channel announcement DM (sent on `/update`) attaches a
`web_app=WebAppInfo(url=f"{MINIAPP_URL}?channel=<id>")` button. On open,
`webapp/app.js` reads `?channel=<id>` (and falls back to
`tg.initDataUnsafe.start_param` matching `^channel_(\d+)$`) and auto-opens
that channel's details view.

Subscription/filter behaviour mirrors the inline-keyboard handlers — setting a
filter on an `off`/no-row channel auto-bumps it to `filtered`, same as
`on_filter_text`. The frontend (`webapp/`) is vanilla HTML/CSS/JS using the
Telegram `--tg-theme-*` CSS variables for native theming. `/app` opens the
Mini App via `InlineKeyboardButton(web_app=WebAppInfo(url=MINIAPP_URL))` and
`main.py` also calls `set_chat_menu_button(MenuButtonWebApp(...))` so the
bot's burger menu launches it.

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

## Behaviour rules

- **Channel list** = admin's currently-subscribed public channels, minus the admin's
  blacklist. Bot users pick from that list.
- **Trigger:** new top-level posts only. Albums coalesce into one summary. Edits ignored.
- **Restart catch-up:** at startup, `client.catch_up` replays posts that
  arrived during downtime against the channel list already in the DB
  (`refresh_channels` is NOT called on startup — it would issue one
  `GetFullChannelRequest` per channel and trigger Telegram flood-wait; admin
  must run `/update` explicitly when their subscription list changes). For each channel with at least
  one non-`off` subscriber on a non-blacklisted row, it queries Telethon
  `iter_messages(min_id=MAX(seen.message_id), reverse=True)` and feeds each
  message through the same `AlbumBuffer` the live handler uses. Messages older
  than `CATCH_UP_WINDOW_HOURS` (default 48h) are dropped to bound API cost.
  Channels with no prior `seen` rows are skipped (no full-history backfill on
  first run for that channel).
- **Skip rule:** posts with no text and no caption (image/video-only) are skipped — no
  summary, no DM.
- **Summary:** one or two sentences in the *source-post* language (do not translate).
- **DM format:** the channel title is rendered as the only hyperlink (HTML
  `<a href="post_url">Title</a>`), followed by the summary on the
  next line. No separate URL line. If the source post has a photo (or for an
  album, the first photo), it is downloaded via Telethon and attached via
  `bot.send_photo` with the formatted text as the caption; otherwise
  `bot.send_message` is used.
- **Access gate:** new users hit `/start` and land in `users.status='pending'`; the
  bot DMs the owner an Allow/Deny inline keyboard (callbacks `approve:<id>` /
  `deny:<id>`). Only `approved` users can use `/usage`, `/app`, and any Mini App
  endpoint. The owner is auto-approved on startup.
- **Storage:**
  - `channels(id, title, blacklisted, username, about)` — `username` and
    `about` are populated during `refresh_channels` (admin-side Telethon
    `GetFullChannelRequest`). Used by the /list details view (ℹ️). Both fields
    are nullable; `upsert_channel` uses `COALESCE(excluded.x, channels.x)` so
    callers passing only `(id, title)` preserve any existing username/about.
  - `subscriptions(user_id, channel_id, mode, filter_prompt)` —
    `mode IN ('off','filtered','debug','all')`. `'off'` rows are kept (instead
    of being deleted on toggle-off) so the per-channel `filter_prompt` survives
    a temporary disable. `'debug'` delivers every post but prefixes a localized
    marker (i18n key `debug_filtered_marker`, e.g. `🐞 FILTERED`) on posts the
    filter would have excluded; with no `filter_prompt` it behaves like `'all'`.
  - `seen(channel_id, message_id)` — restart catch-up dedupe + resume point
    (`MAX(message_id)` per channel = where catch-up starts)
  - `users(user_id, status, username, first_name, language)` —
    `status IN ('pending','approved','denied')`, `language IN ('en','ru')`
  - `usage(user_id, input_tokens, output_tokens)` — per-user delivered-summary tokens
  - `system_usage(id=1, input_tokens, output_tokens)` — total API spend (incl. filter checks)
  - `post_embeddings(channel_id, message_id, created_at, embedding, summary, link)` —
    one row per post that reached at least one recipient. `embedding` is a
    little-endian packed `float32` array (`db.pack_vector`/`unpack_vector`).
    Indexed on `created_at`; pruned via `purge_dedup_older_than` at startup.
  - `delivered(user_id, channel_id, message_id, bot_message_id, is_photo, body,
    created_at, dup_links_json)` — per-user record of every DM that was actually
    sent (including debug-mode duplicate DMs). `body` is the original rendered
    HTML at send time (never mutated). `dup_links_json` is a JSON array of
    `[title, link]` tuples for duplicates that have been chained onto this DM
    via inline URL buttons.
  - `embedding_usage(id=1, tokens)` — running total of OpenAI embedding tokens.
- **Localization:** bot UI is per-user English / Russian. Default `en`. Strings live in
  `informer_bot/i18n.py` (`_STRINGS[lang][key]`, `t(lang, key, **fmt)` helper); the
  user's choice is persisted in `users.language`. Summaries are NOT translated — they
  stay in the source-post language (rule above).
- **Bot UX:**
  - `/start` — for new users, requests admin approval (see Access gate). For
    approved users, greets and points at the Mini App. For pending/denied, the
    appropriate notice.
  - `/help` — text-only listing of available commands. Tells users to open the
    Mini App for channel/filter/language management. Owner sees an extra admin
    section listing `/blacklist` and `/update`.
  - `/usage` — show your input/output token totals + estimated USD cost. Owner sees
    a per-user breakdown plus the system total (actual API spend, including filter checks).
    Available both as a Telegram command and inside the Mini App
    (`GET /api/usage`, top-bar 📊 button).
  - `/app` — replies with an inline `🪟 Open Mini App` button
    (`web_app=WebAppInfo(MINIAPP_URL)`). Replies with `miniapp_unconfigured` if
    `MINIAPP_URL` is unset. Approved users only.
  - `/blacklist` (owner only) — inline keyboard of all channels incl. blacklisted,
    tap to toggle blacklist, callback `bl:<channel_id>`. `Done` button (callback
    `bl_done`) closes the keyboard. 15-per-page pagination (nav callback
    `blpage:<n>`, page held in `context.user_data['bl_page']`, `noop` for the
    counter button). Non-owners get "not allowed".
  - `/update` (owner only) — refresh the channel list from the admin's Telegram
    subscriptions on demand. Non-owners get "not allowed".
  - **Channel/filter/language management** lives entirely in the Mini App. The
    list view shows mode emoji + title; tapping a row opens details with mode
    radio buttons (off/filtered/debug/all), a filter prompt textarea (save /
    clear), and an `🔗 Open in Telegram` link. Setting a filter from `off`
    auto-bumps the row to `filtered` (mirrors the previous Telegram-side rule).
    Language switcher and 📊 usage live in the top bar.
- **Channel-list refresh:** triggered manually by the admin via `/update`
  (NOT run at startup — see catch-up note above). Calls Telethon to fetch the
  admin's current subscriptions — for each channel, also issues
  `GetFullChannelRequest` to pull the `about` description — and
  `db.upsert_channel`s them with `(id, title, username, about)`. When a previously-active channel disappears (admin
  unsubscribed) or becomes blacklisted, the bot DMs each affected subscriber:
  "Channel '<title>' is no longer available." When a brand-new channel id
  (not previously in `channels`) appears, every `approved` user is DM'd a
  localized `channel_new` notice with a single `🪟 Open in Mini App` web-app
  button that deep-links to `MINIAPP_URL?channel=<id>` — the Mini App auto-opens
  that channel's details view so the user picks a mode there. The button is
  omitted when `MINIAPP_URL` is unset. First-run guard: if `channels` was empty
  before the refresh, no announcements are sent.
- **Deduplication:** after summarising, the summary text is embedded once
  and compared against this user's recent `delivered` rows (last
  `DEDUP_WINDOW_HOURS`). Cosine ≥ `DEDUP_THRESHOLD` counts as a duplicate.
  - **Provider** is `EMBEDDING_PROVIDER`: `auto` (default — `openai` if
    `OPENAI_API_KEY` set, else `none`), `openai`
    (`text-embedding-3-small` @ 512 dims, paid), `local` (fastembed on CPU,
    default `intfloat/multilingual-e5-large` @ 1024 dims, no API cost,
    timed in logs as `local embed: ... ms`), or `none` (disabled).
  - **Model-switch purge:** the active provider+model+dims is stored in
    `meta.embedding_id`. On startup, if it differs from the previous run,
    `delivered` and `post_embeddings` are wiped (vectors aren't comparable
    across spaces). Switching freely is fine — you just lose dedup history.
  - **`none` (or `auto` with no key):** `main.py` passes `embed_fn=None` /
    `edit_dm=None`. `handle_new_post` then skips embedding, dedup lookup,
    `delivered` records, and `post_embeddings` writes — DMs go out as if dedup
    didn't exist. The owner is DM'd `dedup_disabled_notice` once at startup
    (no recurring nag).
  - **Normal modes (`filtered`, `all`):** the previous DM gets a new inline URL
    button (one button row per duplicate, button text = source channel title)
    via `bot.edit_message_reply_markup`. The DM body is never mutated — this
    sidesteps Telegram's 1024-char caption / 4096-char text limits. The new
    post is NOT inserted into `delivered` for this user — future duplicates
    keep chaining onto the original DM via `delivered.dup_links_json`. The post
    IS inserted into `post_embeddings` so other users can still match against
    it.
  - **Debug mode:** a fresh DM is sent with a localized `🔁 DUPLICATE` marker
    prefix (i18n key `debug_duplicate_marker`), and `delivered` is recorded
    normally. The "Also:" edit path is not taken.
  - Embedding tokens are tracked in `embedding_usage` and surfaced in `/usage`
    for the owner only.
- **Session security:** `.session` is `chmod 600` + git-ignored. Encrypted-at-rest is a
  later TODO.

## Layout

```
informer_bot/
├── pyproject.toml
├── Dockerfile
├── compose.yaml
├── .gitignore
├── data/                # bind-mounted runtime state (gitignored)
│   ├── .env.example     # template — copy to data/.env and fill in
│   ├── .env             # secrets (gitignored)
│   ├── informer.db      # sqlite (created on first run)
│   └── informer.session # telethon session (created by login.py, chmod 600)
├── informer_bot/
│   ├── config.py        # loads .env, exposes typed settings
│   ├── db.py            # sqlite schema + queries (sync, single-file)
│   ├── i18n.py          # EN/RU UI strings + t() helper
│   ├── summarizer.py    # claude summarize/is_relevant + openai embed_summary + cost estimates
│   ├── dedup.py         # cosine similarity + find_duplicate(per-user, time-windowed)
│   ├── client.py        # telethon: list channels, NewMessage handler
│   ├── album.py         # buffer-and-flush coalescer for multi-photo albums
│   ├── pipeline.py      # handle_new_post + refresh_channels glue
│   ├── bot.py           # ptb handlers: commands, inline keyboards, callbacks
│   ├── webapp.py        # aiohttp server for the Mini App (initData verify + JSON API)
│   └── main.py          # wires client + bot in one asyncio loop
├── webapp/              # Mini App static SPA (served by webapp.py when MINIAPP_URL set)
│   ├── index.html
│   ├── style.css        # uses --tg-theme-* CSS vars for native look
│   └── app.js           # talks to /api/* with X-Telegram-Init-Data header
├── login.py             # one-time interactive: phone + code → .session
└── tests/
    ├── test_db.py
    ├── test_summarizer.py
    ├── test_bot_handlers.py
    ├── test_album.py
    ├── test_dedup.py
    └── test_pipeline.py
```

## TDD order

1. `db.py` — pure SQLite, easiest. Write failing test → implement → green.
2. `summarizer.py` — anthropic SDK call mocked in tests.
3. `bot.py` handlers — ptb's `Application` + a fake `Update`/`Context`.
4. `client.py` — thin Telethon wrapper, smoke-tested with mocked `TelegramClient`.
5. `main.py` — wiring; verified manually (UI behaviour can't be unit-tested).

## Open TODOs (non-blocking)

- Session-file encryption (sops/age) — currently `chmod 600` only.
- Rate / cost guardrails on the summariser — none in v1.
- Deployment beyond local — none in v1.
- **Context7 MCP** is referenced in workflow but not yet configured; using `WebFetch`
  against official docs in the meantime.
