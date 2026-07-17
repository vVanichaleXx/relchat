from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from relchat.core.models import ConversationRef, DialogFolder, Message


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


def save_user_message(conn: sqlite3.Connection, bot_user_id: int, message: Message) -> None:
    save_message(conn, message)
    conn.execute(
        """
        INSERT INTO message_owners(bot_user_id, source, chat_id, message_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(bot_user_id, source, chat_id, message_id) DO NOTHING
        """,
        (bot_user_id, message.source, message.conversation_id, message.source_message_id),
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


def list_user_messages(
    conn: sqlite3.Connection,
    bot_user_id: int,
    conversation_id: str,
    *,
    source: str = "telegram",
    after_message_id: int | None = None,
    limit: int | None = None,
) -> list[Message]:
    where = [
        "message_owners.bot_user_id = ?",
        "messages.source = ?",
        "messages.chat_id = ?",
    ]
    params: list[Any] = [bot_user_id, source, conversation_id]
    if after_message_id is not None:
        where.append("messages.message_id > ?")
        params.append(int(after_message_id))
    sql = f"""
        SELECT messages.* FROM messages
        INNER JOIN message_owners
          ON message_owners.source = messages.source
         AND message_owners.chat_id = messages.chat_id
         AND message_owners.message_id = messages.message_id
        WHERE {' AND '.join(where)}
        ORDER BY messages.timestamp ASC, messages.message_id ASC
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, int(limit)))
    rows = conn.execute(sql, params).fetchall()
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def ensure_user_profile(conn: sqlite3.Connection, bot_user_id: int) -> dict[str, Any]:
    conn.execute(
        """
        INSERT INTO bot_user_profiles(bot_user_id)
        VALUES (?)
        ON CONFLICT(bot_user_id) DO NOTHING
        """,
        (bot_user_id,),
    )
    conn.execute(
        """
        INSERT INTO user_settings(bot_user_id)
        VALUES (?)
        ON CONFLICT(bot_user_id) DO NOTHING
        """,
        (bot_user_id,),
    )
    return get_user_profile(conn, bot_user_id) or {
        "bot_user_id": bot_user_id,
        "onboarding_completed": False,
        "language": "en",
    }


def get_user_profile(conn: sqlite3.Connection, bot_user_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM bot_user_profiles WHERE bot_user_id = ?",
        (bot_user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "bot_user_id": int(row["bot_user_id"]),
        "onboarding_completed": bool(row["onboarding_completed"]),
        "language": row["language"] or "en",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def set_onboarding_completed(conn: sqlite3.Connection, bot_user_id: int, completed: bool) -> None:
    ensure_user_profile(conn, bot_user_id)
    conn.execute(
        """
        UPDATE bot_user_profiles
        SET onboarding_completed = ?, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ?
        """,
        (1 if completed else 0, bot_user_id),
    )


def get_user_settings(conn: sqlite3.Connection, bot_user_id: int) -> dict[str, Any]:
    ensure_user_profile(conn, bot_user_id)
    row = conn.execute(
        "SELECT * FROM user_settings WHERE bot_user_id = ?",
        (bot_user_id,),
    ).fetchone()
    if row is None:
        return default_user_settings(bot_user_id)
    return {
        "bot_user_id": int(row["bot_user_id"]),
        "language": row["language"] or "en",
        "default_period": row["default_period"] or "30d",
        "default_modules": json_loads(row["default_modules"], []),
        "progress_notifications": bool(row["progress_notifications"]),
        "show_technical_details": bool(row["show_technical_details"]),
        "data_retention_days": row["data_retention_days"],
        "confirm_before_delete": bool(row["confirm_before_delete"]),
        "automatic_analysis_master_enabled": bool(row["automatic_analysis_master_enabled"]),
        "automatic_default_notification_enabled": bool(row["automatic_default_notification_enabled"]),
        "automatic_default_minimum_new_messages": int(row["automatic_default_minimum_new_messages"] or 10),
        "automatic_default_inactivity_minutes": int(row["automatic_default_inactivity_minutes"] or 45),
        "automatic_default_cooldown_hours": int(row["automatic_default_cooldown_hours"] or 12),
        "automatic_default_quiet_hours_enabled": bool(row["automatic_default_quiet_hours_enabled"]),
        "automatic_default_quiet_hours_start": row["automatic_default_quiet_hours_start"] or "23:00",
        "automatic_default_quiet_hours_end": row["automatic_default_quiet_hours_end"] or "08:00",
        "automatic_default_preferred_analysis_mode": row["automatic_default_preferred_analysis_mode"] or "local",
    }


def default_user_settings(bot_user_id: int) -> dict[str, Any]:
    return {
        "bot_user_id": bot_user_id,
        "language": "en",
        "default_period": "30d",
        "default_modules": [
            "balance",
            "initiation",
            "response_times",
            "activity",
            "questions",
            "plans",
            "followups",
            "reminders",
        ],
        "progress_notifications": True,
        "show_technical_details": False,
        "data_retention_days": None,
        "confirm_before_delete": True,
        "automatic_analysis_master_enabled": False,
        "automatic_default_notification_enabled": True,
        "automatic_default_minimum_new_messages": 10,
        "automatic_default_inactivity_minutes": 45,
        "automatic_default_cooldown_hours": 12,
        "automatic_default_quiet_hours_enabled": True,
        "automatic_default_quiet_hours_start": "23:00",
        "automatic_default_quiet_hours_end": "08:00",
        "automatic_default_preferred_analysis_mode": "local",
    }


def update_user_setting(conn: sqlite3.Connection, bot_user_id: int, key: str, value: Any) -> None:
    allowed = {
        "language",
        "default_period",
        "default_modules",
        "progress_notifications",
        "show_technical_details",
        "data_retention_days",
        "confirm_before_delete",
        "automatic_analysis_master_enabled",
        "automatic_default_notification_enabled",
        "automatic_default_minimum_new_messages",
        "automatic_default_inactivity_minutes",
        "automatic_default_cooldown_hours",
        "automatic_default_quiet_hours_enabled",
        "automatic_default_quiet_hours_start",
        "automatic_default_quiet_hours_end",
        "automatic_default_preferred_analysis_mode",
    }
    if key not in allowed:
        raise ValueError(f"Unknown user setting: {key}")
    ensure_user_profile(conn, bot_user_id)
    stored = json_dumps(value) if key == "default_modules" else value
    if isinstance(stored, bool):
        stored = 1 if stored else 0
    conn.execute(
        f"""
        UPDATE user_settings
        SET {key} = ?, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ?
        """,
        (stored, bot_user_id),
    )
    if key == "language":
        conn.execute(
            """
            UPDATE bot_user_profiles
            SET language = ?, updated_at = CURRENT_TIMESTAMP
            WHERE bot_user_id = ?
            """,
            (value, bot_user_id),
        )


def save_user_chat(
    conn: sqlite3.Connection,
    bot_user_id: int,
    conversation: ConversationRef,
    *,
    saved: bool | None = None,
    favorite: bool | None = None,
) -> None:
    save_conversation(conn, conversation)
    existing = get_user_chat(conn, bot_user_id, conversation.source, conversation.conversation_id)
    is_saved = bool(existing.get("is_saved")) if existing else False
    is_favorite = bool(existing.get("is_favorite")) if existing else False
    local_title = existing.get("local_title") if existing else None
    if saved is not None:
        is_saved = saved
    if favorite is not None:
        is_favorite = favorite
        if favorite:
            is_saved = True
    conn.execute(
        """
        INSERT INTO user_chats(
          bot_user_id, source, chat_id, chat_type, display_title, local_title,
          username, folder_id, last_message_at, unread_count, is_saved, is_favorite
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bot_user_id, source, chat_id) DO UPDATE SET
          chat_type = excluded.chat_type,
          display_title = excluded.display_title,
          local_title = COALESCE(user_chats.local_title, excluded.local_title),
          username = excluded.username,
          folder_id = excluded.folder_id,
          last_message_at = excluded.last_message_at,
          unread_count = excluded.unread_count,
          is_saved = excluded.is_saved,
          is_favorite = excluded.is_favorite,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            bot_user_id,
            conversation.source,
            conversation.conversation_id,
            conversation.conversation_type,
            conversation.title,
            local_title,
            conversation.username,
            conversation.folder_id,
            conversation.last_message_at,
            conversation.unread_count,
            1 if is_saved else 0,
            1 if is_favorite else 0,
        ),
    )


