"""CLI: ``uv run python -m informer_bot.cli_login --user-id <id>``.

Out-of-band tool for the host owner: takes a provider that the bot has
already approved (status='approved' in the `providers` table) and walks
through Telethon's interactive login on stdin, writing the resulting
session file to `provider.session_path`. The provider must be physically
present (or on the phone) to read out the SMS code and 2FA password.

Refuses to overwrite an existing session unless `--force` is given.

Re-uses the project's `data/.env` via `python-dotenv`. Reads
`TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (required) and `DB_PATH`
(optional, defaults to `data/informer.db`). It deliberately does NOT
go through `informer_bot.config.load_config()` because that loader
requires the full bot config (Anthropic / OpenAI keys, etc.) which is
unrelated to bootstrapping a Telethon session.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

from informer_bot.db import Database


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="informer-bot-login",
        description="Create a Telethon session for an approved provider.",
    )
    parser.add_argument(
        "--user-id", type=int, required=True,
        help="Telegram user id of the approved provider.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing session file.",
    )
    return parser.parse_args(argv)


async def _interactive_login(
    session_path: str, api_id: int, api_hash: str,
) -> None:
    client = TelegramClient(session_path, api_id, api_hash)
    try:
        await client.start()
    finally:
        await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    load_dotenv("data/.env")
    try:
        api_id = int(os.environ["TELEGRAM_API_ID"])
        api_hash = os.environ["TELEGRAM_API_HASH"]
    except KeyError as exc:
        print(
            f"missing env var {exc.args[0]} (set it in data/.env)",
            file=sys.stderr,
        )
        return 1
    db_path = os.environ.get("DB_PATH", "data/informer.db")

    db = Database(db_path)
    provider = db.get_provider(args.user_id)
    if provider is None:
        print(
            f"no provider request for user {args.user_id}; ask them to run "
            f"/become_provider in the bot first",
            file=sys.stderr,
        )
        return 1
    if provider.status == "pending":
        print(
            f"provider {args.user_id} is still pending owner approval",
            file=sys.stderr,
        )
        return 1
    if provider.status == "denied":
        print(
            f"provider {args.user_id} was denied; cannot create session",
            file=sys.stderr,
        )
        return 1

    session_file = Path(provider.session_path)
    if session_file.exists() and not args.force:
        print(
            f"session file already exists at {session_file}; pass --force "
            f"to overwrite",
            file=sys.stderr,
        )
        return 1

    session_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(session_file.parent, 0o700)
    except OSError:
        pass

    try:
        asyncio.run(_interactive_login(str(session_file), api_id, api_hash))
    except Exception as exc:  # noqa: BLE001 -- surface any Telethon failure.
        print(f"login failed: {exc}", file=sys.stderr)
        return 1

    try:
        os.chmod(session_file, 0o600)
    except OSError:
        pass

    print(f"session written to {session_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
