from __future__ import annotations

import sqlite3

from relchat.core.models import ConversationRef, Message


def save_conversation(
    conn: sqlite3.Connection,
    conversation: ConversationRef,
    *,
    selected: bool | None = None,
) -> None:
    selected_value = 1 if selected else 0
    if selected is None:
        conn.execute(
            """
            INSERT INTO chats(source, chat_id, chat_type, chat_title)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, chat_id) DO UPDATE SET
              chat_type = excluded.chat_type,
              chat_title = excluded.chat_title,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                conversation.source,
                conversation.conversation_id,
                conversation.conversation_type,
                conversation.title,
            ),
        )
        return
    conn.execute(
        """
        INSERT INTO chats(source, chat_id, chat_type, chat_title, selected_for_analysis)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source, chat_id) DO UPDATE SET
          chat_type = excluded.chat_type,
          chat_title = excluded.chat_title,
          selected_for_analysis = excluded.selected_for_analysis,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            conversation.source,
            conversation.conversation_id,
            conversation.conversation_type,
            conversation.title,
            selected_value,
        ),
    )


def save_message(conn: sqlite3.Connection, message: Message) -> None:
    conn.execute(
        """
        INSERT INTO messages(
          source, message_id, chat_id, sender_id, sender_name, timestamp, text,
          message_type, reply_to_message_id, reactions, media_type,
          media_duration, forward_info, edit_date, is_outgoing,
          raw_platform_payload_reference
        )
        VALUES (
          :source, :message_id, :chat_id, :sender_id, :sender_name, :timestamp, :text,
          :message_type, :reply_to_message_id, :reactions, :media_type,
          :media_duration, :forward_info, :edit_date, :is_outgoing,
          :raw_platform_payload_reference
        )
        ON CONFLICT(source, chat_id, message_id) DO UPDATE SET
          sender_id = excluded.sender_id,
          sender_name = excluded.sender_name,
          timestamp = excluded.timestamp,
          text = excluded.text,
          message_type = excluded.message_type,
          reply_to_message_id = excluded.reply_to_message_id,
          reactions = excluded.reactions,
          media_type = excluded.media_type,
          media_duration = excluded.media_duration,
          forward_info = excluded.forward_info,
          edit_date = excluded.edit_date,
          is_outgoing = excluded.is_outgoing,
          raw_platform_payload_reference = excluded.raw_platform_payload_reference,
          updated_at = CURRENT_TIMESTAMP
        """,
        message_to_row(message),
    )


def list_messages(conn: sqlite3.Connection, conversation_id: str, *, source: str = "telegram") -> list[Message]:
    rows = conn.execute(
        """
        SELECT * FROM messages
        WHERE source = ? AND chat_id = ?
        ORDER BY timestamp ASC, message_id ASC
        """,
        (source, conversation_id),
    ).fetchall()
    return [message_from_row(row) for row in rows]


def mark_conversation_imported(
    conn: sqlite3.Connection,
    *,
    source: str = "telegram",
    conversation_id: str,
    range_start: str | None,
    range_end: str | None,
    last_message_id: int | None,
) -> None:
    conn.execute(
        """
        UPDATE chats SET
          import_range_start = ?,
          import_range_end = ?,
          last_imported_message_id = ?,
          updated_at = CURRENT_TIMESTAMP
        WHERE source = ? AND chat_id = ?
        """,
        (range_start, range_end, last_message_id, source, conversation_id),
    )


def message_to_row(message: Message) -> dict:
    return {
        "source": message.source,
        "message_id": message.source_message_id,
        "chat_id": message.conversation_id,
        "sender_id": message.sender_id,
        "sender_name": message.sender_name,
        "timestamp": message.timestamp,
        "text": message.text,
        "message_type": message.message_type,
        "reply_to_message_id": message.reply_to_message_id,
        "reactions": message.reactions,
        "media_type": message.media_type,
        "media_duration": message.media_duration,
        "forward_info": message.forward_info,
        "edit_date": message.edit_date,
        "is_outgoing": 1 if message.is_outgoing else 0,
        "raw_platform_payload_reference": message.raw_platform_payload_reference,
    }


def message_from_row(row: sqlite3.Row) -> Message:
    return Message(
        source=row["source"],
        source_message_id=int(row["message_id"]),
        conversation_id=str(row["chat_id"]),
        sender_id=row["sender_id"],
        sender_name=row["sender_name"],
        timestamp=row["timestamp"],
        text=row["text"] or "",
        message_type=row["message_type"],
        reply_to_message_id=row["reply_to_message_id"],
        reactions=row["reactions"],
        media_type=row["media_type"],
        media_duration=row["media_duration"],
        forward_info=row["forward_info"],
        edit_date=row["edit_date"],
        is_outgoing=bool(row["is_outgoing"]),
        raw_platform_payload_reference=row["raw_platform_payload_reference"],
    )
