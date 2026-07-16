from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    api_id: int | None
    api_hash: str | None
    telegram_bot_token: str | None
    allowed_user_ids: frozenset[int]
    data_dir: Path
    db_path: Path
    session_path: Path
    ux_audit_enabled: bool = False
    ux_audit_max_events: int = 1000
    ux_audit_include_user_text: bool = False
    ux_audit_path: Path | None = None
    openai_api_key: str | None = None
    ai_enabled: bool = False
    ai_model: str | None = None
    ai_max_messages: int = 300
    ai_max_chars: int = 30000
    ai_timeout_seconds: int = 90


def parse_allowed_user_ids(value: str | None) -> frozenset[int]:
    if not value or not value.strip():
        return frozenset()
    user_ids = set()
    for item in value.replace(",", " ").split():
        if not item.isdigit():
            raise SystemExit(
                "Invalid RELCHAT_ALLOWED_USER_IDS. Use comma-separated numeric Telegram user IDs."
            )
        user_ids.add(int(item))
    return frozenset(user_ids)


def parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def parse_positive_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def get_settings() -> Settings:
    load_dotenv()
    data_dir = Path(os.environ.get("RELCHAT_DATA_DIR", ROOT / "data")).expanduser()
    db_path = Path(os.environ.get("RELCHAT_DB_PATH", data_dir / "relchat.sqlite3")).expanduser()
    session_path = Path(os.environ.get("RELCHAT_SESSION_PATH", data_dir / "telegram.session")).expanduser()
    ux_audit_path = Path(os.environ.get("RELCHAT_UX_AUDIT_PATH", data_dir / "logs" / "ux-audit.jsonl")).expanduser()
    api_id_raw = os.environ.get("TELEGRAM_API_ID")
    api_id = int(api_id_raw) if api_id_raw and api_id_raw.isdigit() else None
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or None
    allowed_user_ids = parse_allowed_user_ids(os.environ.get("RELCHAT_ALLOWED_USER_IDS"))
    openai_api_key = os.environ.get("OPENAI_API_KEY") or None
    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        telegram_bot_token=telegram_bot_token,
        allowed_user_ids=allowed_user_ids,
        data_dir=data_dir,
        db_path=db_path,
        session_path=session_path,
        ux_audit_enabled=parse_bool(os.environ.get("RELCHAT_UX_AUDIT_ENABLED"), default=False),
        ux_audit_max_events=parse_positive_int(os.environ.get("RELCHAT_UX_AUDIT_MAX_EVENTS"), default=1000),
        ux_audit_include_user_text=parse_bool(os.environ.get("RELCHAT_UX_AUDIT_INCLUDE_USER_TEXT"), default=False),
        ux_audit_path=ux_audit_path,
        openai_api_key=openai_api_key,
        ai_enabled=parse_bool(os.environ.get("RELCHAT_AI_ENABLED"), default=False),
        ai_model=os.environ.get("RELCHAT_AI_MODEL") or None,
        ai_max_messages=parse_positive_int(os.environ.get("RELCHAT_AI_MAX_MESSAGES"), default=300),
        ai_max_chars=parse_positive_int(os.environ.get("RELCHAT_AI_MAX_CHARS"), default=30000),
        ai_timeout_seconds=parse_positive_int(os.environ.get("RELCHAT_AI_TIMEOUT_SECONDS"), default=90),
    )


def require_telegram_credentials(settings: Settings) -> tuple[int, str]:
    if settings.api_id is None or not settings.api_hash:
        raise SystemExit(
            "Missing Telegram credentials. Set TELEGRAM_API_ID and TELEGRAM_API_HASH "
            "in .env or the environment. Create them at https://my.telegram.org/apps."
        )
    return settings.api_id, settings.api_hash
