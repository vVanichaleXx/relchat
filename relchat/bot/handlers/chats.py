from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import (
    format_important_chat_detail,
    format_important_chats,
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
    important_chat_actions_keyboard,
    important_chat_list_keyboard,
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
    list_important_chats,
    list_user_chats,
    remove_user_chat,
    rename_user_chat,
    set_chat_important,
    set_user_chat_favorite,
    update_important_chat_setting,
)
from relchat.database.sqlite import connect, init_db


CHAT_LIST_STATE = "my_chats_current_list"
CHAT_SECTION_STATE = "my_chats_current_section"
IMPORTANT_CHAT_LIST_STATE = "important_chats_current_list"
IMPORTANT_CHAT_PAGE_STATE = "important_chats_current_page"
IMPORTANT_PAGE_SIZE = 10


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
            "important": len(list_important_chats(conn, user_id, limit=1000)),
        }
        language = get_user_settings(conn, user_id).get("language", "en")
    await edit_or_reply(update, format_my_chats_home(counts, language=language), reply_markup=my_chats_keyboard(language))


async def handle_chats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "chats":
        await show_my_chats_home(update, context)
        return True
    if len(parts) < 2 or parts[1] not in {"chats", "chat", "imp"}:
        return False
    if parts[1] == "chats" and len(parts) >= 4 and parts[2] == "sec":
        await show_chat_section(update, context, parts[3])
        return True
    if parts[1] == "chat":
        await handle_chat_action(update, context, parts)
        return True
    if parts[1] == "imp":
        await handle_important_chat_action(update, context, parts)
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
        "important": "important",
    }.get(section, "saved")
    if normalized == "important":
        await show_important_chats(update, context, page=0)
        return
    with connect(settings.db_path) as conn:
        chats = list_user_chats(conn, user_id, section=normalized, limit=50)
        language = get_user_settings(conn, user_id).get("language", "en")
    title = {
        "favorites": t(language, "my_chats_favorites"),
        "recent": t(language, "my_chats_recent"),
        "saved": t(language, "my_chats_saved"),
        "important": t(language, "important_chats_title"),
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


async def show_important_chats(update: Update, context: ContextTypes.DEFAULT_TYPE, *, page: int = 0) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    page = max(0, int(page))
    with connect(settings.db_path) as conn:
        chats = list_important_chats(conn, user_id, limit=IMPORTANT_PAGE_SIZE + 1, offset=page * IMPORTANT_PAGE_SIZE)
        language = get_user_settings(conn, user_id).get("language", "en")
    has_next = len(chats) > IMPORTANT_PAGE_SIZE
    visible = chats[:IMPORTANT_PAGE_SIZE]
    context.user_data[IMPORTANT_CHAT_LIST_STATE] = visible
    context.user_data[IMPORTANT_CHAT_PAGE_STATE] = page
    await edit_or_reply(
        update,
        format_important_chats(visible, page=page, language=language),
        reply_markup=important_chat_list_keyboard(visible, page=page, has_previous=page > 0, has_next=has_next, language=language),
    )


async def handle_important_chat_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    if len(parts) < 3:
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
    action = parts[2]
    if action == "page" and len(parts) >= 4:
        try:
            page = int(parts[3])
        except ValueError:
            page = 0
        await show_important_chats(update, context, page=page)
        return
    if len(parts) < 4:
        return
    try:
        index = int(parts[3])
    except ValueError:
        await edit_or_reply(update, "This chat is no longer available.")
        return
    chats = important_chats(context)
    if index < 0 or index >= len(chats):
        await edit_or_reply(update, "This chat is no longer available.")
        return
    chat = chats[index]
    if action == "item":
        await edit_or_reply(update, format_important_chat_detail(chat, language=language), reply_markup=important_chat_actions_keyboard(chat, index, language=language))
        return
    if action == "open":
        await show_chat_home(update, context, chat, parent={"kind": "my_chats", "section": "important"})
        return
    if action == "settings":
        await show_chat_home(update, context, chat, parent={"kind": "my_chats", "section": "important"})
        from relchat.bot.handlers.chat_home import show_chat_home_section

        await show_chat_home_section(update, context, "settings")
        return
    if action == "disable":
        with connect(settings.db_path) as conn:
            update_important_chat_setting(conn, user_id, chat["source"], chat["chat_id"], "automatic_analysis_enabled", False)
            chats[index] = {**chat, "automatic_analysis_enabled": False}
        await edit_or_reply(update, format_important_chat_detail(chats[index], language=language), reply_markup=important_chat_actions_keyboard(chats[index], index, language=language))
        return
    if action == "remove":
        with connect(settings.db_path) as conn:
            set_chat_important(conn, user_id, chat["source"], chat["chat_id"], False)
        await show_important_chats(update, context, page=int(context.user_data.get(IMPORTANT_CHAT_PAGE_STATE) or 0))


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


def important_chats(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    chats = context.user_data.get(IMPORTANT_CHAT_LIST_STATE, [])
    return chats if isinstance(chats, list) else []
