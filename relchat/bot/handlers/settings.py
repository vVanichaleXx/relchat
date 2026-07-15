from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import (
    format_data_management,
    format_destructive_confirmation,
    format_settings,
    format_storage_summary,
)
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings, render_main_menu
from relchat.bot.keyboards import (
    data_management_keyboard,
    destructive_confirmation_keyboard,
    language_keyboard,
    module_settings_keyboard,
    settings_keyboard,
    settings_period_keyboard,
)
from relchat.bot.state import AWAITING_TEXT, RUNNABLE_MODULE_IDS
from relchat.database.repositories import (
    clear_reminders,
    clear_reports,
    delete_all_user_data,
    delete_imported_messages_for_chat,
    get_user_settings,
    list_user_chats,
    local_storage_summary,
    set_onboarding_completed,
    update_user_setting,
)
from relchat.database.sqlite import connect, init_db


SETTINGS_MODULES = "settings_modules"
DATA_CHAT_LIST = "data_chat_list"


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        user_settings = get_user_settings(conn, user_id)
    await edit_or_reply(update, format_settings(user_settings), reply_markup=settings_keyboard(user_settings, language=user_settings["language"]))


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "settings":
        await show_settings(update, context)
        return True
    if len(parts) < 2 or parts[1] not in {"set", "data"}:
        return False
    if parts[1] == "set":
        await handle_setting_action(update, context, parts)
        return True
    if parts[1] == "data":
        await handle_data_action(update, context, parts)
        return True
    return False


async def handle_setting_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        user_settings = get_user_settings(conn, user_id)
    language = user_settings["language"]
    if len(parts) < 3:
        await show_settings(update, context)
        return
    action = parts[2]
    if action == "language" and len(parts) == 3:
        await edit_or_reply(update, "Language", reply_markup=language_keyboard(language))
        return
    if action == "language" and len(parts) >= 4:
        with connect(settings.db_path) as conn:
            update_user_setting(conn, user_id, "language", parts[3])
        await show_settings(update, context)
        return
    if action == "period" and len(parts) == 3:
        await edit_or_reply(update, "Default import period", reply_markup=settings_period_keyboard(language))
        return
    if action == "period" and len(parts) >= 4:
        with connect(settings.db_path) as conn:
            update_user_setting(conn, user_id, "default_period", parts[3])
        await show_settings(update, context)
        return
    if action == "toggle" and len(parts) >= 4:
        key = parts[3]
        if key in {"progress_notifications", "show_technical_details", "confirm_before_delete"}:
            with connect(settings.db_path) as conn:
                current = get_user_settings(conn, user_id).get(key)
                update_user_setting(conn, user_id, key, not bool(current))
        await show_settings(update, context)
        return
    if action == "modules":
        selected = context.user_data.setdefault(SETTINGS_MODULES, list(user_settings.get("default_modules") or []))
        if len(parts) >= 4:
            if parts[3] == "all":
                context.user_data[SETTINGS_MODULES] = RUNNABLE_MODULE_IDS.copy()
                await show_module_settings(update, context)
                return
            if parts[3] == "clear":
                context.user_data[SETTINGS_MODULES] = []
                await show_module_settings(update, context)
                return
            if parts[3] == "save":
                if not isinstance(selected, list) or not selected:
                    selected = RUNNABLE_MODULE_IDS.copy()
                with connect(settings.db_path) as conn:
                    update_user_setting(conn, user_id, "default_modules", selected)
                context.user_data.pop(SETTINGS_MODULES, None)
                await show_settings(update, context)
                return
        await show_module_settings(update, context)
        return
    if action == "module" and len(parts) >= 4:
        selected = context.user_data.setdefault(SETTINGS_MODULES, list(user_settings.get("default_modules") or []))
        if not isinstance(selected, list):
            selected = []
            context.user_data[SETTINGS_MODULES] = selected
        module_id = parts[3]
        if module_id in RUNNABLE_MODULE_IDS:
            if module_id in selected:
                selected.remove(module_id)
            else:
                selected.append(module_id)
        await show_module_settings(update, context)
        return
    if action == "retention":
        context.user_data[AWAITING_TEXT] = "retention"
        await edit_or_reply(update, "Send a retention period in days, or send keep to keep data until you delete it.")
        return
    if action == "reset_onboarding":
        with connect(settings.db_path) as conn:
            set_onboarding_completed(conn, user_id, False)
        await edit_or_reply(update, "Onboarding reset. Use /start to view it again.")
        return
    if action == "data":
        await edit_or_reply(update, format_data_management(), reply_markup=data_management_keyboard(language))


async def show_module_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        user_settings = get_user_settings(conn, user_id)
    language = user_settings["language"]
    selected = context.user_data.setdefault(SETTINGS_MODULES, list(user_settings.get("default_modules") or []))
    if not isinstance(selected, list):
        selected = []
        context.user_data[SETTINGS_MODULES] = selected
    await edit_or_reply(update, "Default analysis modules", reply_markup=module_settings_keyboard(selected, language=language))


