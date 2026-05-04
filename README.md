# Informer Bot

A Telegram bot that summarises posts from public channels and DMs you a short brief plus a link to the original.

## How it works

1. The admin subscribes their account to public channels.
2. You pick which of those channels you want to follow.
3. When a new post lands in a channel you follow, the bot DMs you a one-sentence summary in the post's original language. The channel's name is shown as a clickable link to the original post, and if the post had a photo (or for albums, the first photo) it's attached.

## Commands

Channel selection, filters, and language all live in the **Mini App** —
Telegram's in-app HTML surface. Open it from the bot's burger menu (≡, left of
the input box) or run `/app`. Every Telegram client (mobile, desktop, web)
supports Mini Apps, so use it for everything below.

In the Mini App you can:
- Tap a channel to open its details and pick a delivery mode:
  - ⬜ Off — saved filter is preserved
  - 🔀 Filtered — only posts matching this channel's filter
  - 🐞 Debug — every post; ones the filter would have rejected are tagged `🐞 FILTERED`
  - ✅ All — every post
- Set a per-channel filter (plain language) in the textarea. Saving a filter
  from Off auto-bumps the channel to Filtered.
- Switch interface language (English / Русский) and view your usage from the
  top bar (📊 button).
- Open the source channel in Telegram via the 🔗 link.

Telegram commands (small surface — everything else is in the Mini App):

- `/start` — request access. New users wait for the admin to approve.
- `/app` — replies with a button that opens the Mini App.
- `/usage` — your token usage and estimated cost (also in the Mini App).
- `/help` — list available commands.

### Admin commands

If you're the bot's `OWNER_ID`, you also get:

- `/blacklist` — toggle channels on/off the public list (channels you've subscribed to but don't want to expose to bot users).
- `/update` — refresh the channel list from your Telegram subscriptions (run after subscribing to or leaving a channel).
- New `/start` requests come to you as an inline Allow / Deny prompt.

## What you'll receive

- One DM per new post, in the channel's language. The channel name is the link back to the original; the photo (if any) is attached.
- Albums (multi-photo posts) arrive as a single summary with the album's first photo.
- Image- or video-only posts (no text/caption) are skipped.
- Edits to existing posts are ignored.
- **Restart catch-up.** If the bot was offline for a while, on startup it replays posts that arrived during the downtime (per channel, capped to the last 48h via `CATCH_UP_WINDOW_HOURS`). Channels you've never received anything from yet aren't backfilled.
- **Duplicates merge.** If the same story shows up in another channel within ~48 hours, the bot adds a new inline URL button (labeled with the source channel) under your original DM instead of sending a second one. In 🐞 debug mode, you instead get a fresh DM prefixed with `🔁 DUPLICATE` so you can see what was deduped.

## Notes

- If a channel disappears from the Mini App, the admin either unsubscribed from it or blacklisted it. You'll get a one-time DM saying it's no longer available.
- When the admin adds a new channel, you'll get a DM with a button that opens the Mini App straight to that channel's details — pick a mode there.
- Only the admin can add or remove channels from the list — there's no way to request new ones through the bot.

## Setup (self-hosting)

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), and a Telegram account that's subscribed to the channels you want to track.

1. **Install dependencies**
   ```sh
   uv sync
   ```

