# Layout & TDD order

## Layout

```
informer_bot/
├── pyproject.toml
├── Dockerfile
├── compose.yaml
├── .gitignore
├── data/                # bind-mounted runtime state (gitignored)
│   ├── .env.example     # template — copy to data/.env and fill in
│   ├── .env             # secrets (gitignored)
│   ├── informer.db      # sqlite (created on first run)
│   └── informer.session # telethon session (created by login.py, chmod 600)
├── informer_bot/
│   ├── config.py            # loads .env, exposes typed settings
│   ├── db.py                # sqlite schema + queries (sync, single-file)
│   ├── i18n.py              # EN/RU UI strings + t() helper
│   ├── summarizer.py        # claude summarize/is_relevant + openai embed_summary + cost estimates
│   ├── dedup.py             # cosine similarity + find_duplicate(per-user, time-windowed)
│   ├── client.py            # telethon: list channels, NewMessage handler
│   ├── album.py             # buffer-and-flush coalescer for multi-photo albums
│   ├── pipeline.py          # handle_new_post + refresh_channels glue
│   ├── bot.py               # ptb handlers: commands, inline keyboards, callbacks
│   ├── webapp.py            # aiohttp server for the Mini App (initData verify + JSON API)
│   ├── remote_processor.py  # bus-group client: send request, await reply, health state
│   ├── fallback_dispatcher.py  # routes summarize/is_relevant/embed: remote when healthy, fallback otherwise
│   └── main.py              # wires client + bot in one asyncio loop
├── processor_bot/           # optional sidecar bot — runs Ollama on a GPU host (see processor-bot.md)
│   ├── config.py
│   ├── handlers.py          # op→handler dispatch (summarize/is_relevant/embed/ping)
│   ├── bot.py               # telethon listener + rate-limited replies
│   └── main.py
├── shared/                  # tiny shared package imported by both bots
│   └── protocol.py          # JSON wire format: requests, replies, encode/decode
├── webapp/                  # Mini App static SPA (served by webapp.py when MINIAPP_URL set)
│   ├── index.html
│   ├── style.css            # uses --tg-theme-* CSS vars for native look
│   └── app.js               # talks to /api/* with X-Telegram-Init-Data header
├── login.py                 # one-time interactive: phone + code → .session
└── tests/
    ├── test_db.py
    ├── test_summarizer.py
    ├── test_bot_handlers.py
    ├── test_album.py
    ├── test_dedup.py
    ├── test_pipeline.py
    ├── test_protocol.py
    ├── test_remote_processor.py
    ├── test_fallback_dispatcher.py
    └── test_processor_handlers.py
```

## TDD order

1. `db.py` — pure SQLite, easiest. Write failing test → implement → green.
2. `summarizer.py` — anthropic SDK call mocked in tests.
3. `bot.py` handlers — ptb's `Application` + a fake `Update`/`Context`.
4. `client.py` — thin Telethon wrapper, smoke-tested with mocked `TelegramClient`.
5. `main.py` — wiring; verified manually (UI behaviour can't be unit-tested).
