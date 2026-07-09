from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from relchat.analytics.metrics import summarize
from relchat.config import get_settings
from relchat.core.models import ConversationEvent, Message
from relchat.database.repositories import (
    list_messages,
    mark_conversation_imported,
    save_conversation,
    save_message,
)
from relchat.database.sqlite import connect, init_db
from relchat.events.extractor import extract_events, summarize_events
from relchat.telegram.client import login
from relchat.telegram.importer import get_conversation, iter_messages, list_conversations


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    return args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relchat", description="Local conversation intelligence tools")
    sub = parser.add_subparsers(dest="command")

    db = sub.add_parser("db", help="Database commands")
    db_sub = db.add_subparsers(dest="db_command")
    db_init = db_sub.add_parser("init", help="Initialize the local SQLite database")
    db_init.set_defaults(handler=cmd_db_init)

    auth = sub.add_parser("auth", help="Telegram authorization commands")
    auth_sub = auth.add_subparsers(dest="auth_command")
    auth_login = auth_sub.add_parser("login", help="Log in with Telegram Client API / MTProto")
    auth_login.add_argument("--phone", help="Phone number in international format")
    auth_login.set_defaults(handler=cmd_auth_login)

    chats = sub.add_parser("chats", help="Chat selection commands")
    chats_sub = chats.add_subparsers(dest="chats_command")
    chats_list = chats_sub.add_parser("list", help="List Telegram dialogs")
    chats_list.add_argument("--limit", type=int, default=50)
    chats_list.set_defaults(handler=cmd_chats_list)
    chats_select = chats_sub.add_parser("select", help="Mark a chat as selected for local analysis")
    chats_select.add_argument("chat_id")
    chats_select.set_defaults(handler=cmd_chats_select)

    importer = sub.add_parser("import", help="Import selected Telegram chat history")
    import_sub = importer.add_subparsers(dest="import_command")
    import_chat = import_sub.add_parser("chat", help="Import one Telegram chat")
    import_chat.add_argument("chat_id")
    import_chat.add_argument("--limit", type=int, default=1000, help="Maximum messages to fetch")
    import_chat.add_argument("--since", default=None, help="Import messages since YYYY-MM-DD or Nd, e.g. 90d")
    import_chat.set_defaults(handler=cmd_import_chat)

    metrics = sub.add_parser("metrics", help="Metrics commands")
    metrics_sub = metrics.add_subparsers(dest="metrics_command")
    metrics_summary = metrics_sub.add_parser("summary", help="Print a basic metrics summary")
    metrics_summary.add_argument("chat_id")
    metrics_summary.add_argument(
        "--show-text",
        action="store_true",
        help="Include message text snippets in local CLI output. This is privacy-sensitive.",
    )
    metrics_summary.set_defaults(handler=cmd_metrics_summary)

    events = sub.add_parser("events", help="Event extraction commands")
    events_sub = events.add_subparsers(dest="events_command")
    events_summary = events_sub.add_parser("summary", help="Print a source-agnostic event summary")
    events_summary.add_argument("chat_id")
    events_summary.add_argument(
        "--show-text",
        action="store_true",
        help="Include message text snippets in local CLI output. This is privacy-sensitive.",
    )
    events_summary.set_defaults(handler=cmd_events_summary)

    return parser


