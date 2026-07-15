from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from relchat.bot.localization import t
from relchat.core.models import Message


def build_chat_home_view_model(
    *,
    chat: dict[str, Any],
    reports: Sequence[dict[str, Any]] = (),
    messages: Sequence[Message] = (),
    reminders: Sequence[dict[str, Any]] = (),
    running: bool = False,
    language: str = "en",
    now: datetime | None = None,
) -> dict[str, Any]:
    anchor = ensure_aware(now or datetime.now(timezone.utc))
    latest_report = reports[0] if reports else None
    previous_report = reports[1] if len(reports) > 1 else None
    metrics = (latest_report or {}).get("metrics_summary") or {}
    events = (latest_report or {}).get("event_summary") or {}
    quality = (latest_report or {}).get("data_quality") or {}
    ordered_messages = sorted(messages, key=message_sort_key)
    chat_type = chat.get("chat_type") or "one_to_one"
    last_activity_at = ordered_messages[-1].timestamp if ordered_messages else (quality.get("range_end") if latest_report else None)
    active_days = len({parse_dt(message.timestamp).date() for message in ordered_messages}) if ordered_messages else 0
    message_count = int((latest_report or {}).get("imported_message_count") or metrics.get("message_count") or len(ordered_messages) or 0)
    recent_change = report_recent_change(latest_report, previous_report)
    rhythm = communication_rhythm(metrics, events, message_count=message_count, active_days=active_days)
    attention = attention_model(
        latest_report,
        reminders=reminders,
        language=language,
        now=anchor,
    )
    state = state_model(
        has_report=latest_report is not None,
        running=running,
        chat_type=chat_type,
        rhythm=rhythm,
        recent_change=recent_change,
        messages=ordered_messages,
        attention_count=int(attention["open_follow_up_count"]),
        confidence=state_confidence(latest_report, message_count),
        language=language,
        now=anchor,
    )
    return {
        "chat": {
            "source": chat.get("source") or "telegram",
            "chat_id": chat.get("chat_id"),
            "title": chat.get("title") or chat.get("local_title") or chat.get("display_title"),
            "chat_type": chat_type,
            "username": chat.get("username"),
            "is_favorite": bool(chat.get("is_favorite")),
        },
        "state": state,
        "activity": {
            "last_activity_at": last_activity_at,
            "last_activity_label": relative_time_label(last_activity_at, now=anchor, language=language),
            "message_count": message_count,
            "active_days": active_days,
            "recent_change": recent_change,
            "recent_change_label": recent_change_label(recent_change, chat_type=chat_type, language=language),
        },
        "communication": {
            "rhythm": rhythm,
            "rhythm_label": rhythm_label(rhythm, chat_type=chat_type, language=language),
            "initiation_summary": initiation_summary(metrics, chat_type=chat_type, language=language),
            "reply_summary": reply_summary(metrics, chat_type=chat_type, language=language),
        },
        "attention": attention,
        "analysis": {
            "has_report": latest_report is not None,
            "last_analysis_at": (latest_report or {}).get("created_at"),
            "last_analysis_label": relative_time_label((latest_report or {}).get("created_at"), now=anchor, language=language),
            "last_period_label": (latest_report or {}).get("period_label"),
            "data_confidence": str(quality.get("confidence") or state["confidence"]),
            "data_confidence_label": confidence_label(str(quality.get("confidence") or state["confidence"]), language=language),
            "running": running,
        },
    }


def attention_model(
    report: dict[str, Any] | None,
    *,
    reminders: Sequence[dict[str, Any]],
    language: str,
    now: datetime,
) -> dict[str, Any]:
    active_reminders = [item for item in reminders if item.get("status") in {"suggested", "confirmed"}]
    confirmed = [item for item in active_reminders if item.get("status") == "confirmed"]
    report_count = report_attention_count(report)
    open_count = report_count + len(active_reminders)
    next_reminder = next_confirmed_reminder(confirmed, now=now, language=language)
    primary_action = t(language, "button_followups") if open_count else None
    return {
        "open_follow_up_count": open_count,
        "confirmed_reminder_count": len(confirmed),
        "next_reminder": next_reminder,
        "primary_action_label": primary_action,
    }


def report_attention_count(report: dict[str, Any] | None) -> int:
    if report is None:
        return 0
    metrics = report.get("metrics_summary") or {}
    events = report.get("event_summary") or {}
    by_type = events.get("by_type") or {}
    return (
        len(metrics.get("unanswered_questions") or [])
        + int(by_type.get("plan_candidate") or 0)
        + int(by_type.get("promise_candidate") or 0)
        + int(by_type.get("follow_up_candidate") or 0)
    )


