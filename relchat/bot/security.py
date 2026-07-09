from __future__ import annotations

from pathlib import Path
from typing import Any

from relchat.config import Settings


class BotSecurityError(RuntimeError):
    pass


def validate_bot_startup(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise BotSecurityError("Missing TELEGRAM_BOT_TOKEN. Set it in .env or the environment.")
    if not settings.allowed_user_ids:
        raise BotSecurityError(
            "RELCHAT_ALLOWED_USER_IDS is empty. Refusing to start a public bot. "
            "Set it to your numeric Telegram user ID."
        )


def is_allowed_update(update: Any, settings: Settings) -> bool:
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", None)
    return isinstance(user_id, int) and user_id in settings.allowed_user_ids


def is_private_chat(update: Any) -> bool:
    chat = getattr(update, "effective_chat", None)
    return getattr(chat, "type", None) == "private"


def mtproto_session_exists(path: Path) -> bool:
    return any(candidate.exists() for candidate in session_path_candidates(path))


def session_path_candidates(path: Path) -> list[Path]:
    return [path, path.with_suffix(path.suffix + ".session"), Path(str(path) + ".session")]
