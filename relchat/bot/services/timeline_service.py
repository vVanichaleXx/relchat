from __future__ import annotations

import math
import struct
import tempfile
import zlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from relchat.core.models import ConversationEvent, Message
from relchat.events.extractor import extract_events


TIMELINE_FILTERS = {"all", "activity", "questions", "plans", "followups", "silences"}
TIMELINE_PAGE_SIZE = 8
TIMELINE_STORY_PAGE_SIZE = 8
SUPPORTED_EVENT_TYPES = {
    "question",
    "unanswered_question",
    "long_silence",
    "plan_candidate",
    "promise_candidate",
    "follow_up_candidate",
}
SENSITIVE_METADATA_WORDS = ("text", "content", "token", "hash", "phone", "session", "secret")


@dataclass(frozen=True)
class TimelineBucket:
    key: str
    label: str
    start: date
    end: date
    total_messages: int
    sender_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TimelineEntry:
    timestamp: str
    entry_type: str
    sender_ref: str | None = None
    source_message_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: str = "medium"
    rule_source: str | None = None


@dataclass(frozen=True)
class TimelineSummary:
    granularity: str
    analyzed_start: str | None
    analyzed_end: str | None
    most_active_label: str | None
    most_active_count: int
    longest_silence_hours: float | None
    meaningful_event_count: int
    recent_change: str
    bucket_count: int
    message_count: int
    chat_type: str


@dataclass(frozen=True)
class RelationshipTimeline:
    granularity: str
    chat_type: str
    buckets: list[TimelineBucket]
    entries: list[TimelineEntry]
    summary: TimelineSummary
    story_items: list["TimelineStoryItem"] = field(default_factory=list)


@dataclass(frozen=True)
class TimelinePage:
    entries: list[TimelineEntry]
    filter_id: str
    page: int
    page_size: int
    total: int
    has_newer: bool
    has_older: bool


@dataclass(frozen=True)
class TimelineStoryItem:
    timestamp: str
    story_type: str
    filter_tags: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    source_message_id: int | None = None
    confidence: str = "medium"


@dataclass(frozen=True)
class TimelineStoryPage:
    entries: list[TimelineStoryItem]
    filter_id: str
    page: int
    page_size: int
    total: int
    has_newer: bool
    has_older: bool


