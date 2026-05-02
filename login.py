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
    tg = TelegramClient(cfg.session_path, cfg.telegram_api_id, cfg.telegram_api_hash)
    await tg.start()
    me = await tg.get_me()
    print(f"Logged in as @{me.username or me.first_name} (id={me.id}).")
    await tg.disconnect()

    session_file = Path(f"{cfg.session_path}.session")
    if session_file.exists():
        os.chmod(session_file, 0o600)
        print(f"Set {session_file} to 0600.")


if __name__ == "__main__":
    asyncio.run(main())
