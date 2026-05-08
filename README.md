# Informer Bot

A Telegram bot that summarises posts from public channels and DMs you a short
brief plus a link to the original.

🇷🇺 [Русская версия](README_RU.md)

## How it works

1. One or more **providers** (the admin is provider #1; other Telegram users can request to become providers and the admin approves) subscribe their accounts to public channels.
2. You pick which of those channels — the union of every approved provider's subscriptions, minus each provider's personal blacklist — you want to follow.
3. When a new post lands in a channel you follow, the bot DMs you a one-sentence summary in the post's original language. The channel's name is shown as a clickable link to the original post, and if the post had a photo (or for albums, the first photo) it's attached.

## Commands

Channel selection, filters, and language all live in the **Mini App** —
Telegram's in-app HTML surface. Open it from the bot's burger menu (≡, left of
the input box) or run `/app`. Every Telegram client (mobile, desktop, web)
supports Mini Apps, so use it for everything below.

In the Mini App you can:
- Tap a channel to open its details and pick a delivery mode:
  - ⬜ Off — saved filter is preserved
  - 🔀 Filtered — only posts matching this channel's filter
  - 🐞 Debug — every post; ones the filter would have rejected are tagged `🐞 FILTERED`
  - ✅ All — every post
- Set a per-channel filter (plain language) in the textarea. Saving a filter
  from Off auto-bumps the channel to Filtered.
- Switch interface language (English / Русский) and view your usage from the
  top bar (📊 button).
- Open the source channel in Telegram via the 🔗 link.

Telegram commands (small surface — everything else is in the Mini App):

- `/start` — request access. New users wait for the admin to approve.
- `/app` — replies with a button that opens the Mini App.
- `/usage` — your token usage and estimated cost (also in the Mini App).
- `/become_provider` — ask the admin to let you contribute channels from your own Telegram account. Same as the "Request to be a provider" pill in the Mini App. Approved providers can hide individual channels via the Mini App's per-channel blacklist toggle.
- `/help` — list available commands.

### Admin commands

If you're the bot's `OWNER_ID`, you also get:

- `/update` — refresh the channel list from every approved provider's Telegram subscriptions (run after a provider subscribes to or leaves a channel).
- `/revoke_provider <user_id>` — remove a provider; their session file and per-provider data are deleted, and any channel that no longer has a contributing provider is dropped.
- New `/start` requests come to you as an inline Allow / Deny prompt; new `/become_provider` requests come the same way.

## What you'll receive

- One DM per new post, in the channel's language. The channel name is the link back to the original; the photo (if any) is attached.
- Albums (multi-photo posts) arrive as a single summary with the album's first photo.
- Image- or video-only posts (no text/caption) are skipped.
- Edits to existing posts are ignored.
- **Restart catch-up.** If the bot was offline for a while, on startup it replays posts that arrived during the downtime (per channel, capped to the last 48h via `CATCH_UP_WINDOW_HOURS`). Channels you've never received anything from yet aren't backfilled.
- **Duplicates merge.** If the same story shows up in another channel within ~48 hours, the bot adds a new inline URL button (labeled with the source channel) under your original DM instead of sending a second one. In 🐞 debug mode, you instead get a fresh DM prefixed with `🔁 DUPLICATE` so you can see what was deduped.

## Notes

- If a channel disappears from the Mini App, every contributing provider has either unsubscribed from it or blacklisted it. You'll get a one-time DM saying it's no longer available.
- When a provider adds a new channel, you'll get a DM with a button that opens the Mini App straight to that channel's details — pick a mode there.
- Only approved providers can add channels to the list. Anyone can apply via `/become_provider`; the admin decides.

## Documentation

**For users**

- [Full feature list](docs/features.md) — every supported feature in one place.

**For self-hosters**

- [Self-hosting setup](docs/setup.md) — install, configure `.env`, log in, run.
- [Run with Docker Compose](docs/docker.md) — production deployment.
- [Mini App URL & hosting](docs/miniapp-hosting.md) — `MINIAPP_URL`, Caddy + Let's Encrypt, alternatives.
- [Embedding provider (deduplication)](docs/embeddings.md) — OpenAI vs local Ollama vs disabled.
- [Processor bot for private GPU hosts](docs/processor-bot.md) — sidecar bot that runs Ollama on a private GPU server, talks to informer over a Telegram bus group.
- [Auto-update from GitHub](docs/auto-update.md) — pull-based cron deploy.
- [Tests](docs/tests.md) — running the test suite.

**For contributors**

- [Internal architecture & dev notes](docs/internals/architecture.md) — start here, then follow the links inside.
