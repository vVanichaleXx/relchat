from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from relchat.core.models import ConversationEvent, ConversationRef, Message
from relchat.events.extractor import summarize_events


MAX_BOT_MESSAGE_LENGTH = 3800
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")


def chunk_text(text: str, *, limit: int = MAX_BOT_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in text.splitlines():
        line_length = len(line) + 1
        if current and current_length + line_length > limit:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        if line_length > limit:
            chunks.extend(split_long_line(line, limit=limit))
            continue
        current.append(line)
        current_length += line_length
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def split_long_line(line: str, *, limit: int) -> list[str]:
    return [line[index : index + limit] for index in range(0, len(line), limit)]


def sanitize_label(value: str | None, *, fallback: str = "unknown", limit: int = 80) -> str:
    text = " ".join((value or "").split())
    if not text:
        return fallback
    return clip_text(PHONE_RE.sub("[redacted phone]", text), limit=limit)


def clip_text(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return f"{value[: limit - 3]}..."


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_start() -> str:
    return (
        "RelChat bot interface v0\n\n"
        "This bot is a private UI for local RelChat data. Telegram chat history is still read through "
        "your local Telethon / MTProto session, not through the Bot API.\n\n"
        f"{format_commands()}"
    )


def format_help() -> str:
    return (
        "RelChat commands\n\n"
        f"{format_commands()}\n\n"
        "Notes:\n"
        "- /chats defaults to 30 rows. Use /chats 50, /chats private 50, /chats groups 50, or /chats channels 50.\n"
        "- Bot replies do not include message text, raw payloads, secrets, phone numbers, or session contents."
    )


def format_commands() -> str:
    return "\n".join(
        [
            "/start - show the bot summary",
            "/help - show all commands",
            "/status - show local setup status",
            "/chats [private|groups|channels] [limit] - list conversations",
            "/import <chat_id> - import 90 days, up to 5000 messages",
            "/metrics <chat_id> - show basic local metrics",
            "/events <chat_id> - show Event Engine v0 summary",
        ]
    )


def format_status(
    *,
    database_exists: bool,
    mtproto_session_exists: bool,
    mtproto_credentials_exist: bool,
    bot_restricted: bool,
    allowed_user_count: int,
) -> str:
    return "\n".join(
        [
            "RelChat status",
            "",
            f"Database exists: {yes_no(database_exists)}",
            f"Telegram MTProto session exists: {yes_no(mtproto_session_exists)}",
            f"Telegram API credentials exist: {yes_no(mtproto_credentials_exist)}",
            f"Bot restricted to allowed user IDs: {yes_no(bot_restricted)} ({allowed_user_count} configured)",
        ]
    )


def format_chat_list(
    conversations: Sequence[ConversationRef],
    *,
    chat_filter: str | None,
    requested_limit: int,
    fetched_count: int,
) -> str:
    label = chat_filter or "all"
    lines = [
        f"Telegram conversations ({label})",
        f"Showing {len(conversations)} of up to {requested_limit} requested; fetched {fetched_count}.",
        "Use /chats private 50, /chats groups 50, or /chats channels 50 to request more.",
        "",
        "chat_id | type | last_message_at | title",
    ]
    if not conversations:
        lines.append("No conversations matched.")
        return "\n".join(lines)

    for conversation in conversations:
        lines.append(
            " | ".join(
                [
                    conversation.conversation_id,
                    sanitize_label(conversation.conversation_type, fallback="unknown", limit=16),
                    sanitize_label(conversation.last_message_at, fallback="unknown", limit=25),
                    sanitize_label(conversation.title, fallback="untitled", limit=60),
                ]
            )
        )
    return "\n".join(lines)


def format_import_result(
    *,
    chat_id: str,
    count: int,
    since: str,
    limit: int,
    range_start: str | None,
    range_end: str | None,
) -> str:
    lines = [
        "Import complete",
        "",
        f"Chat: {chat_id}",
        f"Messages imported: {count}",
        f"Since: {since}",
        f"Limit: {limit}",
    ]
    if range_start or range_end:
        lines.extend(["", f"Imported range start: {range_start or 'unknown'}", f"Imported range end: {range_end or 'unknown'}"])
    return "\n".join(lines)


def format_metrics(summary: dict) -> str:
    lines = [
        "Metrics summary",
        "",
        f"Chat: {summary['chat_id']}",
        f"Messages imported: {summary['message_count']}",
        "",
        "Message count by sender",
    ]
    append_limited_mapping(lines, summary["message_count_by_sender"], value_suffix="")

    initiation = summary["initiation_balance"]
    lines.extend(
        [
            "",
            f"Initiation balance ({initiation['session_count']} sessions, gap > {initiation['gap_hours']}h)",
        ]
    )
    for sender, count in limited_items(initiation["by_sender"]):
        share = initiation["share"].get(sender, 0) * 100
        lines.append(f"{sanitize_label(sender)}: {count} starts ({share:.1f}%)")

    lines.extend(["", "Median response time by responder"])
    for sender, row in limited_items(summary["response_times"]):
        lines.append(
            f"{sanitize_label(sender)}: {row['median_readable'] or 'n/a'} "
            f"({row['count']} replies); active {row['active_median_readable'] or 'n/a'}"
        )

    lines.extend(["", "Average message length"])
    for sender, row in limited_items(summary["average_message_length"]):
        lines.append(f"{sanitize_label(sender)}: {row['avg_chars']} chars over {row['message_count']} text messages")

    unanswered = summary["unanswered_questions"]
    lines.extend(["", f"Unanswered questions: {len(unanswered)}"])
    for item in unanswered[:10]:
        lines.append(
            f"{sanitize_label(item.get('timestamp'), fallback='unknown', limit=25)} "
            f"{sanitize_label(item.get('sender'), fallback='unknown')} "
            f"message_id={item.get('message_id')}"
        )
    if len(unanswered) > 10:
        lines.append(f"...and {len(unanswered) - 10} more")
    return "\n".join(lines)


def format_events(chat_id: str, messages: Sequence[Message], events: Sequence[ConversationEvent]) -> str:
    lines = [
        "Event Engine v0 summary",
        "",
        f"Chat: {chat_id}",
        f"Messages scanned: {len(messages)}",
        f"Events detected: {len(events)}",
    ]
    if not events:
        return "\n".join(lines)

    lines.extend(["", "Event count by type"])
    append_limited_mapping(lines, summarize_events(events), value_suffix="")

    lines.extend(["", "Recent events"])
    for event in events[-20:]:
        details = event_details(event)
        suffix = f" {details}" if details else ""
        lines.append(
            f"{sanitize_label(event.timestamp, fallback='unknown', limit=25)} "
            f"{sanitize_label(event.event_type, fallback='event', limit=30)} "
            f"{event_sender_label(event)}{suffix}"
        )
    return "\n".join(lines)


def append_limited_mapping(lines: list[str], mapping: dict, *, value_suffix: str, limit: int = 10) -> None:
    if not mapping:
        lines.append("none")
        return
    items = list(mapping.items())
    for key, value in items[:limit]:
        lines.append(f"{sanitize_label(str(key))}: {value}{value_suffix}")
    if len(items) > limit:
        lines.append(f"...and {len(items) - limit} more")


def limited_items(mapping: dict, *, limit: int = 10) -> Iterable[tuple]:
    return list(mapping.items())[:limit]


def event_sender_label(event: ConversationEvent) -> str:
    if event.sender_name:
        return sanitize_label(event.sender_name)
    if event.sender_id:
        return f"user:{event.sender_id}"
    return "unknown"


def event_details(event: ConversationEvent) -> str:
    details = []
    if event.source_message_id is not None:
        details.append(f"message_id={event.source_message_id}")
    if event.related_message_id is not None:
        details.append(f"related_message_id={event.related_message_id}")
    gap_hours = event.metadata.get("gap_hours")
    if gap_hours is not None:
        details.append(f"gap={gap_hours}h")
    response_window = event.metadata.get("response_window_hours")
    if response_window is not None:
        details.append(f"response_window={response_window}h")
    return " ".join(details)
