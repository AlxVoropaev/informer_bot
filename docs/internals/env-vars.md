# Required env vars (`data/.env`)

```
TELEGRAM_API_ID=...        # from my.telegram.org
TELEGRAM_API_HASH=...      # from my.telegram.org
TELEGRAM_BOT_TOKEN=...     # from @BotFather
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...         # optional — only consulted when EMBEDDING_PROVIDER picks openai
OWNER_ID=...               # admin's Telegram user id (numeric)
LOG_LEVEL=INFO             # optional, default INFO
EMBEDDING_PROVIDER=auto    # optional: auto|openai|local|none (auto picks openai if key set, else none)
LOCAL_EMBEDDING_MODEL=...  # optional, fastembed model name; default intfloat/multilingual-e5-large
DEDUP_THRESHOLD=0.85       # optional, cosine threshold for "same story"
DEDUP_WINDOW_HOURS=48      # optional, lookback window for dedup
CATCH_UP_WINDOW_HOURS=48   # optional, max age for restart catch-up replay
MINIAPP_URL=               # optional, public HTTPS URL of the Mini App; enables /app, the burger-menu launcher, and the in-process aiohttp server
WEBAPP_HOST=0.0.0.0        # optional, bind host for the Mini App server (default 0.0.0.0)
WEBAPP_PORT=8085           # optional, bind port for the Mini App server (default 8085)
```