2. **Get credentials**
   - `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` — from [my.telegram.org](https://my.telegram.org).
   - `TELEGRAM_BOT_TOKEN` — create a bot via [@BotFather](https://t.me/BotFather).
   - `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com).
   - `OPENAI_API_KEY` — *optional*, from [platform.openai.com](https://platform.openai.com). Used for summary embeddings (dedup); cost is negligible (~$0.02 per million tokens with `text-embedding-3-small`). If you leave it blank, the bot starts fine — deduplication is just disabled, and the owner gets a one-time DM at startup saying so.
   - `OWNER_ID` — your numeric Telegram user ID (ask [@userinfobot](https://t.me/userinfobot)).

#### Embedding provider (deduplication)

Optional, controls how summary embeddings for dedup are computed:

| Var | Values | Default | Notes |
| --- | --- | --- | --- |
| `EMBEDDING_PROVIDER` | `auto` \| `openai` \| `local` \| `none` | `auto` | `auto` picks `openai` if `OPENAI_API_KEY` is set, otherwise `none`. |
| `LOCAL_EMBEDDING_MODEL` | any [fastembed](https://github.com/qdrant/fastembed) model name | `intfloat/multilingual-e5-large` | Only used when provider is `local`. |
| `LOCAL_EMBEDDING_DEVICE` | `cpu` \| `cuda` | `cpu` | `cuda` requires installing `fastembed-gpu` instead of `fastembed`. |
| `DEDUP_THRESHOLD` | float 0..1 | `0.85` | Cosine similarity at or above which two posts count as the same story. |
| `DEDUP_WINDOW_HOURS` | int | `48` | How far back to look for duplicates per user. |
| `CATCH_UP_WINDOW_HOURS` | int | `48` | On restart, replay missed posts up to this age. Set to `0` if you don't want any backfill. |
| `MINIAPP_URL` | full HTTPS URL | *(unset)* | Public URL where Telegram can fetch the Mini App frontend. **Required for regular users** — channel selection, filters, and language live only in the Mini App. See [Where do I get this URL?](#where-do-i-get-miniapp_url) below. When set, the bot starts an in-process aiohttp server on `WEBAPP_HOST:WEBAPP_PORT`, registers the burger-menu launcher, and `/app` becomes available. |
| `WEBAPP_HOST` | host | `0.0.0.0` | Bind address for the Mini App server. |
| `WEBAPP_PORT` | int | `8085` | Bind port for the Mini App server. |

#### Where do I get `MINIAPP_URL`?

You provide it yourself — it's the **public HTTPS URL where Telegram can reach
the bot's built-in Mini App server.** The bot serves `webapp/index.html` from
`http://WEBAPP_HOST:WEBAPP_PORT/`; you put HTTPS in front and give Telegram
that URL. Plain HTTP is rejected by the Telegram client.

Three common ways:

1. **Quick local test — cloudflared (no signup, no account):**
   ```sh
   cloudflared tunnel --url http://localhost:8085
   # → https://random-words-1234.trycloudflare.com
   ```
   Put that URL into `MINIAPP_URL`, restart the bot. URL changes every run.

2. **Quick local test — ngrok (free account):**
   ```sh
   ngrok http 8085
   # → https://abcd-1-2-3-4.ngrok-free.app
   ```

3. **Production — your own host.** If the bot already runs on a VPS with a
   domain, put a reverse proxy (Caddy / nginx with Let's Encrypt) in front of
   `WEBAPP_PORT` and use that HTTPS domain. With Caddy:
   ```caddyfile
   miniapp.example.com {
       reverse_proxy localhost:8085
   }
   ```
   Then `MINIAPP_URL=https://miniapp.example.com`.

##### Default `compose.yaml` setup — Caddy + Let's Encrypt

The bundled `compose.yaml` runs `caddy:2-alpine` as a reverse-proxy sidecar
that auto-fetches and renews HTTPS certificates from Let's Encrypt. **You
need a domain pointing at this host's public IP and ports 80 + 443 open**
(80 is required for the ACME HTTP-01 challenge).

Setup:
1. **Get a domain.** Cheapest option: sign up for [DuckDNS](https://www.duckdns.org/)
   (free, takes 2 minutes) and create a subdomain like
   `informer-yourname.duckdns.org` pointing at your VPS IP. Or use any
   domain you already control.
2. **Add to `data/.env`:**
   ```
   MINIAPP_DOMAIN=informer-yourname.duckdns.org
   MINIAPP_URL=https://informer-yourname.duckdns.org:8443
   ```
   The bundled compose.yaml serves HTTPS on **port 8443**, not 443, because
   the host where this was first deployed already had MTProto VPN on 443.
   Telegram Mini Apps accept non-443 HTTPS URLs. If 443 is free on your
   host, edit `Caddyfile` (drop the `:8443`) and `compose.yaml` (change
   `8443:8443` to `443:443`), and remove the `:8443` from `MINIAPP_URL`.
3. **Open the firewall** for ports 80 and 8443:
   ```sh
   sudo ufw allow 80/tcp && sudo ufw allow 8443/tcp
   ```
   (Plus your cloud provider's security group, if applicable.) Port 80 is
   still required for Let's Encrypt's HTTP-01 challenge.
4. **Bring it up:**
   ```sh
   HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d --build
   docker compose logs -f caddy
   ```
   First boot, Caddy fetches the cert (5–30 seconds). Once you see
   `certificate obtained successfully`, the Mini App is live at
   `https://$MINIAPP_DOMAIN`.

Why Caddy and not Cloudflare's quick tunnel? Russian mobile carriers
DPI-block `*.trycloudflare.com`, and Telegram's in-app WebView inherits the
Telegram app's split-tunnel bypass — so the WebView can't reach trycloudflare
URLs even when the system browser can. A plain VPS IP behind a domain
bypasses both problems.

Caveats:
- Don't run anything else on ports 80 / 443 on the host.
- Free dynamic DNS subdomains (DuckDNS, FreeDNS) work fine but propagate
  slowly the first time — wait a couple of minutes after creating the
  record before starting Caddy.

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

3. **Configure `.env`** (lives in `data/` so it's bind-mounted into the container, not baked into the image)
   ```sh
   cp data/.env.example data/.env
   # then fill in the five values above
   ```

4. **Log in to your Telegram account once** (creates `data/informer.session`, chmod 600):
   ```sh
   uv run python login.py
   ```
   You'll be asked for your phone number and the code Telegram sends you.

5. **Run the bot**
   ```sh
   uv run python -m informer_bot.main
   ```

The process runs both the user-account client (reads channels) and the bot (talks to subscribers) in one asyncio loop. Keep it running — there's no built-in daemonisation.

### Run with Docker Compose

Requirements: Docker with the Compose plugin.

The image is built as a non-root user matching your host uid/gid, so files
written to `./data/` stay owned by you. Pass them at build time from the shell —
they are not stored in `.env`. Bash's `$UID` is a readonly built-in and cannot
be re-exported, so compose reads `HOST_UID` / `HOST_GID` instead:

```sh
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose build
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d
```

Tip: stick that prefix in a shell alias, or `export HOST_UID=$(id -u) HOST_GID=$(id -g)` once per shell.

1. Fill in `data/.env` (step 3 above).

2. **One-time Telethon login** — interactive, asks for your phone number and the code Telegram sends:
   ```sh
   docker compose run --rm bot uv run python login.py
   ```
   This creates `data/informer.session` on the host (the `./data` directory is bind-mounted into the container).

3. **Start the bot:**
   ```sh
   docker compose up -d
   docker compose logs -f bot
   ```

4. **Restart** (e.g. to pick up config or code changes):
   ```sh
   docker compose restart bot
   ```
   For an image rebuild after code changes:
   ```sh
   HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d --build
   ```

5. **Stop:**
   ```sh
   docker compose down
   ```

State (`.env`, `informer.db`, `informer.session`) all live in `./data/` on the host. Back that directory up if you care about your subscriptions and seen-message dedupe.

### Auto-update from GitHub

Pull-based: a cron job checks `origin/main` every minute and rebuilds the container only when there's a new commit. No inbound ports, no secrets, no GitHub Actions.

1. Install the cron entry once:
   ```sh
   ./scripts/install-cron.sh
   ```
   This is idempotent — re-running just refreshes the entry (it's tagged `# informer_bot deploy`).

2. The cron line runs [scripts/deploy.sh](scripts/deploy.sh), which:
   - compares local `HEAD` vs `origin/main` and exits if they match (no rebuild churn);
   - on a new commit: `git pull --ff-only origin main` then `docker compose up -d --build`;
   - appends output to `data/deploy.log`.

3. Watch it work:
   ```sh
   tail -f data/deploy.log
   ```

If `docker` or `git` aren't found when cron runs, prepend `export PATH=/usr/local/bin:/usr/bin:/bin` to `scripts/deploy.sh`. To uninstall: `crontab -l | grep -v 'informer_bot deploy' | crontab -`.

### Tests

```sh
uv run pytest
```
