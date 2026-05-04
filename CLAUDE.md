
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
  `sentence-transformers/intfloat/multilingual-e5-small`, 384 dims, ONNX,
  no PyTorch). Provider chosen via `EMBEDDING_PROVIDER`.
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
LOCAL_EMBEDDING_MODEL=...  # optional, fastembed model name; default intfloat/multilingual-e5-small
DEDUP_THRESHOLD=0.85       # optional, cosine threshold for "same story"
DEDUP_WINDOW_HOURS=48      # optional, lookback window for dedup
```

## Behaviour rules

- **Channel list** = admin's currently-subscribed public channels, minus the admin's
  blacklist. Bot users pick from that list.
- **Trigger:** new top-level posts only. Albums coalesce into one summary. Edits ignored.
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
  `deny:<id>`). Only `approved` users can use `/list`, `/usage`, the per-channel
  filter buttons, and the pending-filter text capture. The owner is auto-approved
  on startup.
- **Storage:**
  - `channels(id, title, blacklisted)`
  - `subscriptions(user_id, channel_id, mode, filter_prompt)` —
    `mode IN ('off','filtered','debug','all')`. `'off'` rows are kept (instead
    of being deleted on toggle-off) so the per-channel `filter_prompt` survives
    a temporary disable. `'debug'` delivers every post but prefixes a localized
    marker (i18n key `debug_filtered_marker`, e.g. `🐞 FILTERED`) on posts the
    filter would have excluded; with no `filter_prompt` it behaves like `'all'`.
  - `seen(channel_id, message_id)` — restart catch-up dedupe
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
  - `/start` — for new users, requests admin approval (see Access gate). For approved
    users, greet + point at `/list`. For pending/denied, the appropriate notice.
  - `/list` — inline keyboard. Each channel row has three buttons (last one
    conditional): the toggle button (`toggle:<channel_id>`), an ✏️ edit button
    (`fedit:<channel_id>`), and a 🗑 delete button (`fdel:<channel_id>`, only
    rendered when a `filter_prompt` exists for that user/channel). The toggle
    cycles `⬜ off/None → 🔀 filtered → 🐞 debug → ✅ all → 🗑-preserved 'off'
    (if a filter_prompt exists) or row-deleted None (if not)`. `🔀 filtered`
    runs the per-channel filter prompt via `summarizer.is_relevant`; if no
    prompt is set for that channel, every post passes (same as `✅ all`). `🐞
    debug` always delivers, but posts the filter would have rejected get a
    localized `🐞 FILTERED` line prepended to the body (filter tokens are still
    charged). A `Done` button (callback `done`) closes the keyboard. No
    pagination.
  - **Filter edit flow:** tapping ✏️ DMs the user the current prompt (if any)
    plus tips and sets `context.user_data['awaiting_filter_for'] = channel_id`.
    The next non-command text message from that user is captured by
    `on_filter_text` and stored as the filter for that channel. If the channel
    was previously `off` or had no row, mode is bumped to `filtered` so the new
    filter takes effect immediately; if it was already `filtered`/`all`, mode is
    left alone. Tapping 🗑 nulls the prompt without changing mode.
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
- **Deduplication:** after summarising, the summary text is embedded once
  and compared against this user's recent `delivered` rows (last
  `DEDUP_WINDOW_HOURS`). Cosine ≥ `DEDUP_THRESHOLD` counts as a duplicate.
  - **Provider** is `EMBEDDING_PROVIDER`: `auto` (default — `openai` if
    `OPENAI_API_KEY` set, else `none`), `openai`
    (`text-embedding-3-small` @ 512 dims, paid), `local` (fastembed on CPU,
    default `intfloat/multilingual-e5-small` @ 384 dims, no API cost,
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
│   └── main.py          # wires client + bot in one asyncio loop
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
