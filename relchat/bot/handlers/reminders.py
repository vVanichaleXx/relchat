from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import format_invalid_date_message, format_reminder_detail, format_reminder_list, format_reminders_home
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings
from relchat.bot.keyboards import reminder_actions_keyboard, reminder_list_keyboard, reminders_home_keyboard
from relchat.bot.services.reminder_service import parse_reminder_time, reminder_counts
from relchat.bot.state import AWAITING_TEXT, EDIT_REMINDER_TARGET
from relchat.database.repositories import (
    get_reminder,
    get_user_settings,
    list_reminders,
    update_reminder_status,
    update_reminder_time,
)
from relchat.database.sqlite import connect, init_db


async def show_reminders_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        counts = reminder_counts(conn, user_id)
        language = get_user_settings(conn, user_id).get("language", "en")
    await edit_or_reply(update, format_reminders_home(counts), reply_markup=reminders_home_keyboard(language))


async def handle_reminders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "reminders":
        await show_reminders_home(update, context)
        return True
    if len(parts) < 2 or parts[1] != "rem":
        return False
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    if len(parts) >= 4 and parts[2] == "list":
        status = parts[3]
        with connect(settings.db_path) as conn:
            reminders = list_reminders(conn, user_id, status=status, limit=30)
            language = get_user_settings(conn, user_id).get("language", "en")
        await edit_or_reply(
            update,
            format_reminder_list(status.title(), reminders),
            reply_markup=reminder_list_keyboard(reminders, language=language),
        )
        return True
    if len(parts) >= 4 and parts[2] == "open":
        await open_reminder(update, context, parts[3])
        return True
    if len(parts) >= 5 and parts[2] == "status":
        reminder_id = parts[3]
        status = parts[4]
        if status not in {"suggested", "confirmed", "completed", "dismissed"}:
            return True
        with connect(settings.db_path) as conn:
            update_reminder_status(conn, reminder_id, user_id, status)
        await open_reminder(update, context, reminder_id)
        return True
    if len(parts) >= 4 and parts[2] == "edit":
        context.user_data[AWAITING_TEXT] = "reminder_time"
        context.user_data[EDIT_REMINDER_TARGET] = parts[3]
        await edit_or_reply(update, "Send the reminder date/time. Examples: 2026-07-13, 13.07.2026, 7 days.")
        return True
    return False


async def open_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder_id: str) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        reminder = get_reminder(conn, reminder_id)
        language = get_user_settings(conn, user_id).get("language", "en")
    if not reminder or reminder["bot_user_id"] != user_id:
        await edit_or_reply(update, "This reminder is no longer available.")
        return
    await edit_or_reply(update, format_reminder_detail(reminder), reply_markup=reminder_actions_keyboard(reminder, language=language))


async def handle_reminders_text(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, text: str) -> bool:
    if mode != "reminder_time":
        return False
    reminder_id = context.user_data.get(EDIT_REMINDER_TARGET)
    if not isinstance(reminder_id, str):
        context.user_data[AWAITING_TEXT] = None
        return True
    reminder_time = parse_reminder_time(text)
    if reminder_time is None:
        await edit_or_reply(update, format_invalid_date_message())
        return True
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        update_reminder_time(conn, reminder_id, user_id, reminder_time)
    context.user_data[AWAITING_TEXT] = None
    context.user_data.pop(EDIT_REMINDER_TARGET, None)
    await open_reminder(update, context, reminder_id)
    return True
