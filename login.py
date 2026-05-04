"""One-time interactive Telethon login. Creates `<session_path>.session` with chmod 600.

Run once before `main.py`:
    uv run python login.py
"""
import asyncio
import os
from pathlib import Path

from telethon import TelegramClient

from informer_bot.config import load_config


async def main() -> None:
    cfg = load_config()

    # Pre-create the session file with restrictive permissions BEFORE Telethon
    # writes secrets into it. Otherwise Telethon would create it with the
    # process umask (typically 0o644 = world-readable) for a brief window.
    session_file = Path(f"{cfg.session_path}.session")
    if not session_file.exists():
        session_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(session_file, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)

    tg = TelegramClient(cfg.session_path, cfg.telegram_api_id, cfg.telegram_api_hash)
    await tg.start()
    me = await tg.get_me()
    print(f"Logged in as @{me.username or me.first_name} (id={me.id}).")
    await tg.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
