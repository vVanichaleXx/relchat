from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta

from relchat.core.models import ConversationEvent, EventMetadataValue, Message


QUESTION_RESPONSE_HOURS = 48
LONG_SILENCE_HOURS = 48

PLAN_PATTERNS = [
    re.compile(r"\b(let'?s|lets|shall we|we should|we could|we can|we need to)\b", re.IGNORECASE),
    re.compile(
        r"\b(meet|call|talk|visit|book|schedule|plan|go)\b.*"
        r"\b(today|tonight|tomorrow|weekend|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        re.IGNORECASE,
    ),
]

PROMISE_PATTERNS = [
    re.compile(r"\b(i|we)\s+(will|can|promise|am going to|are going to|gonna)\b", re.IGNORECASE),
    re.compile(r"\b(i'll|we'll)\b", re.IGNORECASE),
]

HEALTH_PATTERNS = [
    re.compile(
        r"\b(sick|ill|doctor|hospital|clinic|therapy|therapist|medicine|medication|"
        r"headache|fever|covid|flu|anxiety|anxious|depression|panic|exhausted)\b",
        re.IGNORECASE,
    )
]

FOLLOW_UP_PATTERNS = [
    re.compile(
        r"\b(follow up|check in|circle back|get back to|let me know|any update|update me|"
        r"remind me|don't forget|dont forget|ping me|deadline|due)\b",
        re.IGNORECASE,
    )
]


def extract_events(messages: Sequence[Message]) -> list[ConversationEvent]:
    ordered = sorted(messages, key=message_sort_key)
    events: list[ConversationEvent] = []

    events.extend(extract_long_silences(ordered))
    for index, message in enumerate(ordered):
        text = normalized_text(message)
        if not text:
            continue
        if is_question(text):
            events.append(make_event("question", message, metadata={"rule": "question_mark"}))
            if is_unanswered_question(ordered, index):
                events.append(
                    make_event(
                        "unanswered_question",
                        message,
                        metadata={"response_window_hours": QUESTION_RESPONSE_HOURS},
                    )
                )
        events.extend(extract_candidate_events(message, text))

    return sorted(events, key=event_sort_key)


def summarize_events(events: Sequence[ConversationEvent]) -> dict[str, int]:
    counts = Counter(event.event_type for event in events)
    return dict(counts.most_common())


def extract_long_silences(messages: Sequence[Message]) -> list[ConversationEvent]:
    events: list[ConversationEvent] = []
    for previous, current in zip(messages, messages[1:]):
        gap = parse_ts(current.timestamp) - parse_ts(previous.timestamp)
        if gap > timedelta(hours=LONG_SILENCE_HOURS):
            events.append(
                make_event(
                    "long_silence",
                    current,
                    related_message_id=previous.source_message_id,
                    metadata={
                        "gap_hours": round(gap.total_seconds() / 3600, 2),
                        "threshold_hours": LONG_SILENCE_HOURS,
                    },
                )
            )
    return events


def extract_candidate_events(message: Message, text: str) -> list[ConversationEvent]:
    candidates = [
        ("plan_candidate", PLAN_PATTERNS),
        ("promise_candidate", PROMISE_PATTERNS),
        ("health_candidate", HEALTH_PATTERNS),
        ("follow_up_candidate", FOLLOW_UP_PATTERNS),
    ]
    events = []
    for event_type, patterns in candidates:
        if matches_any(patterns, text):
            events.append(make_event(event_type, message, metadata={"rule": "keyword"}))
    return events


def is_question(text: str) -> bool:
    return "?" in text


def is_unanswered_question(messages: Sequence[Message], question_index: int) -> bool:
    question = messages[question_index]
    asked_at = parse_ts(question.timestamp)
    asker = sender_key(question)
    for later in messages[question_index + 1 :]:
        later_at = parse_ts(later.timestamp)
        if later_at - asked_at > timedelta(hours=QUESTION_RESPONSE_HOURS):
            break
        if sender_key(later) != asker:
            return False
    return True


def matches_any(patterns: Sequence[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def make_event(
    event_type: str,
    message: Message,
    *,
    related_message_id: int | None = None,
    metadata: dict[str, EventMetadataValue] | None = None,
) -> ConversationEvent:
    return ConversationEvent(
        source=message.source,
        conversation_id=message.conversation_id,
        event_type=event_type,
        timestamp=message.timestamp,
        source_message_id=message.source_message_id,
        sender_id=message.sender_id,
        sender_name=message.sender_name,
        related_message_id=related_message_id,
        metadata=metadata or {},
    )


def normalized_text(message: Message) -> str:
    return " ".join((message.text or "").split())


def sender_key(message: Message) -> str:
    return message.sender_id or message.sender_name or ""


def message_sort_key(message: Message) -> tuple[datetime, int]:
    return (parse_ts(message.timestamp), message.source_message_id)


def event_sort_key(event: ConversationEvent) -> tuple[datetime, int, str]:
    return (parse_ts(event.timestamp), event.source_message_id or 0, event.event_type)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
