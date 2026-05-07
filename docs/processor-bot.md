# processor_bot

A separate Telegram bot that runs on a private GPU host and serves
`informer_bot` over a private Telegram group. Use it when the GPU
machine cannot be reached from the informer host (corporate / private
network), but both can still reach Telegram outbound.

## Why it exists

`CHAT_PROVIDER=ollama` and `EMBEDDING_PROVIDER=ollama` assume the Ollama
endpoint is reachable from the informer host (usually `localhost`). If
the GPU host is unreachable over IP, Telegram itself becomes the
message bus: both bots talk to Telegram, and Telegram forwards messages
between them through a private group.

If a reverse tunnel (Tailscale, Cloudflare Tunnel, SSH `-R`) is
available, prefer that over `processor_bot` — there's no new code path
and the existing `ollama` provider just works.

## Topology

```
┌────────────────┐   request JSON    ┌─────────────────┐
│   informer_bot │  ───────────────▶ │  bus group      │
│   (VPS)        │                   │  (private chat) │
│                │ ◀───────────────  │                 │
└────────────────┘   reply JSON      └─────────────────┘
                                             ▲
                                             │ replies as bot user
                                             │
                                     ┌───────┴──────────┐
                                     │  processor_bot   │
                                     │  (private GPU)   │
                                     │  + local Ollama  │
                                     └──────────────────┘
```

Both bots are members of the same private group. The informer reads
each reply, deletes both the request and reply messages, then returns
the result to the pipeline.

## Setup

1. Create a second bot via `@BotFather` → record its token (`PROCESSOR_BOT_TOKEN`).
2. Create a private Telegram group. Add **both** bots to it, grant
   each delete-message rights. Disable history-for-new-members so an
   added third party cannot read past traffic.
3. Get the group's chat id (negative integer). Add it to both `.env`
   files as `BUS_GROUP_ID`.
4. Get each bot's numeric user id. The informer needs
   `PROCESSOR_BOT_USER_ID`; the processor needs `INFORMER_BOT_USER_ID`.
   Both filter incoming messages by sender, so traffic from anyone
   else in the group is ignored.
5. On the informer host: `CHAT_PROVIDER=remote` and/or
   `EMBEDDING_PROVIDER=remote`, plus the bus vars from step 3-4. See
   [internals/env-vars.md](internals/env-vars.md) for the full list.
6. On the GPU host: install Ollama, pull the chat + embedding models,
   then run `python -m processor_bot`.

## Wire protocol

Every request and reply is JSON. The full schema lives in
`shared/protocol.py`; this is a summary.

Requests (informer → processor, sent as the message body):

```
{"op": "summarize",   "id": "<uuid>", "text": "..."}
{"op": "is_relevant", "id": "<uuid>", "text": "...", "filter_prompt": "..."}
{"op": "embed",       "id": "<uuid>", "text": "...", "dimensions": 512}
{"op": "ping",        "id": "<uuid>"}
```

Replies (processor → informer, via Telegram reply):

```
{"id": "<uuid>", "ok": true,  "text": "...", "input_tokens": N, "output_tokens": N}
{"id": "<uuid>", "ok": true,  "relevant": true|false, "input_tokens": N, "output_tokens": N}
{"id": "<uuid>", "ok": false, "error": "..."}
```

`embed` replies arrive as a `.json` file attachment named
`embedding.json` (a 512-dim float vector exceeds Telegram's 4096-char
text-message limit). The file content is JSON of shape
`{"id": ..., "ok": true, "vector": [...], "tokens": N}`.

Correlation is by the `id` field, not by Telegram's `reply_to`. After
a successful round-trip the informer deletes both messages.

## Failure handling

The remote client tracks a `HEALTHY` / `UNHEALTHY` state.

- A real call (summarize / is_relevant / embed) that times out marks
  the state `UNHEALTHY` immediately and returns control to the
  fallback dispatcher.
- A background ping loop (`HEALTH_CHECK_INTERVAL_SECONDS`, default
  60s) probes the processor. Success transitions to `HEALTHY`;
  failure to `UNHEALTHY`.
- On every state transition the owner gets a DM:
  - `⚠️ Processor unreachable, fail-safe enabled (Claude/OpenAI).`
  - `✅ Processor recovered, back on local models.`
- While unhealthy, summarize/is_relevant/embed go to the providers
  named by `CHAT_PROVIDER_FALLBACK` and `EMBEDDING_PROVIDER_FALLBACK`
  (default `anthropic` and `openai`).

A logical error from the processor (`ok: false`) also triggers the
fallback for that single call, but does not flip global state.

## Rate limits

Both bots throttle sends to the bus group at ≥1 second between
messages. Telegram's per-chat soft limit is well above that, but
staying conservative keeps the bot safe from FloodWait under burst
catch-up.

## Running

### Bare metal

```
uv sync
PROCESSOR_BOT_TOKEN=... BUS_GROUP_ID=... INFORMER_BOT_USER_ID=... \
TELEGRAM_API_ID=... TELEGRAM_API_HASH=... \
uv run python -m processor_bot
```

### Docker (recommended for unattended deployment)

```
HOST_UID=$(id -u) HOST_GID=$(id -g) \
docker compose -f compose.processor.yaml up -d --build
```

Uses `Dockerfile.processor` — leaner than the informer image: no Mini
App, no Caddy. Reaches Ollama on the host via
`host.docker.internal` (set
`OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` in `data/.env`).

For pull-based auto-deploy from GitHub, see
[auto-update.md](auto-update.md).

The session file lives at `data/processor.session` by default
(`SESSION_PATH`). No SQLite, no Mini App, no user state — the
processor is stateless.
