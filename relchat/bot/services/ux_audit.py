from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from relchat.bot.formatters import clip_text
from relchat.config import Settings


LOGGER = logging.getLogger(__name__)
CURRENT_AUDIT_SETTINGS: ContextVar[Settings | None] = ContextVar("relchat_current_ux_audit_settings", default=None)
MAX_STRING_LENGTH = 1200
MAX_BUTTON_ROWS = 12
MAX_BUTTONS_PER_ROW = 4
DEFAULT_DEBUG_EXPORT_LIMIT = 300

PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
API_HASH_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
SESSION_PATH_RE = re.compile(r"[\w./~ -]*telegram\.session(?:\.\w+)?", re.IGNORECASE)
AUTH_CODE_RE = re.compile(r"\b(?:code|login code|auth code)\s*[:=]\s*\d{4,8}\b", re.IGNORECASE)


@dataclass(frozen=True)
class UxAuditStatus:
    enabled: bool
    user_event_count: int
    max_events: int
    include_user_text: bool
    last_event_time: str | None
    log_file_exists: bool


@dataclass(frozen=True)
class DebugExportRequest:
    limit: int | None = DEFAULT_DEBUG_EXPORT_LIMIT
    since: datetime | None = None
    label: str = "last 300 events"


def record_ux_event(
    settings: Settings,
    event_type: str,
    *,
    update: Any | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if not audit_enabled(settings):
        return
    path = audit_path(settings)
    if path is None:
        return
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": sanitize_value(event_type),
        "update": update_metadata(update),
        "payload": sanitize_value(payload or {}),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        trim_audit_log(path, settings.ux_audit_max_events)
    except Exception as exc:
        LOGGER.debug("Could not write UX audit event: %s", exc.__class__.__name__)


def set_current_audit_settings(settings: Settings) -> None:
    CURRENT_AUDIT_SETTINGS.set(settings)


def clear_current_audit_settings() -> None:
    CURRENT_AUDIT_SETTINGS.set(None)


def current_audit_settings() -> Settings | None:
    return CURRENT_AUDIT_SETTINGS.get()


def record_current_ux_event(
    event_type: str,
    *,
    update: Any | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    settings = current_audit_settings()
    if settings is not None:
        record_ux_event(settings, event_type, update=update, payload=payload)


def audit_enabled(settings: Settings) -> bool:
    return bool(settings.ux_audit_enabled)


def audit_path(settings: Settings) -> Path | None:
    return settings.ux_audit_path


def trim_audit_log(path: Path, max_events: int) -> None:
    if max_events <= 0 or not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_events:
        return
    path.write_text("\n".join(lines[-max_events:]) + "\n", encoding="utf-8")


def update_metadata(update: Any | None) -> dict[str, Any]:
    if update is None:
        return {}
    user = getattr(update, "effective_user", None)
    chat = getattr(update, "effective_chat", None)
    message = getattr(update, "effective_message", None)
    query = getattr(update, "callback_query", None)
    query_message = getattr(query, "message", None) if query is not None else None
    return sanitize_value(
        {
            "update_id": getattr(update, "update_id", None),
            "user_id": getattr(user, "id", None),
            "chat_type": getattr(chat, "type", None),
            "message_id": getattr(message, "message_id", None),
            "callback_message_id": getattr(query_message, "message_id", None),
        }
    )


def incoming_command_payload(update: Any) -> dict[str, Any]:
    text = getattr(getattr(update, "effective_message", None), "text", "") or ""
    command = text.split(maxsplit=1)[0] if text.startswith("/") else None
    return {"command": sanitize_value(command), "argument_count": max(0, len(text.split()) - 1)}


def incoming_text_payload(text: str, *, mode: str | None, include_text: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": sanitize_value(mode),
        "text_length": len(text),
        "text_included": bool(include_text),
    }
    if include_text:
        payload["text"] = sanitize_text(text)
    else:
        payload["text"] = "[omitted by RELCHAT_UX_AUDIT_INCLUDE_USER_TEXT=false]"
    return payload


def callback_payload(callback_data: str | None, parts: list[str] | None = None) -> dict[str, Any]:
    value = callback_data or ""
    return {
        "callback_data": sanitize_text(value, limit=200),
        "callback_length": len(value),
        "parts": sanitize_value(parts or []),
    }


def outgoing_payload(
    text: str,
    *,
    action: str,
    reply_markup: Any | None = None,
    chunk_index: int | None = None,
    chunk_count: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": action,
        "text_length": len(text),
        "text_preview": outgoing_text_preview(text),
    }
    if chunk_index is not None and chunk_count is not None:
        payload["chunk_index"] = chunk_index
        payload["chunk_count"] = chunk_count
    keyboard = keyboard_payload(reply_markup)
    if keyboard:
        payload["keyboard"] = keyboard
    return payload


def outgoing_text_preview(text: str) -> str:
    lowered = text.casefold()
    private_markers = (
        "communication analysis",
        "communication score",
        "replies that weakened",
        "analysis completed automatically",
        "direct findings",
        "аналитика общения",
        "анализ общения",
        "оценка общения",
        "анализ выполнен автоматически",
        "общая оценка",
        "ответы, которые мешали",
    )
    if any(marker in lowered for marker in private_markers):
        return "[omitted private analysis]"
    return sanitize_text(text, limit=min(MAX_STRING_LENGTH, 300))


def error_payload(exc: Exception, *, reference: str | None = None) -> dict[str, Any]:
    payload = {"error_type": exc.__class__.__name__}
    if reference:
        payload["reference"] = reference
    return payload


def keyboard_payload(reply_markup: Any | None) -> list[list[dict[str, Any]]]:
    rows = getattr(reply_markup, "inline_keyboard", None)
    if not rows:
        return []
    result = []
    for row in list(rows)[:MAX_BUTTON_ROWS]:
        rendered_row = []
        for button in list(row)[:MAX_BUTTONS_PER_ROW]:
            data = getattr(button, "callback_data", None)
            rendered_row.append(
                {
                    "text": sanitize_text(str(getattr(button, "text", "") or ""), limit=80),
                    "callback_data": sanitize_text(str(data or ""), limit=120) if data else None,
                    "callback_length": len(str(data or "")) if data else 0,
                }
            )
        result.append(rendered_row)
    return result


def sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            safe_key = sanitize_text(str(key), limit=120)
            if safe_key == "timestamp" and isinstance(item, str):
                result[safe_key] = item
            else:
                result[safe_key] = sanitize_value(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [sanitize_value(item) for item in list(value)[:100]]
    return f"[{value.__class__.__name__}]"


def sanitize_text(value: str, *, limit: int = MAX_STRING_LENGTH) -> str:
    text = value.replace("\x00", "")
    text = BOT_TOKEN_RE.sub("[redacted bot token]", text)
    text = AUTH_CODE_RE.sub("[redacted login code]", text)
    text = API_HASH_RE.sub("[redacted api hash]", text)
    text = PHONE_RE.sub("[redacted phone]", text)
    text = SESSION_PATH_RE.sub("[redacted session path]", text)
    return clip_text(text, limit)


def load_ux_audit_events(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if limit is not None and limit > 0:
        lines = lines[-limit:]
    events = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(sanitize_value(value))
    return events


def user_ux_audit_events(
    path: Path,
    user_id: int,
    *,
    limit: int | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    events = [
        event
        for event in load_ux_audit_events(path)
        if event_user_id(event) == user_id and event_in_time_window(event, since)
    ]
    if limit is not None and limit > 0:
        return events[-limit:]
    return events


def ux_audit_status(settings: Settings, user_id: int) -> UxAuditStatus:
    path = audit_path(settings)
    exists = bool(path and path.exists())
    events = user_ux_audit_events(path, user_id) if path else []
    last_event_time = str(events[-1].get("timestamp")) if events else None
    return UxAuditStatus(
        enabled=bool(settings.ux_audit_enabled),
        user_event_count=len(events),
        max_events=settings.ux_audit_max_events,
        include_user_text=bool(settings.ux_audit_include_user_text),
        last_event_time=last_event_time,
        log_file_exists=exists,
    )


def clear_ux_audit_events_for_user(path: Path, user_id: int) -> int:
    if not path.exists():
        return 0
    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if isinstance(value, dict) and event_user_id(value) == user_id:
            removed += 1
            continue
        kept.append(line)
    path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    return removed


def event_user_id(event: dict[str, Any]) -> int | None:
    update = event.get("update") or {}
    raw = update.get("user_id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def event_datetime(event: dict[str, Any]) -> datetime | None:
    raw = event.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def event_in_time_window(event: dict[str, Any], since: datetime | None) -> bool:
    if since is None:
        return True
    timestamp = event_datetime(event)
    return bool(timestamp and timestamp >= since)


def parse_debug_export_request(args: list[str], *, now: datetime | None = None) -> DebugExportRequest:
    if not args:
        return DebugExportRequest()
    value = args[0].strip().lower()
    if value.isdigit():
        limit = max(1, min(int(value), 1000))
        return DebugExportRequest(limit=limit, label=f"last {limit} events")
    if value.endswith("m") and value[:-1].isdigit():
        minutes = max(1, min(int(value[:-1]), 24 * 60))
        anchor = now or datetime.now(timezone.utc)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        return DebugExportRequest(limit=None, since=anchor - timedelta(minutes=minutes), label=f"last {minutes} minutes")
    return DebugExportRequest()


def format_ux_audit_status(status: UxAuditStatus) -> str:
    return "\n".join(
        [
            "UX audit status",
            "",
            f"UX audit enabled: {yes_no(status.enabled)}",
            f"Event count: {status.user_event_count}",
            f"Maximum configured events: {status.max_events}",
            f"User text included: {yes_no(status.include_user_text)}",
            f"Last event time: {status.last_event_time or 'none'}",
            f"Log file exists: {yes_no(status.log_file_exists)}",
        ]
    )


def format_debug_export(events: list[dict[str, Any]], *, label: str = "last 300 events") -> str:
    lines = [
        "RelChat UX Debug Export",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Scope: {label}",
        f"Events: {len(events)}",
        "",
    ]
    if not events:
        lines.append("No UX audit events matched this request.")
        return "\n".join(lines)

    button_labels: dict[str, str] = {}
    for index, event in enumerate(events, start=1):
        payload = event.get("payload") or {}
        event_type = str(event.get("event_type") or "unknown")
        direction = debug_event_direction(event_type)
        lines.append(f"{index}. {event.get('timestamp', 'unknown')}  {direction}  {event_type}")
        lines.extend(debug_payload_lines(payload, button_labels=button_labels))
        update_button_labels(button_labels, payload)
    return "\n".join(lines)


def debug_event_direction(event_type: str) -> str:
    if event_type.startswith("incoming_"):
        return "USER"
    return "BOT"


def debug_payload_lines(payload: dict[str, Any], *, button_labels: dict[str, str]) -> list[str]:
    lines: list[str] = []
    command = payload.get("command")
    if command:
        lines.append(f"   command: {command}")
    callback_data = payload.get("callback_data")
    if callback_data:
        lines.append(f"   callback route: {callback_route(payload)}")
        label = button_labels.get(str(callback_data))
        if label:
            lines.append(f"   callback/button label: {label}")
    action = payload.get("action")
    if action:
        lines.append(f"   edit vs new reply: {action}")
    text_preview = payload.get("text_preview")
    if text_preview:
        lines.append(f"   screen: {screen_title(str(text_preview))}")
        lines.append(f"   visible bot text: {text_preview}")
    if "error_type" in payload:
        safe_error = payload.get("reference") or payload.get("error_type")
        lines.append(f"   safe error: {safe_error}")
    buttons = visible_button_labels(payload)
    if buttons:
        lines.append(f"   visible buttons: {buttons}")
    duration = payload_duration(payload)
    if duration:
        lines.append(f"   duration: {duration}")
    return lines


def callback_route(payload: dict[str, Any]) -> str:
    parts = payload.get("parts")
    if isinstance(parts, list) and parts:
        return " > ".join(str(part) for part in parts)
    return str(payload.get("callback_data") or "")


def visible_button_labels(payload: dict[str, Any]) -> str | None:
    keyboard = payload.get("keyboard") or []
    labels = []
    for row in keyboard:
        row_labels = [str(button.get("text") or "") for button in row if button.get("text")]
        if row_labels:
            labels.append(" | ".join(row_labels))
    return " / ".join(labels) if labels else None


def update_button_labels(button_labels: dict[str, str], payload: dict[str, Any]) -> None:
    for row in payload.get("keyboard") or []:
        for button in row:
            callback_data = button.get("callback_data")
            label = button.get("text")
            if callback_data and label:
                button_labels[str(callback_data)] = str(label)


def screen_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return clip_text(stripped, 80)
    return "Screen"


def payload_duration(payload: dict[str, Any]) -> str | None:
    for key in ("duration", "duration_ms", "elapsed", "elapsed_seconds"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_ux_audit_report(events: list[dict[str, Any]]) -> str:
    lines = [
        "RelChat UX Audit",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Events: {len(events)}",
        "",
    ]
    if not events:
        lines.append("No UX audit events found.")
        return "\n".join(lines)
    for index, event in enumerate(events, start=1):
        update = event.get("update") or {}
        payload = event.get("payload") or {}
        lines.append(f"{index}. {event.get('timestamp')} - {event.get('event_type')}")
        user_id = update.get("user_id")
        chat_type = update.get("chat_type")
        if user_id or chat_type:
            lines.append(f"   user={user_id or 'unknown'} chat={chat_type or 'unknown'}")
        lines.extend(format_payload_lines(payload))
    return "\n".join(lines)


def format_payload_lines(payload: dict[str, Any]) -> list[str]:
    lines = []
    for key in [
        "command",
        "mode",
        "callback_data",
        "action",
        "text",
        "text_preview",
        "text_length",
        "error_type",
        "reference",
    ]:
        if key in payload:
            lines.append(f"   {key}: {payload[key]}")
    keyboard = payload.get("keyboard") or []
    if keyboard:
        button_lines = []
        for row in keyboard[:4]:
            labels = [str(button.get("text") or "") for button in row]
            button_lines.append(" | ".join(labels))
        lines.append(f"   buttons: {' / '.join(button_lines)}")
    return lines
