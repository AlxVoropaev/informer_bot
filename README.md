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

3. **Configure `.env`**
   ```sh
   cp .env.example .env
   # then fill in the five values above
   ```

4. **Log in to your Telegram account once** (creates a `.session` file, chmod 600):
   ```sh
   uv run python login.py
   ```
   You'll be asked for your phone number and the code Telegram sends you.

5. **Run the bot**
   ```sh
   uv run python -m informer_bot.main
   ```

The process runs both the user-account client (reads channels) and the bot (talks to subscribers) in one asyncio loop. Keep it running — there's no built-in daemonisation.

### Tests

```sh
uv run pytest
```
