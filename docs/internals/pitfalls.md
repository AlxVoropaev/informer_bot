# Pitfalls

Non-obvious gotchas, invariants, and "things that broke before and why" —
curated from real bug fixes so future sessions reload them as context.

Add an entry when you fix a bug whose root cause wasn't obvious from the code,
or when you discover an invariant that's easy to violate. Don't pad — generic
advice belongs in `CLAUDE.md`, not here. Each entry should be specific enough
that someone could re-introduce the bug without it, and impossible to with.

## Telethon / sessions

### A live Telethon client holds a SQLite handle on its `.session` file

**Symptom:** unlinking or overwriting `<session_path>` while the client is
running corrupts auth state; shutdown then crashes on the orphaned handle, and
a false "session OK" check passes against the deleted file.
**Why:** Telethon's SQLite session backend keeps `.session` (and
`.session-journal`) open for the lifetime of the client. The OS holds the
inode until the handle is closed.
**How to avoid:** for re-login, write to `<session_path>.relogin` and only
swap atomically over the live path after a successful sign-in. For logout,
disconnect the running client first, then unlink the file and journal. Never
touch the live `.session` file behind a running client's back.
**Evidence:** `a9dbaf8` (fix(miniapp): non-destructive re-login, provider
logout, degraded mode), `a32500c` (fix(miniapp): hot-reload provider Telethon
client after Mini App login), `a58227e` (fix(miniapp): unlink stale session
file on forced provider login).

### Telethon writes the session file with the process umask

**Symptom:** `data/sessions/<user_id>.session` lands on disk world-readable
(0o644) with the API hash and auth key already written, before any
permission tightening can run.
**Why:** Telethon creates the SQLite file lazily inside `tg.start()` using
the default umask, and only writes secrets afterwards. There is no
public hook to set the file mode atomically.
**How to avoid:** pre-create the session file with `os.open(..., 0o600)`
before calling `tg.start()`. Parent dir should be `0o700`.
**Evidence:** `7468a98` (fix(login): pre-create session file with mode 0o600).

### Refreshing the channel list at startup triggers FloodWait

**Symptom:** fresh container start sleeps for ~30 s on
`GetFullChannelRequest`, blocking the event loop and delaying every other
Telethon call.
**Why:** `refresh_channels` issues one `GetFullChannelRequest` per
subscribed channel (needed for the `about` field). The burst on cold start
exceeds Telegram's server-side rate limit. Telethon then sleeps reactively
in `FloodWaitError`.
**How to avoid:** never call `refresh_channels` from startup. Catch-up
runs against the existing DB. The admin runs `/update` explicitly when
their subscription list changes. Throttle MTProto calls via the
`expensive_limiter` (1 req/s) singleton in `informer_bot/throttle.py`.
**Evidence:** `95fcb4e` (fix: skip channel-list refresh at startup),
`ac5385e` (feat(throttle): rate-limit Telegram API calls to prevent FloodWait).

## Pipeline / dedup

### `mark_seen` runs before delivery — every post-`mark_seen` exception leaks the post