def build_relationship_timeline(
    *,
    messages: Sequence[Message],
    reports: Sequence[dict[str, Any]] = (),
    reminders: Sequence[dict[str, Any]] = (),
    semantic_events: Sequence[dict[str, Any]] = (),
    chat_type: str | None = None,
    granularity: str = "week",
) -> RelationshipTimeline:
    resolved_granularity = "month" if granularity == "month" else "week"
    ordered_messages = sorted(messages, key=message_sort_key)
    buckets = build_buckets(ordered_messages, granularity=resolved_granularity)
    sender_refs = sender_reference_map(ordered_messages, chat_type=chat_type)
    events = extract_events(ordered_messages) if ordered_messages else []
    entries: list[TimelineEntry] = []

    for bucket in buckets:
        entry_type = "activity_period" if bucket.total_messages else "quiet_period"
        entries.append(
            TimelineEntry(
                timestamp=bucket.start.isoformat(),
                entry_type=entry_type,
                metadata={
                    "bucket_label": bucket.label,
                    "message_count": bucket.total_messages,
                    "sender_counts": bucket.sender_counts,
                    "granularity": resolved_granularity,
                },
                confidence="high" if bucket.total_messages else "medium",
                rule_source="message_count",
            )
        )

    for event in events:
        if event.event_type not in SUPPORTED_EVENT_TYPES:
            continue
        entries.append(timeline_entry_from_event(event, sender_refs))

    for reminder in reminders:
        if reminder.get("status") != "confirmed":
            continue
        if reminder.get("reminder_time"):
            timestamp = str(reminder["reminder_time"])
        else:
            timestamp = str(reminder.get("updated_at") or reminder.get("created_at") or "")
        entries.append(
            TimelineEntry(
                timestamp=timestamp,
                entry_type="confirmed_reminder",
                metadata={"event_type": reminder.get("event_type"), "status": "confirmed"},
                confidence="high",
                rule_source="user_confirmed",
            )
        )

    for report in reports:
        if report.get("job_status") and report.get("job_status") != "completed":
            continue
        entries.append(
            TimelineEntry(
                timestamp=str(report.get("created_at") or report.get("period_end") or report.get("period_start") or ""),
                entry_type="analysis_completed",
                metadata={
                    "period_label": report.get("period_label"),
                    "message_count": int(report.get("imported_message_count") or 0),
                    "confidence": (report.get("data_quality") or {}).get("confidence"),
                },
                confidence=str((report.get("data_quality") or {}).get("confidence") or "medium"),
                rule_source="completed_report",
            )
        )

    entries = sorted(entries, key=entry_sort_key, reverse=True)
    story_items = build_story_items(
        messages=ordered_messages,
        reports=reports,
        reminders=reminders,
        semantic_events=semantic_events,
        events=events,
        buckets=buckets,
        chat_type=chat_type or "one_to_one",
    )
    summary = summarize_timeline(
        buckets=buckets,
        entries=entries,
        messages=ordered_messages,
        chat_type=chat_type or "one_to_one",
        granularity=resolved_granularity,
    )
    return RelationshipTimeline(
        granularity=resolved_granularity,
        chat_type=chat_type or "one_to_one",
        buckets=buckets,
        entries=entries,
        summary=summary,
        story_items=story_items,
    )


def build_buckets(messages: Sequence[Message], *, granularity: str) -> list[TimelineBucket]:
    if not messages:
        return []
    parsed = [(message, parse_ts(message.timestamp)) for message in messages]
    first_start = bucket_start(parsed[0][1].date(), granularity)
    last_start = bucket_start(parsed[-1][1].date(), granularity)
    bucket_counts: dict[date, Counter[str]] = defaultdict(Counter)
    for message, timestamp in parsed:
        start = bucket_start(timestamp.date(), granularity)
        bucket_counts[start][sender_key(message)] += 1

    buckets: list[TimelineBucket] = []
    current = first_start
    while current <= last_start:
        end = bucket_end(current, granularity)
        counts = dict(bucket_counts.get(current, Counter()))
        buckets.append(
            TimelineBucket(
                key=current.isoformat(),
                label=bucket_label(current, granularity),
                start=current,
                end=end,
                total_messages=sum(counts.values()),
                sender_counts=counts,
            )
        )
        current = next_bucket(current, granularity)
    return buckets


def filter_timeline_entries(entries: Sequence[TimelineEntry], filter_id: str) -> list[TimelineEntry]:
    selected = filter_id if filter_id in TIMELINE_FILTERS else "all"
    if selected == "all":
        return list(entries)
    return [entry for entry in entries if selected in entry_filters(entry.entry_type)]


def paginate_timeline_entries(
    entries: Sequence[TimelineEntry],
    *,
    filter_id: str = "all",
    page: int = 0,
    page_size: int = TIMELINE_PAGE_SIZE,
) -> TimelinePage:
    filtered = filter_timeline_entries(entries, filter_id)
    normalized_page = max(0, page)
    start = normalized_page * page_size
    if start >= len(filtered) and filtered:
        normalized_page = max(0, math.ceil(len(filtered) / page_size) - 1)
        start = normalized_page * page_size
    end = start + page_size
    return TimelinePage(
        entries=filtered[start:end],
        filter_id=filter_id if filter_id in TIMELINE_FILTERS else "all",
        page=normalized_page,
        page_size=page_size,
        total=len(filtered),
        has_newer=normalized_page > 0,
        has_older=end < len(filtered),
    )


