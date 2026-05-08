# Features

A complete list of what the bot can do today, complementing the short overview in the [README](../README.md).

## Delivery

- Each new post arrives as a single DM with a one-sentence summary in the post's original language.
- The channel name in every DM is a clickable link back to the original post.
- Posts with photos arrive with the photo attached; albums collapse into one DM showing the first photo.
- Posts that contain only an image or video, with no text or caption, are skipped.
- Edits made to already-delivered posts are ignored.
- After downtime, the bot replays missed posts on startup, capped to the last 48 hours per channel.

## Per-channel modes

- ⬜ **Off** — the channel is paused while its saved filter is kept for later.
- 🔀 **Filtered** — only posts matching the channel's natural-language filter are delivered.
- 🐞 **Debug** — every post is delivered, and ones the filter would have rejected are tagged `🐞 FILTERED`.
- ✅ **All** — every post from the channel arrives without filtering.

## Filters

- Each channel has its own filter written in plain natural language, and an AI checks every post against it.
- Filters survive switching the channel off, so re-enabling the channel restores them automatically.
- Saving a filter while the channel is in Off mode flips it into Filtered mode for you.

## Deduplication

- Posts telling the same story across different channels within ~48 hours are detected as duplicates.
- A duplicate is merged into the original DM as an extra inline link button instead of a second message.
- A user-level "duplicate debug" toggle delivers duplicates as fresh DMs prefixed with `🔁 DUPLICATE`.
- The dedup time window and similarity threshold are configurable, and dedup can be disabled entirely.

## Auto-delete

- Each user can set a window between 1 and 720 hours after which delivered DMs are auto-deleted.
- Every DM carries a 💾 **Save** button that exempts it from auto-deletion, and tapping it again re-arms the timer.
- When a duplicate is chained onto an earlier DM, the delete timer is extended unless the original was saved.

## Mini App (in-Telegram UI)

- A channel list lets you subscribe and pick a delivery mode in one tap.
- A per-channel filter editor accepts plain-text input.
- An interface language switcher (English / Русский) is available, while summaries always stay in the source language.
- A usage dashboard shows your token consumption and estimated cost broken down by provider.
- A 🔗 link opens the source channel directly in Telegram.
- Deep links from notification DMs jump straight to the relevant channel's settings.

## Access control

- New users request access with `/start` and wait for the admin's inline Allow / Deny decision.
- The admin can blacklist channels they're subscribed to but don't want exposed to bot users.
- When a channel disappears because the admin unsubscribed or blacklisted it, affected users get a one-time "no longer available" DM.
- When the admin adds a new channel, every approved user gets a DM with a button that jumps to that channel in the Mini App.

## Commands

- `/start` — request access or view your current status.
- `/app` — open the Mini App.
- `/usage` — show your token usage and cost estimate.
- `/help` — list available commands.
- Admin: `/update` refreshes the channel list from Telegram subscriptions, and `/blacklist` toggles channel visibility.

## AI providers

- Summarization works with Anthropic Claude, OpenAI, or a local Ollama instance, picked per environment.
- The embedding provider used for deduplication is independently configurable (OpenAI, Ollama, remote processor, or off).
- An optional sidecar **processor bot** runs on a private GPU host and serves summarization and embeddings over a private Telegram bus group, with automatic fallback to Claude or OpenAI if it goes offline.
- The admin gets DM notifications when the processor goes unreachable or recovers.
- The admin can override the default summarization prompt with a custom one.

## Cost tracking

- Per-user token counters (input plus output) are tracked separately for each provider.
- USD cost estimates are shown in the Mini App and via `/usage`.
- Embedding token usage is counted separately from summarization.
