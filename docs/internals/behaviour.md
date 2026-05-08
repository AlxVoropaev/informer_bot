# Behaviour rules

See also: [storage.md](storage.md), [dedup.md](dedup.md),
[auto-delete.md](auto-delete.md).

- **Channel list** = union of (each approved provider's subscribed channels) − (each
  provider's personal blacklist), where the personal blacklist is provider-scoped
  (provider A blacklisting X does NOT hide X from bot users if provider B has X).
- **Trigger:** new top-level posts only. Albums coalesce into one summary. Edits ignored.
- **Source dedup:** live posts that arrive on multiple Telethon clients (because >1
  provider subscribes to the same channel) are claimed via a process-local in-flight
  set keyed by `(channel_id, message_id)` injected into each NewMessage handler — the
  first handler wins. The persistent `seen` table is still updated post-delivery so
  restart catch-up stays crash-safe.
- **Restart catch-up:** at startup, `client.catch_up` replays posts that
  arrived during downtime against the channel list already in the DB
  (`refresh_channels` is NOT called on startup — it would issue one
  `GetFullChannelRequest` per channel and trigger Telegram flood-wait; admin
  must run `/update` explicitly when their subscription list changes). For each
  channel that is currently visible (≥1 approved provider contributes it AND
  not every contributing provider has it blacklisted) and has at least one
  non-`off` subscriber, it queries Telethon
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
- **Providers:** any approved user can request to become a channel-contributing
  provider, either via the Telegram command `/become_provider` or via the Mini App
  "Request to be a provider" pill. Lifecycle: `pending` → `approved` (owner approves)
  → "active" (derived: a session file exists at `provider.session_path`). `denied`
  is terminal until manual reset. Each new request DMs the owner an Allow/Deny
  inline keyboard (callbacks `provider_approve:<id>` / `provider_deny:<id>`). After
  approval, the owner runs the CLI `uv run python -m informer_bot.cli_login --user-id
  <id>` to complete the interactive Telethon login (phone/code/2FA) and write
  `data/sessions/<user_id>.session` (mode 0o600; parent dir 0o700). The owner's own
  session stays at `data/informer.session` and is migrated as-is into the providers
  table at first run. Revocation is `/revoke_provider <user_id>` (owner only): hard
  remove — deletes the `providers` row (cascades `channel_blacklist` and
  `provider_channels`), unlinks the session file best-effort, then runs
  `prune_orphan_channels` to drop any channel that no longer has a contributing
  provider and DMs affected subscribers `channel_gone`.
- **Localization:** bot UI is per-user English / Russian. Default `en`. Strings live in
  `informer_bot/i18n.py` (`_STRINGS[lang][key]`, `t(lang, key, **fmt)` helper); the
  user's choice is persisted in `users.language`. Summaries are NOT translated — they
  stay in the source-post language (rule above).
- **Bot UX:**
  - `/start` — for new users, requests admin approval (see Access gate). For
    approved users, greets and points at the Mini App. For pending/denied, the
    appropriate notice.
  - `/help` — text-only listing of available commands. Tells users to open the
    Mini App for channel/filter/language management; mentions `/become_provider`
    for users who want to contribute channels. Owner sees an extra admin section
    listing `/update` and `/revoke_provider`.
  - `/usage` — show your input/output token totals + estimated USD cost,
    broken down per provider (`anthropic`, `remote`, etc.) plus a total.
    Costs are looked up per-provider via `summarizer.estimate_cost_usd`, so
    free local providers (Ollama, remote) read $0 while any fallback to
    Claude/OpenAI keeps its real price. Owner sees a per-user, per-provider
    breakdown plus the system total (actual API spend, including filter
    checks). Available both as a Telegram command and inside the Mini App
    (`GET /api/usage`, top-bar 📊 button).
  - `/app` — replies with an inline `🪟 Open Mini App` button
    (`web_app=WebAppInfo(MINIAPP_URL)`). Replies with `miniapp_unconfigured` if
    `MINIAPP_URL` is unset. Approved users only.
  - `/become_provider` — any approved user requests provider role. Status routes
    to `provider_owner_already` / `provider_already_pending` /
    `provider_already_approved` / `provider_request_denied`; a fresh request DMs
    the owner an Allow/Deny inline keyboard
    (`provider_approve:<id>` / `provider_deny:<id>`). Mirrors the Mini App
    "Request to be a provider" pill.
  - `/revoke_provider <user_id>` (owner only) — hard-remove a provider; deletes
    the `providers` row (cascades `channel_blacklist` and `provider_channels`),
    unlinks the session file, and prunes any orphan channels.
  - `/update` (owner only) — refresh the channel list. Iterates every approved
    provider sequentially with a 2 s inter-provider sleep to cap amplified
    flood-wait risk. Non-owners get "not allowed".
  - **Channel/filter/language management** lives entirely in the Mini App. The
    list view shows mode emoji + title; tapping a row opens details with mode
    radio buttons (off/filtered/debug/all), a filter prompt textarea (save /
    clear), and an `🔗 Open in Telegram` link. Setting a filter from `off`
    auto-bumps the row to `filtered` (mirrors the previous Telegram-side rule).
    Language switcher and 📊 usage live in the top bar. Approved providers also
    see their personal blacklist toggle in the channel detail view; ⛔ marks
    blacklisted rows in the list.
- **Channel-list refresh:** triggered manually by the admin via `/update`
  (NOT run at startup — see catch-up note above). Iterates every approved
  provider sequentially with a 2 s inter-provider sleep to cap amplified
  flood-wait risk. For each provider, calls Telethon to fetch their current
  dialogs — for each channel, also issues `GetFullChannelRequest` to pull the
  `about` description — `db.upsert_channel`s them with `(id, title, username,
  about)`, and replaces that provider's row set in `provider_channels`. After
  all providers have been refreshed, channels with no remaining contributing
  provider are deleted via `prune_orphan_channels` and each affected subscriber
  is DM'd `channel_gone` ("Channel '<title>' is no longer available."). When a
  brand-new channel id (not previously in `channels`) appears, every `approved`
  user is DM'd a localized `channel_new` notice with a single `🪟 Open in Mini
  App` web-app button that deep-links to `MINIAPP_URL?channel=<id>` — the Mini
  App auto-opens that channel's details view so the user picks a mode there.
  The button is omitted when `MINIAPP_URL` is unset. First-run guard: if
  `channels` was empty before the refresh, no announcements are sent.
- **Session security:** session files are `chmod 600` + git-ignored
  (`data/informer.session` for the owner; `data/sessions/<user_id>.session` —
  parent dir `chmod 700` — for additional providers). Encrypted-at-rest is a
  later TODO.