def filter_timeline_story_items(entries: Sequence[TimelineStoryItem], filter_id: str) -> list[TimelineStoryItem]:
    selected = filter_id if filter_id in TIMELINE_FILTERS else "all"
    if selected == "all":
        return list(entries)
    return [entry for entry in entries if selected in entry.filter_tags]


def paginate_timeline_story(
    entries: Sequence[TimelineStoryItem],
    *,
    filter_id: str = "all",
    page: int = 0,
    page_size: int = TIMELINE_STORY_PAGE_SIZE,
) -> TimelineStoryPage:
    filtered = filter_timeline_story_items(entries, filter_id)
    normalized_page = max(0, page)
    start = normalized_page * page_size
    if start >= len(filtered) and filtered:
        normalized_page = max(0, math.ceil(len(filtered) / page_size) - 1)
        start = normalized_page * page_size
    end = start + page_size
    return TimelineStoryPage(
        entries=filtered[start:end],
        filter_id=filter_id if filter_id in TIMELINE_FILTERS else "all",
        page=normalized_page,
        page_size=page_size,
        total=len(filtered),
        has_newer=normalized_page > 0,
        has_older=end < len(filtered),
    )


def build_story_items(
    *,
    messages: Sequence[Message],
    reports: Sequence[dict[str, Any]],
    reminders: Sequence[dict[str, Any]],
    semantic_events: Sequence[dict[str, Any]],
    events: Sequence[ConversationEvent],
    buckets: Sequence[TimelineBucket],
    chat_type: str,
) -> list[TimelineStoryItem]:
    items: list[TimelineStoryItem] = []
    items.extend(activity_story_items(messages, chat_type=chat_type))
    items.extend(silence_story_items(messages, chat_type=chat_type))
    items.extend(event_story_items(events))
    items.extend(reminder_story_items(reminders))
    items.extend(report_story_items(reports))
    items.extend(semantic_story_items(semantic_events))
    items.extend(activity_change_story_items(buckets))
    return sorted(items, key=story_sort_key, reverse=True)


def activity_story_items(messages: Sequence[Message], *, chat_type: str) -> list[TimelineStoryItem]:
    by_day: dict[date, list[Message]] = defaultdict(list)
    for message in messages:
        by_day[parse_ts(message.timestamp).date()].append(message)
    items: list[TimelineStoryItem] = []
    for day_messages in by_day.values():
        ordered = sorted(day_messages, key=message_sort_key)
        latest = ordered[-1]
        items.append(
            TimelineStoryItem(
                timestamp=latest.timestamp,
                story_type="activity_day",
                filter_tags=("activity",),
                source_message_id=latest.source_message_id,
                confidence="high",
                metadata={
                    "message_count": len(ordered),
                    "active_periods": active_period_count(ordered),
                    "day_part": dominant_day_part(ordered),
                    "chat_type": chat_type,
                },
            )
        )
    return items


def silence_story_items(messages: Sequence[Message], *, chat_type: str) -> list[TimelineStoryItem]:
    items: list[TimelineStoryItem] = []
    ordered = sorted(messages, key=message_sort_key)
    for previous, current in zip(ordered, ordered[1:]):
        previous_at = parse_ts(previous.timestamp)
        current_at = parse_ts(current.timestamp)
        gap = current_at - previous_at
        if gap <= timedelta(hours=48):
            continue
        gap_days = round(gap.total_seconds() / 86400, 1)
        items.append(
            TimelineStoryItem(
                timestamp=previous.timestamp,
                story_type="quiet_started",
                filter_tags=("silences",),
                source_message_id=previous.source_message_id,
                confidence="high",
                metadata={"gap_days": gap_days, "chat_type": chat_type},
            )
        )
        items.append(
            TimelineStoryItem(
                timestamp=current.timestamp,
                story_type="conversation_resumed",
                filter_tags=("activity", "silences"),
                source_message_id=current.source_message_id,
                confidence="high",
                metadata={"gap_days": gap_days, "chat_type": chat_type},
            )
        )
    return items


