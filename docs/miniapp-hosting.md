# Mini App URL & hosting

The Mini App is the primary user surface — channel selection, filters, and
language live there. To enable it you need a public HTTPS URL Telegram can
reach, set as `MINIAPP_URL`.

## Where do I get `MINIAPP_URL`?

You provide it yourself — it's the **public HTTPS URL where Telegram can reach
the bot's built-in Mini App server.** The bot serves `webapp/index.html` from
`http://WEBAPP_HOST:WEBAPP_PORT/`; you put HTTPS in front and give Telegram
that URL. Plain HTTP is rejected by the Telegram client.

Three common ways:

### 1. Quick local test — cloudflared (no signup, no account)

```sh
cloudflared tunnel --url http://localhost:8085
# → https://random-words-1234.trycloudflare.com
```

Put that URL into `MINIAPP_URL`, restart the bot. URL changes every run.

> ⚠️ Russian mobile carriers DPI-block `*.trycloudflare.com`, and Telegram's
> in-app WebView inherits the Telegram app's split-tunnel bypass — so the
> WebView can't reach trycloudflare URLs even when the system browser can.
> Use only for local testing.

### 2. Quick local test — ngrok (free account)

```sh
ngrok http 8085
# → https://abcd-1-2-3-4.ngrok-free.app
```

### 3. Production — your own host

If the bot already runs on a VPS with a domain, put a reverse proxy
(Caddy / nginx with Let's Encrypt) in front of `WEBAPP_PORT` and use that
HTTPS domain. With Caddy:

```caddyfile
miniapp.example.com {
    reverse_proxy localhost:8085
}
```

Then `MINIAPP_URL=https://miniapp.example.com`.

## Default `compose.yaml` setup — Caddy + Let's Encrypt

The bundled `compose.yaml` runs `caddy:2-alpine` as a reverse-proxy sidecar
that auto-fetches and renews HTTPS certificates from Let's Encrypt. **You
need a domain pointing at this host's public IP and ports 80 + 443 open**
(80 is required for the ACME HTTP-01 challenge).

### Setup

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

### Why Caddy and not Cloudflare's quick tunnel?

Russian mobile carriers DPI-block `*.trycloudflare.com`, and Telegram's
in-app WebView inherits the Telegram app's split-tunnel bypass — so the
WebView can't reach trycloudflare URLs even when the system browser can. A
plain VPS IP behind a domain bypasses both problems.

### Caveats

- Don't run anything else on ports 80 / 443 on the host.
- Free dynamic DNS subdomains (DuckDNS, FreeDNS) work fine but propagate
  slowly the first time — wait a couple of minutes after creating the
  record before starting Caddy.