async def handle_data_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
    if len(parts) < 3:
        await edit_or_reply(update, format_data_management(), reply_markup=data_management_keyboard(language))
        return
    action = parts[2]
    if action == "summary":
        with connect(settings.db_path) as conn:
            summary = local_storage_summary(conn, user_id)
        await edit_or_reply(update, format_storage_summary(summary), reply_markup=data_management_keyboard(language))
        return
    if action == "delete_reports":
        await edit_or_reply(update, format_destructive_confirmation("delete report history"), reply_markup=destructive_confirmation_keyboard("reports", language=language))
        return
    if action == "delete_reminders":
        await edit_or_reply(update, format_destructive_confirmation("delete reminders"), reply_markup=destructive_confirmation_keyboard("reminders", language=language))
        return
    if action == "delete_all":
        await edit_or_reply(update, format_destructive_confirmation("delete all local RelChat user data"), reply_markup=destructive_confirmation_keyboard("all", language=language))
        return
    if action == "delete_chat":
        with connect(settings.db_path) as conn:
            chats = list_user_chats(conn, user_id, limit=50)
        context.user_data[DATA_CHAT_LIST] = chats
        rows = [
            [InlineKeyboardButton(f"{index + 1}. {chat.get('title') or 'Untitled chat'}", callback_data=f"rc:data:chat:{index}")]
            for index, chat in enumerate(chats)
        ]
        rows.append([InlineKeyboardButton("Back", callback_data="rc:set:data")])
        await edit_or_reply(update, "Choose a chat for local imported-data deletion.", reply_markup=InlineKeyboardMarkup(rows))
        return
    if action == "chat" and len(parts) >= 4:
        await confirm_chat_data_delete(update, context, parts[3], language=language)
        return
    if action == "confirm" and len(parts) >= 4:
        await run_data_confirmation(update, context, parts[3])
        return
    if action == "confirm_chat" and len(parts) >= 4:
        await delete_chat_imported_data(update, context, parts[3])


async def confirm_chat_data_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, value: str, *, language: str) -> None:
    chats = context.user_data.get(DATA_CHAT_LIST, [])
    try:
        index = int(value)
    except ValueError:
        return
    if not isinstance(chats, list) or index < 0 or index >= len(chats):
        await edit_or_reply(update, "This chat is no longer available.")
        return
    chat = chats[index]
    await edit_or_reply(
        update,
        format_destructive_confirmation(f"delete imported local data for {chat.get('title') or 'this chat'}"),
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Delete imported local data", callback_data=f"rc:data:confirm_chat:{index}")],
                [InlineKeyboardButton("Cancel", callback_data="rc:set:data")],
            ]
        ),
    )


async def delete_chat_imported_data(update: Update, context: ContextTypes.DEFAULT_TYPE, value: str) -> None:
    chats = context.user_data.get(DATA_CHAT_LIST, [])
    try:
        index = int(value)
    except ValueError:
        return
    if not isinstance(chats, list) or index < 0 or index >= len(chats):
        await edit_or_reply(update, "This chat is no longer available.")
        return
    chat = chats[index]
    settings = get_context_settings(context)
    with connect(settings.db_path) as conn:
        delete_imported_messages_for_chat(conn, chat["source"], chat["chat_id"], bot_user_id=bot_user_id(update))
        language = get_user_settings(conn, bot_user_id(update)).get("language", "en")
    await edit_or_reply(update, "Imported local data for this chat was deleted.", reply_markup=data_management_keyboard(language))


async def run_data_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    if action == "reports":
        with connect(settings.db_path) as conn:
            clear_reports(conn, user_id)
            language = get_user_settings(conn, user_id).get("language", "en")
        await edit_or_reply(update, "Local report history was deleted.", reply_markup=data_management_keyboard(language))
        return
    if action == "reminders":
        with connect(settings.db_path) as conn:
            clear_reminders(conn, user_id)
            language = get_user_settings(conn, user_id).get("language", "en")
        await edit_or_reply(update, "Local reminders were deleted.", reply_markup=data_management_keyboard(language))
        return
    if action == "all":
        with connect(settings.db_path) as conn:
            delete_all_user_data(conn, user_id)
        await render_main_menu(update, context)


async def handle_settings_text(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, text: str) -> bool:
    if mode != "retention":
        return False
    value = " ".join(text.strip().lower().split())
    days = None
    if value not in {"keep", "none", "off"}:
        if not value.isdigit() or int(value) < 1:
            await edit_or_reply(update, "Send a positive number of days, or send keep.")
            return True
        days = int(value)
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        update_user_setting(conn, user_id, "data_retention_days", days)
    context.user_data[AWAITING_TEXT] = None
    await show_settings(update, context)
    return True
