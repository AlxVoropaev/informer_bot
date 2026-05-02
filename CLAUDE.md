
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

## 4. Always Use a Worktree

**Run code-changing subagents in an isolated git worktree.**

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
- Storage: **SQLite** (single file, `informer.db`) + Telethon `.session` file.
- Config: **`.env`** loaded via `python-dotenv`. Never commit `.env` or `*.session`.
- Tests: **pytest** + **pytest-asyncio**. TDD — failing test before code.

## Required env vars (`.env`)

```
TELEGRAM_API_ID=...        # from my.telegram.org
TELEGRAM_API_HASH=...      # from my.telegram.org
TELEGRAM_BOT_TOKEN=...     # from @BotFather
ANTHROPIC_API_KEY=...
OWNER_ID=...               # admin's Telegram user id (numeric)
```

## Behaviour rules

- **Channel list** = admin's currently-subscribed public channels, minus the admin's
  blacklist. Bot users pick from that list.
- **Trigger:** new top-level posts only. Albums coalesce into one summary. Edits ignored.
- **Skip rule:** posts with no text and no caption (image/video-only) are skipped — no
  summary, no DM.
- **Summary:** 1–2 sentences in the *source-post* language (do not translate).
- **Storage:** `channels(id, title, blacklisted)`, `subscriptions(user_id, channel_id)`,
  `seen(channel_id, msg_id)` for restart catch-up dedupe.
- **Bot UX:**
  - `/start` — greet + point at `/list`.
  - `/list` — inline keyboard, `✅/⬜ Title`, callback `toggle:<channel_id>`. No pagination.
  - `/blacklist` (owner only) — inline keyboard of all channels incl. blacklisted,
    tap to toggle blacklist, callback `bl:<channel_id>`. Non-owners get "not allowed".
- **Channel-list refresh:** background task every 10 min calls Telethon to fetch the
  admin's current subscriptions and `db.upsert_channel`s them. When a previously-active
  channel disappears (admin unsubscribed) or becomes blacklisted, the bot DMs each
  affected subscriber: "Channel '<title>' is no longer available."
- **Session security:** `.session` is `chmod 600` + git-ignored. Encrypted-at-rest is a
  later TODO.

## Layout (target)

```
informer_bot/
├── pyproject.toml
├── .env.example
├── .gitignore
├── informer_bot/
│   ├── config.py        # loads .env, exposes typed settings
│   ├── db.py            # sqlite schema + queries (sync, single-file)
│   ├── summarizer.py    # claude api call → str
│   ├── client.py        # telethon: list channels, NewMessage handler
│   ├── bot.py           # ptb handlers: /start, /list, inline toggle keyboard
│   └── main.py          # wires client + bot in one asyncio loop
├── login.py             # one-time interactive: phone + code → .session
└── tests/
    ├── test_db.py
    ├── test_summarizer.py
    ├── test_bot_handlers.py
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
