from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import format_help, format_help_page
from relchat.bot.handlers.common import edit_or_reply, render_main_menu, user_language
from relchat.bot.keyboards import back_main_keyboard, help_keyboard, main_keyboard
from relchat.bot.state import AWAITING_TEXT, clear_flow


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
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "help":
        language = user_language(update, context)
        await edit_or_reply(update, format_help(), reply_markup=help_keyboard(language))
        return True
    if len(parts) >= 3 and parts[1] == "help":
        language = user_language(update, context)
        await edit_or_reply(update, format_help_page(parts[2], language=language), reply_markup=back_main_keyboard(language))
        return True
    return False
