from __future__ import annotations

from pathlib import Path

from relchat.config import Settings, require_telegram_credentials
from relchat.bot.services.telethon_lifecycle import safe_disconnect
from relchat.telegram.normalizer import display_name
from relchat.utils.files import ensure_private_parent, protect_existing_file


def import_telethon():
    try:
        from telethon import TelegramClient
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Telethon is not installed. Install dependencies with: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return TelegramClient


def secure_session_path(path: Path) -> str:
    ensure_private_parent(path)
    return str(path)


def protect_session_file(path: Path) -> None:
    for candidate in [path, path.with_suffix(path.suffix + ".session"), Path(str(path) + ".session")]:
        protect_existing_file(candidate)


def make_client(settings: Settings):
    TelegramClient = import_telethon()
    api_id, api_hash = require_telegram_credentials(settings)
    session = secure_session_path(settings.session_path)
    return TelegramClient(session, api_id, api_hash)


async def login(settings: Settings, phone: str | None = None) -> None:
    client = make_client(settings)
    await client.start(phone=phone)
    me = await client.get_me()
    await safe_disconnect(client)
    protect_session_file(settings.session_path)
    name = display_name(me)
    print(f"Logged in as {name} ({getattr(me, 'id', 'unknown')}).")
    print(f"Session stored locally at {settings.session_path}. Keep this file private.")