def next_confirmed_reminder(reminders: Sequence[dict[str, Any]], *, now: datetime, language: str) -> dict[str, Any] | None:
    dated = []
    for reminder in reminders:
        parsed = parse_dt_or_none(str(reminder.get("reminder_time") or ""))
        if parsed is not None:
            dated.append((parsed, reminder))
    if not dated:
        return None
    upcoming = [(when, item) for when, item in dated if when >= now]
    selected_when, selected = min(upcoming or dated, key=lambda row: abs((row[0] - now).total_seconds()))
    return {
        "at": selected_when.isoformat(),
        "label": relative_time_label(selected_when.isoformat(), now=now, language=language),
        "status": selected.get("status"),
        "event_type": selected.get("event_type"),
    }


def state_model(
    *,
    has_report: bool,
    running: bool,
    chat_type: str,
    rhythm: str,
    recent_change: str,
    messages: Sequence[Message],
    attention_count: int,
    confidence: str,
    language: str,
    now: datetime,
) -> dict[str, Any]:
    if running:
        label = "updating"
        tone = "neutral"
        headline = t(language, "chat_home_v4_state_running")
    elif not has_report:
        label = "no_analysis"
        tone = "neutral"
        headline = t(language, "chat_home_v4_state_no_analysis")
    elif has_long_silence(messages, now=now):
        label = "long_silence"
        tone = "attention"
        headline = long_silence_headline(chat_type, language=language)
    elif attention_count:
        label = "attention"
        tone = "attention"
        headline = t(language, "chat_home_v4_state_attention")
    elif rhythm == "quiet" or recent_change == "down":
        label = "quiet"
        tone = "neutral"
        headline = quiet_headline(chat_type, language=language)
    elif recent_change == "up":
        label = "more_active"
        tone = "neutral"
        headline = active_headline(chat_type, language=language)
    else:
        label = "stable"
        tone = "positive"
        headline = stable_headline(chat_type, language=language)
    return {
        "label": label,
        "tone": tone,
        "headline": headline,
        "icon": status_icon(label),
        "title": status_title(label, language=language),
        "explanation": headline,
        "confidence": confidence,
    }


def stable_headline(chat_type: str, *, language: str) -> str:
    if chat_type == "group":
        return t(language, "chat_home_v4_state_group_stable")
    if chat_type == "channel":
        return t(language, "chat_home_v4_state_channel_stable")
    return t(language, "chat_home_v4_state_stable")


def quiet_headline(chat_type: str, *, language: str) -> str:
    if chat_type == "group":
        return t(language, "chat_home_v4_state_group_quiet")
    if chat_type == "channel":
        return t(language, "chat_home_v4_state_channel_quiet")
    return t(language, "chat_home_v4_state_quiet")


def active_headline(chat_type: str, *, language: str) -> str:
    if chat_type == "group":
        return t(language, "chat_home_v4_state_group_active")
    if chat_type == "channel":
        return t(language, "chat_home_v4_state_channel_active")
    return t(language, "chat_home_v4_state_active")


def long_silence_headline(chat_type: str, *, language: str) -> str:
    if chat_type == "group":
        return t(language, "chat_home_v4_state_group_long_silence")
    if chat_type == "channel":
        return t(language, "chat_home_v4_state_channel_long_silence")
    return t(language, "chat_home_v4_state_long_silence")


def status_icon(label: str) -> str:
    return {
        "stable": "🟢",
        "more_active": "🟢",
        "quiet": "🟡",
        "attention": "🟠",
        "long_silence": "🔴",
        "no_analysis": "⚪",
        "updating": "⚪",
    }.get(label, "⚪")


def status_title(label: str, *, language: str) -> str:
    return {
        "stable": t(language, "status_active"),
        "more_active": t(language, "status_active"),
        "quiet": t(language, "status_quiet"),
        "attention": t(language, "status_attention"),
        "long_silence": t(language, "status_long_silence"),
        "no_analysis": t(language, "status_no_analysis"),
        "updating": t(language, "status_loading"),
    }.get(label, t(language, "status_no_analysis"))


def has_long_silence(messages: Sequence[Message], *, now: datetime) -> bool:
    if not messages:
        return False
    last = parse_dt(messages[-1].timestamp)
    return (now - last).days >= 9


def communication_rhythm(metrics: dict[str, Any], events: dict[str, Any], *, message_count: int, active_days: int) -> str:
    if message_count <= 0:
        return "unknown"
    if active_days <= 0:
        return "unknown"
    long_silences = int(((events.get("by_type") or {}).get("long_silence")) or 0)
    if long_silences >= 2 and message_count < 50:
        return "quiet"
    if active_days <= 2 and message_count >= 20:
        return "bursty"
    response = metrics.get("response_times") or {}
    if response and total_response_count(response) < 3:
        return "quiet"
    return "regular"


