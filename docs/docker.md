# Run with Docker Compose

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

1. Fill in `data/.env` (see [setup.md](setup.md)).

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
