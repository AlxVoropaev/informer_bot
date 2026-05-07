# Required env vars (`data/.env`)

```
TELEGRAM_API_ID=...        # from my.telegram.org
TELEGRAM_API_HASH=...      # from my.telegram.org
TELEGRAM_BOT_TOKEN=...     # from @BotFather
ANTHROPIC_API_KEY=...      # required only when CHAT_PROVIDER=anthropic (the default)
OPENAI_API_KEY=...         # optional — only consulted when EMBEDDING_PROVIDER picks openai
OWNER_ID=...               # admin's Telegram user id (numeric)
LOG_LEVEL=INFO             # optional, default INFO
EMBEDDING_PROVIDER=auto    # optional: auto|openai|ollama|remote|none (auto picks openai if key set, else none)
CHAT_PROVIDER=anthropic    # optional: anthropic|ollama|remote (default anthropic)
OLLAMA_BASE_URL=http://localhost:11434/v1  # optional, OpenAI-compatible endpoint of your Ollama server
OLLAMA_CHAT_MODEL=qwen3.5:4b                # optional, Ollama tag used when CHAT_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=qwen3-embedding:4b   # optional, Ollama tag used when EMBEDDING_PROVIDER=ollama
BUS_GROUP_ID=                # required when CHAT_PROVIDER=remote or EMBEDDING_PROVIDER=remote — id of the private Telegram group used to talk to processor_bot
PROCESSOR_BOT_USER_ID=       # required when CHAT_PROVIDER=remote or EMBEDDING_PROVIDER=remote — numeric user id of processor_bot
PROCESSOR_TIMEOUT_SECONDS=60 # optional, seconds to wait for a remote reply (default 60)
HEALTH_CHECK_INTERVAL_SECONDS=60 # optional, ping interval used to track processor health (default 60)
CHAT_PROVIDER_FALLBACK=anthropic # optional: anthropic|ollama — used when CHAT_PROVIDER=remote and the processor is unreachable (default anthropic)
EMBEDDING_PROVIDER_FALLBACK=openai # optional: openai|ollama|none — used when EMBEDDING_PROVIDER=remote and the processor is unreachable (default openai)
DEDUP_THRESHOLD=0.85       # optional, cosine threshold for "same story"
DEDUP_WINDOW_HOURS=48      # optional, lookback window for dedup
CATCH_UP_WINDOW_HOURS=48   # optional, max age for restart catch-up replay
MINIAPP_URL=               # optional, public HTTPS URL of the Mini App; enables /app, the burger-menu launcher, and the in-process aiohttp server
WEBAPP_HOST=0.0.0.0        # optional, bind host for the Mini App server (default 0.0.0.0)
WEBAPP_PORT=8085           # optional, bind port for the Mini App server (default 8085)
```

## processor_bot only

```
PROCESSOR_BOT_TOKEN=...    # from @BotFather, distinct from TELEGRAM_BOT_TOKEN
BUS_GROUP_ID=...           # negative integer id of the private bus group
INFORMER_BOT_USER_ID=...   # numeric Telegram user id of the informer bot (sender filter)
SESSION_PATH=data/processor  # optional, Telethon session path (default data/processor)
```
