from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from relchat.core.models import ConversationRef, Message


SOURCE = "telegram"


def normalize_dialog(dialog: Any) -> ConversationRef:
    return ConversationRef(
        source=SOURCE,
        conversation_id=str(dialog.id),
        conversation_type=dialog_type(dialog),
        title=dialog.name,
        last_message_at=iso_or_none(getattr(getattr(dialog, "message", None), "date", None)),
        username=dialog_username(dialog),
        folder_id=dialog_folder_id(dialog),
        unread_count=safe_int(getattr(dialog, "unread_count", 0)),
    )


def normalize_entity(entity: Any, fallback_id: str) -> ConversationRef:
    return ConversationRef(
        source=SOURCE,
        conversation_id=str(getattr(entity, "id", fallback_id)),
        conversation_type=entity_type(entity),
        title=display_name(entity),
        username=getattr(entity, "username", None),
    )


def normalize_message(message: Any, conversation_id: str, sender: Any | None) -> Message:
    text = getattr(message, "raw_text", None) or getattr(message, "message", None) or ""
    media_type, media_duration = media_info(message)
    return Message(
        source=SOURCE,
        source_message_id=int(message.id),
        conversation_id=str(conversation_id),
        sender_id=str(getattr(message, "sender_id", "") or ""),
        sender_name=display_name(sender) if sender else None,
        timestamp=iso_or_none(message.date) or datetime.now(timezone.utc).isoformat(),
        text=text,
        message_type=message_type(message, text, media_type),
        reply_to_message_id=getattr(message, "reply_to_msg_id", None),
        reactions=json.dumps(reaction_summary(message), ensure_ascii=False),
        media_type=media_type,
        media_duration=media_duration,
        forward_info=json.dumps(forward_summary(message), ensure_ascii=False),
        edit_date=iso_or_none(getattr(message, "edit_date", None)),
        is_outgoing=bool(getattr(message, "out", False)),
        raw_platform_payload_reference=None,
    )


def display_name(entity: Any | None) -> str:
    if entity is None:
        return "unknown"
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    first = getattr(entity, "first_name", None) or ""
    last = getattr(entity, "last_name", None) or ""
    full = f"{first} {last}".strip()
    if full:
        return full
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    return str(getattr(entity, "id", "unknown"))


def entity_ref(value: str) -> int | str:
    normalized = value.strip()
    if normalized.lstrip("-").isdigit():
        return int(normalized)
    return normalized


def dialog_type(dialog: Any) -> str:
    if getattr(dialog, "is_user", False):
        entity = getattr(dialog, "entity", None)
        if getattr(entity, "bot", False):
            return "bot"
        if getattr(entity, "self", False):
            return "self"
        return "one_to_one"
    if getattr(dialog, "is_group", False):
        return "group"
    if getattr(dialog, "is_channel", False):
        return "channel"
    return "unknown"


def entity_type(entity: Any) -> str:
    if hasattr(entity, "first_name") or hasattr(entity, "last_name"):
        if getattr(entity, "bot", False):
            return "bot"
        if getattr(entity, "self", False):
            return "self"
        return "one_to_one"
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False) or hasattr(entity, "participants_count"):
        return "group"
    return "unknown"


def dialog_username(dialog: Any) -> str | None:
    entity = getattr(dialog, "entity", None)
    username = getattr(entity, "username", None)
    return str(username) if username else None


def dialog_folder_id(dialog: Any) -> int | None:
    folder_id = getattr(dialog, "folder_id", None)
    if folder_id is None:
        return None
    try:
        return int(folder_id)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def iso_or_none(value: Any | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def message_type(message: Any, text: str, media_type: str | None) -> str:
    if media_type:
        return media_type
    if text:
        return "text"
    if getattr(message, "action", None):
        return "service"
    return "empty"


def media_info(message: Any) -> tuple[str | None, float | None]:
    checks = [
        ("voice", "voice"),
        ("video_note", "video_note"),
        ("video", "video"),
        ("photo", "photo"),
        ("audio", "audio"),
        ("sticker", "sticker"),
        ("document", "document"),
    ]
    media_type = None
    for attr, label in checks:
        try:
            if getattr(message, attr, None):
                media_type = label
                break
        except Exception:
            continue
    duration = None
    document = getattr(message, "document", None)
    for attr in getattr(document, "attributes", []) or []:
        if hasattr(attr, "duration"):
            try:
                duration = float(attr.duration)
            except (TypeError, ValueError):
                duration = None
            break
    return media_type, duration


def reaction_summary(message: Any) -> list[dict]:
    reactions = getattr(message, "reactions", None)
    results = getattr(reactions, "results", None) or []
    summary = []
    for item in results:
        reaction = getattr(item, "reaction", None)
        value = getattr(reaction, "emoticon", None) or str(reaction)
        summary.append({"reaction": value, "count": getattr(item, "count", 1)})
    return summary


def forward_summary(message: Any) -> dict | None:
    fwd = getattr(message, "fwd_from", None)
    if not fwd:
        return None
    return {
        "date": iso_or_none(getattr(fwd, "date", None)),
        "from_id": str(getattr(fwd, "from_id", "") or ""),
        "from_name": getattr(fwd, "from_name", None),
        "channel_post": getattr(fwd, "channel_post", None),
    }
