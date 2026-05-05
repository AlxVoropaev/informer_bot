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
| `EMBEDDING_PROVIDER` | `auto` \| `openai` \| `local` \| `none` | `auto` | `auto` picks `openai` if `OPENAI_API_KEY` is set, otherwise `none`. |
| `LOCAL_EMBEDDING_MODEL` | any [fastembed](https://github.com/qdrant/fastembed) model name | `intfloat/multilingual-e5-large` | Only used when provider is `local`. |
| `LOCAL_EMBEDDING_DEVICE` | `cpu` \| `cuda` | `cpu` | `cuda` requires installing `fastembed-gpu` instead of `fastembed`. |
| `DEDUP_THRESHOLD` | float 0..1 | `0.85` | Cosine similarity at or above which two posts count as the same story. |
| `DEDUP_WINDOW_HOURS` | int | `48` | How far back to look for duplicates per user. |
| `CATCH_UP_WINDOW_HOURS` | int | `48` | On restart, replay missed posts up to this age. Set to `0` if you don't want any backfill. |
| `MINIAPP_URL` | full HTTPS URL | *(unset)* | Public URL where Telegram can fetch the Mini App frontend. **Required for regular users** — channel selection, filters, and language live only in the Mini App. See [miniapp-hosting.md](miniapp-hosting.md). When set, the bot starts an in-process aiohttp server on `WEBAPP_HOST:WEBAPP_PORT`, registers the burger-menu launcher, and `/app` becomes available. |
| `WEBAPP_HOST` | host | `0.0.0.0` | Bind address for the Mini App server. |
| `WEBAPP_PORT` | int | `8085` | Bind port for the Mini App server. |

## Provider details

- `openai` — `text-embedding-3-small` @ 512 dims, paid (~$0.02 / 1M tokens).
- `local` — runs the model via fastembed (ONNX, no PyTorch). Default model is
  `intfloat/multilingual-e5-large` (~2.2 GB on disk, 1024 dims, top-tier
  multilingual quality including Russian).
  - **CPU:** budget ~3 GB RAM at steady state. Tiny VPS hosts (≤1 GB RAM, no
    swap) will OOM-kill the process silently mid-load — if you see the bot
    looping after `local embedder: loading ...` with no error, fall back to
    `openai` or `none`. For a smaller-footprint CPU run, override
    `LOCAL_EMBEDDING_MODEL=intfloat/multilingual-e5-small` (~120 MB, 384 dims).
  - **GPU:** set `LOCAL_EMBEDDING_DEVICE=cuda` and swap the dependency from
    `fastembed` to `fastembed-gpu` (`uv add fastembed-gpu`). The container
    image needs CUDA available and the `nvidia` runtime configured.
  - The model cache is persisted under `data/fastembed_cache/` so it survives
    container restarts.
- `none` — disable dedup entirely; owner gets a one-time DM at startup.

Switching between providers (or between local model names) is safe — on the
next startup the bot detects the change and wipes the dedup index, since
embedding spaces aren't comparable across models.
