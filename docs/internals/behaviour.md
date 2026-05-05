# Behaviour rules

See also: [storage.md](storage.md), [dedup.md](dedup.md),
[auto-delete.md](auto-delete.md).

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
- **Session security:** `.session` is `chmod 600` + git-ignored. Encrypted-at-rest is a
  later TODO.
