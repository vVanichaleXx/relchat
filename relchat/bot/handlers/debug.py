from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from relchat.bot.handlers.common import bot_user_id, get_context_settings, reply_chunks, require_access
from relchat.bot.services.ux_audit import (
    clear_ux_audit_events_for_user,
    format_debug_export,
    format_ux_audit_status,
    parse_debug_export_request,
    user_ux_audit_events,
    ux_audit_status,
)


async def debug_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    await reply_chunks(update, format_ux_audit_status(ux_audit_status(settings, user_id)))


async def debug_export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    path = settings.ux_audit_path
    if path is None:
        await reply_chunks(update, "UX audit path is not configured.")
        return
    request = parse_debug_export_request(list(getattr(context, "args", []) or []))
    events = user_ux_audit_events(path, user_id, limit=request.limit, since=request.since)
    export_path = write_debug_export(path, user_id=user_id, text=format_debug_export(events, label=request.label))
    message = update.effective_message
    if message is None:
        return
    try:
        with export_path.open("rb") as handle:
            await message.reply_document(
                document=handle,
                filename=export_path.name,
                caption=f"RelChat UX audit export ({len(events)} events).",
            )
    except Exception:
        await reply_chunks(update, f"Could not send debug export. The local export file was kept as {export_path.name}.")


async def debug_clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    await reply_chunks(
        update,
        "Clear your local UX audit events?\n\nThis does not delete chats, reports, reminders, the database, or Telegram data.",
        reply_markup=debug_clear_confirmation_keyboard(),
    )


async def handle_debug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) < 4 or parts[1] != "debug" or parts[2] != "clear":
        return False
    if parts[3] == "cancel":
        await reply_chunks(update, "Debug clear cancelled.")
        return True
    if parts[3] != "confirm":
        return False
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    path = settings.ux_audit_path
    removed = clear_ux_audit_events_for_user(path, user_id) if path is not None else 0
    await reply_chunks(update, f"Cleared {removed} UX audit events for your bot user.")
    if path is not None:
        clear_ux_audit_events_for_user(path, user_id)
    return True


def debug_clear_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Clear my UX audit events", callback_data="rc:debug:clear:confirm")],
            [InlineKeyboardButton("Cancel", callback_data="rc:debug:clear:cancel")],
        ]
    )


def write_debug_export(audit_path: Path, *, user_id: int, text: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    export_dir = audit_path.parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"relchat-ux-audit-{timestamp}.txt"
    export_path.write_text(text, encoding="utf-8")
    return export_path
