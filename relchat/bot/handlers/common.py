from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import chunk_text, format_main_menu
from relchat.bot.keyboards import main_keyboard
from relchat.bot.localization import t
from relchat.bot.security import is_allowed_update, is_private_chat, mtproto_session_exists
from relchat.bot.services.ux_audit import (
    error_payload,
    incoming_command_payload,
    outgoing_payload,
    record_current_ux_event,
    set_current_audit_settings,
)
from relchat.config import Settings
from relchat.database.repositories import dashboard_counts, ensure_user_profile, get_user_settings
from relchat.database.sqlite import connect, init_db


class BotCommandError(RuntimeError):
    pass


async def require_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = get_context_settings(context)
    if not is_allowed_update(update, settings):
        return False
    set_current_audit_settings(settings)
    if not is_private_chat(update):
        record_current_ux_event("access_rejected", update=update, payload={"reason": "non_private_chat"})
        await reply_chunks(update, "RelChat replies only in a private bot chat.")
        return False
    message_text = getattr(getattr(update, "effective_message", None), "text", "") or ""
    if message_text.startswith("/"):
        record_current_ux_event("incoming_command", update=update, payload=incoming_command_payload(update))
    return True


def get_context_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    settings = context.application.bot_data.get("settings")
    if not isinstance(settings, Settings):
        raise BotCommandError("Bot settings are not initialized.")
    return settings


def bot_user_id(update: Update) -> int:
    user = update.effective_user
    if user is None or not isinstance(user.id, int):
        raise BotCommandError("Telegram user is unavailable.")
    return user.id


def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        return ensure_user_profile(conn, bot_user_id(update))


def user_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        return get_user_settings(conn, bot_user_id(update)).get("language", "en")


async def render_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        ensure_user_profile(conn, user_id)
        language = get_user_settings(conn, user_id).get("language", "en")
        counts = dashboard_counts(conn, user_id)
    text = format_main_menu(
        language=language,
        telegram_connected=mtproto_session_exists(settings.session_path),
        saved_chats=counts["saved_chats"],
        reports=counts["reports"],
        followups=counts["active_reminders"],
        running_jobs=counts["running_jobs"],
    )
    await edit_or_reply(update, text, reply_markup=main_keyboard(language))


async def reply_chunks(update: Update, text: str, *, reply_markup: Any | None = None) -> None:
    message = update.effective_message
    if message is None:
        return
    chunks = chunk_text(text)
    for index, chunk in enumerate(chunks):
        kwargs = {}
        if index == 0 and reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        await message.reply_text(chunk, **kwargs)
        record_current_ux_event(
            "bot_reply",
            update=update,
            payload=outgoing_payload(
                chunk,
                action="reply",
                reply_markup=reply_markup if index == 0 else None,
                chunk_index=index + 1,
                chunk_count=len(chunks),
            ),
        )


async def edit_or_reply(update: Update, text: str, *, reply_markup: Any | None = None) -> None:
    query = getattr(update, "callback_query", None)
    message = getattr(query, "message", None) if query is not None else None
    chunks = chunk_text(text)
    if message is not None and len(chunks) == 1:
        try:
            await query.edit_message_text(chunks[0], reply_markup=reply_markup)
            record_current_ux_event(
                "bot_edit",
                update=update,
                payload=outgoing_payload(chunks[0], action="edit", reply_markup=reply_markup),
            )
            return
        except Exception as exc:
            if exc.__class__.__name__ != "BadRequest":
                raise
    await reply_chunks(update, text, reply_markup=reply_markup)


def ensure_mtproto_ready(settings: Settings) -> None:
    if settings.api_id is None or not settings.api_hash:
        raise BotCommandError("Telegram local authorization is not configured yet.")
    if not mtproto_session_exists(settings.session_path):
        raise BotCommandError("Telegram is not connected locally yet.")


def safe_error_text(exc: Exception, *, language: str = "en") -> str:
    if isinstance(exc, BotCommandError):
        return str(exc)
    if isinstance(exc, sqlite3.DatabaseError):
        return t(language, "database_problem")
    name = exc.__class__.__name__.lower()
    if "floodwait" in name or "flood_wait" in name:
        return t(language, "flood_wait")
    if "unauthorized" in name or "session" in name or "auth" in name:
        return t(language, "auth_expired")
    if "forbidden" in name or "private" in name or "notfound" in name:
        return t(language, "chat_inaccessible")
    return t(language, "unexpected_error", reference=error_reference())


def error_reference() -> str:
    return f"err_{uuid.uuid4().hex[:8]}"


async def show_safe_error(update: Update, context: ContextTypes.DEFAULT_TYPE, exc: Exception) -> None:
    record_current_ux_event("handler_error", update=update, payload=error_payload(exc))
    try:
        language = user_language(update, context)
    except Exception:
        language = "en"
    await edit_or_reply(update, safe_error_text(exc, language=language), reply_markup=main_keyboard(language))
