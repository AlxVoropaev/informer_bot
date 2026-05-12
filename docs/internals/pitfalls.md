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

### `shared/` must be in the Dockerfile

**Symptom:** bot image boots, then immediately crashes on
`from shared.protocol import ...`.
**Why:** `shared/` is a sibling package consumed by both `informer_bot/`
and `processor_bot/`. It's easy to forget when copying source into the
image.
**How to avoid:** when adding a new top-level package, double-check
every `Dockerfile` that needs it.
**Evidence:** `14a393b` (fix(docker): copy shared/ into bot image).
