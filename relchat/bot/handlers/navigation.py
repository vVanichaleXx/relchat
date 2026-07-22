from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import format_help, format_help_page
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings, render_main_menu, user_language
from relchat.bot.keyboards import back_main_keyboard, help_keyboard, main_keyboard
from relchat.bot.localization import t
from relchat.bot.services.native_navigation import pop_back, push_screen, resolve_nav_token
from relchat.bot.services.ux_audit import record_ux_event
from relchat.bot.state import AWAITING_TEXT, clear_flow
from relchat.database.repositories import get_user_chat, get_user_settings, mark_user_chat_opened
from relchat.database.sqlite import connect


async def handle_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) >= 2 and parts[1] == "noop":
        return True
    if len(parts) >= 2 and parts[1] == "cancel":
        clear_flow(context.user_data)
        context.user_data[AWAITING_TEXT] = None
        await render_main_menu(update, context)
        return True
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "main":
        clear_flow(context.user_data)
        await render_main_menu(update, context)
        return True
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "back":
        await navigate_back(update, context)
        return True
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] in {"analyze", "private", "groups", "channels", "bots", "favorites", "recent"}:
        from relchat.bot.handlers.analysis import load_chat_browser

        category = "private" if parts[2] == "analyze" else parts[2]
        await load_chat_browser(update, context, category=category)
        return True
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "search":
        from relchat.bot.handlers.analysis import show_chat_search_prompt

        await show_chat_search_prompt(update, context)
        return True
    if len(parts) >= 3 and parts[1] == "quick":
        await open_quick_access_chat(update, context, parts[2])
        return True
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "help":
        language = user_language(update, context)
        await edit_or_reply(update, format_help(), reply_markup=help_keyboard(language))
        return True
    if len(parts) >= 3 and parts[1] == "help":
        language = user_language(update, context)
        await edit_or_reply(update, format_help_page(parts[2], language=language), reply_markup=back_main_keyboard(language))
        return True
    return False


async def navigate_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = pop_back(context.user_data)
    if not entry:
        await render_main_menu(update, context)
        return
    screen_id = str(entry.get("screen_id") or "")
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    if screen_id.startswith("chat_list:"):
        from relchat.bot.handlers.analysis import load_chat_browser

        await load_chat_browser(update, context, category=screen_id.split(":", 1)[1], page=int(payload.get("page") or 0), replace_navigation=True)
        return
    if screen_id == "chat_home":
        from relchat.bot.handlers.chat_home import show_chat_home

        chat = payload.get("chat")
        if isinstance(chat, dict):
            await show_chat_home(update, context, chat, push_navigation=False)
            return
    await render_main_menu(update, context)


async def open_quick_access_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    payload = resolve_nav_token(context.user_data, bot_user_id=user_id, token=token)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
    if not payload:
        record_ux_event(settings, "navigation_stale_callback", payload={"stale_callback": True, "screen_id": "quick_access"})
        await edit_or_reply(update, t(language, "nav_stale_menu"), reply_markup=main_keyboard(language))
        return
    source = str(payload.get("source") or "telegram")
    chat_id = str(payload.get("chat_id") or "")
    with connect(settings.db_path) as conn:
        chat = get_user_chat(conn, user_id, source, chat_id)
        if chat:
            mark_user_chat_opened(conn, user_id, source, chat_id)
    if not chat:
        record_ux_event(settings, "navigation_stale_callback", payload={"stale_callback": True, "screen_id": "quick_access"})
        await edit_or_reply(update, t(language, "nav_stale_menu"), reply_markup=main_keyboard(language))
        return
    from relchat.bot.handlers.chat_home import show_chat_home

    push_screen(context.user_data, "main_menu", payload={}, replace=True)
    record_ux_event(
        settings,
        "quick_access_used",
        payload={"quick_access_used": True, "screen_id": "chat_home", "previous_screen_id": "main_menu", "chat_type": chat.get("chat_type")},
    )
    await show_chat_home(update, context, chat, parent={"kind": "quick"}, push_navigation=True)