def event_story_items(events: Sequence[ConversationEvent]) -> list[TimelineStoryItem]:
    story_types = {
        "question": ("question_detected", ("questions",)),
        "unanswered_question": ("unanswered_question", ("questions", "followups")),
        "plan_candidate": ("plan_mentioned", ("plans",)),
        "promise_candidate": ("promise_mentioned", ("plans", "followups")),
        "follow_up_candidate": ("followup_suggested", ("followups",)),
    }
    items: list[TimelineStoryItem] = []
    for event in events:
        mapped = story_types.get(event.event_type)
        if mapped is None:
            continue
        story_type, tags = mapped
        items.append(
            TimelineStoryItem(
                timestamp=event.timestamp,
                story_type=story_type,
                filter_tags=tags,
                source_message_id=event.source_message_id,
                confidence="medium",
                metadata=safe_event_metadata(event.metadata),
            )
        )
    return items


def reminder_story_items(reminders: Sequence[dict[str, Any]]) -> list[TimelineStoryItem]:
    status_to_type = {
        "suggested": "reminder_suggested",
        "confirmed": "reminder_confirmed",
        "completed": "reminder_completed",
        "dismissed": "reminder_dismissed",
    }
    items: list[TimelineStoryItem] = []
    for reminder in reminders:
        story_type = status_to_type.get(str(reminder.get("status") or ""))
        if story_type is None:
            continue
        timestamp = str(reminder.get("reminder_time") or reminder.get("updated_at") or reminder.get("created_at") or "")
        items.append(
            TimelineStoryItem(
                timestamp=timestamp,
                story_type=story_type,
                filter_tags=("followups",),
                confidence="high" if reminder.get("status") == "confirmed" else "medium",
                metadata={"status": reminder.get("status"), "event_type": reminder.get("event_type")},
            )
        )
    return items


def report_story_items(reports: Sequence[dict[str, Any]]) -> list[TimelineStoryItem]:
    items: list[TimelineStoryItem] = []
    for report in reports:
        if report.get("job_status") and report.get("job_status") != "completed":
            continue
        items.append(
            TimelineStoryItem(
                timestamp=str(report.get("created_at") or report.get("period_end") or report.get("period_start") or ""),
                story_type="analysis_completed",
                filter_tags=("activity",),
                confidence=str((report.get("data_quality") or {}).get("confidence") or "medium"),
                metadata={
                    "period_label": report.get("period_label"),
                    "message_count": int(report.get("imported_message_count") or 0),
                },
            )
        )
    return items


def semantic_story_items(events: Sequence[dict[str, Any]]) -> list[TimelineStoryItem]:
    items: list[TimelineStoryItem] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        if not event_type.startswith("semantic_"):
            continue
        timestamp = str(event.get("created_at") or event.get("period_end") or event.get("period_scope") or "")
        items.append(
            TimelineStoryItem(
                timestamp=timestamp,
                story_type=event_type,
                filter_tags=("activity", "semantics"),
                confidence=str(event.get("confidence") or "low"),
                metadata={
                    "title": event.get("title"),
                    "summary": event.get("summary"),
                    "severity": event.get("severity"),
                    "evidence_count": int(event.get("evidence_count") or 0),
                    "period_scope": event.get("period_scope"),
                    "context_scope": event.get("context_scope"),
                },
            )
        )
    return items


def activity_change_story_items(buckets: Sequence[TimelineBucket]) -> list[TimelineStoryItem]:
    items: list[TimelineStoryItem] = []
    active = [bucket for bucket in buckets if bucket.total_messages]
    for previous, current in zip(active, active[1:]):
        if previous.total_messages < 5 or current.total_messages < 5:
            continue
        ratio = current.total_messages / previous.total_messages
        if ratio >= 1.25:
            story_type = "activity_increased"
        elif ratio <= 0.75:
            story_type = "activity_decreased"
        else:
            continue
        items.append(
            TimelineStoryItem(
                timestamp=current.start.isoformat(),
                story_type=story_type,
                filter_tags=("activity",),
                confidence="medium",
                metadata={
                    "current_count": current.total_messages,
                    "previous_count": previous.total_messages,
                    "period_label": current.label,
                },
            )
        )
    return items


