# Deduplication

After summarising, the summary text is embedded once and compared against
this user's recent `delivered` rows (last `DEDUP_WINDOW_HOURS`). Cosine
≥ `DEDUP_THRESHOLD` counts as a duplicate.

- **Provider** is `EMBEDDING_PROVIDER`: `auto` (default — `openai` if
  `OPENAI_API_KEY` set, else `none`), `openai`
  (`text-embedding-3-small` @ 512 dims, paid), `local` (fastembed on CPU,
  default `intfloat/multilingual-e5-large` @ 1024 dims, no API cost,
  timed in logs as `local embed: ... ms`), or `none` (disabled).
- **Model-switch purge:** the active provider+model+dims is stored in
  `meta.embedding_id`. On startup, if it differs from the previous run,
  `delivered` and `post_embeddings` are wiped (vectors aren't comparable
  across spaces). Switching freely is fine — you just lose dedup history.
- **`none` (or `auto` with no key):** `main.py` passes `embed_fn=None` /
  `edit_dm=None`. `handle_new_post` then skips embedding, dedup lookup,
  `delivered` records, and `post_embeddings` writes — DMs go out as if dedup
  didn't exist. The owner is DM'd `dedup_disabled_notice` once at startup
  (no recurring nag).
- **Normal modes (`filtered`, `all`):** the previous DM gets a new inline URL
  button (one button row per duplicate, button text = source channel title)
  via `bot.edit_message_reply_markup`. The DM body is never mutated — this
  sidesteps Telegram's 1024-char caption / 4096-char text limits. The new
  post is NOT inserted into `delivered` for this user — future duplicates
  keep chaining onto the original DM via `delivered.dup_links_json`. The post
  IS inserted into `post_embeddings` so other users can still match against
  it.
- **Dedup-debug toggle (user-level, `users.dedup_debug`):** when on, the
  edit-chain path is bypassed. A fresh DM is sent with a localized
  `🔁 DUPLICATE` marker prefix (i18n key `debug_duplicate_marker`) plus a
  trailing `↳ Original: <a href="…">Source channel title</a>` line (i18n
  key `original_label`) pointing at the previously-delivered duplicate, and
  `delivered` is recorded normally. Independent of the per-channel `'debug'`
  mode — they're orthogonal: filter-debug tags filter-excluded posts;
  dedup-debug surfaces dedup matches.
- Embedding tokens are tracked in `embedding_usage` and surfaced in `/usage`
  for the owner only.