def get_user_chat(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM user_chats
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (bot_user_id, source, chat_id),
    ).fetchone()
    return user_chat_from_row(row) if row is not None else None


def list_user_chats(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    section: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    where = ["bot_user_id = ?"]
    params: list[Any] = [bot_user_id]
    order = "updated_at DESC"
    if section == "favorites":
        where.append("is_favorite = 1")
    elif section == "saved":
        where.append("is_saved = 1")
    elif section == "recent":
        where.append("recent_analyzed_at IS NOT NULL")
        order = "recent_analyzed_at DESC"
    sql = f"SELECT * FROM user_chats WHERE {' AND '.join(where)} ORDER BY {order}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [user_chat_from_row(row) for row in rows]


def list_cached_conversations(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    source: str = "telegram",
    limit: int | None = None,
) -> list[ConversationRef]:
    params: list[Any] = [bot_user_id, source]
    sql = """
        SELECT * FROM user_chats
        WHERE bot_user_id = ? AND source = ?
        ORDER BY COALESCE(last_message_at, updated_at) DESC
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [conversation_ref_from_user_chat(user_chat_from_row(row)) for row in rows]


def save_dialog_cache(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    conversations: Iterable[ConversationRef],
    folders: Iterable[DialogFolder],
    folder_memberships: dict[int, set[str]] | None = None,
    source: str = "telegram",
) -> None:
    ensure_user_profile(conn, bot_user_id)
    for conversation in conversations:
        save_user_chat(conn, bot_user_id, conversation)
    conn.execute(
        "DELETE FROM dialog_folders WHERE bot_user_id = ? AND source = ?",
        (bot_user_id, source),
    )
    conn.execute(
        "DELETE FROM dialog_folder_memberships WHERE bot_user_id = ? AND source = ?",
        (bot_user_id, source),
    )
    for folder in folders:
        conn.execute(
            """
            INSERT INTO dialog_folders(bot_user_id, source, folder_id, title)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bot_user_id, source, folder_id) DO UPDATE SET
              title = excluded.title,
              updated_at = CURRENT_TIMESTAMP
            """,
            (bot_user_id, source, int(folder.folder_id), folder.title),
        )
    for folder_id, chat_ids in (folder_memberships or {}).items():
        for chat_id in chat_ids:
            conn.execute(
                """
                INSERT INTO dialog_folder_memberships(bot_user_id, source, folder_id, chat_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(bot_user_id, source, folder_id, chat_id) DO UPDATE SET
                  updated_at = CURRENT_TIMESTAMP
                """,
                (bot_user_id, source, int(folder_id), str(chat_id)),
            )


def list_cached_dialog_folders(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    source: str = "telegram",
) -> list[DialogFolder]:
    rows = conn.execute(
        """
        SELECT folder_id, title FROM dialog_folders
        WHERE bot_user_id = ? AND source = ?
        ORDER BY folder_id ASC
        """,
        (bot_user_id, source),
    ).fetchall()
    return [DialogFolder(folder_id=int(row["folder_id"]), title=row["title"]) for row in rows]


def cached_folder_memberships(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    source: str = "telegram",
) -> dict[int, set[str]]:
    rows = conn.execute(
        """
        SELECT folder_id, chat_id FROM dialog_folder_memberships
        WHERE bot_user_id = ? AND source = ?
        """,
        (bot_user_id, source),
    ).fetchall()
    memberships: dict[int, set[str]] = {}
    for row in rows:
        memberships.setdefault(int(row["folder_id"]), set()).add(str(row["chat_id"]))
    return memberships


def set_user_chat_saved(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    saved: bool,
) -> None:
    conn.execute(
        """
        UPDATE user_chats
        SET is_saved = ?, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (1 if saved else 0, bot_user_id, source, chat_id),
    )


def set_user_chat_favorite(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    favorite: bool,
) -> None:
    conn.execute(
        """
        UPDATE user_chats
        SET is_favorite = ?, is_saved = CASE WHEN ? = 1 THEN 1 ELSE is_saved END, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (1 if favorite else 0, 1 if favorite else 0, bot_user_id, source, chat_id),
    )


def rename_user_chat(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    local_title: str | None,
) -> None:
    conn.execute(
        """
        UPDATE user_chats
        SET local_title = ?, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (local_title, bot_user_id, source, chat_id),
    )


def mark_user_chat_analyzed(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    report_id: str,
) -> None:
    conn.execute(
        """
        UPDATE user_chats
        SET is_saved = 1,
            recent_analyzed_at = CURRENT_TIMESTAMP,
            last_report_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (report_id, bot_user_id, source, chat_id),
    )


def remove_user_chat(conn: sqlite3.Connection, bot_user_id: int, source: str, chat_id: str) -> None:
    conn.execute(
        """
        DELETE FROM user_chats
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (bot_user_id, source, chat_id),
    )