def cmd_db_init(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    print(f"Initialized database at {settings.db_path}")
    return 0


def cmd_auth_login(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    asyncio.run(login(settings, phone=args.phone))
    return 0


def cmd_chats_list(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    conversations = asyncio.run(list_conversations(settings, limit=args.limit))
    if not conversations:
        print("No dialogs returned.")
        return 0
    print(f"{'chat_id':>16}  {'type':<12}  {'last_message':<25}  name")
    print("-" * 80)
    with connect(settings.db_path) as conn:
        for conversation in conversations:
            save_conversation(conn, conversation)
            print(
                f"{conversation.conversation_id:>16}  "
                f"{conversation.conversation_type:<12}  "
                f"{(conversation.last_message_at or ''):<25}  "
                f"{conversation.title or ''}"
            )
    return 0


def cmd_chats_select(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    conversation = asyncio.run(get_conversation(settings, args.chat_id))
    with connect(settings.db_path) as conn:
        save_conversation(
            conn,
            conversation,
            selected=True,
        )
    print(f"Selected chat {args.chat_id}: {conversation.title} ({conversation.conversation_type})")
    return 0


def cmd_import_chat(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    since = parse_since(args.since)
    conversation = asyncio.run(get_conversation(settings, args.chat_id))
    count = 0
    last_message_id = None
    range_start = None
    range_end = None
    with connect(settings.db_path) as conn:
        save_conversation(
            conn,
            conversation,
            selected=True,
        )

        async def run_import() -> None:
            nonlocal count, last_message_id, range_start, range_end
            async for message in iter_messages(settings, args.chat_id, limit=args.limit, since=since):
                save_message(conn, message)
                count += 1
                last_message_id = message.source_message_id
                range_start = message.timestamp if range_start is None else min(range_start, message.timestamp)
                range_end = message.timestamp if range_end is None else max(range_end, message.timestamp)
                if count % 250 == 0:
                    conn.commit()
                    print(f"Imported {count} messages...")

        asyncio.run(run_import())
        mark_conversation_imported(
            conn,
            source=conversation.source,
            conversation_id=args.chat_id,
            range_start=range_start,
            range_end=range_end,
            last_message_id=last_message_id,
        )
    print(f"Imported {count} messages into {settings.db_path}")
    return 0


def cmd_metrics_summary(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        messages = list_messages(conn, args.chat_id, source="telegram")
    summary = summarize(messages, args.chat_id)
    print_summary(summary, show_text=args.show_text)
    return 0


def cmd_events_summary(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        messages = list_messages(conn, args.chat_id, source="telegram")
    events = extract_events(messages)
    print_events_summary(args.chat_id, messages, events, show_text=args.show_text)
    return 0


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("d") and value[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(days=int(value[:-1]))
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def print_summary(summary: dict, *, show_text: bool = False) -> None:
    print(f"Chat: {summary['chat_id']}")
    print(f"Messages imported: {summary['message_count']}")
    print()
    print("Message count by sender")
    for sender, count in summary["message_count_by_sender"].items():
        print(f"  {sender}: {count}")
    print()
    initiation = summary["initiation_balance"]
    print(f"Initiation balance ({initiation['session_count']} sessions, gap > {initiation['gap_hours']}h)")
    for sender, count in initiation["by_sender"].items():
        share = initiation["share"].get(sender, 0) * 100
        print(f"  {sender}: {count} starts ({share:.1f}%)")
    print()
    print("Median response time by responder")
    for sender, row in summary["response_times"].items():
        print(
            f"  {sender}: {row['median_readable'] or 'n/a'} "
            f"({row['count']} speaker-change replies); "
            f"active median {row['active_median_readable'] or 'n/a'}"
        )
    print()
    print("Average message length")
    for sender, row in summary["average_message_length"].items():
        print(f"  {sender}: {row['avg_chars']} chars over {row['message_count']} text messages")
    print()
    unanswered = summary["unanswered_questions"]
    print(f"Unanswered questions: {len(unanswered)}")
    for item in unanswered[:10]:
        if show_text:
            print(f"  [{item['timestamp']}] {item['sender']}: {item['text']}")
        else:
            print(f"  [{item['timestamp']}] {item['sender']} message_id={item['message_id']}")


def print_events_summary(
    chat_id: str,
    messages: list[Message],
    events: list[ConversationEvent],
    *,
    show_text: bool = False,
) -> None:
    print(f"Chat: {chat_id}")
    print(f"Messages scanned: {len(messages)}")
    print(f"Events detected: {len(events)}")
    if not events:
        return

    print()
    print("Event count by type")
    for event_type, count in summarize_events(events).items():
        print(f"  {event_type}: {count}")

    print()
    print("Recent events")
    text_by_message_id = {message.source_message_id: message.text for message in messages}
    for event in events[-20:]:
        print(f"  [{event.timestamp}] {event.event_type} {event_sender_label(event)} {event_details(event)}")
        if show_text and event.source_message_id is not None:
            text = text_by_message_id.get(event.source_message_id)
            if text:
                print(f"    text: {clip_text(text)}")


def event_sender_label(event: ConversationEvent) -> str:
    if event.sender_name:
        return event.sender_name
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


def clip_text(value: str, limit: int = 240) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."
