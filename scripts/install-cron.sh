#!/usr/bin/env bash
# Install (or refresh) the cron entry that runs scripts/deploy.sh every 1 minutes.
# Idempotent — re-running replaces the existing entry instead of duplicating it.
set -euo pipefail

deploy_script="$(cd "$(dirname "$0")" && pwd)/deploy.sh"
marker="# informer_bot deploy"
schedule="*/1 * * * *"

if [[ ! -x "$deploy_script" ]]; then
    echo "deploy.sh not found or not executable at $deploy_script" >&2
    exit 1
fi

current=$(crontab -l 2>/dev/null || true)
filtered=$(printf '%s\n' "$current" | grep -vF "$marker" || true)
new_entry="$schedule $deploy_script $marker"

printf '%s\n%s\n' "$filtered" "$new_entry" | sed '/^$/d' | crontab -

echo "installed cron entry:"
echo "  $new_entry"