def render_timeline_chart(
    messages: Sequence[Message],
    *,
    chat_type: str | None = None,
    granularity: str = "week",
    output_dir: Path | None = None,
) -> Path:
    resolved_granularity = "month" if granularity == "month" else "week"
    buckets = build_buckets(sorted(messages, key=message_sort_key), granularity=resolved_granularity)
    if not buckets:
        raise ValueError("timeline chart needs at least one message")

    output = tempfile.NamedTemporaryFile(prefix="relchat_timeline_", suffix=".png", dir=output_dir, delete=False)
    output_path = Path(output.name)
    output.close()
    try:
        pixels = draw_chart_pixels(buckets, chat_type=chat_type)
        write_png(output_path, pixels)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return output_path


def timeline_entry_from_event(event: ConversationEvent, sender_refs: dict[str, str]) -> TimelineEntry:
    metadata = safe_event_metadata(event.metadata)
    if event.related_message_id is not None:
        metadata["related_message_id"] = event.related_message_id
    return TimelineEntry(
        timestamp=event.timestamp,
        entry_type=event.event_type,
        sender_ref=sender_refs.get(event_sender_key(event)),
        source_message_id=event.source_message_id,
        metadata=metadata,
        confidence="medium",
        rule_source=str(event.metadata.get("rule") or event.event_type),
    )


def summarize_timeline(
    *,
    buckets: Sequence[TimelineBucket],
    entries: Sequence[TimelineEntry],
    messages: Sequence[Message],
    chat_type: str,
    granularity: str,
) -> TimelineSummary:
    active_buckets = [bucket for bucket in buckets if bucket.total_messages]
    most_active = max(active_buckets, key=lambda bucket: bucket.total_messages, default=None)
    silence_hours = [
        float(entry.metadata["gap_hours"])
        for entry in entries
        if entry.entry_type == "long_silence" and isinstance(entry.metadata.get("gap_hours"), (int, float))
    ]
    meaningful_count = sum(
        1
        for entry in entries
        if entry.entry_type
        in {
            "question",
            "unanswered_question",
            "long_silence",
            "plan_candidate",
            "promise_candidate",
            "follow_up_candidate",
            "confirmed_reminder",
            "analysis_completed",
        }
    )
    return TimelineSummary(
        granularity=granularity,
        analyzed_start=messages[0].timestamp if messages else None,
        analyzed_end=messages[-1].timestamp if messages else None,
        most_active_label=most_active.label if most_active else None,
        most_active_count=most_active.total_messages if most_active else 0,
        longest_silence_hours=max(silence_hours) if silence_hours else None,
        meaningful_event_count=meaningful_count,
        recent_change=recent_change(active_buckets),
        bucket_count=len(buckets),
        message_count=len(messages),
        chat_type=chat_type,
    )


def recent_change(active_buckets: Sequence[TimelineBucket]) -> str:
    if len(active_buckets) < 2:
        return "unavailable"
    previous = active_buckets[-2].total_messages
    current = active_buckets[-1].total_messages
    if previous < 5 or current < 5:
        return "limited"
    ratio = (current - previous) / previous
    if ratio > 0.2:
        return "higher"
    if ratio < -0.2:
        return "lower"
    return "similar"


