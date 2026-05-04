#!/usr/bin/env bash
# Cleans every common dev/runtime cache. Run as your user; sudo only where needed.
# Each block is gated on the relevant tool being installed.
set -u

have() { command -v "$1" >/dev/null 2>&1; }

if have apt-get; then
    echo "=== apt ==="
    sudo apt-get clean
    sudo apt-get autoclean
    sudo apt-get autoremove -y
    sudo rm -rf /var/lib/apt/lists/*
fi

echo "=== HuggingFace / fastembed / torch ==="
rm -rf ~/.cache/huggingface
rm -rf /tmp/fastembed_cache
rm -rf ~/.cache/torch
rm -rf ~/.cache/sentence_transformers

if have uv; then
    echo "=== uv ==="
    uv cache clean
fi
rm -rf ~/.cache/uv

if have pip; then
    echo "=== pip ==="
    pip cache purge || true
fi
rm -rf ~/.cache/pip

if have docker; then
    echo "=== Docker ==="
    docker system prune -af --volumes
    docker builder prune -af
fi

if have npm; then
    echo "=== npm ==="
    npm cache clean --force
fi
if have yarn; then
    echo "=== yarn ==="
    yarn cache clean
fi
if have pnpm; then
    echo "=== pnpm ==="
    pnpm store prune
fi
rm -rf ~/.npm ~/.yarn/cache ~/.pnpm-store ~/.cache/node-gyp

echo "=== Python build artifacts (cwd) ==="
find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache -o -name .tox \) -prune -exec rm -rf {} +

if have cargo; then
    echo "=== Cargo ==="
    rm -rf ~/.cargo/registry/cache ~/.cargo/registry/src ~/.cargo/git/checkouts
fi

if have go; then
    echo "=== Go ==="
    go clean -cache -modcache -testcache
fi

if have ccache; then
    echo "=== ccache ==="
    ccache -C
fi

echo "=== generic user caches ==="
rm -rf ~/.cache/thumbnails ~/.cache/pip-tools ~/.cache/playwright

if have journalctl; then
    echo "=== systemd journal (keep last 100M) ==="
    sudo journalctl --vacuum-size=100M
fi

echo "=== /tmp & /var/tmp (files older than 1d) ==="
sudo find /tmp /var/tmp -type f -atime +1 -delete 2>/dev/null || true

echo "=== Done ==="
df -h /