def delete_imported_messages_for_chat(
    conn: sqlite3.Connection,
    source: str,
    chat_id: str,
    *,
    bot_user_id: int | None = None,
) -> int:
    before = conn.total_changes
    if bot_user_id is None:
        conn.execute(
            "DELETE FROM message_owners WHERE source = ? AND chat_id = ?",
            (source, chat_id),
        )
        conn.execute(
            "DELETE FROM messages WHERE source = ? AND chat_id = ?",
            (source, chat_id),
        )
        return conn.total_changes - before
    conn.execute(
        """
        DELETE FROM message_owners
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (bot_user_id, source, chat_id),
    )
    conn.execute(
        """
        DELETE FROM messages
        WHERE source = ? AND chat_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM message_owners
            WHERE message_owners.source = messages.source
              AND message_owners.chat_id = messages.chat_id
              AND message_owners.message_id = messages.message_id
          )
        """,
        (source, chat_id),
    )
    return conn.total_changes - before


def user_chat_from_row(row: sqlite3.Row) -> dict[str, Any]:
    title = row["local_title"] or row["display_title"]
    return {
        "bot_user_id": int(row["bot_user_id"]),
        "source": row["source"],
        "chat_id": row["chat_id"],
        "chat_type": row["chat_type"],
        "display_title": row["display_title"],
        "local_title": row["local_title"],
        "title": title,
        "username": row["username"],
        "folder_id": row["folder_id"],
        "last_message_at": row["last_message_at"],
        "unread_count": int(row["unread_count"] or 0),
        "is_saved": bool(row["is_saved"]),
        "is_favorite": bool(row["is_favorite"]),
        "recent_analyzed_at": row["recent_analyzed_at"],
        "last_report_id": row["last_report_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def conversation_ref_from_user_chat(chat: dict[str, Any]) -> ConversationRef:
    return ConversationRef(
        source=chat.get("source") or "telegram",
        conversation_id=str(chat.get("chat_id") or ""),
        conversation_type=str(chat.get("chat_type") or "unknown"),
        title=chat.get("title") or chat.get("display_title"),
        last_message_at=chat.get("last_message_at"),
        username=chat.get("username"),
        folder_id=chat.get("folder_id"),
        unread_count=int(chat.get("unread_count") or 0),
    )


IMPORTANT_CHAT_SETTING_KEYS = {
    "is_important",
    "automatic_analysis_enabled",
    "automatic_notification_enabled",
    "minimum_new_messages",
    "inactivity_threshold_minutes",
    "cooldown_hours",
    "quiet_hours_enabled",
    "quiet_hours_start",
    "quiet_hours_end",
    "preferred_analysis_mode",
    "automatic_delivery_mode",
    "last_automatic_analysis_at",
    "last_observed_message_at",
    "last_automatic_message_id",
    "automation_paused_until",
}


def important_chat_defaults(user_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = user_settings or {}
    return {
        "is_important": False,
        "automatic_analysis_enabled": False,
        "automatic_notification_enabled": bool(settings.get("automatic_default_notification_enabled", True)),
        "minimum_new_messages": int(settings.get("automatic_default_minimum_new_messages") or 10),
        "inactivity_threshold_minutes": int(settings.get("automatic_default_inactivity_minutes") or 45),
        "cooldown_hours": int(settings.get("automatic_default_cooldown_hours") or 12),
        "quiet_hours_enabled": bool(settings.get("automatic_default_quiet_hours_enabled", True)),
        "quiet_hours_start": settings.get("automatic_default_quiet_hours_start") or "23:00",
        "quiet_hours_end": settings.get("automatic_default_quiet_hours_end") or "08:00",
        "preferred_analysis_mode": settings.get("automatic_default_preferred_analysis_mode") or "local",
        "automatic_delivery_mode": "suggest",
        "last_automatic_analysis_at": None,
        "last_observed_message_at": None,
        "last_automatic_message_id": None,
        "automation_paused_until": None,
    }


def get_important_chat_settings(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
) -> dict[str, Any]:
    user_settings = get_user_settings(conn, bot_user_id)
    defaults = important_chat_defaults(user_settings)
    row = conn.execute(
        """
        SELECT * FROM important_chat_settings
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (bot_user_id, source, chat_id),
    ).fetchone()
    if row is None:
        return {
            "bot_user_id": bot_user_id,
            "source": source,
            "chat_id": chat_id,
            **defaults,
        }
    return important_chat_settings_from_row(row, defaults=defaults)


def ensure_important_chat_settings(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
) -> dict[str, Any]:
    current = get_important_chat_settings(conn, bot_user_id, source, chat_id)
    conn.execute(
        """
        INSERT INTO important_chat_settings(
          bot_user_id, source, chat_id, is_important, automatic_analysis_enabled,
          automatic_notification_enabled, minimum_new_messages,
          inactivity_threshold_minutes, cooldown_hours, quiet_hours_enabled,
          quiet_hours_start, quiet_hours_end, preferred_analysis_mode,
          automatic_delivery_mode
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bot_user_id, source, chat_id) DO NOTHING
        """,
        (
            bot_user_id,
            source,
            chat_id,
            1 if current["is_important"] else 0,
            1 if current["automatic_analysis_enabled"] else 0,
            1 if current["automatic_notification_enabled"] else 0,
            current["minimum_new_messages"],
            current["inactivity_threshold_minutes"],
            current["cooldown_hours"],
            1 if current["quiet_hours_enabled"] else 0,
            current["quiet_hours_start"],
            current["quiet_hours_end"],
            current["preferred_analysis_mode"],
            current["automatic_delivery_mode"],
        ),
    )
    return get_important_chat_settings(conn, bot_user_id, source, chat_id)


def set_chat_important(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    important: bool,
) -> dict[str, Any]:
    ensure_important_chat_settings(conn, bot_user_id, source, chat_id)
    conn.execute(
        """
        UPDATE important_chat_settings
        SET is_important = ?,
            automatic_analysis_enabled = CASE WHEN ? = 0 THEN 0 ELSE automatic_analysis_enabled END,
            updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (1 if important else 0, 1 if important else 0, bot_user_id, source, chat_id),
    )
    if important:
        conn.execute(
            """
            UPDATE user_chats
            SET is_saved = 1, updated_at = CURRENT_TIMESTAMP
            WHERE bot_user_id = ? AND source = ? AND chat_id = ?
            """,
            (bot_user_id, source, chat_id),
        )
    return get_important_chat_settings(conn, bot_user_id, source, chat_id)


def update_important_chat_setting(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    key: str,
    value: Any,
) -> dict[str, Any]:
    if key not in IMPORTANT_CHAT_SETTING_KEYS:
        raise ValueError(f"Unknown important-chat setting: {key}")
    ensure_important_chat_settings(conn, bot_user_id, source, chat_id)
    stored = normalize_important_setting_value(key, value)
    conn.execute(
        f"""
        UPDATE important_chat_settings
        SET {key} = ?, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (stored, bot_user_id, source, chat_id),
    )
    return get_important_chat_settings(conn, bot_user_id, source, chat_id)


def list_important_chats(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT important_chat_settings.*, user_chats.display_title, user_chats.local_title,
               user_chats.chat_type, user_chats.username, user_chats.last_report_id,
               automation_states.pending_new_message_count,
               automation_states.last_automatic_analysis_at AS state_last_automatic_analysis_at
        FROM important_chat_settings
        LEFT JOIN user_chats
          ON user_chats.bot_user_id = important_chat_settings.bot_user_id
         AND user_chats.source = important_chat_settings.source
         AND user_chats.chat_id = important_chat_settings.chat_id
        LEFT JOIN automation_states
          ON automation_states.bot_user_id = important_chat_settings.bot_user_id
         AND automation_states.source = important_chat_settings.source
         AND automation_states.chat_id = important_chat_settings.chat_id
        WHERE important_chat_settings.bot_user_id = ?
          AND important_chat_settings.is_important = 1
        ORDER BY important_chat_settings.updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (bot_user_id, max(1, int(limit)), max(0, int(offset))),
    ).fetchall()
    user_settings = get_user_settings(conn, bot_user_id)
    defaults = important_chat_defaults(user_settings)
    return [important_chat_settings_from_row(row, defaults=defaults) for row in rows]


