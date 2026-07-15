from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import format_onboarding
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings, render_main_menu, require_access
from relchat.bot.keyboards import onboarding_keyboard
from relchat.bot.security import mtproto_session_exists
from relchat.database.repositories import ensure_user_profile, get_user_settings, set_onboarding_completed
from relchat.database.sqlite import connect, init_db


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        profile = ensure_user_profile(conn, user_id)
        language = get_user_settings(conn, user_id).get("language", profile.get("language", "en"))
    if profile.get("onboarding_completed"):
        await render_main_menu(update, context)
        return
    connected = mtproto_session_exists(settings.session_path)
    await edit_or_reply(
        update,
        format_onboarding(1, language=language, telegram_connected=connected),
        reply_markup=onboarding_keyboard(1, connected=connected, language=language),
    )


async def handle_onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) < 3 or parts[1] != "onb":
        return False
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        ensure_user_profile(conn, user_id)
        language = get_user_settings(conn, user_id).get("language", "en")
    if parts[2] == "done":
        with connect(settings.db_path) as conn:
            set_onboarding_completed(conn, user_id, True)
        await render_main_menu(update, context)
        return True
    try:
        step = int(parts[2])
    except ValueError:
        step = 1
    step = min(max(step, 1), 3)
    connected = mtproto_session_exists(settings.session_path)
    await edit_or_reply(
        update,
        format_onboarding(step, language=language, telegram_connected=connected),
        reply_markup=onboarding_keyboard(step, connected=connected, language=language),
    )
    return True