def rhythm_label(rhythm: str, *, chat_type: str, language: str) -> str:
    if chat_type == "channel":
        labels = {
            "regular": "chat_home_v4_cadence_regular",
            "bursty": "chat_home_v4_cadence_bursty",
            "quiet": "chat_home_v4_cadence_quiet",
            "unknown": "chat_home_v4_unknown",
        }
    else:
        labels = {
            "regular": "chat_home_v4_rhythm_regular",
            "bursty": "chat_home_v4_rhythm_bursty",
            "quiet": "chat_home_v4_rhythm_quiet",
            "unknown": "chat_home_v4_unknown",
        }
    return t(language, labels.get(rhythm, "chat_home_v4_unknown"))


def recent_change_label(change: str, *, chat_type: str, language: str) -> str:
    if chat_type == "channel":
        labels = {
            "up": "chat_home_v4_posting_up",
            "stable": "chat_home_v4_posting_stable",
            "down": "chat_home_v4_posting_down",
            "unknown": "chat_home_v4_recent_unknown",
        }
    else:
        labels = {
            "up": "chat_home_v4_activity_up",
            "stable": "chat_home_v4_activity_stable",
            "down": "chat_home_v4_activity_down",
            "unknown": "chat_home_v4_recent_unknown",
        }
    return t(language, labels.get(change, "chat_home_v4_recent_unknown"))


def report_recent_change(report: dict[str, Any] | None, previous_report: dict[str, Any] | None) -> str:
    if report is None or previous_report is None:
        return "unknown"
    current_count = int(report.get("imported_message_count") or (report.get("metrics_summary") or {}).get("message_count") or 0)
    previous_count = int(previous_report.get("imported_message_count") or (previous_report.get("metrics_summary") or {}).get("message_count") or 0)
    if current_count < 10 or previous_count < 10:
        return "unknown"
    if previous_count == 0:
        return "unknown"
    ratio = current_count / previous_count
    if ratio >= 1.25:
        return "up"
    if ratio <= 0.75:
        return "down"
    return "stable"


def initiation_summary(metrics: dict[str, Any], *, chat_type: str, language: str) -> str:
    if chat_type == "channel":
        return t(language, "chat_home_v4_not_used_for_channels")
    initiation = metrics.get("initiation_balance") or {}
    by_sender = initiation.get("by_sender") or {}
    session_count = int(initiation.get("session_count") or 0)
    if not by_sender or session_count <= 0:
        return t(language, "chat_home_v4_unknown")
    top = max(int(value) for value in by_sender.values())
    if top / max(1, session_count) >= 0.65:
        return t(language, "chat_home_v4_initiation_one_sided")
    if chat_type == "group":
        return t(language, "chat_home_v4_group_initiation_balanced")
    return t(language, "chat_home_v4_initiation_balanced")


def reply_summary(metrics: dict[str, Any], *, chat_type: str, language: str) -> str:
    if chat_type == "channel":
        return t(language, "chat_home_v4_not_used_for_channels")
    response = metrics.get("response_times") or {}
    count = total_response_count(response)
    if count < 3:
        return t(language, "chat_home_v4_reply_limited")
    return t(language, "chat_home_v4_reply_observed")


def total_response_count(response_times: dict[str, Any]) -> int:
    total = 0
    for row in response_times.values():
        if isinstance(row, dict):
            total += int(row.get("count") or 0)
    return total


def state_confidence(report: dict[str, Any] | None, message_count: int) -> str:
    if report is None or message_count < 10:
        return "low"
    quality = report.get("data_quality") or {}
    value = str(quality.get("confidence") or "medium").lower()
    if value in {"high", "medium", "low"}:
        return value
    return "medium"


def confidence_label(value: str, *, language: str) -> str:
    return {
        "high": t(language, "confidence_high"),
        "medium": t(language, "confidence_medium"),
        "low": t(language, "confidence_low"),
    }.get(str(value).lower(), t(language, "confidence_medium"))


def relative_time_label(value: str | None, *, now: datetime, language: str) -> str:
    parsed = parse_dt_or_none(value or "")
    if parsed is None:
        return t(language, "not_available")
    day_delta = (parsed.date() - now.date()).days
    if day_delta == 0:
        return t(language, "relative_today")
    if day_delta == -1:
        return t(language, "relative_yesterday")
    if day_delta == 1:
        return t(language, "relative_tomorrow")
    if day_delta < 0 and abs(day_delta) <= 30:
        return t(language, "relative_days_ago", count=abs(day_delta))
    if day_delta > 0 and day_delta <= 30:
        return t(language, "relative_in_days", count=day_delta)
    return parsed.date().isoformat()


def message_sort_key(message: Message) -> tuple[datetime, int]:
    return (parse_dt(message.timestamp), message.source_message_id)


def parse_dt_or_none(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parse_dt(value)
    except ValueError:
        return None


def parse_dt(value: str) -> datetime:
    return ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
