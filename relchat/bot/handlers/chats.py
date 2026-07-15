from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import (
    format_period_prompt,
    format_remove_chat_confirmation,
    format_report_overview,
    format_saved_chat_detail,
    format_saved_chat_section,
)
from relchat.bot.handlers.chat_home import show_chat_home
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings
from relchat.bot.keyboards import (
    period_keyboard,
    remove_chat_confirmation_keyboard,
    report_sections_keyboard,
    saved_chat_actions_keyboard,
    saved_chat_list_keyboard,
)
from relchat.bot.localization import t
from relchat.bot.state import AWAITING_TEXT, RENAME_CHAT_TARGET, get_flow
from relchat.database.repositories import (
    delete_imported_messages_for_chat,
    delete_reports_for_chat,
    get_report,
    get_user_settings,
    list_user_chats,
    remove_user_chat,
    rename_user_chat,
    set_user_chat_favorite,
)
from relchat.database.sqlite import connect, init_db


CHAT_LIST_STATE = "my_chats_current_list"
CHAT_SECTION_STATE = "my_chats_current_section"


async def show_my_chats_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from relchat.bot.formatters import format_my_chats_home
    from relchat.bot.keyboards import my_chats_keyboard

    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        counts = {
            "favorites": len(list_user_chats(conn, user_id, section="favorites", limit=1000)),
            "recent": len(list_user_chats(conn, user_id, section="recent", limit=1000)),
            "saved": len(list_user_chats(conn, user_id, section="saved", limit=1000)),
        }
        language = get_user_settings(conn, user_id).get("language", "en")
    await edit_or_reply(update, format_my_chats_home(counts, language=language), reply_markup=my_chats_keyboard(language))


async def handle_chats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "chats":
        await show_my_chats_home(update, context)
        return True
    if len(parts) < 2 or parts[1] not in {"chats", "chat"}:
        return False
    if parts[1] == "chats" and len(parts) >= 4 and parts[2] == "sec":
        await show_chat_section(update, context, parts[3])
        return True
    if parts[1] == "chat":
        await handle_chat_action(update, context, parts)
        return True
    return False


async def show_chat_section(update: Update, context: ContextTypes.DEFAULT_TYPE, section: str) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    normalized = {
        "favorites": "favorites",
        "recent": "recent",
        "saved": "saved",
    }.get(section, "saved")
    with connect(settings.db_path) as conn:
        chats = list_user_chats(conn, user_id, section=normalized, limit=50)
        language = get_user_settings(conn, user_id).get("language", "en")
    title = {
        "favorites": t(language, "my_chats_favorites"),
        "recent": t(language, "my_chats_recent"),
        "saved": t(language, "my_chats_saved"),
    }.get(normalized, t(language, "my_chats_saved"))
    context.user_data[CHAT_LIST_STATE] = chats
    context.user_data[CHAT_SECTION_STATE] = normalized
    await edit_or_reply(
        update,
        format_saved_chat_section(title, chats, language=language, section=normalized),
        reply_markup=saved_chat_list_keyboard(chats, language=language),
    )


async def handle_chat_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    if len(parts) < 4:
        return
    action = parts[2]
    try:
        index = int(parts[3])
    except ValueError:
        await edit_or_reply(update, "This chat is no longer available.")
        return
    chats = current_chats(context)
    if index < 0 or index >= len(chats):
        await edit_or_reply(update, "This chat is no longer available.")
        return
    chat = chats[index]
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")

    if action == "item":
        await show_chat_home(update, context, chat, parent={"kind": "my_chats", "section": context.user_data.get(CHAT_SECTION_STATE, "saved")})
        return
    if action == "analyze":
        flow = get_flow(context.user_data)
        flow.clear()
        flow.update(
            {
                "source": chat["source"],
                "chat_id": chat["chat_id"],
                "chat_title": chat["title"],
                "chat_type": chat["chat_type"],
            }
        )
        with connect(settings.db_path) as conn:
            flow["modules"] = get_user_settings(conn, user_id).get("default_modules", [])
        await edit_or_reply(
            update,
            format_period_prompt(chat_title=chat["title"], chat_type=chat["chat_type"]),
            reply_markup=period_keyboard(language),
        )
        return
    if action == "report":
        report_id = chat.get("last_report_id")
        if not report_id:
            await edit_or_reply(update, "No report exists for this chat yet.", reply_markup=saved_chat_actions_keyboard(chat, index, language=language))
            return
        with connect(settings.db_path) as conn:
            report = get_report(conn, report_id)
        if not report:
            await edit_or_reply(update, "The latest report is no longer available.", reply_markup=saved_chat_actions_keyboard(chat, index, language=language))
            return
        await edit_or_reply(update, format_report_overview(report), reply_markup=report_sections_keyboard(report, language=language))
        return
    if action == "fav":
        with connect(settings.db_path) as conn:
            set_user_chat_favorite(conn, user_id, chat["source"], chat["chat_id"], not chat.get("is_favorite"))
            chats[index] = {**chat, "is_favorite": not chat.get("is_favorite")}
        await edit_or_reply(update, format_saved_chat_detail(chats[index]), reply_markup=saved_chat_actions_keyboard(chats[index], index, language=language))
        return
    if action == "rename":
        context.user_data[AWAITING_TEXT] = "rename_chat"
        context.user_data[RENAME_CHAT_TARGET] = index
        await edit_or_reply(update, "Send a local name for this chat. This changes only the RelChat label.")
        return
    if action == "remove":
        await edit_or_reply(update, format_remove_chat_confirmation(chat), reply_markup=remove_chat_confirmation_keyboard(index, language=language))
        return
    if action == "remove_confirm":
        with connect(settings.db_path) as conn:
            delete_imported_messages_for_chat(conn, chat["source"], chat["chat_id"], bot_user_id=user_id)
            delete_reports_for_chat(conn, user_id, chat["source"], chat["chat_id"])
            remove_user_chat(conn, user_id, chat["source"], chat["chat_id"])
        await show_my_chats_home(update, context)


async def handle_chats_text(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, text: str) -> bool:
    if mode != "rename_chat":
        return False
    index = context.user_data.get(RENAME_CHAT_TARGET)
    chats = current_chats(context)
    if not isinstance(index, int) or index < 0 or index >= len(chats):
        context.user_data[AWAITING_TEXT] = None
        await edit_or_reply(update, "This chat is no longer available.")
        return True
    chat = chats[index]
    title = " ".join(text.split())[:80] or None
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        rename_user_chat(conn, user_id, chat["source"], chat["chat_id"], title)
        language = get_user_settings(conn, user_id).get("language", "en")
    chat = {**chat, "local_title": title, "title": title or chat.get("display_title")}
    chats[index] = chat
    context.user_data[AWAITING_TEXT] = None
    context.user_data.pop(RENAME_CHAT_TARGET, None)
    await edit_or_reply(update, format_saved_chat_detail(chat), reply_markup=saved_chat_actions_keyboard(chat, index, language=language))
    return True


def current_chats(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    chats = context.user_data.get(CHAT_LIST_STATE, [])
    return chats if isinstance(chats, list) else []
