from __future__ import annotations

from relchat.bot.state import iso_date, parse_user_date
from relchat.database.repositories import list_reminders


REMINDER_STATUSES = ("suggested", "confirmed", "completed", "dismissed")


def reminder_counts(conn, bot_user_id: int) -> dict[str, int]:
    return {status: len(list_reminders(conn, bot_user_id, status=status, limit=1000)) for status in REMINDER_STATUSES}


def parse_reminder_time(value: str) -> str | None:
    parsed = parse_user_date(value)
    return iso_date(parsed)
