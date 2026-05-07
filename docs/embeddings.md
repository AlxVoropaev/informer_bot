# Embedding provider (deduplication)

After summarising a post the bot embeds the summary text and compares it to
the user's recent deliveries. If the cosine similarity is above
`DEDUP_THRESHOLD`, the new post is treated as a duplicate of the previous one
(merged in as an inline URL button instead of a fresh DM, unless dedup-debug
is on).

This is optional — set `EMBEDDING_PROVIDER=none` (or simply leave
`OPENAI_API_KEY` blank with the default `auto`) and the bot ships posts as if
dedup didn't exist.

## Configuration

| Var | Values | Default | Notes |
| --- | --- | --- | --- |
| `EMBEDDING_PROVIDER` | `auto` \| `openai` \| `ollama` \| `remote` \| `none` | `auto` | `auto` picks `openai` if `OPENAI_API_KEY` is set, otherwise `none`. `remote` routes through `processor_bot` — see [internals/processor-bot.md](internals/processor-bot.md). |
| `OLLAMA_BASE_URL` | URL | `http://localhost:11434/v1` | OpenAI-compatible endpoint of your local Ollama server. Shared with `CHAT_PROVIDER=ollama`. |
| `OLLAMA_EMBEDDING_MODEL` | any Ollama embedding tag | `qwen3-embedding:4b` | Only used when provider is `ollama`. |
| `DEDUP_THRESHOLD` | float 0..1 | `0.85` | Cosine similarity at or above which two posts count as the same story. |
| `DEDUP_WINDOW_HOURS` | int | `48` | How far back to look for duplicates per user. |
| `CATCH_UP_WINDOW_HOURS` | int | `48` | On restart, replay missed posts up to this age. Set to `0` if you don't want any backfill. |
| `MINIAPP_URL` | full HTTPS URL | *(unset)* | Public URL where Telegram can fetch the Mini App frontend. **Required for regular users** — channel selection, filters, and language live only in the Mini App. See [miniapp-hosting.md](miniapp-hosting.md). When set, the bot starts an in-process aiohttp server on `WEBAPP_HOST:WEBAPP_PORT`, registers the burger-menu launcher, and `/app` becomes available. |
| `WEBAPP_HOST` | host | `0.0.0.0` | Bind address for the Mini App server. |
| `WEBAPP_PORT` | int | `8085` | Bind port for the Mini App server. |

## Provider details

- `openai` — `text-embedding-3-small` @ 512 dims, paid (~$0.02 / 1M tokens).
- `ollama` — runs the model via a local [Ollama](https://ollama.com) server.
  Default tag is `qwen3-embedding:4b` (1024 dims, no API cost). Requires
  Ollama to be installed and the model pulled
  (`ollama pull qwen3-embedding:4b`). Point `OLLAMA_BASE_URL` at your server
  if it isn't on `localhost:11434`.
- `remote` — sends the request to `processor_bot` over a private Telegram bus
  group. Use this when the GPU host is on a private network and cannot be
  reached over IP from the informer host. See
  [internals/processor-bot.md](internals/processor-bot.md) for setup and the
  wire protocol.
- `none` — disable dedup entirely; owner gets a one-time DM at startup.

Switching between providers (or between Ollama model tags) is safe — on the
next startup the bot detects the change and wipes the dedup index, since
embedding spaces aren't comparable across models.