def list_automation_enabled_chats(conn: sqlite3.Connection, *, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT important_chat_settings.*, user_chats.display_title, user_chats.local_title,
               user_chats.chat_type, user_chats.username, user_settings.automatic_analysis_master_enabled,
               user_settings.default_modules, user_settings.automatic_default_notification_enabled,
               user_settings.automatic_default_minimum_new_messages,
               user_settings.automatic_default_inactivity_minutes,
               user_settings.automatic_default_cooldown_hours,
               user_settings.automatic_default_quiet_hours_enabled,
               user_settings.automatic_default_quiet_hours_start,
               user_settings.automatic_default_quiet_hours_end,
               user_settings.automatic_default_preferred_analysis_mode
        FROM important_chat_settings
        INNER JOIN user_settings
          ON user_settings.bot_user_id = important_chat_settings.bot_user_id
        LEFT JOIN user_chats
          ON user_chats.bot_user_id = important_chat_settings.bot_user_id
         AND user_chats.source = important_chat_settings.source
         AND user_chats.chat_id = important_chat_settings.chat_id
        WHERE important_chat_settings.is_important = 1
          AND important_chat_settings.automatic_analysis_enabled = 1
          AND user_settings.automatic_analysis_master_enabled = 1
        ORDER BY important_chat_settings.updated_at ASC
    """
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        user_defaults = important_chat_defaults(
            {
                "automatic_default_notification_enabled": bool(row["automatic_default_notification_enabled"]),
                "automatic_default_minimum_new_messages": int(row["automatic_default_minimum_new_messages"] or 10),
                "automatic_default_inactivity_minutes": int(row["automatic_default_inactivity_minutes"] or 45),
                "automatic_default_cooldown_hours": int(row["automatic_default_cooldown_hours"] or 12),
                "automatic_default_quiet_hours_enabled": bool(row["automatic_default_quiet_hours_enabled"]),
                "automatic_default_quiet_hours_start": row["automatic_default_quiet_hours_start"],
                "automatic_default_quiet_hours_end": row["automatic_default_quiet_hours_end"],
                "automatic_default_preferred_analysis_mode": row["automatic_default_preferred_analysis_mode"],
            }
        )
        item = important_chat_settings_from_row(row, defaults=user_defaults)
        item["automatic_analysis_master_enabled"] = bool(row["automatic_analysis_master_enabled"])
        item["default_modules"] = json_loads(row["default_modules"], [])
        result.append(item)
    return result


def important_chat_settings_from_row(row: sqlite3.Row, *, defaults: dict[str, Any]) -> dict[str, Any]:
    keys = set(row.keys())
    local_title = row["local_title"] if "local_title" in keys else None
    display_title = row["display_title"] if "display_title" in keys else None
    title = local_title or display_title
    value = {
        "bot_user_id": int(row["bot_user_id"]),
        "source": row["source"],
        "chat_id": row["chat_id"],
        "chat_type": row["chat_type"] if "chat_type" in keys else None,
        "title": title,
        "username": row["username"] if "username" in keys else None,
        "last_report_id": row["last_report_id"] if "last_report_id" in keys else None,
        "is_important": bool(row["is_important"]),
        "automatic_analysis_enabled": bool(row["automatic_analysis_enabled"]),
        "automatic_notification_enabled": bool(row["automatic_notification_enabled"]),
        "minimum_new_messages": int(row["minimum_new_messages"] or defaults["minimum_new_messages"]),
        "inactivity_threshold_minutes": int(row["inactivity_threshold_minutes"] or defaults["inactivity_threshold_minutes"]),
        "cooldown_hours": int(row["cooldown_hours"] or defaults["cooldown_hours"]),
        "quiet_hours_enabled": bool(row["quiet_hours_enabled"]),
        "quiet_hours_start": row["quiet_hours_start"] or defaults["quiet_hours_start"],
        "quiet_hours_end": row["quiet_hours_end"] or defaults["quiet_hours_end"],
        "preferred_analysis_mode": row["preferred_analysis_mode"] or defaults["preferred_analysis_mode"],
        "automatic_delivery_mode": row["automatic_delivery_mode"] or "suggest",
        "last_automatic_analysis_at": row["last_automatic_analysis_at"],
        "last_observed_message_at": row["last_observed_message_at"],
        "last_automatic_message_id": row["last_automatic_message_id"],
        "automation_paused_until": row["automation_paused_until"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if "pending_new_message_count" in keys:
        value["pending_new_message_count"] = int(row["pending_new_message_count"] or 0)
    if "state_last_automatic_analysis_at" in keys and row["state_last_automatic_analysis_at"]:
        value["last_automatic_analysis_at"] = row["state_last_automatic_analysis_at"]
    return value


def normalize_important_setting_value(key: str, value: Any) -> Any:
    if key in {"is_important", "automatic_analysis_enabled", "automatic_notification_enabled", "quiet_hours_enabled"}:
        return 1 if bool(value) else 0
    if key in {"minimum_new_messages", "inactivity_threshold_minutes", "cooldown_hours", "last_automatic_message_id"}:
        return int(value) if value is not None else None
    if key == "preferred_analysis_mode":
        return str(value) if str(value) in {"local", "ai"} else "local"
    if key == "automatic_delivery_mode":
        return str(value) if str(value) in {"suggest", "auto"} else "suggest"
    return value


def get_automation_state(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM automation_states
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
        """,
        (bot_user_id, source, chat_id),
    ).fetchone()
    if row is None:
        return {
            "bot_user_id": bot_user_id,
            "source": source,
            "chat_id": chat_id,
            "observed_message_cursor": None,
            "last_observed_message_at": None,
            "last_automatic_message_id": None,
            "last_automatic_analysis_at": None,
            "last_notification_at": None,
            "pending_new_message_count": 0,
            "pending_range_start_message_id": None,
            "pending_range_end_message_id": None,
            "pending_deliver_after": None,
            "last_pause_candidate_at": None,
            "suppressed_reason": None,
        }
    return automation_state_from_row(row)


