from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.question_metrics import build_question_metrics
from relchat.core.models import Message


LONG_HISTORY_MESSAGE_THRESHOLD = 1500
LONG_HISTORY_DAY_THRESHOLD = 90
LONG_HISTORY_SESSION_THRESHOLD = 30
MAX_SEGMENT_WINDOWS = 18


@dataclass(frozen=True)
class SegmentWindow:
    label: str
    start: str
    end: str
    message_count: int
    outgoing_count: int
    incoming_count: int
    user_question_rate: float
    other_question_rate: float
    long_pause_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "message_count": self.message_count,
            "outgoing_count": self.outgoing_count,
            "incoming_count": self.incoming_count,
            "user_question_rate": self.user_question_rate,
            "other_question_rate": self.other_question_rate,
            "long_pause_count": self.long_pause_count,
        }


def build_long_history_summary(
    messages: Sequence[Message],
    *,
    period_label: str,
    session_count: int | None = None,
    context_category: str = "unknown",
    language: str = "en",
) -> dict[str, Any]:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    span_days = history_span_days(ordered)
    should_segment = len(ordered) > LONG_HISTORY_MESSAGE_THRESHOLD or span_days > LONG_HISTORY_DAY_THRESHOLD or int(session_count or 0) > LONG_HISTORY_SESSION_THRESHOLD
    windows = segment_history(ordered, max_windows=MAX_SEGMENT_WINDOWS) if should_segment else []
    baseline = baseline_summary(windows, context_category=context_category, language=language) if windows else ""
    recent = recent_change_summary(windows, context_category=context_category, language=language) if windows else ""
    return {
        "policy": "long_history_v1",
        "period_label": period_label,
        "segmented": bool(windows),
        "reason": segmentation_reason(len(ordered), span_days, int(session_count or 0)) if should_segment else "not_needed",
        "message_count": len(ordered),
        "span_days": span_days,
        "window_count": len(windows),
        "recent_window_message_count": windows[-1].message_count if windows else 0,
        "windows": [window.to_dict() for window in windows],
        "scope_note": history_scope_note(windows, total_messages=len(ordered), language=language) if windows else "",
        "current_picture": current_picture_summary(windows, context_category=context_category, language=language) if windows else "",
        "long_term_pattern": baseline,
        "recent_change": recent,
        "limitations": [t(language, "history_segmentation_limitation")] if windows else [],
    }


def history_scope_note(windows: Sequence[SegmentWindow], *, total_messages: int, language: str) -> str:
    if not windows:
        return ""
    return t(language, "history_scope_note", total=total_messages, recent=windows[-1].message_count)


def history_span_days(messages: Sequence[Message]) -> int:
    if len(messages) < 2:
        return 0
    start = parse_datetime(messages[0].timestamp)
    end = parse_datetime(messages[-1].timestamp)
    return max(0, (end - start).days)


def segmentation_reason(message_count: int, span_days: int, session_count: int) -> str:
    if message_count > LONG_HISTORY_MESSAGE_THRESHOLD:
        return "message_count"
    if span_days > LONG_HISTORY_DAY_THRESHOLD:
        return "duration"
    if session_count > LONG_HISTORY_SESSION_THRESHOLD:
        return "session_count"
    return "not_needed"


def segment_history(messages: Sequence[Message], *, max_windows: int = MAX_SEGMENT_WINDOWS) -> list[SegmentWindow]:
    if not messages:
        return []
    span_days = history_span_days(messages)
    if span_days >= 60:
        buckets = monthly_buckets(messages)
    else:
        buckets = activity_buckets(messages, max_windows=max_windows)
    ordered_keys = sorted(buckets)
    if len(ordered_keys) > max_windows:
        ordered_keys = ordered_keys[-max_windows:]
    return [window_from_messages(key, buckets[key]) for key in ordered_keys if buckets[key]]


def monthly_buckets(messages: Sequence[Message]) -> dict[str, list[Message]]:
    buckets: dict[str, list[Message]] = defaultdict(list)
    for message in messages:
        timestamp = parse_datetime(message.timestamp)
        buckets[f"{timestamp.year:04d}-{timestamp.month:02d}"].append(message)
    return buckets


