# Auto-delete

Opt-in per user via the Mini App settings (⚙️ icon in the top bar). Range
1..720 hours; absent / NULL disables the feature.

- **On send:** when `users.auto_delete_hours` is set, every delivered DM gets
  a `💾 Save` inline button (`callback_data="save"`) and the `delivered` row
  stores `delete_at = now + hours * 3600`. When unset, no button is added and
  `delete_at` stays NULL.
- **Save tap:** toggles `delivered.saved`. Save→Saved sets `saved=1,
  delete_at=NULL` and relabels the button to `✅ Saved`. Saved→Save sets
  `saved=0` and re-arms `delete_at = now + current_hours * 3600` (NULL when
  the feature was meanwhile turned off). The keyboard rebuild preserves the
  existing dup-link URL-button rows so chained duplicates aren't lost.
- **Dedup chain interaction (rule c, both):** when a duplicate is chained
  onto an existing DM via `edit_dm`, the original row's `delete_at` is
  extended to `now + current_hours * 3600` *only if* the row is still
  unsaved (`extend_delivered_delete_at` is a no-op when `saved=1`). On
  auto-deletion the whole `delivered` row is removed, so future similar
  posts land as fresh DMs (no stale chain).
- **Sweeper:** `informer_bot.main.sweep_due_deletions` runs as an asyncio
  task on the same loop, ticking every 60s. Each tick calls
  `db.list_due_deletions(now)`, issues `bot.delete_message` for each row
  (failures are logged at WARNING — usually means the user already deleted
  it), and then drops the row from `delivered`. The task is started in
  `main.main()` and cancelled in `graceful_shutdown`.