**Symptom:** a post is recorded in `seen` (so catch-up won't replay it) but
the user never received the DM. Permanently lost.
**Why:** `handle_new_post` marks the post seen early to make catch-up
crash-safe. Anything that raises after that point — empty summary, remote
embed failure, summarizer `None` content, etc. — drops the post.
**How to avoid:** every step after `mark_seen` must either succeed or
degrade gracefully (skip dedup, send DM anyway, log warning) rather than
raising. Guard `None`/empty returns from external providers (Ollama,
remote processor); treat unreachable remote embed as `EMBEDDING_PROVIDER=none`
for that one post.
**Evidence:** `e42ea7b` (fix(pipeline): degrade gracefully when remote embed
is unavailable), `7117e6b` (fix(summarizer): guard None content/usage from
Ollama responses), `c1cad7a` (fix(summarize): disable Qwen3 thinking; skip
posts with empty summary).

### `delivered` powers Save and auto-delete, not just dedup

**Symptom:** with `EMBEDDING_PROVIDER=none`, the Save button silently
no-ops (and `on_save` can't find the row), and auto-delete never fires.
**Why:** earlier code gated `record_delivered` on `emb is not None`,
treating it as a dedup-only artifact. It's actually the bookkeeping row for
Save and the auto-delete sweeper as well.
**How to avoid:** always insert a `delivered` row after a successful DM,
regardless of dedup state.
**Evidence:** `587a2db` (fix(pipeline): record delivered rows when dedup is
disabled).

### Empty-string summaries poison the dedup index

**Symptom:** subsequent unrelated posts get treated as duplicates and
chained onto an irrelevant DM.
**Why:** Qwen3-via-Ollama can spend its entire output budget on hidden
chain-of-thought and return empty `message.content`. Embedding the empty
string produces a degenerate vector that matches every other empty-summary
post.
**How to avoid:** when `summarize` returns empty text, log a warning and
skip the post — do not embed it, do not insert into `post_embeddings`. For
Qwen3 specifically, disable thinking via `extra_body={"think": False}`
(the `/no_think` prompt directive is ignored by the model).
**Evidence:** `c1cad7a` (fix(summarize): disable Qwen3 thinking; skip posts
with empty summary), `7644a0b` (fix(summarize): use Ollama think=False to
disable Qwen3 CoT).

### Ollama thinking models can return empty content even with `think:false`

**Symptom:** a single post silently never reaches users; bot logs show
`empty summary (provider=remote in=N out=4000) — model produced no text`
with `completion_tokens` pinned at the full `MAX_TOKENS_OLLAMA` cap.
Observed in production on 2026-05-14 for post `1266112149/2872`
(@FreakingTeens) under `qwen3.5:4b`.
**Why:** thinking-class Ollama models (qwen3.5, qwen3) can still burn the
entire output budget on hidden reasoning even when called with
`extra_body={"think": False}`. The OpenAI-compatible response then has
`message.content=""` (or `None`) but `usage.completion_tokens == max_tokens`.
The naive `if not summary.text: return` path that guarded the dedup index
(see "Empty-string summaries poison the dedup index" above) silently
dropped the post.
**How to avoid:** detect the cap-hit explicitly. `Summary.truncated` is set
to True whenever the summarizer's completion reached the limit
(`completion_tokens >= MAX_TOKENS_OLLAMA` for Ollama,
`response.stop_reason == "max_tokens"` for Anthropic) and propagates
through `SummarizeReply.truncated`. The pipeline branches on
`(empty?, truncated?)`: empty+truncated → DM each recipient a localized
notice with no embedding; non-empty+truncated → deliver with a
`summary_truncated_marker` prefix; empty+not-truncated keeps the
original silent-skip. Don't reintroduce a blanket `if not summary.text:
return` — it loses the truncation signal.
**Evidence:** `<this commit>` (feat(pipeline): DM users when the
summarizer hits its token cap).

### Embedding-space changes silently corrupt dedup

**Symptom:** dedup recall drops to noise after switching embedding provider
or model — old and new vectors live in different spaces and aren't
comparable.
**Why:** cosine similarity between vectors from different embedding models
is meaningless. The bot can't detect a model swap from the vectors alone.
**How to avoid:** stamp `meta.embedding_id` as `provider+model+dims`. For
local providers check at startup; for `remote` the processor returns the
model name on every `EmbedReply` and the informer recomputes the id then.
On mismatch, wipe `delivered` and `post_embeddings` — losing dedup history
is acceptable, mixing spaces is not.
**Evidence:** `27ef2a8` (feat(dedup): purge index when remote embedding
model changes).

### Blacklist visibility vs. delivery were two different queries

**Symptom:** a provider blacklists a channel they're the sole contributor to.
The Mini App correctly hides the channel from Subscribe, but live posts still
arrive in their DMs.
**Why:** `Database.subscribers_for_channel` used a legacy owner-centric filter
keyed off `meta.owner_id`. On fresh installs created from `_SCHEMA` at version
13+, the multi-provider migration never runs and `meta.owner_id` is never
written; the filter falls back to `provider_user_id = -1` and matches nothing,
so the blacklist is effectively ignored on the delivery path. Meanwhile
`list_visible_channels` used the correct multi-provider rule, so the two
disagreed.
**How to avoid:** delivery follows visibility. `subscribers_for_channel` now
requires an approved provider that contributes the channel AND hasn't
blacklisted it — the same predicate as `list_visible_channels` /
`is_visible_channel`. Do not re-introduce the `meta.owner_id` shortcut in any
new helper that gates delivery.
**Evidence:** `<this commit>` (fix(db): align subscribers_for_channel with
multi-provider visibility).

## Auto-delete

### Don't drop the `delivered` row when Telegram's delete fails

**Symptom:** transient Telegram failure (rate limit, network blip, 5xx) on
the auto-delete sweep leaves the user's DM in their chat forever, while the
bookkeeping row is gone so the next sweep won't retry.
**Why:** earlier code unconditionally called `delete_delivered_row` after
`delete_message`, even when the latter raised.
**How to avoid:** only delete the row on successful Telegram delete. Failed
sweeps retry on the next 60 s tick.
**Evidence:** `73c2dc1` (fix(main): keep delivered row when Telegram delete
fails).

### Permanent-delete-failures must still drop the row

**Symptom:** user wipes their DM history with the bot, or a row's
`delete_at` is older than 48 h. Telegram answers `BadRequest("Message to
delete not found")` / `BadRequest("Message can't be deleted for everyone")`
on every sweep. The previous fix (keep row on any failure) re-logs the same
WARNINGs forever — once per minute, per row.
**Why:** the keep-on-failure rule is correct for *transient* failures but
not for terminal ones where the goal (message gone) is already met or is
unreachable.
**How to avoid:** in `sweep_due_deletions`, catch `telegram.error.BadRequest`
separately. If `str(exc).lower()` contains
`"message to delete not found"` or `"message can't be deleted for everyone"`,
log INFO and drop the row. Any other `BadRequest`, or any non-`BadRequest`
exception, keeps the existing WARNING + `continue` (retry next tick). Match
via lowercased `in` substring, not equality — Telegram's exact strings drift.
**Evidence:** `<this commit>` (fix(auto-delete): drop delivered row when
telegram says message is gone).

## Mini App / webapp

### One SQLite connection, three async writers — serialize at the Python layer

**Symptom:** sporadic `sqlite3.ProgrammingError` / corruption-shaped
errors when PTB handlers and the aiohttp Mini App server hit the DB
concurrently.
**Why:** the shared `sqlite3.Connection` is opened with
`check_same_thread=False`, which lifts Python's thread-check but does not
make the connection safe under concurrent access.
**How to avoid:** every public `Database` method body runs under
`with self._lock:` (a `threading.Lock` set in `__init__`). Don't bypass
this lock with raw `conn.execute(...)` from outside `db.py`. Coarse but
adequate for the bot's traffic; WAL is a separate TODO.
**Evidence:** `cfe8205` (fix(db): serialize Connection access; restructure
migrations).

### `/api/*` is the public attack surface — validate everything

**Symptom:** `int(channel_id)` raises 500 on garbage input; missing
`auth_date` is silently accepted; 4 KiB prompt + a few clients exhaust
memory; per-endpoint approval checks drift out of sync.
**Why:** the Mini App's `X-Telegram-Init-Data` HMAC proves *who* the caller
is, not *what* they're sending — body fields and rate are still untrusted.
**How to avoid:** reject `initData` with missing `auth_date`; rate-limit
30 req/60 s per user on every `/api/*` call; cap `client_max_size` at
128 KiB; cap `summary_prompt` at 4 KiB; wrap every `int()` of caller input
in try/except → 400; gate `users.status='approved'` in the auth middleware,
not per-endpoint.
**Evidence:** `364b3cb` (fix(webapp): require auth_date, rate-limit /api/*,
hoist auth check), `8dca3c1` (fix(webapp): harden /api/* and clarify
summary_prompt UX).

### Inline-keyboard callbacks can race with `/update`

**Symptom:** the admin taps a per-channel toggle button and the bot raises
`ValueError` (or 500) because the channel was just removed by a concurrent
refresh.
**Why:** the channel list shown in the inline keyboard is a snapshot at
the time the message was sent; `/update` can prune the row before the user
taps.
**How to avoid:** in every channel-scoped callback handler, look the
channel up via `db.get_channel` and answer the callback with a localized
`channel_unavailable` message when it's gone, rather than indexing into a
list-comprehension result.
**Evidence:** `bdda7f3` (fix(bot): use get_channel + None-check in
blacklist toggle).

### `_channel_payload` must include the provider's own channels, not just `list_visible_channels()`

**Symptom:** an approved provider blacklists every channel they own (e.g.
via one click on the Provide tab's bulk "Deselect all" / "Select all") and
the Mini App's Provide tab goes empty — they have no UI path to un-blacklist
and are permanently stuck.
**Why:** the Provide tab in `webapp/app.js` renders `state.channels`
filtered by the provider's owned-channel set. `state.channels` came from
`_channel_payload`, which sourced only from `db.list_visible_channels()` —
and a channel blacklisted by its sole provider is invisible.
**How to avoid:** in `_channel_payload`, union the visible list with the
caller's own channels when they are an `approved` provider. The Provide tab
MUST still include owned channels even when blacklisted (so the un-blacklist
UI isn't stranded). The Subscribe tab MUST filter them out — a channel that
only appears via this owned-channel fallback is not actually subscribable
from anyone else's contribution, so showing it there is misleading. The
payload carries a per-channel `subscribable` flag (True iff the channel
came from `list_visible_channels()`) so the JS can filter Subscribe without
dropping the Provide-tab fallback.
**Evidence:** `984c754` (flip Provide indicator to whitelist-style),
`0462190` (bulk Select/Deselect all) made one-click bulk blacklisting
trivial and exposed this; fix in `fix(miniapp): provider bulk Select-all
semantics + always-show owned channels`; `<this commit>`
(fix(miniapp): hide owned-blacklisted channels from Subscribe tab) added
the `subscribable` flag to also hide them from Subscribe.

### `channel_gone` has two triggers — orphan AND all-providers-blacklisted

**Symptom:** a provider blacklists their only-providing channel; subscribers
stop receiving posts but never get the documented "no longer available" DM
(`docs/features.md:52-53`, `docs/usage.md:57`).
**Why:** the historic orphan-detection path
(`prune_orphan_channels` → `channels_with_no_provider`) only fires when
`provider_channels` empties, which blacklisting never does — blacklisting
only inserts into `channel_blacklist`. The blacklist endpoints called
`prune_orphan_channels` cosmetically but it was a no-op for the blacklist
case.
**How to avoid:** the blacklist endpoint (`_blacklist` in
`informer_bot/webapp.py`) snapshots
`list_visible_channels()` before the write and calls
`notify_subscribers_of_lost_visibility` after, which DMs subscribers of
any channel that lost visibility. Do not reuse `subscribers_for_channel`
from this path — it has a legacy owner-blacklist filter that silently
drops the very users we want to notify; use
`list_subscribed_users_for_channel` instead.
**Evidence:** `<this commit>` (`fix(miniapp): DM subscribers when a
channel goes invisible due to blacklist`).

### Owner needs an `approved` row in `providers` on fresh installs

**Symptom:** fresh DB → `/api/providers` returns `[]` → Mini App's
Providers section is empty with no Login button → owner can't onboard via
the UI; `/api/become_provider` also rejects the owner. Stuck.
**Why:** the legacy single→multi-provider migration auto-inserts the owner
with `status='approved'`, but fresh installs skip that migration path
entirely.
**How to avoid:** on startup, ensure the owner has an approved `providers`
row pointing at `data/sessions/{owner_id}.session` (matching the
`become_provider` path convention). `status='approved'` only means a row
exists; whether a session file is on disk is a separate runtime check.
**Evidence:** `2bc22a9` (fix(bot): auto-approve owner as provider on fresh
DB).

### Author CSS `display: flex` silently overrides the `hidden` HTML attribute

**Symptom:** JS sets `element.hidden = true` and the element stays
visible. Most visibly: the Provider banner, the Subscribe/Provide tabs,
and the Select-all/Deselect-all bulk-actions row bled through above
sub-screens (Settings, Usage, channel details). Some sister elements
with no `display` rule hid correctly, making the inconsistency
confusing.
**Why:** the HTML `hidden` attribute resolves to `display: none` in the
UA stylesheet. Any author CSS rule that sets `display: flex` (or
`block`, `grid`, etc.) on the same element wins on origin/cascade order
and overrides it. `.provider-banner`, `.tabs`, and `.bulk-actions` in
`webapp/style.css` all declare `display: flex`, so every
`element.hidden = true` call against them was a silent no-op. The
codebase uses the `hidden` attribute in 36 places, all assuming it
actually hides.
**How to avoid:** `webapp/style.css` includes a global
`[hidden] { display: none !important; }` rule directly under the
existing `.hidden { display: none !important; }` rule. Don't remove it.
When adding a new element with `display: flex/grid/block/...`, you
don't need to do anything — the global rule keeps the attribute
working. Equivalent alternative: use the `.hidden` class instead of the
attribute (also `!important`), but the codebase mixes both, so the CSS
rule is the safer fix.
**Evidence:** `871fc11` (fix(miniapp): force [hidden] attribute to
override display: flex in CSS); the prior partial fix `41e5159`
(fix(miniapp): hide provider banner and active-model on settings/usage
screens) added the right JS calls but did not solve the visibility
problem for elements with `display: flex`.

## Processor-bot / bus group

### Bus messages must go via the bot account, as JSON file attachments

**Symptom:** bus requests appear in the group from the admin's user
account (not the bot); long channel posts hit Telegram's 4096-char text
limit and are silently truncated on the wire.
**Why:** sending via the Telethon user session puts the admin on the
record. Sending JSON as plain text caps payload at 4096 chars (1024 for
captions).
**How to avoid:** use PTB on both ends — `Application.bot.send_document`,
`get_file`, `delete_messages` — and ship every protocol message as a
`.json` file attachment. Requires bot-to-bot communication enabled at
@BotFather for both bots.
**Evidence:** `bcc1d82` (fix(bus): send from bot account and use JSON file
attachments).

### Ping health and last-seen models are independent state — refresh them together

**Symptom:** the remote processor recovers from being unhealthy, the owner
gets the "✅ Processor recovered, back on local models." DM, but the Mini
App provider UI still shows `Model: Remote — (no reply yet)` for both chat
and embedding.
**Why:** `_healthy` is flipped by `run_health_check_loop()` on a successful
`ping()`, but `_last_chat_model` / `_last_embed_model` were only populated
from `SummarizeReply.model` / `EmbedReply.model` inside `summarize()` /
`embed()`. A successful ping after a cold start (or after recovery, before
the next real call) left both `None`, and the `/state` endpoint rendered
"(no reply yet)" while the bot was already on local models.
**How to avoid:** `PingReply` carries `chat_model` and `embed_model` so a
successful ping is a complete state refresh. When adding any new piece of
UI state derived from the remote, decide whether it should update on ping
too — otherwise the binary `_healthy` and the "last work-reply" fields can
diverge for the entire time between recovery and the next real call.
**Evidence:** `<this commit>` (fix(remote): include chat/embed model names
in PingReply so UI stays in sync with health state).

### `shared/` must be in the Dockerfile

**Symptom:** bot image boots, then immediately crashes on
`from shared.protocol import ...`.
**Why:** `shared/` is a sibling package consumed by both `informer_bot/`
and `processor_bot/`. It's easy to forget when copying source into the
image.
**How to avoid:** when adding a new top-level package, double-check
every `Dockerfile` that needs it.
**Evidence:** `14a393b` (fix(docker): copy shared/ into bot image).
