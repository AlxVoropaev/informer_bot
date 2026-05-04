# Informer Bot

A Telegram bot that summarises posts from public channels and DMs you a short brief plus a link to the original.

## How it works

1. The admin subscribes their account to public channels.
2. You pick which of those channels you want to follow.
3. When a new post lands in a channel you follow, the bot DMs you a one-sentence summary in the post's original language. The channel's name is shown as a clickable link to the original post, and if the post had a photo (or for albums, the first photo) it's attached.

## Commands

- `/start` — request access. New users wait for the admin to approve; once approved you're pointed at `/list`.
- `/list` — show the available channels. Each channel has a full-width title button and an icon row below it: ℹ️ info, 🔗 open in Telegram (only for public channels with a username), ✏️ edit filter (plus 🗑 when a filter is set). Tap the channel name to cycle delivery modes:
  - ⬜ — off (you don't get posts from this channel; saved filter is preserved)
  - 🔀 — filtered (only posts matching this channel's filter are delivered)
  - 🐞 — debug (every post is delivered, but ones the filter would have rejected are prefixed with `🐞 FILTERED`)
  - ✅ — all (every post is delivered)
  Tap 🔗 to open the channel in Telegram for a quick look. Tap ℹ️ for the full details view: the channel's description (from the author), the same 🔗 open-in-Telegram button, plus toggle / edit-filter / delete-filter — `⬅ Back to list` returns to the same page.
  Tap ✏️ to set or update the filter prompt for that one channel — the bot asks you to send the prompt as your next message. Tap 🗑 to delete it. Filters are stored per channel; setting a filter from "off" automatically activates 🔀 for that channel.
- `/usage` — show your token usage and estimated cost.
- `/language` — switch interface language (English / Русский).
- `/help` — list all available commands.

That's it. No pagination, no spam — toggle what you want, optionally narrow it with a per-channel filter, and read the briefs as they arrive.

### Admin commands

If you're the bot's `OWNER_ID`, you also get:

- `/blacklist` — toggle channels on/off the public list (channels you've subscribed to but don't want to expose to bot users).
- `/update` — refresh the channel list from your Telegram subscriptions (run after subscribing to or leaving a channel).
- New `/start` requests come to you as an inline Allow / Deny prompt.

## What you'll receive

- One DM per new post, in the channel's language. The channel name is the link back to the original; the photo (if any) is attached.
- Albums (multi-photo posts) arrive as a single summary with the album's first photo.
- Image- or video-only posts (no text/caption) are skipped.
- Edits to existing posts are ignored.
- **Restart catch-up.** If the bot was offline for a while, on startup it replays posts that arrived during the downtime (per channel, capped to the last 48h via `CATCH_UP_WINDOW_HOURS`). Channels you've never received anything from yet aren't backfilled.
- **Duplicates merge.** If the same story shows up in another channel within ~48 hours, the bot adds a new inline URL button (labeled with the source channel) under your original DM instead of sending a second one. In 🐞 debug mode, you instead get a fresh DM prefixed with `🔁 DUPLICATE` so you can see what was deduped.

## Notes

- If a channel disappears from `/list`, the admin either unsubscribed from it or blacklisted it. You'll get a one-time DM saying it's no longer available.
- Only the admin can add or remove channels from the list — there's no way to request new ones through the bot.

## Setup (self-hosting)

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), and a Telegram account that's subscribed to the channels you want to track.

1. **Install dependencies**
   ```sh
   uv sync
   ```

2. **Get credentials**
   - `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` — from [my.telegram.org](https://my.telegram.org).
   - `TELEGRAM_BOT_TOKEN` — create a bot via [@BotFather](https://t.me/BotFather).
   - `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com).
   - `OPENAI_API_KEY` — *optional*, from [platform.openai.com](https://platform.openai.com). Used for summary embeddings (dedup); cost is negligible (~$0.02 per million tokens with `text-embedding-3-small`). If you leave it blank, the bot starts fine — deduplication is just disabled, and the owner gets a one-time DM at startup saying so.
   - `OWNER_ID` — your numeric Telegram user ID (ask [@userinfobot](https://t.me/userinfobot)).

#### Embedding provider (deduplication)

Optional, controls how summary embeddings for dedup are computed:

| Var | Values | Default | Notes |
| --- | --- | --- | --- |
| `EMBEDDING_PROVIDER` | `auto` \| `openai` \| `local` \| `none` | `auto` | `auto` picks `openai` if `OPENAI_API_KEY` is set, otherwise `none`. |
| `LOCAL_EMBEDDING_MODEL` | any [fastembed](https://github.com/qdrant/fastembed) model name | `intfloat/multilingual-e5-large` | Only used when provider is `local`. |
| `LOCAL_EMBEDDING_DEVICE` | `cpu` \| `cuda` | `cpu` | `cuda` requires installing `fastembed-gpu` instead of `fastembed`. |
| `DEDUP_THRESHOLD` | float 0..1 | `0.85` | Cosine similarity at or above which two posts count as the same story. |
| `DEDUP_WINDOW_HOURS` | int | `48` | How far back to look for duplicates per user. |
| `CATCH_UP_WINDOW_HOURS` | int | `48` | On restart, replay missed posts up to this age. Set to `0` if you don't want any backfill. |

- `openai` — `text-embedding-3-small` @ 512 dims, paid (~$0.02 / 1M tokens).
- `local` — runs the model via fastembed (ONNX, no PyTorch). Default model is
  `intfloat/multilingual-e5-large` (~2.2 GB on disk, 1024 dims, top-tier
  multilingual quality including Russian).
  - **CPU:** budget ~3 GB RAM at steady state. Tiny VPS hosts (≤1 GB RAM, no
    swap) will OOM-kill the process silently mid-load — if you see the bot
    looping after `local embedder: loading ...` with no error, fall back to
    `openai` or `none`. For a smaller-footprint CPU run, override
    `LOCAL_EMBEDDING_MODEL=intfloat/multilingual-e5-small` (~120 MB, 384 dims).
  - **GPU:** set `LOCAL_EMBEDDING_DEVICE=cuda` and swap the dependency from
    `fastembed` to `fastembed-gpu` (`uv add fastembed-gpu`). The container
    image needs CUDA available and the `nvidia` runtime configured.
  - The model cache is persisted under `data/fastembed_cache/` so it survives
    container restarts.
- `none` — disable dedup entirely; owner gets a one-time DM at startup.

Switching between providers (or between local model names) is safe — on the
next startup the bot detects the change and wipes the dedup index, since
embedding spaces aren't comparable across models.

3. **Configure `.env`** (lives in `data/` so it's bind-mounted into the container, not baked into the image)
   ```sh
   cp data/.env.example data/.env
   # then fill in the five values above
   ```

4. **Log in to your Telegram account once** (creates `data/informer.session`, chmod 600):
   ```sh
   uv run python login.py
   ```
   You'll be asked for your phone number and the code Telegram sends you.

5. **Run the bot**
   ```sh
   uv run python -m informer_bot.main
   ```

The process runs both the user-account client (reads channels) and the bot (talks to subscribers) in one asyncio loop. Keep it running — there's no built-in daemonisation.

### Run with Docker Compose

Requirements: Docker with the Compose plugin.

The image is built as a non-root user matching your host uid/gid, so files
written to `./data/` stay owned by you. Pass them at build time from the shell —
they are not stored in `.env`. Bash's `$UID` is a readonly built-in and cannot
be re-exported, so compose reads `HOST_UID` / `HOST_GID` instead:

```sh
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose build
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d
```

Tip: stick that prefix in a shell alias, or `export HOST_UID=$(id -u) HOST_GID=$(id -g)` once per shell.

1. Fill in `data/.env` (step 3 above).

2. **One-time Telethon login** — interactive, asks for your phone number and the code Telegram sends:
   ```sh
   docker compose run --rm bot uv run python login.py
   ```
   This creates `data/informer.session` on the host (the `./data` directory is bind-mounted into the container).

3. **Start the bot:**
   ```sh
   docker compose up -d
   docker compose logs -f bot
   ```

4. **Restart** (e.g. to pick up config or code changes):
   ```sh
   docker compose restart bot
   ```
   For an image rebuild after code changes:
   ```sh
   HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d --build
   ```

5. **Stop:**
   ```sh
   docker compose down
   ```

State (`.env`, `informer.db`, `informer.session`) all live in `./data/` on the host. Back that directory up if you care about your subscriptions and seen-message dedupe.

### Tests

```sh
uv run pytest
```
