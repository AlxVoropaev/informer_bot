# Storage schema

- `channels(id, title, blacklisted, username, about)` — `username` and
  `about` are populated during `refresh_channels` (admin-side Telethon
  `GetFullChannelRequest`). Used by the /list details view (ℹ️). Both fields
  are nullable; `upsert_channel` uses `COALESCE(excluded.x, channels.x)` so
  callers passing only `(id, title)` preserve any existing username/about.
- `subscriptions(user_id, channel_id, mode, filter_prompt)` —
  `mode IN ('off','filtered','debug','all')`. `'off'` rows are kept (instead
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
- `usage(user_id, input_tokens, output_tokens)` — per-user delivered-summary tokens
- `system_usage(id=1, input_tokens, output_tokens)` — total API spend (incl. filter checks)
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
- `embedding_usage(id=1, tokens)` — running total of OpenAI embedding tokens.
