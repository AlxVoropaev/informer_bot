#!/usr/bin/env bash
# Pull latest main and rebuild the bot container if anything changed.
# Intended to be run from cron. Logs to data/deploy.log.
set -euo pipefail

cd "$(dirname "$0")/.."

exec >> data/deploy.log 2>&1
echo "=== $(date -Is) deploy check ==="

git fetch --quiet origin main
local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse origin/main)

if [[ "$local_sha" == "$remote_sha" ]]; then
    echo "up to date ($local_sha), nothing to do"
    exit 0
fi

echo "updating $local_sha -> $remote_sha"
git pull --ff-only origin main
export HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose up -d --build
echo "deploy complete"
