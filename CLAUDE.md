
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
OWNER_ID=...               # admin's Telegram user id (numeric)
LOG_LEVEL=INFO             # optional, default INFO
```

## Behaviour rules

- **Channel list** = admin's currently-subscribed public channels, minus the admin's
  blacklist. Bot users pick from that list.
- **Trigger:** new top-level posts only. Albums coalesce into one summary. Edits ignored.
- **Skip rule:** posts with no text and no caption (image/video-only) are skipped — no
  summary, no DM.
- **Summary:** 1–2 sentences in the *source-post* language (do not translate).
- **Access gate:** new users hit `/start` and land in `users.status='pending'`; the
  bot DMs the owner an Allow/Deny inline keyboard (callbacks `approve:<id>` /
  `deny:<id>`). Only `approved` users can use `/list`, `/filter`, `/usage`. The owner
  is auto-approved on startup.
- **Storage:**
  - `channels(id, title, blacklisted)`
  - `subscriptions(user_id, channel_id, mode)` — `mode IN ('filtered','all')`
  - `seen(channel_id, message_id)` — restart catch-up dedupe
  - `users(user_id, status, username, first_name, filter_prompt, language)` —
    `status IN ('pending','approved','denied')`, `language IN ('en','ru')`
  - `usage(user_id, input_tokens, output_tokens)` — per-user delivered-summary tokens
  - `system_usage(id=1, input_tokens, output_tokens)` — total API spend (incl. filter checks)
- **Localization:** bot UI is per-user English / Russian. Default `en`. Strings live in
  `informer_bot/i18n.py` (`_STRINGS[lang][key]`, `t(lang, key, **fmt)` helper); the
  user's choice is persisted in `users.language`. Summaries are NOT translated — they
  stay in the source-post language (rule above).
- **Bot UX:**
  - `/start` — for new users, requests admin approval (see Access gate). For approved
    users, greet + point at `/list`. For pending/denied, the appropriate notice.
  - `/list` — inline keyboard, three-mode cycle on each row: `⬜ off → 🔀 filtered → ✅ all`,
    callback `toggle:<channel_id>`. `🔀 filtered` runs the user's `/filter` prompt
    against each post via `summarizer.is_relevant`; `✅ all` delivers every post. A
    `Done` button (callback `done`) closes the keyboard. No pagination.
  - `/filter <text>` — set personal content filter (used in `🔀` mode). `/filter` alone
    shows the current filter; `/filter clear` removes it.
  - `/usage` — show your input/output token totals + estimated USD cost. Owner sees
    a per-user breakdown plus the system total (actual API spend, including filter checks).
  - `/language` — inline keyboard `[English] [Русский]`, callback `lang:<code>`.
  - `/help` — list available commands. Owner sees an extra admin section.
  - `/blacklist` (owner only) — inline keyboard of all channels incl. blacklisted,
    tap to toggle blacklist, callback `bl:<channel_id>`. `Done` button (callback
    `bl_done`) closes the keyboard. Non-owners get "not allowed".
  - `/update` (owner only) — refresh the channel list from the admin's Telegram
    subscriptions on demand. Non-owners get "not allowed".
- **Channel-list refresh:** triggered manually by the admin via `/update` (also runs
  once at startup). Calls Telethon to fetch the admin's current subscriptions and
  `db.upsert_channel`s them. When a previously-active channel disappears (admin
  unsubscribed) or becomes blacklisted, the bot DMs each affected subscriber:
  "Channel '<title>' is no longer available."
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
│   ├── summarizer.py    # claude api call → summarize() + is_relevant() + cost estimate
│   ├── client.py        # telethon: list channels, NewMessage handler
│   ├── album.py         # buffer-and-flush coalescer for multi-photo albums
│   ├── pipeline.py      # handle_new_post + refresh_channels glue
│   ├── bot.py           # ptb handlers: commands, inline keyboards, callbacks
│   └── main.py          # wires client + bot in one asyncio loop
├── login.py             # one-time interactive: phone + code → .session
└── tests/
    ├── test_db.py
    ├── test_summarizer.py
    ├── test_bot_handlers.py
    ├── test_album.py
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
