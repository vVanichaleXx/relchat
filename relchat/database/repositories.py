from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ai', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    return conn.total_changes - before


def delete_reports_for_chat(conn: sqlite3.Connection, bot_user_id: int, source: str, chat_id: str) -> int:
    before = conn.total_changes
    conn.execute(
        "DELETE FROM reports WHERE bot_user_id = ? AND source = ? AND chat_id = ?",
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
    return {
        **saved,
        "known_chats": int(chats or 0),
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
    conn.execute("DELETE FROM reminders WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM user_settings WHERE bot_user_id = ?", (bot_user_id,))
    conn.execute("DELETE FROM bot_user_profiles WHERE bot_user_id = ?", (bot_user_id,))