def upsert_automation_state(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    **values: Any,
) -> dict[str, Any]:
    current = get_automation_state(conn, bot_user_id, source, chat_id)
    current.update(values)
    conn.execute(
        """
        INSERT INTO automation_states(
          bot_user_id, source, chat_id, observed_message_cursor,
          last_observed_message_at, last_automatic_message_id,
          last_automatic_analysis_at, last_notification_at,
          pending_new_message_count, pending_range_start_message_id,
          pending_range_end_message_id, pending_deliver_after,
          last_pause_candidate_at, suppressed_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bot_user_id, source, chat_id) DO UPDATE SET
          observed_message_cursor = excluded.observed_message_cursor,
          last_observed_message_at = excluded.last_observed_message_at,
          last_automatic_message_id = excluded.last_automatic_message_id,
          last_automatic_analysis_at = excluded.last_automatic_analysis_at,
          last_notification_at = excluded.last_notification_at,
          pending_new_message_count = excluded.pending_new_message_count,
          pending_range_start_message_id = excluded.pending_range_start_message_id,
          pending_range_end_message_id = excluded.pending_range_end_message_id,
          pending_deliver_after = excluded.pending_deliver_after,
          last_pause_candidate_at = excluded.last_pause_candidate_at,
          suppressed_reason = excluded.suppressed_reason,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            bot_user_id,
            source,
            chat_id,
            current.get("observed_message_cursor"),
            current.get("last_observed_message_at"),
            current.get("last_automatic_message_id"),
            current.get("last_automatic_analysis_at"),
            current.get("last_notification_at"),
            int(current.get("pending_new_message_count") or 0),
            current.get("pending_range_start_message_id"),
            current.get("pending_range_end_message_id"),
            current.get("pending_deliver_after"),
            current.get("last_pause_candidate_at"),
            current.get("suppressed_reason"),
        ),
    )
    return get_automation_state(conn, bot_user_id, source, chat_id)


def automation_state_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "bot_user_id": int(row["bot_user_id"]),
        "source": row["source"],
        "chat_id": row["chat_id"],
        "observed_message_cursor": row["observed_message_cursor"],
        "last_observed_message_at": row["last_observed_message_at"],
        "last_automatic_message_id": row["last_automatic_message_id"],
        "last_automatic_analysis_at": row["last_automatic_analysis_at"],
        "last_notification_at": row["last_notification_at"],
        "pending_new_message_count": int(row["pending_new_message_count"] or 0),
        "pending_range_start_message_id": row["pending_range_start_message_id"],
        "pending_range_end_message_id": row["pending_range_end_message_id"],
        "pending_deliver_after": row["pending_deliver_after"],
        "last_pause_candidate_at": row["last_pause_candidate_at"],
        "suppressed_reason": row["suppressed_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def automatic_range_exists(
    conn: sqlite3.Connection,
    bot_user_id: int,
    source: str,
    chat_id: str,
    start_message_id: int,
    end_message_id: int,
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM automatic_analysis_ranges
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
          AND start_message_id = ? AND end_message_id = ?
        """,
        (bot_user_id, source, chat_id, int(start_message_id), int(end_message_id)),
    ).fetchone()
    return row is not None