def activity_buckets(messages: Sequence[Message], *, max_windows: int) -> dict[str, list[Message]]:
    if not messages:
        return {}
    chunk_size = max(1, len(messages) // max(1, min(max_windows, 8)))
    buckets: dict[str, list[Message]] = {}
    for index in range(0, len(messages), chunk_size):
        chunk = list(messages[index : index + chunk_size])
        if not chunk:
            continue
        buckets[f"segment-{len(buckets) + 1:02d}"] = chunk
    return buckets


def window_from_messages(label: str, messages: Sequence[Message]) -> SegmentWindow:
    questions = build_question_metrics(messages, language="en")
    you = ((questions.get("by_participant") or {}).get("you") or {})
    other = ((questions.get("by_participant") or {}).get("other") or {})
    return SegmentWindow(
        label=label,
        start=messages[0].timestamp,
        end=messages[-1].timestamp,
        message_count=len(messages),
        outgoing_count=sum(1 for message in messages if message.is_outgoing),
        incoming_count=sum(1 for message in messages if not message.is_outgoing),
        user_question_rate=float(you.get("per_100_messages") or 0.0),
        other_question_rate=float(other.get("per_100_messages") or 0.0),
        long_pause_count=count_long_pauses(messages),
    )


def count_long_pauses(messages: Sequence[Message], *, gap_days: int = 14) -> int:
    count = 0
    previous: datetime | None = None
    for message in messages:
        current = parse_datetime(message.timestamp)
        if previous is not None and current - previous >= timedelta(days=gap_days):
            count += 1
        previous = current
    return count


def current_picture_summary(windows: Sequence[SegmentWindow], *, context_category: str, language: str) -> str:
    if not windows:
        return ""
    recent = windows[-1]
    if context_category == "work":
        return t(language, "history_current_work", messages=recent.message_count, questions=f"{recent.user_question_rate:.1f}")
    if context_category == "family":
        return t(language, "history_current_family", messages=recent.message_count)
    return t(language, "history_current_general", messages=recent.message_count)


def baseline_summary(windows: Sequence[SegmentWindow], *, context_category: str, language: str) -> str:
    if not windows:
        return ""
    total_messages = sum(window.message_count for window in windows)
    outgoing = sum(window.outgoing_count for window in windows)
    incoming = sum(window.incoming_count for window in windows)
    share = max(outgoing, incoming) / max(1, outgoing + incoming)
    if share <= 0.55:
        if context_category == "work":
            return t(language, "history_baseline_work_balanced", messages=total_messages)
        if context_category == "family":
            return t(language, "history_baseline_family_balanced", messages=total_messages)
        return t(language, "history_baseline_balanced", messages=total_messages)
    side = t(language, "local_side_you") if outgoing > incoming else t(language, "local_side_other")
    return t(language, "history_baseline_uneven", side=side, messages=total_messages)


def recent_change_summary(windows: Sequence[SegmentWindow], *, context_category: str, language: str) -> str:
    if len(windows) < 2:
        return t(language, "history_recent_limited")
    recent = windows[-1]
    previous = windows[-2]
    recent_user_share = recent.outgoing_count / max(1, recent.message_count)
    previous_user_share = previous.outgoing_count / max(1, previous.message_count)
    if abs(recent_user_share - previous_user_share) >= 0.12:
        side = t(language, "local_side_you") if recent_user_share > previous_user_share else t(language, "local_side_other")
        return t(language, "history_recent_initiative_shift", side=side)
    if recent.user_question_rate > previous.user_question_rate + 3.0:
        return t(language, "history_recent_work_more_questions") if context_category == "work" else t(language, "history_recent_more_questions")
    if recent.long_pause_count > previous.long_pause_count:
        return t(language, "history_recent_more_pauses")
    if context_category == "family":
        return t(language, "history_recent_family_stable")
    if context_category == "work":
        return t(language, "history_recent_work_stable")
    return t(language, "history_recent_stable")


def parse_datetime(value: str) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
