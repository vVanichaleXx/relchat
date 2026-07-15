from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.analytics.metrics import summarize
from relchat.core.models import ConversationEvent, Message
from relchat.database.repositories import create_reminder, create_report, mark_user_chat_analyzed
from relchat.events.extractor import summarize_events


REMINDER_EVENT_TYPES = {
    "reminder_candidate",
    "follow_up_candidate",
    "plan_candidate",
    "promise_candidate",
}


def build_report(
    conn,
    *,
    bot_user_id: int,
    job: dict[str, Any],
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
    modules: list[str],
    range_start: str | None,
    range_end: str | None,
) -> dict[str, Any]:
    ordered_messages = sorted(messages, key=lambda message: (message.timestamp, message.source_message_id))
    metrics = summarize(ordered_messages, job["chat_id"])
    sanitized_metrics = sanitize_metrics(metrics)
    event_summary = build_event_summary(events)
    data_quality = build_data_quality(ordered_messages, range_start=range_start, range_end=range_end, period_id=job["period_id"])
    report = create_report(
        conn,
        bot_user_id=bot_user_id,
        job_id=job["job_id"],
        source=job["source"],
        chat_id=job["chat_id"],
        chat_title=job.get("chat_title"),
        period_id=job["period_id"],
        period_label=job["period_label"],
        period_start=job.get("period_start"),
        period_end=job.get("period_end"),
        imported_message_count=len(ordered_messages),
        modules=modules,
        job_status="completed",
        metrics_summary=sanitized_metrics,
        event_summary=event_summary,
        data_quality=data_quality,
    )
    mark_user_chat_analyzed(conn, bot_user_id, job["source"], job["chat_id"], report["report_id"])
    create_suggested_reminders(conn, bot_user_id=bot_user_id, report=report, events=events)
    return report


def sanitize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(metrics)
    sanitized["unanswered_questions"] = [
        {
            "message_id": item.get("message_id"),
            "timestamp": item.get("timestamp"),
            "sender": item.get("sender"),
        }
        for item in metrics.get("unanswered_questions") or []
    ]
    return sanitized


def build_event_summary(events: Sequence[ConversationEvent]) -> dict[str, Any]:
    by_type = summarize_events(events)
    return {
        "total_events": len(events),
        "by_type": by_type,
        "reminder_candidates": sum(by_type.get(event_type, 0) for event_type in REMINDER_EVENT_TYPES),
    }


def build_data_quality(
    messages: Sequence[Message],
    *,
    range_start: str | None,
    range_end: str | None,
    period_id: str,
) -> dict[str, Any]:
    count = len(messages)
    if count == 0:
        completeness = "no messages in selected period"
        confidence = "none"
    elif count < 30:
        completeness = "limited sample"
        confidence = "low"
    elif period_id == "full":
        completeness = "full local import completed"
        confidence = "medium"
    else:
        completeness = "selected period imported"
        confidence = "medium"
    return {
        "message_count": count,
        "range_start": range_start,
        "range_end": range_end,
        "period_id": period_id,
        "completeness": completeness,
        "confidence": confidence,
    }


def create_suggested_reminders(
    conn,
    *,
    bot_user_id: int,
    report: dict[str, Any],
    events: Sequence[ConversationEvent],
    limit: int = 10,
) -> None:
    created = 0
    seen_message_ids: set[int | None] = set()
    for event in events:
        if event.event_type not in REMINDER_EVENT_TYPES:
            continue
        if event.source_message_id in seen_message_ids:
            continue
        seen_message_ids.add(event.source_message_id)
        create_reminder(
            conn,
            bot_user_id=bot_user_id,
            source=report["source"],
            chat_id=report["chat_id"],
            chat_title=report.get("chat_title"),
            report_id=report["report_id"],
            event_type=event.event_type,
            title=reminder_title(event, report.get("chat_title")),
            reminder_time=event.timestamp,
            status="suggested",
            metadata={
                "source_message_id": event.source_message_id,
                "related_message_id": event.related_message_id,
                "rule": event.metadata.get("rule"),
            },
        )
        created += 1
        if created >= limit:
            break


def reminder_title(event: ConversationEvent, chat_title: str | None) -> str:
    label = {
        "reminder_candidate": "Review explicit reminder",
        "follow_up_candidate": "Review follow-up",
        "plan_candidate": "Review plan",
        "promise_candidate": "Review promise",
    }.get(event.event_type, "Review reminder")
    if chat_title:
        return f"{label} in {chat_title}"
    return label
