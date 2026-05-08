# TODO(security): pin to a sha256 digest for supply-chain integrity. Run:
#   docker pull ghcr.io/astral-sh/uv:python3.12-bookworm-slim
#   docker inspect ghcr.io/astral-sh/uv:python3.12-bookworm-slim --format '{{.RepoDigests}}'
# then replace the tag below with `...:python3.12-bookworm-slim@sha256:<digest>`.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG UID
ARG GID

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/informer.db \
    SESSION_PATH=/app/data/informer

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project

RUN groupadd -g "${GID}" app \
 && useradd -u "${UID}" -g "${GID}" -d /home/app -m -s /bin/sh app

COPY --chown=app:app informer_bot ./informer_bot
COPY --chown=app:app shared ./shared
COPY --chown=app:app webapp ./webapp
COPY --chown=app:app login.py ./login.py

RUN mkdir -p /app/data && chown app:app /app/data

USER app

CMD ["uv", "run", "--no-sync", "python", "-m", "informer_bot.main"]
