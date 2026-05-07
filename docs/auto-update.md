# Auto-update from GitHub

Pull-based: a cron job checks `origin/main` every minute and rebuilds the
container only when there's a new commit. No inbound ports, no secrets, no
GitHub Actions.

1. Install the cron entry once:
   ```sh
   ./scripts/install-cron.sh
   ```
   This is idempotent — re-running just refreshes the entry (it's tagged
   `# informer_bot deploy`).

2. The cron line runs [scripts/deploy.sh](../scripts/deploy.sh), which:
   - compares local `HEAD` vs `origin/main` and exits if they match (no
     rebuild churn);
   - on a new commit: `git pull --ff-only origin main` then
     `docker compose up -d --build`;
   - appends output to `data/deploy.log`.

3. Watch it work:
   ```sh
   tail -f data/deploy.log
   ```

If `docker` or `git` aren't found when cron runs, prepend
`export PATH=/usr/local/bin:/usr/bin:/bin` to `scripts/deploy.sh`.

To uninstall: `crontab -l | grep -v 'informer_bot deploy' | crontab -`.

## processor_bot (GPU host)

Same idea, separate scripts. On the GPU host, after cloning the repo and
filling in `data/.env`:

```sh
./scripts/install-cron-processor.sh
```

Tagged `# processor_bot deploy`. The cron line runs
[scripts/deploy-processor.sh](../scripts/deploy-processor.sh), which fetches
`origin/main` and rebuilds via `docker compose -f compose.processor.yaml up
-d --build` only on a new commit. Logs to `data/deploy-processor.log`.

The processor image (`Dockerfile.processor`) is leaner than informer's: no
Mini App, no Caddy. It runs `python -m processor_bot` and reaches Ollama on
the host via `host.docker.internal` (set
`OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` in `data/.env`).

To uninstall: `crontab -l | grep -v 'processor_bot deploy' | crontab -`.
