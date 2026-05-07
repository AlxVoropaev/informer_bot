#!/usr/bin/env bash
# Pull latest main and rebuild the processor container if anything changed.
# Intended to be run from cron on the GPU host. Logs to data/deploy-processor.log.
set -euo pipefail

cd "$(dirname "$0")/.."

git fetch --quiet origin main
local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse origin/main)

if [[ "$local_sha" == "$remote_sha" ]]; then
    exit 0
fi

exec >> data/deploy-processor.log 2>&1
echo "=== $(date -Is) updating $local_sha -> $remote_sha ==="
git pull --ff-only origin main
export HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f compose.processor.yaml up -d --build
echo "deploy complete"
