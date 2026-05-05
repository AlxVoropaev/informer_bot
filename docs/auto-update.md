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