def entry_filters(entry_type: str) -> set[str]:
    mapping = {
        "activity_period": {"activity"},
        "analysis_completed": {"activity"},
        "question": {"questions"},
        "unanswered_question": {"questions", "followups"},
        "plan_candidate": {"plans"},
        "promise_candidate": {"plans", "followups"},
        "follow_up_candidate": {"followups"},
        "confirmed_reminder": {"followups"},
        "long_silence": {"silences"},
        "quiet_period": {"silences"},
    }
    return mapping.get(entry_type, set())


def safe_event_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(word in lowered for word in SENSITIVE_METADATA_WORDS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe


def sender_reference_map(messages: Sequence[Message], *, chat_type: str | None) -> dict[str, str]:
    refs: dict[str, str] = {}
    prefix = "member" if chat_type == "group" else "participant"
    if chat_type == "channel":
        prefix = "channel"
    for message in messages:
        key = sender_key(message)
        if key in refs:
            continue
        if prefix == "channel":
            refs[key] = "channel"
        else:
            refs[key] = f"{prefix}_{len(refs) + 1}"
    return refs


def sender_key(message: Message) -> str:
    return message.sender_id or message.sender_name or "unknown"


def event_sender_key(event: ConversationEvent) -> str:
    return event.sender_id or event.sender_name or "unknown"


def message_sort_key(message: Message) -> tuple[datetime, int]:
    return (parse_ts(message.timestamp), message.source_message_id)


def entry_sort_key(entry: TimelineEntry) -> tuple[datetime, int]:
    return (parse_ts(entry.timestamp), entry.source_message_id or 0)


def story_sort_key(entry: TimelineStoryItem) -> tuple[datetime, int]:
    priority = {
        "conversation_resumed": 80,
        "followup_suggested": 75,
        "unanswered_question": 74,
        "reminder_confirmed": 72,
        "reminder_suggested": 70,
        "activity_increased": 65,
        "activity_decreased": 65,
        "activity_day": 60,
        "plan_mentioned": 55,
        "promise_mentioned": 54,
        "question_detected": 50,
        "analysis_completed": 45,
        "quiet_started": 40,
        "reminder_completed": 35,
        "reminder_dismissed": 30,
    }.get(entry.story_type, 0)
    return (parse_ts(entry.timestamp), priority)


def active_period_count(messages: Sequence[Message]) -> int:
    if not messages:
        return 0
    count = 1
    ordered = sorted(messages, key=message_sort_key)
    for previous, current in zip(ordered, ordered[1:]):
        if parse_ts(current.timestamp) - parse_ts(previous.timestamp) > timedelta(hours=2):
            count += 1
    return count


def dominant_day_part(messages: Sequence[Message]) -> str | None:
    if not messages:
        return None
    counts: Counter[str] = Counter()
    for message in messages:
        hour = parse_ts(message.timestamp).hour
        if 5 <= hour < 12:
            counts["morning"] += 1
        elif 12 <= hour < 17:
            counts["afternoon"] += 1
        elif 17 <= hour < 23:
            counts["evening"] += 1
        else:
            counts["night"] += 1
    return counts.most_common(1)[0][0]


def parse_ts(value: str) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def bucket_start(value: date, granularity: str) -> date:
    if granularity == "month":
        return value.replace(day=1)
    return value - timedelta(days=value.weekday())


def bucket_end(start: date, granularity: str) -> date:
    if granularity == "month":
        next_start = next_bucket(start, granularity)
        return next_start - timedelta(days=1)
    return start + timedelta(days=6)


def next_bucket(start: date, granularity: str) -> date:
    if granularity == "month":
        if start.month == 12:
            return date(start.year + 1, 1, 1)
        return date(start.year, start.month + 1, 1)
    return start + timedelta(days=7)


def bucket_label(start: date, granularity: str) -> str:
    if granularity == "month":
        return start.strftime("%Y-%m")
    return start.isoformat()


def draw_chart_pixels(buckets: Sequence[TimelineBucket], *, chat_type: str | None) -> tuple[int, int, bytearray]:
    width = 720
    height = 360
    pixels = bytearray([255] * width * height * 3)
    margin_left = 52
    margin_right = 24
    margin_top = 28
    margin_bottom = 42
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    def point(index: int, value: int, max_value: int) -> tuple[int, int]:
        x = margin_left + int((plot_width * index) / max(1, len(buckets) - 1))
        y = margin_top + plot_height - int((plot_height * value) / max(1, max_value))
        return x, y

    max_total = max((bucket.total_messages for bucket in buckets), default=1)
    draw_rect(pixels, width, 0, 0, width, height, (250, 250, 247))
    for step in range(5):
        y = margin_top + int((plot_height * step) / 4)
        draw_line(pixels, width, margin_left, y, width - margin_right, y, (225, 225, 220))
    draw_line(pixels, width, margin_left, margin_top, margin_left, height - margin_bottom, (90, 90, 90))
    draw_line(pixels, width, margin_left, height - margin_bottom, width - margin_right, height - margin_bottom, (90, 90, 90))

    if chat_type == "one_to_one":
        sender_order = ordered_sender_keys(buckets)[:2]
        colors = [(42, 106, 189), (210, 89, 76)]
        max_value = max(
            [max_total]
            + [max((bucket.sender_counts.get(sender, 0) for bucket in buckets), default=0) for sender in sender_order]
        )
        for sender_index, sender in enumerate(sender_order):
            points = [point(index, bucket.sender_counts.get(sender, 0), max_value) for index, bucket in enumerate(buckets)]
            for first, second in zip(points, points[1:]):
                draw_line(pixels, width, first[0], first[1], second[0], second[1], colors[sender_index])
            for x, y in points:
                draw_rect(pixels, width, x - 3, y - 3, 7, 7, colors[sender_index])
    else:
        bar_width = max(4, int(plot_width / max(1, len(buckets)) * 0.55))
        for index, bucket in enumerate(buckets):
            x, y = point(index, bucket.total_messages, max_total)
            bottom = height - margin_bottom
            draw_rect(pixels, width, x - bar_width // 2, y, bar_width, max(1, bottom - y), (42, 130, 105))

    return width, height, pixels


def ordered_sender_keys(buckets: Sequence[TimelineBucket]) -> list[str]:
    counts: Counter[str] = Counter()
    order: list[str] = []
    for bucket in buckets:
        for sender, count in bucket.sender_counts.items():
            if sender not in counts:
                order.append(sender)
            counts[sender] += count
    return sorted(order, key=lambda sender: (-counts[sender], order.index(sender)))


def draw_rect(pixels: bytearray, width: int, x: int, y: int, rect_width: int, rect_height: int, color: tuple[int, int, int]) -> None:
    height = len(pixels) // (width * 3)
    for row in range(max(0, y), min(height, y + rect_height)):
        for col in range(max(0, x), min(width, x + rect_width)):
            set_pixel(pixels, width, col, row, color)


def draw_line(pixels: bytearray, width: int, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        set_pixel(pixels, width, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        double_error = 2 * error
        if double_error >= dy:
            error += dy
            x0 += sx
        if double_error <= dx:
            error += dx
            y0 += sy


def set_pixel(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    height = len(pixels) // (width * 3)
    if x < 0 or x >= width or y < 0 or y >= height:
        return
    index = (y * width + x) * 3
    pixels[index : index + 3] = bytes(color)


def write_png(path: Path, image: tuple[int, int, bytearray]) -> None:
    width, height, pixels = image
    rows = []
    for y in range(height):
        row_start = y * width * 3
        rows.append(b"\x00" + bytes(pixels[row_start : row_start + width * 3]))
    raw = b"".join(rows)
    with path.open("wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        handle.write(png_chunk(b"IDAT", zlib.compress(raw, level=6)))
        handle.write(png_chunk(b"IEND", b""))


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def contains_raw_text(entries: Iterable[TimelineEntry], text: str) -> bool:
    return any(text in str(entry.metadata) for entry in entries)
