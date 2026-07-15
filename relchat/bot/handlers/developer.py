from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

from relchat.analytics.metrics import summarize
from relchat.bot.formatters import (
    format_chat_list,
    format_events,
    format_help,
    format_import_result,
    format_metrics,
    format_status,
)
from relchat.bot.handlers.common import (
    BotCommandError,
    ensure_mtproto_ready,
    get_context_settings,
    reply_chunks,
    require_access,
    show_safe_error,
)
from relchat.bot.keyboards import main_keyboard
from relchat.bot.security import mtproto_session_exists
from relchat.config import Settings
from relchat.core.models import ConversationRef
from relchat.database.repositories import list_messages, mark_conversation_imported, save_conversation, save_user_message
from relchat.database.sqlite import connect, init_db
from relchat.events.extractor import extract_events
from relchat.telegram.importer import get_conversation, iter_messages, list_conversations


DEFAULT_CHAT_LIMIT = 30
MAX_CHAT_LIMIT = 100
DEFAULT_IMPORT_LIMIT = 5000
DEFAULT_IMPORT_SINCE = "90d"
CHAT_FILTERS = {
    "private": "one_to_one",
    "groups": "group",
    "channels": "channel",
}


@dataclass(frozen=True)
class ChatListArgs:
    chat_filter: str | None
    limit: int


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    await reply_chunks(update, format_help(), reply_markup=main_keyboard())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    settings = get_context_settings(context)
    await reply_chunks(
        update,
        format_status(
            database_exists=settings.db_path.exists(),
            mtproto_session_exists=mtproto_session_exists(settings.session_path),
            mtproto_credentials_exist=settings.api_id is not None and bool(settings.api_hash),
            bot_restricted=bool(settings.allowed_user_ids),
            allowed_user_count=len(settings.allowed_user_ids),
        ),
    )


async def chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    try:
        settings = get_context_settings(context)
        ensure_mtproto_ready(settings)
        args = parse_chats_args(context.args)
        init_db(settings.db_path)
        conversations = await list_conversations(settings, limit=conversation_fetch_limit(args))
        with connect(settings.db_path) as conn:
            for conversation in conversations:
                save_conversation(conn, conversation)
        filtered = filter_and_sort_conversations(conversations, args.chat_filter)[: args.limit]
        await reply_chunks(
            update,
            format_chat_list(
                filtered,
                chat_filter=args.chat_filter,
                requested_limit=args.limit,
                fetched_count=len(conversations),
            ),
        )
    except Exception as exc:
        await show_safe_error(update, context, exc)


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    try:
        settings = get_context_settings(context)
        ensure_mtproto_ready(settings)
        chat_id = parse_single_chat_id(context.args, command="/import")
        since = parse_since(DEFAULT_IMPORT_SINCE)
        await reply_chunks(update, f"Importing chat {chat_id} since {DEFAULT_IMPORT_SINCE}.")
        init_db(settings.db_path)
        conversation = await get_conversation(settings, chat_id)
        count = 0
        last_message_id = None
        range_start = None
        range_end = None
        with connect(settings.db_path) as conn:
            save_conversation(conn, conversation, selected=True)
            async for message in iter_messages(settings, chat_id, limit=DEFAULT_IMPORT_LIMIT, since=since):
                save_user_message(conn, update.effective_user.id, message)
                count += 1
                last_message_id = message.source_message_id
                range_start = message.timestamp if range_start is None else min(range_start, message.timestamp)
                range_end = message.timestamp if range_end is None else max(range_end, message.timestamp)
                if count % 250 == 0:
                    conn.commit()
            mark_conversation_imported(
                conn,
                source=conversation.source,
                conversation_id=chat_id,
                range_start=range_start,
                range_end=range_end,
                last_message_id=last_message_id,
            )
        await reply_chunks(
            update,
            format_import_result(
                chat_id=chat_id,
                count=count,
                since=DEFAULT_IMPORT_SINCE,
                limit=DEFAULT_IMPORT_LIMIT,
                range_start=range_start,
                range_end=range_end,
            ),
        )
    except Exception as exc:
        await show_safe_error(update, context, exc)


async def metrics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    try:
        settings = get_context_settings(context)
        chat_id = parse_single_chat_id(context.args, command="/metrics")
        init_db(settings.db_path)
        with connect(settings.db_path) as conn:
            messages = list_messages(conn, chat_id, source="telegram")
        await reply_chunks(update, format_metrics(summarize(messages, chat_id)))
    except Exception as exc:
        await show_safe_error(update, context, exc)


async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return
    try:
        settings = get_context_settings(context)
        chat_id = parse_single_chat_id(context.args, command="/events")
        init_db(settings.db_path)
        with connect(settings.db_path) as conn:
            messages = list_messages(conn, chat_id, source="telegram")
        await reply_chunks(update, format_events(chat_id, messages, extract_events(messages)))
    except Exception as exc:
        await show_safe_error(update, context, exc)


def parse_chats_args(args: list[str]) -> ChatListArgs:
    chat_filter = None
    limit = DEFAULT_CHAT_LIMIT
    for arg in args:
        normalized = arg.strip().lower()
        if not normalized:
            continue
        if normalized in CHAT_FILTERS:
            chat_filter = normalized
            continue
        if normalized.isdigit():
            limit = max(1, min(int(normalized), MAX_CHAT_LIMIT))
            continue
        raise BotCommandError("Usage: /chats [private|groups|channels] [limit]")
    return ChatListArgs(chat_filter=chat_filter, limit=limit)


def parse_single_chat_id(args: list[str], *, command: str) -> str:
    if len(args) != 1 or not args[0].strip():
        raise BotCommandError(f"Usage: {command} <chat_id>")
    return args[0].strip()


def conversation_fetch_limit(args: ChatListArgs) -> int:
    if args.chat_filter is None:
        return args.limit
    return min(max(args.limit * 4, 100), 300)


def filter_and_sort_conversations(conversations: list[ConversationRef], chat_filter: str | None) -> list[ConversationRef]:
    if chat_filter is None:
        return conversations
    conversation_type = CHAT_FILTERS[chat_filter]
    filtered = [conversation for conversation in conversations if conversation.conversation_type == conversation_type]
    return sorted(filtered, key=lambda item: (1 if item.last_message_at else 0, item.last_message_at or ""), reverse=True)


def parse_since(value: str) -> datetime:
    if value.endswith("d") and value[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(days=int(value[:-1]))
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
