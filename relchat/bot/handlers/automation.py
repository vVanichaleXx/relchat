from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import format_job_progress
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings
from relchat.bot.keyboards import job_progress_keyboard, main_keyboard
from relchat.bot.localization import t
from relchat.bot.services.analysis_jobs import start_background_job
from relchat.bot.state import DEFAULT_MODULE_IDS
from relchat.database.repositories import (
    create_analysis_job,
    get_pending_automatic_notification,
    get_user_settings,
    list_user_messages,
    update_automatic_notification_status,
    update_important_chat_setting,
    update_user_setting,
)
from relchat.database.sqlite import connect


async def handle_automation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) < 3 or parts[1] != "auto":
        return False
    action = parts[2]
    notification_id = parts[3] if len(parts) >= 4 else ""
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        notification = get_pending_automatic_notification(conn, user_id, notification_id) if notification_id else None
    if action == "disable_all":
        with connect(settings.db_path) as conn:
            update_user_setting(conn, user_id, "automatic_analysis_master_enabled", False)
        await edit_or_reply(update, t(language, "automation_disabled"), reply_markup=main_keyboard(language))
        return True
    if not notification:
        await edit_or_reply(update, t(language, "expired_navigation"), reply_markup=main_keyboard(language))
        return True
    if action == "notnow":
        with connect(settings.db_path) as conn:
            update_automatic_notification_status(conn, user_id, notification_id, "dismissed")
        await edit_or_reply(update, t(language, "button_not_now"), reply_markup=main_keyboard(language))
        return True
    if action == "disable":
        with connect(settings.db_path) as conn:
            update_important_chat_setting(conn, user_id, notification["source"], notification["chat_id"], "automatic_analysis_enabled", False)
            update_automatic_notification_status(conn, user_id, notification_id, "dismissed")
        await edit_or_reply(update, t(language, "automation_disabled"), reply_markup=main_keyboard(language))
        return True
    if action == "analyze":
        await start_analysis_from_notification(update, context, notification, language=language)
        return True
    return False


async def start_analysis_from_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, notification: dict, *, language: str) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    query = update.callback_query
    progress_chat_id = query.message.chat_id if query and query.message else None
    progress_message_id = query.message.message_id if query and query.message else None
    with connect(settings.db_path) as conn:
        messages = [
            message
            for message in list_user_messages(conn, user_id, notification["chat_id"], source=notification["source"])
            if notification["range_start_message_id"] <= message.source_message_id <= notification["range_end_message_id"]
        ]
        period_start = messages[0].timestamp if messages else None
        period_end = messages[-1].timestamp if messages else None
        user_settings = get_user_settings(conn, user_id)
        job = create_analysis_job(
            conn,
            bot_user_id=user_id,
            source=notification["source"],
            chat_id=notification["chat_id"],
            chat_title=notification.get("chat_title"),
            period_id="automatic_pause",
            period_label="Automatic paused conversation",
            period_start=period_start,
            period_end=period_end,
            modules=user_settings.get("default_modules") or DEFAULT_MODULE_IDS,
            progress_chat_id=progress_chat_id,
            progress_message_id=progress_message_id,
            analysis_mode="local",
        )
        update_automatic_notification_status(conn, user_id, notification["notification_id"], "accepted")
    await edit_or_reply(update, format_job_progress(job), reply_markup=job_progress_keyboard(job["job_id"], language=language))
    start_background_job(context.application, settings, job["job_id"])
