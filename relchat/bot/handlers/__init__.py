from __future__ import annotations

from typing import Any

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from relchat.bot.handlers.analysis import handle_analysis_callback, handle_analysis_text
from relchat.bot.handlers.chat_home import handle_chat_home_callback
from relchat.bot.handlers.chats import handle_chats_callback, handle_chats_text
from relchat.bot.handlers.common import edit_or_reply, require_access, show_safe_error, user_language
from relchat.bot.handlers.debug import (
    debug_clear_command,
    debug_export_command,
    debug_status_command,
    handle_debug_callback,
)
from relchat.bot.handlers.developer import (
    chats_command,
    events_command,
    help_command,
    import_command,
    metrics_command,
    status_command,
)
from relchat.bot.handlers.navigation import handle_navigation_callback
from relchat.bot.handlers.onboarding import handle_onboarding_callback, start_command
from relchat.bot.handlers.reminders import handle_reminders_callback, handle_reminders_text
from relchat.bot.handlers.reports import handle_reports_callback
from relchat.bot.handlers.settings import handle_settings_callback, handle_settings_text
from relchat.bot.keyboards import main_keyboard
from relchat.bot.localization import t
from relchat.bot.services.ux_audit import callback_payload, incoming_text_payload, record_current_ux_event
from relchat.bot.state import AWAITING_TEXT, callback_parts


def register_handlers(application: Any) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("chats", chats_command))
    application.add_handler(CommandHandler("import", import_command))
    application.add_handler(CommandHandler("metrics", metrics_command))
    application.add_handler(CommandHandler("events", events_command))
    application.add_handler(CommandHandler("debug_status", debug_status_command))
    application.add_handler(CommandHandler(["debug_export", "debug_log", "debug_report"], debug_export_command))
    application.add_handler(CommandHandler("debug_clear", debug_clear_command))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is not None:
        await query.answer()
    if not await require_access(update, context):
        return
    raw_data = getattr(query, "data", None)
    parts = callback_parts(raw_data)
    record_current_ux_event("incoming_callback", update=update, payload=callback_payload(raw_data, parts))
    if not parts:
        return
    try:
        for handler in [
            handle_onboarding_callback,
            handle_navigation_callback,
            handle_chat_home_callback,
            handle_analysis_callback,
            handle_chats_callback,
            handle_reports_callback,
            handle_reminders_callback,
            handle_settings_callback,
            handle_debug_callback,
        ]:
            if await handler(update, context, parts):
                return
        language = user_language(update, context)
        await edit_or_reply(
            update,
            t(language, "unknown_action"),
            reply_markup=main_keyboard(language),
        )
    except Exception as exc:
        await show_safe_error(update, context, exc)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mode = context.user_data.get(AWAITING_TEXT)
    if not mode:
        return
    if not await require_access(update, context):
        return
    text = (getattr(update.effective_message, "text", "") or "").strip()
    settings = context.application.bot_data.get("settings")
    include_text = bool(getattr(settings, "ux_audit_include_user_text", False))
    record_current_ux_event(
        "incoming_text",
        update=update,
        payload=incoming_text_payload(text, mode=str(mode), include_text=include_text),
    )
    try:
        for handler in [
            handle_analysis_text,
            handle_chats_text,
            handle_reminders_text,
            handle_settings_text,
        ]:
            if await handler(update, context, str(mode), text):
                return
    except Exception as exc:
        await show_safe_error(update, context, exc)
