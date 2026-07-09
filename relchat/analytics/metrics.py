from __future__ import annotations

import statistics
from collections.abc import Sequence
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from relchat.core.models import Message


SESSION_GAP_HOURS = 12
ACTIVE_RESPONSE_HOURS = 6
QUESTION_RESPONSE_HOURS = 48


def summarize(messages: Sequence[Message], conversation_id: str) -> dict:
    return {
        "chat_id": conversation_id,
        "message_count": len(messages),
        "message_count_by_sender": message_count_by_sender(messages),
        "initiation_balance": initiation_balance(messages),
        "response_times": response_times(messages),
        "average_message_length": average_message_length(messages),
        "unanswered_questions": unanswered_questions(messages),
    }


def message_count_by_sender(messages: Sequence[Message]) -> dict:
    counts = Counter(sender_label(message) for message in messages)
    return dict(counts.most_common())


def initiation_balance(messages: Sequence[Message]) -> dict:
    if not messages:
        return {"session_count": 0, "gap_hours": SESSION_GAP_HOURS, "by_sender": {}, "share": {}}
    sessions: list[list[Message]] = []
    current: list[Message] = []
    previous_time: datetime | None = None
    for message in messages:
        ts = parse_ts(message.timestamp)
        if previous_time and ts - previous_time > timedelta(hours=SESSION_GAP_HOURS):
            sessions.append(current)
            current = []
        current.append(message)
        previous_time = ts
    if current:
        sessions.append(current)
    counts = Counter(sender_label(session[0]) for session in sessions if session)
    total = sum(counts.values()) or 1
    return {
        "session_count": len(sessions),
        "gap_hours": SESSION_GAP_HOURS,
        "by_sender": dict(counts.most_common()),
        "share": {sender: round(count / total, 3) for sender, count in counts.items()},
    }


def response_times(messages: Sequence[Message]) -> dict:
    by_responder: dict[str, list[float]] = defaultdict(list)
    active_by_responder: dict[str, list[float]] = defaultdict(list)
    for previous, current in zip(messages, messages[1:]):
        if previous.sender_id == current.sender_id:
            continue
        gap = (parse_ts(current.timestamp) - parse_ts(previous.timestamp)).total_seconds()
        if gap < 0:
            continue
        responder = sender_label(current)
        by_responder[responder].append(gap)
        if gap <= ACTIVE_RESPONSE_HOURS * 3600:
            active_by_responder[responder].append(gap)
    senders = sorted(set(by_responder) | set(active_by_responder))
    return {
        sender: {
            "count": len(by_responder.get(sender, [])),
            "median_seconds": median_or_none(by_responder.get(sender, [])),
            "median_readable": human_duration(median_or_none(by_responder.get(sender, []))),
            "active_count": len(active_by_responder.get(sender, [])),
            "active_median_seconds": median_or_none(active_by_responder.get(sender, [])),
            "active_median_readable": human_duration(median_or_none(active_by_responder.get(sender, []))),
        }
        for sender in senders
    }


def average_message_length(messages: Sequence[Message]) -> dict:
    lengths: dict[str, list[int]] = defaultdict(list)
    for message in messages:
        text = message.text or ""
        if text:
            lengths[sender_label(message)].append(len(text))
    return {
        sender: {
            "message_count": len(values),
            "avg_chars": round(sum(values) / len(values), 2) if values else 0,
        }
        for sender, values in sorted(lengths.items())
    }


def unanswered_questions(messages: Sequence[Message]) -> list[dict]:
    out = []
    for index, message in enumerate(messages):
        text = message.text or ""
        if "?" not in text:
            continue
        asked_at = parse_ts(message.timestamp)
        asker_id = message.sender_id
        answered = False
        for later in messages[index + 1 :]:
            later_at = parse_ts(later.timestamp)
            if later_at - asked_at > timedelta(hours=QUESTION_RESPONSE_HOURS):
                break
            if later.sender_id != asker_id:
                answered = True
                break
        if not answered:
            out.append(
                {
                    "message_id": message.source_message_id,
                    "timestamp": message.timestamp,
                    "sender": sender_label(message),
                    "text": text[:240],
                }
            )
    return out


def sender_label(message: Message) -> str:
    if message.sender_name:
        return message.sender_name
    if message.sender_id:
        return f"user:{message.sender_id}"
    return "unknown"


def parse_ts(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def human_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"
