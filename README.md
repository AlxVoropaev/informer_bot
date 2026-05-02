# Informer Bot

A Telegram bot that summarises posts from public channels and DMs you a short brief plus a link to the original.

## How it works

1. The admin subscribes their account to public channels.
2. You pick which of those channels you want to follow.
3. When a new post lands in a channel you follow, the bot DMs you a 1–2-sentence summary in the post's original language and a link to it.

## Commands

- `/start` — greet and point you at `/list`.
- `/list` — show the available channels. Tap a row to toggle:
  - ✅ — you're subscribed
  - ⬜ — not subscribed

That's it. No settings, no pagination, no spam — just toggle what you want and read the briefs as they arrive.

## What you'll receive

- One DM per new post, in the channel's language, with a link to the original.
- Albums (multi-photo posts) arrive as a single summary.
- Image- or video-only posts (no text/caption) are skipped.
- Edits to existing posts are ignored.

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
   - `OWNER_ID` — your numeric Telegram user ID (ask [@userinfobot](https://t.me/userinfobot)).

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

4. **Stop:**
   ```sh
   docker compose down
   ```

State (`.env`, `informer.db`, `informer.session`) all live in `./data/` on the host. Back that directory up if you care about your subscriptions and seen-message dedupe.

### Tests

```sh
uv run pytest
```
