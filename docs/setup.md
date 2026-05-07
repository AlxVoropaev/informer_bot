# Self-hosting setup

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), and a Telegram account that's subscribed to the channels you want to track.

## 1. Install dependencies

```sh
uv sync
```

## 2. Get credentials

- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` — from [my.telegram.org](https://my.telegram.org).
- `TELEGRAM_BOT_TOKEN` — create a bot via [@BotFather](https://t.me/BotFather).
- `ANTHROPIC_API_KEY` — required when `CHAT_PROVIDER=anthropic` (the default), from [console.anthropic.com](https://console.anthropic.com).
- `OPENAI_API_KEY` — *optional*, from [platform.openai.com](https://platform.openai.com). Used for summary embeddings (dedup); cost is negligible (~$0.02 per million tokens with `text-embedding-3-small`). If you leave it blank, the bot starts fine — deduplication is just disabled, and the owner gets a one-time DM at startup saying so.
- `OWNER_ID` — your numeric Telegram user ID (ask [@userinfobot](https://t.me/userinfobot)).

For deduplication tuning and the embedding provider table, see
[embeddings.md](embeddings.md).

For Mini App hosting (`MINIAPP_URL`, Caddy, alternatives), see
[miniapp-hosting.md](miniapp-hosting.md).

## 3. Configure `.env`

`.env` lives in `data/` so it's bind-mounted into the container, not baked into the image:

```sh
cp data/.env.example data/.env
# then fill in the five values above
```

## 4. Log in to your Telegram account once

Creates `data/informer.session`, chmod 600:

```sh
uv run python login.py
```

You'll be asked for your phone number and the code Telegram sends you.

## 5. Run the bot

```sh
uv run python -m informer_bot.main
```

The process runs both the user-account client (reads channels) and the bot (talks to subscribers) in one asyncio loop. Keep it running — there's no built-in daemonisation.

For Docker Compose deployment, see [docker.md](docker.md).
