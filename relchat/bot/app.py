from __future__ import annotations

from relchat.bot.security import BotSecurityError, validate_bot_startup
from relchat.config import Settings, get_settings
from relchat.database.repositories import mark_stale_running_jobs_failed
from relchat.database.sqlite import connect, init_db


def import_application_builder():
    try:
        from telegram.ext import ApplicationBuilder
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "python-telegram-bot is not installed. Install dependencies with: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return ApplicationBuilder


def run_bot(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    try:
        validate_bot_startup(settings)
    except BotSecurityError as exc:
        raise SystemExit(str(exc)) from exc

    ApplicationBuilder = import_application_builder()
    from relchat.bot.handlers import register_handlers

    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        mark_stale_running_jobs_failed(conn)

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.bot_data["settings"] = settings
    register_handlers(application)
    print(f"Starting RelChat bot. Allowed user IDs configured: {len(settings.allowed_user_ids)}.")
    application.run_polling()
    return 0