def record_automatic_range(
    conn: sqlite3.Connection,
    *,
    bot_user_id: int,
    source: str,
    chat_id: str,
    start_message_id: int,
    end_message_id: int,
    message_count: int,
    action: str,
    analysis_id: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    range_id = new_id("auto")
    conn.execute(
        """
        INSERT INTO automatic_analysis_ranges(
          range_id, bot_user_id, source, chat_id, start_message_id,
          end_message_id, message_count, action, analysis_id, report_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bot_user_id, source, chat_id, start_message_id, end_message_id)
        DO UPDATE SET
          action = excluded.action,
          analysis_id = COALESCE(excluded.analysis_id, automatic_analysis_ranges.analysis_id),
          report_id = COALESCE(excluded.report_id, automatic_analysis_ranges.report_id),
          completed_at = CURRENT_TIMESTAMP
        """,
        (
            range_id,
            bot_user_id,
            source,
            chat_id,
            int(start_message_id),
            int(end_message_id),
            max(0, int(message_count)),
            action,
            analysis_id,
            report_id,
        ),
    )
    return {
        "range_id": range_id,
        "bot_user_id": bot_user_id,
        "source": source,
        "chat_id": chat_id,
        "start_message_id": int(start_message_id),
        "end_message_id": int(end_message_id),
        "message_count": max(0, int(message_count)),
        "action": action,
        "analysis_id": analysis_id,
        "report_id": report_id,
    }


def create_pending_automatic_notification(
    conn: sqlite3.Connection,
    *,
    bot_user_id: int,
    source: str,
    chat_id: str,
    chat_title: str | None,
    range_start_message_id: int,
    range_end_message_id: int,
    notification_type: str,
    deliver_after: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    notification_id = new_id("not")
    conn.execute(
        """
        INSERT INTO pending_automatic_notifications(
          notification_id, bot_user_id, source, chat_id, chat_title,
          range_start_message_id, range_end_message_id, notification_type,
          status, deliver_after, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            notification_id,
            bot_user_id,
            source,
            chat_id,
            chat_title,
            int(range_start_message_id),
            int(range_end_message_id),
            notification_type,
            deliver_after,
            json_dumps(payload or {}),
        ),
    )
    return get_pending_automatic_notification(conn, bot_user_id, notification_id) or {"notification_id": notification_id}


def get_pending_automatic_notification(
    conn: sqlite3.Connection,
    bot_user_id: int,
    notification_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM pending_automatic_notifications
        WHERE notification_id = ? AND bot_user_id = ?
        """,
        (notification_id, bot_user_id),
    ).fetchone()
    return automatic_notification_from_row(row) if row is not None else None


def list_due_automatic_notifications(
    conn: sqlite3.Connection,
    *,
    now: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM pending_automatic_notifications
        WHERE status = 'pending'
          AND (deliver_after IS NULL OR deliver_after <= ?)
        ORDER BY COALESCE(deliver_after, created_at) ASC
        LIMIT ?
        """,
        (now, max(1, int(limit))),
    ).fetchall()
    return [automatic_notification_from_row(row) for row in rows]


def update_automatic_notification_status(
    conn: sqlite3.Connection,
    bot_user_id: int,
    notification_id: str,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE pending_automatic_notifications
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND notification_id = ?
        """,
        (status, bot_user_id, notification_id),
    )


def count_automatic_notifications_since(
    conn: sqlite3.Connection,
    bot_user_id: int,
    since_iso: str,
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count FROM pending_automatic_notifications
        WHERE bot_user_id = ? AND status IN ('delivered','completed') AND updated_at >= ?
        """,
        (bot_user_id, since_iso),
    ).fetchone()
    return int(row["count"] or 0)


def automatic_notification_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "notification_id": row["notification_id"],
        "bot_user_id": int(row["bot_user_id"]),
        "source": row["source"],
        "chat_id": row["chat_id"],
        "chat_title": row["chat_title"],
        "range_start_message_id": int(row["range_start_message_id"]),
        "range_end_message_id": int(row["range_end_message_id"]),
        "notification_type": row["notification_type"],
        "status": row["status"],
        "deliver_after": row["deliver_after"],
        "payload": json_loads(row["payload_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_period_comparison(
    conn: sqlite3.Connection,
    *,
    bot_user_id: int,
    source: str,
    chat_id: str,
    comparison_type: str,
    status: str,
    quality: str,
    result: dict[str, Any],
    current_report_id: str | None = None,
    previous_report_id: str | None = None,
    current_analysis_id: str | None = None,
    previous_analysis_id: str | None = None,
) -> dict[str, Any]:
    comparison_id = new_id("cmp")
    conn.execute(
        """
        INSERT INTO period_comparisons(
          comparison_id, bot_user_id, source, chat_id, comparison_type,
          current_report_id, previous_report_id, current_analysis_id,
          previous_analysis_id, status, quality, result_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            comparison_id,
            bot_user_id,
            source,
            chat_id,
            comparison_type,
            current_report_id,
            previous_report_id,
            current_analysis_id,
            previous_analysis_id,
            status,
            quality,
            json_dumps(result),
        ),
    )
    return get_period_comparison(conn, bot_user_id, comparison_id) or {"comparison_id": comparison_id}


def get_period_comparison(
    conn: sqlite3.Connection,
    bot_user_id: int,
    comparison_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM period_comparisons
        WHERE bot_user_id = ? AND comparison_id = ?
        """,
        (bot_user_id, comparison_id),
    ).fetchone()
    return period_comparison_from_row(row) if row is not None else None


def latest_period_comparison_for_report(
    conn: sqlite3.Connection,
    bot_user_id: int,
    report_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM period_comparisons
        WHERE bot_user_id = ? AND current_report_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (bot_user_id, report_id),
    ).fetchone()
    return period_comparison_from_row(row) if row is not None else None


def latest_period_comparison_for_analysis(
    conn: sqlite3.Connection,
    bot_user_id: int,
    analysis_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM period_comparisons
        WHERE bot_user_id = ? AND current_analysis_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (bot_user_id, analysis_id),
    ).fetchone()
    return period_comparison_from_row(row) if row is not None else None


def period_comparison_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "comparison_id": row["comparison_id"],
        "bot_user_id": int(row["bot_user_id"]),
        "source": row["source"],
        "chat_id": row["chat_id"],
        "comparison_type": row["comparison_type"],
        "current_report_id": row["current_report_id"],
        "previous_report_id": row["previous_report_id"],
        "current_analysis_id": row["current_analysis_id"],
        "previous_analysis_id": row["previous_analysis_id"],
        "status": row["status"],
        "quality": row["quality"],
        "result": json_loads(row["result_json"], {}),
        "created_at": row["created_at"],
    }


def create_analysis_job(
    conn: sqlite3.Connection,
    *,
    bot_user_id: int,
    source: str,
    chat_id: str,
    chat_title: str | None,
    period_id: str,
    period_label: str,
    period_start: str | None,
    period_end: str | None,
    modules: list[str],
    progress_chat_id: int | None = None,
    progress_message_id: int | None = None,
    analysis_mode: str = "local",
) -> dict[str, Any]:
    job_id = new_id("job")
    conn.execute(
        """
        INSERT INTO analysis_jobs(
          job_id, bot_user_id, source, chat_id, chat_title, period_id,
          period_label, period_start, period_end, modules, status,
          progress_chat_id, progress_message_id, analysis_mode
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
        """,
        (
            job_id,
            bot_user_id,
            source,
            chat_id,
            chat_title,
            period_id,
            period_label,
            period_start,
            period_end,
            json_dumps(modules),
            progress_chat_id,
            progress_message_id,
            analysis_mode,
        ),
    )
    return get_analysis_job(conn, job_id) or {"job_id": job_id}


def get_analysis_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM analysis_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return analysis_job_from_row(row) if row is not None else None


def list_analysis_jobs(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    statuses: Iterable[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    params: list[Any] = [bot_user_id]
    where = ["bot_user_id = ?"]
    status_values = list(statuses or [])
    if status_values:
        placeholders = ",".join("?" for _ in status_values)
        where.append(f"status IN ({placeholders})")
        params.extend(status_values)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT * FROM analysis_jobs
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [analysis_job_from_row(row) for row in rows]


def update_analysis_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: str | None = None,
    progress_percent: int | None = None,
    imported_message_count: int | None = None,
    error_reference: str | None = None,
    error_message: str | None = None,
    report_id: str | None = None,
    ai_analysis_id: str | None = None,
    started: bool = False,
    completed: bool = False,
    elapsed_seconds: int | None = None,
) -> None:
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = []
    if status is not None:
        assignments.append("status = ?")
        params.append(status)
    if progress_percent is not None:
        assignments.append("progress_percent = ?")
        params.append(max(0, min(100, int(progress_percent))))
    if imported_message_count is not None:
        assignments.append("imported_message_count = ?")
        params.append(max(0, int(imported_message_count)))
    if error_reference is not None:
        assignments.append("error_reference = ?")
        params.append(error_reference)
    if error_message is not None:
        assignments.append("error_message = ?")
        params.append(error_message)
    if report_id is not None:
        assignments.append("report_id = ?")
        params.append(report_id)
    if ai_analysis_id is not None:
        assignments.append("ai_analysis_id = ?")
        params.append(ai_analysis_id)
    if started:
        assignments.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    if completed:
        assignments.append("completed_at = CURRENT_TIMESTAMP")
    if elapsed_seconds is not None:
        assignments.append("elapsed_seconds = ?")
        params.append(max(0, int(elapsed_seconds)))
    params.append(job_id)
    conn.execute(
        f"UPDATE analysis_jobs SET {', '.join(assignments)} WHERE job_id = ?",
        params,
    )


def mark_stale_running_jobs_failed(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    conn.execute(
        """
        UPDATE analysis_jobs
        SET status = 'failed',
            error_reference = COALESCE(error_reference, 'restart'),
            error_message = COALESCE(error_message, 'stale_after_restart'),
            progress_percent = CASE WHEN progress_percent > 99 THEN 99 ELSE progress_percent END,
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('queued','loading','importing','analyzing')
        """
    )
    return conn.total_changes - before


def analysis_job_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "bot_user_id": int(row["bot_user_id"]),
        "source": row["source"],
        "chat_id": row["chat_id"],
        "chat_title": row["chat_title"],
        "period_id": row["period_id"],
        "period_label": row["period_label"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "modules": json_loads(row["modules"], []),
        "status": row["status"],
        "progress_percent": int(row["progress_percent"] or 0),
        "imported_message_count": int(row["imported_message_count"] or 0),
        "error_reference": row["error_reference"],
        "error_message": row["error_message"],
        "report_id": row["report_id"],
        "progress_chat_id": row["progress_chat_id"],
        "progress_message_id": row["progress_message_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "elapsed_seconds": row["elapsed_seconds"],
        "analysis_mode": row["analysis_mode"] if "analysis_mode" in row.keys() else "local",
        "ai_analysis_id": row["ai_analysis_id"] if "ai_analysis_id" in row.keys() else None,
    }


AI_CONSENT_TYPE = "openai_communication_analysis"
AI_CONSENT_VERSION = "v1"


def accept_ai_consent(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    consent_type: str = AI_CONSENT_TYPE,
    policy_version: str = AI_CONSENT_VERSION,
) -> dict[str, Any]:
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO ai_consents(bot_user_id, consent_type, policy_version, accepted_at, revoked_at)
        VALUES (?, ?, ?, ?, NULL)
        ON CONFLICT(bot_user_id, consent_type, policy_version) DO UPDATE SET
          accepted_at = excluded.accepted_at,
          revoked_at = NULL,
          updated_at = CURRENT_TIMESTAMP
        """,
        (bot_user_id, consent_type, policy_version, timestamp),
    )
    return get_ai_consent(conn, bot_user_id, consent_type=consent_type, policy_version=policy_version) or {}


def revoke_ai_consent(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    consent_type: str = AI_CONSENT_TYPE,
    policy_version: str = AI_CONSENT_VERSION,
) -> None:
    conn.execute(
        """
        UPDATE ai_consents
        SET revoked_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE bot_user_id = ? AND consent_type = ? AND policy_version = ?
        """,
        (now_iso(), bot_user_id, consent_type, policy_version),
    )


def get_ai_consent(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    consent_type: str = AI_CONSENT_TYPE,
    policy_version: str = AI_CONSENT_VERSION,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM ai_consents
        WHERE bot_user_id = ? AND consent_type = ? AND policy_version = ?
        """,
        (bot_user_id, consent_type, policy_version),
    ).fetchone()
    if row is None:
        return None
    return {
        "bot_user_id": int(row["bot_user_id"]),
        "consent_type": row["consent_type"],
        "policy_version": row["policy_version"],
        "accepted_at": row["accepted_at"],
        "revoked_at": row["revoked_at"],
        "active": bool(row["accepted_at"]) and not bool(row["revoked_at"]),
    }


def has_active_ai_consent(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    consent_type: str = AI_CONSENT_TYPE,
    policy_version: str = AI_CONSENT_VERSION,
) -> bool:
    consent = get_ai_consent(conn, bot_user_id, consent_type=consent_type, policy_version=policy_version)
    return bool(consent and consent.get("active"))


def create_ai_analysis(
    conn: sqlite3.Connection,
    *,
    bot_user_id: int,
    job_id: str | None,
    report_id: str | None,
    source: str,
    chat_id: str,
    chat_title: str | None,
    model_name: str | None,
    analysis_mode: str = "ai",
    status: str,
    period_id: str | None,
    period_label: str | None,
    period_start: str | None,
    period_end: str | None,
    message_count_sent: int = 0,
    char_count_sent: int = 0,
    coverage: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    dimensions: dict[str, Any] | None = None,
    overall_score: float | None = None,
    confidence: str | None = None,
    consent_version: str | None = AI_CONSENT_VERSION,
    token_usage: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    analysis_id = new_id("ai")
    conn.execute(
        """
        INSERT INTO ai_analyses(
          analysis_id, bot_user_id, report_id, job_id, source, chat_id, chat_title,
          model_name, analysis_mode, status, period_id, period_label, period_start,
          period_end, message_count_sent, char_count_sent, coverage, result_json,
          dimensions_json, overall_score, confidence, consent_version, token_usage,
          error_code
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            analysis_id,
            bot_user_id,
            report_id,
            job_id,
            source,
            chat_id,
            chat_title,
            model_name,
            analysis_mode,
            status,
            period_id,
            period_label,
            period_start,
            period_end,
            max(0, int(message_count_sent)),
            max(0, int(char_count_sent)),
            json_dumps(coverage or {}),
            json_dumps(result) if result is not None else None,
            json_dumps(dimensions or {}),
            overall_score,
            confidence,
            consent_version,
            json_dumps(token_usage or {}),
            error_code,
        ),
    )
    return get_ai_analysis(conn, analysis_id, bot_user_id=bot_user_id) or {"analysis_id": analysis_id}


def update_ai_analysis_status(
    conn: sqlite3.Connection,
    analysis_id: str,
    *,
    bot_user_id: int,
    status: str,
    error_code: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE ai_analyses
        SET status = ?, error_code = COALESCE(?, error_code)
        WHERE analysis_id = ? AND bot_user_id = ?
        """,
        (status, error_code, analysis_id, bot_user_id),
    )


def get_ai_analysis(conn: sqlite3.Connection, analysis_id: str, *, bot_user_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM ai_analyses WHERE analysis_id = ? AND bot_user_id = ?",
        (analysis_id, bot_user_id),
    ).fetchone()
    return ai_analysis_from_row(row) if row is not None else None


def latest_ai_analysis_for_chat(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    source: str,
    chat_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM ai_analyses
        WHERE bot_user_id = ? AND source = ? AND chat_id = ? AND status = 'completed'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (bot_user_id, source, chat_id),
    ).fetchone()
    return ai_analysis_from_row(row) if row is not None else None


def latest_ai_analysis_for_report(
    conn: sqlite3.Connection,
    bot_user_id: int,
    report_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM ai_analyses
        WHERE bot_user_id = ? AND report_id = ? AND status = 'completed'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (bot_user_id, report_id),
    ).fetchone()
    return ai_analysis_from_row(row) if row is not None else None


def has_running_ai_analysis(conn: sqlite3.Connection, bot_user_id: int, *, source: str, chat_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM analysis_jobs
        WHERE bot_user_id = ? AND source = ? AND chat_id = ?
          AND analysis_mode = 'ai'
          AND status IN ('queued','loading','importing','analyzing')
        LIMIT 1
        """,
        (bot_user_id, source, chat_id),
    ).fetchone()
    return row is not None


def ai_analysis_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "analysis_id": row["analysis_id"],
        "bot_user_id": int(row["bot_user_id"]),
        "report_id": row["report_id"],
        "job_id": row["job_id"],
        "source": row["source"],
        "chat_id": row["chat_id"],
        "chat_title": row["chat_title"],
        "model_name": row["model_name"],
        "analysis_mode": row["analysis_mode"],
        "status": row["status"],
        "period_id": row["period_id"],
        "period_label": row["period_label"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "created_at": row["created_at"],
        "message_count_sent": int(row["message_count_sent"] or 0),
        "char_count_sent": int(row["char_count_sent"] or 0),
        "coverage": json_loads(row["coverage"], {}),
        "result": json_loads(row["result_json"], {}) if row["result_json"] else {},
        "dimensions": json_loads(row["dimensions_json"], {}),
        "overall_score": row["overall_score"],
        "confidence": row["confidence"],
        "consent_version": row["consent_version"],
        "token_usage": json_loads(row["token_usage"], {}),
        "error_code": row["error_code"],
    }


def create_report(
    conn: sqlite3.Connection,
    *,
    bot_user_id: int,
    job_id: str | None,
    source: str,
    chat_id: str,
    chat_title: str | None,
    period_id: str,
    period_label: str,
    period_start: str | None,
    period_end: str | None,
    imported_message_count: int,
    modules: list[str],
    job_status: str,
    metrics_summary: dict[str, Any],
    event_summary: dict[str, Any],
    data_quality: dict[str, Any],
) -> dict[str, Any]:
    report_id = new_id("rep")
    conn.execute(
        """
        INSERT INTO reports(
          report_id, bot_user_id, job_id, source, chat_id, chat_title,
          period_id, period_label, period_start, period_end,
          imported_message_count, modules, job_status, metrics_summary,
          event_summary, data_quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            bot_user_id,
            job_id,
            source,
            chat_id,
            chat_title,
            period_id,
            period_label,
            period_start,
            period_end,
            imported_message_count,
            json_dumps(modules),
            job_status,
            json_dumps(metrics_summary),
            json_dumps(event_summary),
            json_dumps(data_quality),
        ),
    )
    return get_report(conn, report_id) or {"report_id": report_id}


def get_report(conn: sqlite3.Connection, report_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
    return report_from_row(row) if row is not None else None


def list_reports(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    chat_id: str | None = None,
    favorites: bool = False,
    limit: int = 10,
) -> list[dict[str, Any]]:
    where = ["bot_user_id = ?"]
    params: list[Any] = [bot_user_id]
    if chat_id is not None:
        where.append("chat_id = ?")
        params.append(chat_id)
    if favorites:
        where.append("is_favorite = 1")
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT * FROM reports
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [report_from_row(row) for row in rows]


def set_report_favorite(conn: sqlite3.Connection, report_id: str, favorite: bool) -> None:
    conn.execute(
        "UPDATE reports SET is_favorite = ? WHERE report_id = ?",
        (1 if favorite else 0, report_id),
    )


def delete_report(conn: sqlite3.Connection, report_id: str, bot_user_id: int) -> None:
    conn.execute(
        "DELETE FROM reports WHERE report_id = ? AND bot_user_id = ?",
        (report_id, bot_user_id),
    )


def clear_reports(conn: sqlite3.Connection, bot_user_id: int) -> int:
    before = conn.total_changes
    conn.execute("DELETE FROM reports WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM period_comparisons WHERE bot_user_id = ?", (bot_user_id,))
    return conn.total_changes - before


def delete_reports_for_chat(conn: sqlite3.Connection, bot_user_id: int, source: str, chat_id: str) -> int:
    before = conn.total_changes
    conn.execute(
        "DELETE FROM reports WHERE bot_user_id = ? AND source = ? AND chat_id = ?",
        (bot_user_id, source, chat_id),
    )
    conn.execute(
        "DELETE FROM period_comparisons WHERE bot_user_id = ? AND source = ? AND chat_id = ?",
        (bot_user_id, source, chat_id),
    )
    return conn.total_changes - before


def report_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "report_id": row["report_id"],
        "bot_user_id": int(row["bot_user_id"]),
        "job_id": row["job_id"],
        "source": row["source"],
        "chat_id": row["chat_id"],
        "chat_title": row["chat_title"],
        "period_id": row["period_id"],
        "period_label": row["period_label"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "created_at": row["created_at"],
        "imported_message_count": int(row["imported_message_count"] or 0),
        "modules": json_loads(row["modules"], []),
        "job_status": row["job_status"],
        "metrics_summary": json_loads(row["metrics_summary"], {}),
        "event_summary": json_loads(row["event_summary"], {}),
        "data_quality": json_loads(row["data_quality"], {}),
        "is_favorite": bool(row["is_favorite"]),
    }


def create_reminder(
    conn: sqlite3.Connection,
    *,
    bot_user_id: int,
    source: str = "telegram",
    chat_id: str | None = None,
    chat_title: str | None = None,
    report_id: str | None = None,
    event_type: str | None = None,
    title: str,
    reminder_time: str | None = None,
    status: str = "suggested",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reminder_id = new_id("rem")
    conn.execute(
        """
        INSERT INTO reminders(
          reminder_id, bot_user_id, source, chat_id, chat_title, report_id,
          event_type, title, reminder_time, status, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reminder_id,
            bot_user_id,
            source,
            chat_id,
            chat_title,
            report_id,
            event_type,
            title,
            reminder_time,
            status,
            json_dumps(metadata or {}),
        ),
    )
    return get_reminder(conn, reminder_id) or {"reminder_id": reminder_id}


def get_reminder(conn: sqlite3.Connection, reminder_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reminders WHERE reminder_id = ?", (reminder_id,)).fetchone()
    return reminder_from_row(row) if row is not None else None


def list_reminders(
    conn: sqlite3.Connection,
    bot_user_id: int,
    *,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    where = ["bot_user_id = ?"]
    params: list[Any] = [bot_user_id]
    if status is not None:
        where.append("status = ?")
        params.append(status)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT * FROM reminders
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [reminder_from_row(row) for row in rows]


def update_reminder_status(conn: sqlite3.Connection, reminder_id: str, bot_user_id: int, status: str) -> None:
    conn.execute(
        """
        UPDATE reminders
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE reminder_id = ? AND bot_user_id = ?
        """,
        (status, reminder_id, bot_user_id),
    )


def update_reminder_time(
    conn: sqlite3.Connection,
    reminder_id: str,
    bot_user_id: int,
    reminder_time: str | None,
) -> None:
    conn.execute(
        """
        UPDATE reminders
        SET reminder_time = ?, status = 'confirmed', updated_at = CURRENT_TIMESTAMP
        WHERE reminder_id = ? AND bot_user_id = ?
        """,
        (reminder_time, reminder_id, bot_user_id),
    )


def clear_reminders(conn: sqlite3.Connection, bot_user_id: int) -> int:
    before = conn.total_changes
    conn.execute("DELETE FROM reminders WHERE bot_user_id = ?", (bot_user_id,))
    return conn.total_changes - before


def reminder_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "reminder_id": row["reminder_id"],
        "bot_user_id": int(row["bot_user_id"]),
        "source": row["source"],
        "chat_id": row["chat_id"],
        "chat_title": row["chat_title"],
        "report_id": row["report_id"],
        "event_type": row["event_type"],
        "title": row["title"],
        "reminder_time": row["reminder_time"],
        "status": row["status"],
        "metadata": json_loads(row["metadata"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def dashboard_counts(conn: sqlite3.Connection, bot_user_id: int) -> dict[str, int]:
    saved = conn.execute(
        "SELECT COUNT(*) AS count FROM user_chats WHERE bot_user_id = ? AND is_saved = 1",
        (bot_user_id,),
    ).fetchone()["count"]
    reports = conn.execute(
        "SELECT COUNT(*) AS count FROM reports WHERE bot_user_id = ?",
        (bot_user_id,),
    ).fetchone()["count"]
    running = conn.execute(
        """
        SELECT COUNT(*) AS count FROM analysis_jobs
        WHERE bot_user_id = ? AND status IN ('queued','loading','importing','analyzing')
        """,
        (bot_user_id,),
    ).fetchone()["count"]
    reminders = conn.execute(
        "SELECT COUNT(*) AS count FROM reminders WHERE bot_user_id = ? AND status IN ('suggested','confirmed')",
        (bot_user_id,),
    ).fetchone()["count"]
    return {
        "saved_chats": int(saved or 0),
        "reports": int(reports or 0),
        "running_jobs": int(running or 0),
        "active_reminders": int(reminders or 0),
    }


def local_storage_summary(conn: sqlite3.Connection, bot_user_id: int) -> dict[str, int]:
    saved = dashboard_counts(conn, bot_user_id)
    messages = conn.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
    chats = conn.execute(
        "SELECT COUNT(*) AS count FROM user_chats WHERE bot_user_id = ?",
        (bot_user_id,),
    ).fetchone()["count"]
    jobs = conn.execute(
        "SELECT COUNT(*) AS count FROM analysis_jobs WHERE bot_user_id = ?",
        (bot_user_id,),
    ).fetchone()["count"]
    important = conn.execute(
        "SELECT COUNT(*) AS count FROM important_chat_settings WHERE bot_user_id = ? AND is_important = 1",
        (bot_user_id,),
    ).fetchone()["count"]
    return {
        **saved,
        "known_chats": int(chats or 0),
        "important_chats": int(important or 0),
        "messages": int(messages or 0),
        "jobs": int(jobs or 0),
    }


def delete_all_user_data(conn: sqlite3.Connection, bot_user_id: int) -> None:
    chat_rows = conn.execute(
        "SELECT source, chat_id FROM user_chats WHERE bot_user_id = ?",
        (bot_user_id,),
    ).fetchall()
    for row in chat_rows:
        delete_imported_messages_for_chat(conn, row["source"], row["chat_id"], bot_user_id=bot_user_id)
    conn.execute("DELETE FROM user_chats WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM reports WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM analysis_jobs WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM ai_analyses WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM reminders WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM important_chat_settings WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM automation_states WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM automatic_analysis_ranges WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM pending_automatic_notifications WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM period_comparisons WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM ai_consents WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM user_settings WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM bot_user_profiles WHERE bot_user_id = ?", (bot_user_id,))
