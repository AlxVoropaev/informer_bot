# Storage schema

- `channels(id, title, username, about)` — `username` and `about` are populated
  during `refresh_channels` (per-provider Telethon `GetFullChannelRequest`).
  Used by the channel details view (ℹ️). Both fields are nullable;
  `upsert_channel` uses `COALESCE(excluded.x, channels.x)` so callers passing
  only `(id, title)` preserve any existing username/about. Per-provider
  blacklists live in `channel_blacklist`; the legacy global
  `channels.blacklisted` column was migrated into
  `channel_blacklist(OWNER_ID, channel_id)` and dropped (v11→v12).
- `providers(user_id, status, session_path, requested_at, approved_at)` —
  provider lifecycle. `status ∈ {pending, approved, denied}`. Owner is
  auto-seeded by the v11→v12 migration with `status='approved'` and
  `session_path='data/informer.session'`. `status='approved'` does NOT mean
  the session file exists; that's checked at runtime by the multi-session
  orchestrator (`provider_clients`).
- `channel_blacklist(provider_user_id, channel_id)` — per-provider blacklist.
  Composite PK; CASCADE on provider OR channel deletion.
- `provider_channels(provider_user_id, channel_id)` — which Telegram channels
  each provider's user-account currently subscribes to. Refreshed on every
  `/update`. Used by `list_visible_channels` (channel hidden iff every approved
  provider that contributes it has it blacklisted) and by orphan detection
  (`channels_with_no_provider`). Seeded for the owner from the existing
  `channels` table by the v12→v13 migration.
- `subscriptions(user_id, channel_id, mode, filter_prompt)` —
  `mode IN ('off','filtered','debug','all')` (mirrored in code by the
  `informer_bot.modes.SubscriptionMode` `StrEnum`). `'off'` rows are kept (instead
  of being deleted on toggle-off) so the per-channel `filter_prompt` survives
  a temporary disable. `'debug'` is the **filter-debug** mode: it delivers
  every post but prefixes a localized marker (i18n key
  `debug_filtered_marker`, e.g. `🐞 FILTERED`) on posts the filter would
  have excluded; with no `filter_prompt` it behaves like `'all'`. (Dedup
  debugging is a separate, user-level toggle — see `users.dedup_debug`.)
- `seen(channel_id, message_id)` — restart catch-up dedupe + resume point
  (`MAX(message_id)` per channel = where catch-up starts)
- `users(user_id, status, username, first_name, language, auto_delete_hours, dedup_debug)` —
  `status IN ('pending','approved','denied')`, `language IN ('en','ru')`,
  `auto_delete_hours` is the per-user auto-delete window (NULL = feature off),
  `dedup_debug` is a 0/1 user-level flag — when 1, duplicate-of-recent posts
  are delivered as a fresh DM tagged `🔁 DUPLICATE` with a `↳ Original: …`
  link instead of being silently chained as a button on the original DM.
- `usage(user_id, provider, input_tokens, output_tokens)` —
  per-user delivered-summary tokens, broken down by provider
  (`anthropic`, `openai`, `ollama`, `remote`, plus `unknown` for legacy
  pre-v11 rows). `(user_id, provider)` is the primary key.
- `system_usage(provider, input_tokens, output_tokens)` —
  total API spend (incl. filter checks), one row per provider.
- `post_embeddings(channel_id, message_id, created_at, embedding, summary, link)` —
  one row per post that reached at least one recipient. `embedding` is a
  little-endian packed `float32` array (`db.pack_vector`/`unpack_vector`).
  Indexed on `created_at`; pruned via `purge_dedup_older_than` at startup.
- `delivered(user_id, channel_id, message_id, bot_message_id, is_photo, body,
  created_at, dup_links_json, saved, delete_at)` — per-user record of every
  DM that was actually sent (including debug-mode duplicate DMs). `body` is
  the original rendered HTML at send time (never mutated). `dup_links_json`
  is a JSON array of `[title, link]` tuples for duplicates that have been
  chained onto this DM via inline URL buttons. `saved` (0/1) and `delete_at`
  (UNIX seconds, NULL when not scheduled) drive the Auto-delete feature; the
  sweeper deletes rows where `saved=0 AND delete_at <= now`.
- `embedding_usage(provider, tokens)` — running total of embedding tokens,
  one row per provider.
- `meta(key, value)` — small key-value store for runtime-pinned values.
  `schema_version` tracks which migrations have run. `summary_prompt` holds
  the owner's custom summarization prompt override (see [miniapp.md](miniapp.md)).
  `owner_id` is populated by the multi-provider migration so the legacy compat
  shims (`Channel.blacklisted`, `set_blacklisted`) know who "owner" is.
