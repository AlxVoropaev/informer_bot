# Architecture

## What this is

Telegram news aggregator. A Telethon **user-account client** (the admin's account) reads
posts from public channels the admin is subscribed to. A python-telegram-bot **bot**
exposes those channels to bot users; when a bot user has a channel enabled and a new
post lands, Claude summarises it and the bot DMs the user a 1–2-sentence brief plus a
link to the original.

One Python process runs both the client and the bot inside a single asyncio loop.

A second process (`processor_bot`) is optional: when running local Ollama on a
private GPU machine that the informer host cannot reach over the network, set
`CHAT_PROVIDER=remote` / `EMBEDDING_PROVIDER=remote` and run `processor_bot`
on the GPU host. The two bots talk over a private Telegram group ("the bus
group"). See [processor-bot.md](../processor-bot.md).

## Roles

- **Admin** (single, hard-coded `OWNER_ID`): owns the user-account session, owns the
  source-of-truth channel list, can blacklist channels.
- **Bot users** (many): subscribe via the bot, toggle channels on/off from the admin's
  (post-blacklist) list, receive DMs.

## Stack

- Python 3.12, managed with `uv` (`pyproject.toml`, `uv sync`, `uv run`).
- Telegram client: **Telethon** (MTProto user account, real-time `events.NewMessage`).
- Telegram bot: **python-telegram-bot** (v21+, asyncio).
- LLM: **anthropic** SDK, model `claude-haiku-4-5` (cheap & fast for summaries).
  Setting `CHAT_PROVIDER=ollama` swaps Claude for a local `qwen3.5:4b` via
  Ollama's OpenAI-compatible endpoint. `CHAT_PROVIDER=remote` routes calls
  through `processor_bot` over the bus group; if the processor is unreachable,
  informer falls back to the `CHAT_PROVIDER_FALLBACK` provider (Claude by default)
  and DMs the owner.
- Embeddings (dedup): pluggable. **OpenAI** `text-embedding-3-small` @ 512 dims
  (paid) or **Ollama** (`qwen3-embedding:4b` @ 1024 dims, local, no API cost)
  when `EMBEDDING_PROVIDER=ollama`. `EMBEDDING_PROVIDER=remote` routes through
  `processor_bot` with `EMBEDDING_PROVIDER_FALLBACK` as the safety net.
- Storage: **SQLite** (single file, `data/informer.db`) + Telethon
  `data/informer.session` file. The `data/` directory holds all mutable state
  and is bind-mounted into the Docker container.
- Config: **`.env`** (lives in `data/.env`) loaded via `python-dotenv`. Never
  commit `.env` or `*.session`.
- Container: **Dockerfile** + **compose.yaml** (`compose.yaml` not the legacy
  `docker-compose.yml`). Image is built as a non-root user matching host
  `HOST_UID`/`HOST_GID` so files written to `./data/` stay owned by you.
- Tests: **pytest** + **pytest-asyncio**. TDD — failing test before code.

## Operational notes

- **SQLite journal mode.** The DB connection currently relies on the default
  rollback journal (`DELETE`). With three async writers (pipeline, sweeper,
  webapp) sharing one file, switching to `PRAGMA journal_mode=WAL` would
  allow readers and writers to overlap. Not yet enabled — see
  [todos.md](todos.md).
- **Single event loop, two Telegram clients.** Telethon (user account,
  ingest) and python-telegram-bot (bot account, DMs + Mini App) share one
  asyncio loop. A burst of catch-up summaries can briefly delay bot command
  handling. This is intentional: keeping one loop avoids cross-process
  state and a second SQLite connection. Document the trade-off if scaling
  past personal use.
