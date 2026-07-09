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
    data_dir: Path
    db_path: Path
    session_path: Path


def get_settings() -> Settings:
    load_dotenv()
    data_dir = Path(os.environ.get("RELCHAT_DATA_DIR", ROOT / "data")).expanduser()
    db_path = Path(os.environ.get("RELCHAT_DB_PATH", data_dir / "relchat.sqlite3")).expanduser()
    session_path = Path(os.environ.get("RELCHAT_SESSION_PATH", data_dir / "telegram.session")).expanduser()
    api_id_raw = os.environ.get("TELEGRAM_API_ID")
    api_id = int(api_id_raw) if api_id_raw and api_id_raw.isdigit() else None
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        data_dir=data_dir,
        db_path=db_path,
        session_path=session_path,
    )


def require_telegram_credentials(settings: Settings) -> tuple[int, str]:
    if settings.api_id is None or not settings.api_hash:
        raise SystemExit(
            "Missing Telegram credentials. Set TELEGRAM_API_ID and TELEGRAM_API_HASH "
            "in .env or the environment. Create them at https://my.telegram.org/apps."
        )
    return settings.api_id, settings.api_hash
