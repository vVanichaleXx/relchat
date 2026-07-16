from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from relchat.analytics.metrics import summarize
from relchat.config import Settings
from relchat.core.models import ConversationEvent, Message
from relchat.events.extractor import summarize_events


CONSENT_VERSION = "v1"
ANALYSIS_VERSION = "communication_v1"
POSITIVE_DIMENSIONS = {
    "reciprocity": 0.20,
    "initiative_balance": 0.15,
    "reply_quality": 0.15,
    "topic_continuation": 0.15,
    "respectfulness": 0.15,
    "question_engagement": 0.10,
    "planning_cooperation": 0.10,
}
RISK_DIMENSIONS = {
    "pressure_risk": 0.20,
    "hostility": 0.20,
    "dismissiveness": 0.15,
    "unanswered_question_rate": 0.15,
    "sarcasm_intensity": 0.10,
}
SUPPORTING_DIMENSIONS = {
    "reply_consistency",
    "emotional_acknowledgement",
}
DIMENSION_IDS = tuple(POSITIVE_DIMENSIONS.keys() | RISK_DIMENSIONS.keys() | SUPPORTING_DIMENSIONS)
CONFIDENCE_VALUES = {"low", "medium", "high"}
CONVERSATION_STATES = {
    "active_balanced",
    "active_uneven",
    "warm_irregular",
    "quiet_after_active",
    "planning_focused",
    "casual",
    "needs_follow_up",
    "insufficient_data",
}
WEAK_REPLY_CATEGORIES = {
    "ignored_question",
    "abrupt_reply",
    "sarcasm_instead_of_answer",
    "dismissive",
    "topic_switch",
    "low_effort",
    "hostile",
    "pressure",
    "missing_acknowledgement",
}
SEVERITY_VALUES = {"low", "medium", "high"}
FORBIDDEN_OUTPUT_TERMS = {
    "avoidant",
    "narcissist",
    "narcissism",
    "personality disorder",
    "depression",
    "anxiety disorder",
    "autism",
    "trauma",
    "lost interest",
    "they love you",
    "they like you",
    "definitely love",
    "for sure lost interest",
    "make them chase",
    "manipulate",
    "manipulation tactic",
}

PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
API_HASH_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
USERNAME_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{4,}\b")
SESSION_RE = re.compile(r"[\w./~ -]*telegram\.session(?:\.\w+)?", re.IGNORECASE)


class AIAnalysisError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AIInputBundle:
    payload: dict[str, Any]
    message_count_sent: int
    char_count_sent: int
    coverage: dict[str, Any]


@dataclass(frozen=True)
class AIAnalysisOutcome:
    result: dict[str, Any]
    message_count_sent: int
    char_count_sent: int
    coverage: dict[str, Any]
    token_usage: dict[str, Any]
    model_name: str


COMMUNICATION_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "summary",
        "conversation_state",
        "confidence",
        "participant_analysis",
        "positive_patterns",
        "problem_patterns",
        "weak_reply_patterns",
        "advice",
        "limitations",
    ],
    "properties": {
        "summary": {"type": "string"},
        "conversation_state": {"type": "string", "enum": sorted(CONVERSATION_STATES - {"insufficient_data"})},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "participant_analysis": {
            "type": "object",
            "additionalProperties": False,
            "required": ["you", "other"],
            "properties": {
                "you": {"$ref": "#/$defs/participant"},
                "other": {"$ref": "#/$defs/participant"},
            },
        },
        "positive_patterns": {"type": "array", "maxItems": 6, "items": {"$ref": "#/$defs/pattern"}},
        "problem_patterns": {"type": "array", "maxItems": 6, "items": {"$ref": "#/$defs/problem_pattern"}},
        "weak_reply_patterns": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "explanation", "severity", "anonymous_message_reference"],
                "properties": {
                    "category": {"type": "string", "enum": sorted(WEAK_REPLY_CATEGORIES)},
                    "explanation": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "anonymous_message_reference": {"type": "string"},
                },
            },
        },
        "advice": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["priority", "title", "explanation", "example"],
                "properties": {
                    "priority": {"type": "integer"},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "example": {"type": "string"},
                },
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "$defs": {
        "participant": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "observable_patterns", "strengths", "possible_improvements"],
            "properties": {
                "summary": {"type": "string"},
                "observable_patterns": {"type": "array", "items": {"type": "string"}},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "possible_improvements": {"type": "array", "items": {"type": "string"}},
            },
        },
        "pattern": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "explanation", "evidence_type"],
            "properties": {
                "title": {"type": "string"},
                "explanation": {"type": "string"},
                "evidence_type": {"type": "string", "enum": ["metric", "event", "message_pattern"]},
            },
        },
        "problem_pattern": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "explanation", "severity", "evidence_type"],
            "properties": {
                "title": {"type": "string"},
                "explanation": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                "evidence_type": {"type": "string", "enum": ["metric", "event", "message_pattern"]},
            },
        },
    },
}


async def run_ai_communication_analysis(
    settings: Settings,
    *,
    chat: dict[str, Any],
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
    period_label: str,
    client_factory: Callable[[Settings], Any] | None = None,
) -> AIAnalysisOutcome:
    if not settings.ai_enabled:
        raise AIAnalysisError("ai_disabled")
    if not settings.openai_api_key:
        raise AIAnalysisError("missing_api_key")
    if not settings.ai_model:
        raise AIAnalysisError("missing_model")
    bundle = build_ai_input_bundle(settings, chat=chat, messages=messages, events=events, period_label=period_label)
    if not bundle.payload["messages"]:
        raise AIAnalysisError("no_messages")
    client = client_factory(settings) if client_factory else default_openai_client(settings)
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(create_response, client, settings, bundle.payload),
            timeout=settings.ai_timeout_seconds,
        )
    except TimeoutError as exc:
        raise AIAnalysisError("timeout") from exc
    except Exception as exc:
        raise AIAnalysisError(ai_error_code(exc)) from exc
    result = validate_ai_result(
        extract_response_text(response),
        dimensions=bundle.payload.get("local_dimensions"),
        message_count=bundle.coverage.get("available_messages", 0),
        coverage=bundle.coverage,
    )
    return AIAnalysisOutcome(
        result=result,
        message_count_sent=bundle.message_count_sent,
        char_count_sent=bundle.char_count_sent,
        coverage=bundle.coverage,
        token_usage=response_usage(response),
        model_name=settings.ai_model,
    )


def default_openai_client(settings: Settings) -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise AIAnalysisError("openai_sdk_missing") from exc
    return OpenAI(api_key=settings.openai_api_key, timeout=settings.ai_timeout_seconds)


def create_response(client: Any, settings: Settings, payload: dict[str, Any]) -> Any:
    return client.responses.create(
        model=settings.ai_model,
        input=[
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "relchat_communication_analysis",
                "strict": True,
                "schema": COMMUNICATION_ANALYSIS_SCHEMA,
            }
        },
        max_output_tokens=2400,
    )


def system_prompt() -> str:
    return COMMUNICATION_ANALYSIS_SYSTEM_PROMPT


COMMUNICATION_ANALYSIS_SYSTEM_PROMPT = (
    "You create evidence-based communication analysis from anonymized Telegram message data. "
    "Analyze visible communication only. Do not diagnose personality, mental health, attachment style, or hidden feelings. "
    "Do not claim attraction, love, deliberate testing, manipulation, or loss of interest as fact. "
    "Use cautious language and distinguish observed facts from possible interpretations. "
    "Base conclusions on supplied local metrics, event summaries, deterministic dimensions, and selected anonymized messages. "
    "Do not invent numeric evidence and do not choose the final score. "
    "Never include Telegram identities, usernames, phone numbers, IDs, or private message quotes. "
    "Never advise manipulation, jealousy tactics, pressure, deliberate silence, or making someone chase. "
    "Return only schema-valid JSON."
)


def build_ai_input_bundle(
    settings: Settings,
    *,
    chat: dict[str, Any],
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
    period_label: str,
) -> AIInputBundle:
    ordered = [message for message in sorted(messages, key=lambda item: (item.timestamp, item.source_message_id)) if message.text or message.message_type]
    limited_by_message = select_representative_messages(ordered, events, max_messages=settings.ai_max_messages, chat_type=chat.get("chat_type"))
    char_count = 0
    sender_labels = sender_label_map(limited_by_message, chat_type=chat.get("chat_type"))
    selected_messages: list[Message] = []
    for message in reversed(limited_by_message):
        text = minimize_text(message.text or "")
        entry = {
            "sender": sender_labels.get(message.sender_id or "", "PARTICIPANT"),
            "timestamp": message.timestamp,
            "type": message.message_type,
            "text": text,
        }
        entry_length = len(json.dumps(entry, ensure_ascii=False))
        if char_count + entry_length > settings.ai_max_chars:
            break
        selected_messages.append(message)
        char_count += entry_length
    selected_messages.reverse()
    id_to_ref = {message.source_message_id: f"m{index + 1}" for index, message in enumerate(selected_messages)}
    rendered: list[dict[str, Any]] = []
    for index, message in enumerate(selected_messages, start=1):
        entry = {
            "ref": f"m{index}",
            "sender": sender_labels.get(message.sender_id or "", "PARTICIPANT"),
            "timestamp": message.timestamp,
            "type": message.message_type,
            "text": minimize_text(message.text or ""),
        }
        if message.reply_to_message_id in id_to_ref:
            entry["reply_to"] = id_to_ref[message.reply_to_message_id]
        rendered.append(entry)
    metrics = summarize(ordered, "conversation")
    dimensions = build_deterministic_dimensions(ordered, events, chat_type=safe_chat_type(chat.get("chat_type")))
    score = communication_score_from_dimensions(dimensions, message_count=len(ordered))
    metric_labels = {
        metric_sender_key(message): sender_labels.get(message.sender_id or "", "PARTICIPANT")
        for message in ordered
    }
    coverage = {
        "requested_period": period_label,
        "available_messages": len(ordered),
        "sent_messages": len(rendered),
        "char_count": char_count,
        "partial": len(rendered) < len(ordered),
        "local_metrics_cover_full_period": True,
        "ai_sample_strategy": "recent_messages_with_event_context",
        "limits": {"max_messages": settings.ai_max_messages, "max_chars": settings.ai_max_chars},
    }
    payload = {
        "task": "Communication analysis",
        "analysis_version": ANALYSIS_VERSION,
        "chat_type": safe_chat_type(chat.get("chat_type")),
        "period": period_label,
        "scoring_formula": score_formula_description(),
        "local_summary": local_summary(anonymize_metrics(metrics, metric_labels), events),
        "local_dimensions": dimensions,
        "deterministic_score": score,
        "coverage": coverage,
        "messages": rendered,
    }
    return AIInputBundle(payload=payload, message_count_sent=len(rendered), char_count_sent=char_count, coverage=coverage)


def select_representative_messages(
    ordered: Sequence[Message],
    events: Sequence[ConversationEvent],
    *,
    max_messages: int,
    chat_type: str | None,
) -> list[Message]:
    if max_messages <= 0:
        return []
    if len(ordered) <= max_messages:
        return list(ordered)
    by_id = {message.source_message_id: message for message in ordered}
    selected: dict[int, Message] = {}
    for event in events:
        for source_id in (event.source_message_id, event.related_message_id):
            if source_id in by_id:
                selected[source_id] = by_id[source_id]
    remaining = max_messages - len(selected)
    if remaining <= 0:
        return sorted(selected.values(), key=lambda item: (item.timestamp, item.source_message_id))[:max_messages]
    if chat_type == "one_to_one":
        recent = list(reversed(ordered))
        outgoing = [message for message in recent if message.is_outgoing and message.source_message_id not in selected]
        incoming = [message for message in recent if not message.is_outgoing and message.source_message_id not in selected]
        each_side = max(1, remaining // 2)
        for message in outgoing[:each_side] + incoming[:each_side]:
            selected[message.source_message_id] = message
        remaining = max_messages - len(selected)
    for message in reversed(ordered):
        if remaining <= 0:
            break
        if message.source_message_id in selected:
            continue
        selected[message.source_message_id] = message
        remaining -= 1
    return sorted(selected.values(), key=lambda item: (item.timestamp, item.source_message_id))[:max_messages]


def sender_label_map(messages: Sequence[Message], *, chat_type: str | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    other_index = 1
    for message in messages:
        sender_id = message.sender_id or ""
        if sender_id in labels:
            continue
        if chat_type == "one_to_one":
            labels[sender_id] = "YOU" if message.is_outgoing else "OTHER"
        else:
            labels[sender_id] = "YOU" if message.is_outgoing else f"PARTICIPANT_{other_index}"
            if not message.is_outgoing:
                other_index += 1
    return labels


def minimize_text(value: str) -> str:
    text = value.replace("\x00", "")
    text = BOT_TOKEN_RE.sub("[redacted bot token]", text)
    text = API_HASH_RE.sub("[redacted api hash]", text)
    text = PHONE_RE.sub("[redacted phone]", text)
    text = USERNAME_RE.sub("[redacted username]", text)
    text = SESSION_RE.sub("[redacted session]", text)
    return text[:2000]


def safe_chat_type(value: Any) -> str:
    return str(value) if value in {"one_to_one", "group", "channel"} else "unknown"


def metric_sender_key(message: Message) -> str:
    if message.sender_name:
        return message.sender_name
    if message.sender_id:
        return f"user:{message.sender_id}"
    return "unknown"


def anonymize_metrics(metrics: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    result = dict(metrics)
    result.pop("chat_id", None)
    result["message_count_by_sender"] = anonymize_keyed_dict(metrics.get("message_count_by_sender"), labels)
    initiation = dict(metrics.get("initiation_balance") or {})
    initiation["by_sender"] = anonymize_keyed_dict(initiation.get("by_sender"), labels)
    initiation["share"] = anonymize_keyed_dict(initiation.get("share"), labels)
    result["initiation_balance"] = initiation
    result["response_times"] = anonymize_keyed_dict(metrics.get("response_times"), labels)
    result["average_message_length"] = anonymize_keyed_dict(metrics.get("average_message_length"), labels)
    result["unanswered_questions"] = [
        {
            "timestamp": item.get("timestamp"),
            "sender": labels.get(str(item.get("sender") or ""), "Participant"),
        }
        for item in metrics.get("unanswered_questions") or []
        if isinstance(item, dict)
    ]
    return result


def anonymize_keyed_dict(value: Any, labels: dict[str, str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        result[labels.get(str(key), "Participant")] = item
    return result


def local_summary(metrics: dict[str, Any], events: Sequence[ConversationEvent]) -> dict[str, Any]:
    return {
        "message_count": metrics.get("message_count", 0),
        "initiation_balance": metrics.get("initiation_balance", {}),
        "response_times": metrics.get("response_times", {}),
        "average_message_length": metrics.get("average_message_length", {}),
        "unanswered_question_count": len(metrics.get("unanswered_questions") or []),
        "events": summarize_events(events),
    }


def build_deterministic_dimensions(
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
    *,
    chat_type: str = "one_to_one",
) -> dict[str, dict[str, Any]]:
    message_count = len(messages)
    metrics = summarize(messages, "conversation")
    event_counts = summarize_events(events)
    if chat_type != "one_to_one":
        return group_activity_dimensions(message_count, event_counts)

    outgoing_count = sum(1 for message in messages if message.is_outgoing)
    incoming_count = message_count - outgoing_count
    session_count = int((metrics.get("initiation_balance") or {}).get("session_count") or 0)
    outgoing_initiations = outgoing_session_starts(messages)
    response_rows = metrics.get("response_times") or {}
    response_counts = [int(row.get("count") or 0) for row in response_rows.values() if isinstance(row, dict)]
    reply_evidence = sum(response_counts)
    unanswered_count = len(metrics.get("unanswered_questions") or [])
    plan_count = int(event_counts.get("plan_candidate", 0) or 0)
    promise_count = int(event_counts.get("promise_candidate", 0) or 0)
    follow_up_count = int(event_counts.get("follow_up_candidate", 0) or 0)

    dimensions = {
        "reciprocity": dimension_row(
            score=balance_score(outgoing_count, incoming_count),
            evidence_count=message_count,
            explanation="Estimated from visible message participation between YOU and OTHER.",
            unavailable_reason="Not enough messages to compare participation." if message_count < 6 else None,
        ),
        "initiative_balance": dimension_row(
            score=balance_score(outgoing_initiations, max(0, session_count - outgoing_initiations)) if session_count >= 3 else None,
            evidence_count=session_count,
            explanation="Estimated from who starts visible conversation sessions.",
            unavailable_reason="Not enough conversation starts were detected." if session_count < 3 else None,
        ),
        "reply_consistency": dimension_row(
            score=min(10.0, 4.5 + min(reply_evidence, 10) * 0.45) if reply_evidence else None,
            evidence_count=reply_evidence,
            explanation="Estimated from visible reply opportunities and response timing.",
            unavailable_reason="Not enough reply pairs were detected." if reply_evidence < 2 else None,
        ),
        "reply_quality": dimension_row(
            score=max(0.0, min(10.0, 7.0 - unanswered_count * 0.8 + min(reply_evidence, 6) * 0.2)) if message_count >= 10 else None,
            evidence_count=max(reply_evidence, unanswered_count),
            explanation="Estimated from unanswered-question candidates and available reply opportunities.",
            unavailable_reason="Not enough messages for a stable reply-quality estimate." if message_count < 10 else None,
        ),
        "topic_continuation": dimension_row(
            score=min(10.0, 5.0 + min(session_count, 8) * 0.35) if session_count >= 2 else None,
            evidence_count=session_count,
            explanation="Estimated from repeated visible conversation sessions in the selected period.",
            unavailable_reason="Not enough conversation sessions were detected." if session_count < 2 else None,
        ),
        "question_engagement": dimension_row(
            score=max(0.0, 8.0 - unanswered_count * 1.2) if message_count >= 10 else None,
            evidence_count=unanswered_count,
            explanation="Estimated from unanswered-question candidates.",
            unavailable_reason="Not enough messages to assess question engagement." if message_count < 10 else None,
        ),
        "planning_cooperation": dimension_row(
            score=max(0.0, min(10.0, 5.5 + plan_count * 0.6 - follow_up_count * 0.4)) if plan_count or promise_count or follow_up_count else None,
            evidence_count=plan_count + promise_count + follow_up_count,
            explanation="Estimated from plan, promise, and follow-up candidates.",
            unavailable_reason="No plan or follow-up candidates were detected." if not (plan_count or promise_count or follow_up_count) else None,
        ),
        "emotional_acknowledgement": dimension_row(
            score=None,
            evidence_count=0,
            explanation="Local deterministic analysis does not yet measure emotional acknowledgement directly.",
            unavailable_reason="This dimension needs explicit text interpretation.",
        ),
        "respectfulness": dimension_row(
            score=7.0,
            evidence_count=message_count,
            explanation="Local deterministic analysis found no strong hostility signal in available rule-based events.",
            unavailable_reason=None if message_count >= 6 else "Not enough messages to assess respectfulness.",
        ),
        "sarcasm_intensity": dimension_row(
            score=0.0,
            evidence_count=0,
            explanation="No harmful sarcasm signal is inferred by local metrics alone.",
            unavailable_reason=None,
            risk=True,
        ),
        "pressure_risk": dimension_row(
            score=min(10.0, float(follow_up_count + promise_count) * 1.2),
            evidence_count=follow_up_count + promise_count,
            explanation="Estimated from follow-up and promise candidates. Higher values mean more visible pressure risk.",
            unavailable_reason=None,
            risk=True,
        ),
        "hostility": dimension_row(
            score=0.0,
            evidence_count=0,
            explanation="No hostility signal is inferred by local metrics alone.",
            unavailable_reason=None,
            risk=True,
        ),
        "dismissiveness": dimension_row(
            score=0.0,
            evidence_count=0,
            explanation="Dismissive wording is not inferred unless text interpretation is available.",
            unavailable_reason=None,
            risk=True,
        ),
        "unanswered_question_rate": dimension_row(
            score=min(10.0, unanswered_count * 2.0),
            evidence_count=unanswered_count,
            explanation="Risk estimate from unanswered-question candidates. Higher values mean more unresolved questions.",
            unavailable_reason=None,
            risk=True,
        ),
    }
    return dimensions


def group_activity_dimensions(message_count: int, event_counts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    follow_up_count = int(event_counts.get("follow_up_candidate", 0) or 0)
    unanswered_count = int(event_counts.get("unanswered_question", 0) or 0) + int(event_counts.get("question", 0) or 0)
    return {
        "reciprocity": dimension_row(
            score=None,
            evidence_count=message_count,
            explanation="One-to-one reciprocity is not meaningful for this chat type.",
            unavailable_reason="This is not a private one-to-one conversation.",
        ),
        "reply_quality": dimension_row(
            score=6.0 if message_count >= 20 else None,
            evidence_count=message_count,
            explanation="Estimated from group/channel activity volume only.",
            unavailable_reason="Not enough activity for a stable estimate." if message_count < 20 else None,
        ),
        "respectfulness": dimension_row(
            score=7.0 if message_count >= 6 else None,
            evidence_count=message_count,
            explanation="Local deterministic analysis found no strong hostility signal in available rule-based events.",
            unavailable_reason="Not enough messages to assess wording patterns." if message_count < 6 else None,
        ),
        "pressure_risk": dimension_row(
            score=min(10.0, follow_up_count * 1.2),
            evidence_count=follow_up_count,
            explanation="Estimated from visible follow-up candidates.",
            risk=True,
        ),
        "unanswered_question_rate": dimension_row(
            score=min(10.0, unanswered_count * 1.5),
            evidence_count=unanswered_count,
            explanation="Estimated from visible question and unanswered-question candidates.",
            risk=True,
        ),
    }


def dimension_row(
    *,
    score: float | None,
    evidence_count: int,
    explanation: str,
    unavailable_reason: str | None = None,
    risk: bool = False,
) -> dict[str, Any]:
    available = score is not None and not unavailable_reason
    return {
        "score": round(clamp_score(float(score)), 1) if score is not None else None,
        "confidence": evidence_confidence(evidence_count),
        "evidence_count": max(0, int(evidence_count)),
        "explanation": explanation,
        "unavailable_reason": unavailable_reason,
        "available": available,
        "risk": risk,
    }


def evidence_confidence(count: int) -> str:
    if count >= 30:
        return "high"
    if count >= 8:
        return "medium"
    return "low"


def balance_score(first_count: int, second_count: int) -> float | None:
    total = first_count + second_count
    if total < 6:
        return None
    share = max(first_count, second_count) / total
    return clamp_score(10.0 - max(0.0, share - 0.5) * 16.0)


def outgoing_session_starts(messages: Sequence[Message], *, gap_hours: int = 12) -> int:
    count = 0
    previous_time: datetime | None = None
    for message in messages:
        ts = parse_iso_datetime(message.timestamp)
        if previous_time is None or ts - previous_time > timedelta(hours=gap_hours):
            if message.is_outgoing:
                count += 1
        previous_time = ts
    return count


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def extract_response_text(response: Any) -> str:
    if getattr(response, "status", None) == "incomplete":
        raise AIAnalysisError("incomplete")
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                raise AIAnalysisError("content_refused")
            if getattr(content, "type", None) == "output_text":
                return str(getattr(content, "text", ""))
    raise AIAnalysisError("malformed_output")


def validate_ai_result(
    value: str | dict[str, Any],
    *,
    dimensions: dict[str, Any] | None = None,
    message_count: int = 0,
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        data = json.loads(value) if isinstance(value, str) else dict(value)
    except Exception as exc:
        raise AIAnalysisError("malformed_output") from exc
    if "overall_score" in data or "dimensions" in data:
        raise AIAnalysisError("model_score_not_allowed")
    required = {
        "summary",
        "conversation_state",
        "confidence",
        "participant_analysis",
        "positive_patterns",
        "problem_patterns",
        "weak_reply_patterns",
        "advice",
        "limitations",
    }
    missing = required - data.keys()
    if missing:
        raise AIAnalysisError("malformed_output")
    extra = set(data.keys()) - required
    if extra:
        raise AIAnalysisError("malformed_output")
    conversation_state = str(data.get("conversation_state") or "")
    if conversation_state not in CONVERSATION_STATES:
        raise AIAnalysisError("malformed_output")
    data["conversation_state"] = conversation_state
    confidence = str(data.get("confidence") or "low")
    data["confidence"] = confidence if confidence in CONFIDENCE_VALUES else "low"
    data["score_confidence"] = data["confidence"]
    data["participant_analysis"] = validate_participants(data.get("participant_analysis"))
    data["participants"] = participant_analysis_to_legacy(data["participant_analysis"])
    data["positive_patterns"] = validate_patterns(data.get("positive_patterns"), problem=False)
    data["problem_patterns"] = validate_patterns(data.get("problem_patterns"), problem=True)
    data["weak_reply_patterns"] = validate_weak_replies(data.get("weak_reply_patterns"))
    data["advice"] = validate_advice(data.get("advice"))
    data["summary"] = sanitize_ai_text(data.get("summary"), limit=900)
    data["limitations"] = string_list(data.get("limitations"), limit=6, text_limit=280)
    clean_dimensions = validate_dimensions(dimensions or {})
    score = communication_score_from_dimensions(clean_dimensions, message_count=message_count)
    data["dimensions"] = clean_dimensions
    data["overall_score"] = score["score"]
    data["score_state"] = score
    data["coverage"] = safe_coverage(coverage or {})
    data["analysis_version"] = ANALYSIS_VERSION
    if contains_forbidden_claims(data):
        raise AIAnalysisError("unsafe_output")
    return data


def validate_dimensions(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, row in value.items():
        key = str(key)
        if key == "unresolved_question_rate":
            key = "unanswered_question_rate"
        if key not in DIMENSION_IDS and key not in {"hostility", "dismissiveness", "unanswered_question_rate"}:
            continue
        if not isinstance(row, dict):
            continue
        score_value = row.get("score")
        score: float | None
        try:
            score = clamp_score(float(score_value)) if score_value is not None else None
        except (TypeError, ValueError):
            score = None
        confidence = str(row.get("confidence") or "low")
        try:
            evidence_count = max(0, int(row.get("evidence_count") or 0))
        except (TypeError, ValueError):
            evidence_count = 0
        unavailable = sanitize_ai_text(row.get("unavailable_reason"), limit=220) or None
        available = bool(row.get("available", score is not None and not unavailable)) and score is not None and not unavailable
        result[key] = {
            "score": round(score, 1) if score is not None else None,
            "confidence": confidence if confidence in CONFIDENCE_VALUES else "low",
            "evidence_count": evidence_count,
            "explanation": sanitize_ai_text(row.get("explanation"), limit=500),
            "unavailable_reason": unavailable,
            "available": available,
            "risk": bool(row.get("risk")) or key in RISK_DIMENSIONS,
        }
    return result


def validate_participants(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "you": participant_block(value.get("you")),
        "other": participant_block(value.get("other")),
    }


def participant_block(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "summary": sanitize_ai_text(row.get("summary"), limit=320),
        "observable_patterns": string_list(row.get("observable_patterns") or row.get("communication_style"), limit=6),
        "strengths": string_list(row.get("strengths"), limit=4),
        "possible_improvements": string_list(row.get("possible_improvements") or row.get("problems"), limit=4),
    }


def participant_analysis_to_legacy(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "you": {
            "communication_style": value.get("you", {}).get("observable_patterns", []),
            "strengths": value.get("you", {}).get("strengths", []),
            "problems": value.get("you", {}).get("possible_improvements", []),
        },
        "other": {
            "communication_style": value.get("other", {}).get("observable_patterns", []),
            "strengths": value.get("other", {}).get("strengths", []),
            "problems": value.get("other", {}).get("possible_improvements", []),
        },
    }


def validate_patterns(value: Any, *, problem: bool) -> list[dict[str, str]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, str]] = []
    for row in rows[:6]:
        if isinstance(row, str):
            item = {
                "title": sanitize_ai_text(row, limit=120),
                "explanation": "",
                "evidence_type": "metric",
            }
        elif isinstance(row, dict):
            evidence_type = str(row.get("evidence_type") or "metric")
            if evidence_type not in {"metric", "event", "message_pattern"}:
                raise AIAnalysisError("malformed_output")
            item = {
                "title": sanitize_ai_text(row.get("title"), limit=120),
                "explanation": sanitize_ai_text(row.get("explanation"), limit=420),
                "evidence_type": evidence_type,
            }
            if problem:
                severity = str(row.get("severity") or "low")
                if severity not in SEVERITY_VALUES:
                    raise AIAnalysisError("malformed_output")
                item["severity"] = severity
        else:
            continue
        if item["title"]:
            result.append(item)
    return result


def validate_weak_replies(value: Any) -> list[dict[str, str]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "")
        if category == "sarcasm":
            category = "sarcasm_instead_of_answer"
        if category not in WEAK_REPLY_CATEGORIES:
            raise AIAnalysisError("malformed_output")
        severity = str(row.get("severity") or "low")
        if severity not in SEVERITY_VALUES:
            raise AIAnalysisError("malformed_output")
        result.append(
            {
                "category": category,
                "explanation": sanitize_ai_text(row.get("explanation"), limit=600),
                "severity": severity,
                "anonymous_message_reference": sanitize_ai_text(row.get("anonymous_message_reference") or row.get("message_reference"), limit=40),
            }
        )
    return result


def validate_advice(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for index, row in enumerate(rows[:3], start=1):
        if not isinstance(row, dict):
            continue
        try:
            priority = int(row.get("priority") or index)
        except (TypeError, ValueError):
            priority = index
        result.append(
            {
                "priority": priority,
                "title": sanitize_ai_text(row.get("title"), limit=120),
                "explanation": sanitize_ai_text(row.get("explanation"), limit=600),
                "example": sanitize_ai_text(row.get("example"), limit=240),
            }
        )
    result = sorted(result, key=lambda item: int(item.get("priority") or 99))
    if not result:
        raise AIAnalysisError("missing_advice")
    return result[:3]


def string_list(value: Any, *, limit: int = 8, text_limit: int = 240) -> list[str]:
    rows = value if isinstance(value, list) else []
    return [sanitize_ai_text(item, limit=text_limit) for item in rows[:limit] if str(item).strip()]


def safe_coverage(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("requested_period", "available_messages", "sent_messages", "char_count", "partial", "local_metrics_cover_full_period", "ai_sample_strategy"):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[key] = item
    limits = value.get("limits")
    if isinstance(limits, dict):
        result["limits"] = {str(key): limits[key] for key in limits if isinstance(limits[key], (str, int, float, bool))}
    return result


def sanitize_ai_output(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_ai_text(value, limit=1200)
    if isinstance(value, list):
        return [sanitize_ai_text(item, limit=500) for item in value[:12] if str(item).strip()]
    return value


def sanitize_ai_text(value: Any, *, limit: int) -> str:
    return minimize_text(str(value or ""))[:limit]


def contains_forbidden_claims(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).casefold()
    return any(term in text for term in FORBIDDEN_OUTPUT_TERMS)


def derive_overall_score(dimensions: dict[str, dict[str, Any]]) -> float:
    score = communication_score_from_dimensions(dimensions, message_count=30)
    if score["score"] is None:
        raise AIAnalysisError("missing_dimensions")
    return float(score["score"])


def communication_score_from_dimensions(dimensions: dict[str, dict[str, Any]], *, message_count: int) -> dict[str, Any]:
    if message_count < 10:
        return {
            "score": None,
            "confidence": "low",
            "insufficient_data": True,
            "explanation": "Not enough messages for a stable communication score.",
            "available_positive_weight": 0.0,
        }
    positive = weighted_average(dimensions, POSITIVE_DIMENSIONS)
    positive_weight = available_weight(dimensions, POSITIVE_DIMENSIONS)
    if positive is None or positive_weight < 0.35:
        return {
            "score": None,
            "confidence": "low",
            "insufficient_data": True,
            "explanation": "Too few supported communication dimensions are available.",
            "available_positive_weight": round(positive_weight, 3),
        }
    risk = weighted_average(dimensions, RISK_DIMENSIONS) or 0.0
    score = round(clamp_score(positive - risk * 0.45), 1)
    evidence_count = sum(int(row.get("evidence_count") or 0) for row in dimensions.values() if isinstance(row, dict))
    return {
        "score": score,
        "confidence": evidence_confidence(min(message_count, evidence_count)),
        "insufficient_data": False,
        "explanation": score_formula_description(),
        "available_positive_weight": round(positive_weight, 3),
        "risk_penalty": round(risk * 0.45, 2),
    }


def weighted_average(dimensions: dict[str, dict[str, Any]], weights: dict[str, float]) -> float | None:
    total = 0.0
    weight_total = 0.0
    for key, weight in weights.items():
        if key not in dimensions:
            continue
        row = dimensions[key]
        if not isinstance(row, dict) or row.get("score") is None or row.get("available") is False:
            continue
        total += float(row["score"]) * weight
        weight_total += weight
    if weight_total <= 0:
        return None
    return total / weight_total


def available_weight(dimensions: dict[str, dict[str, Any]], weights: dict[str, float]) -> float:
    return sum(
        weight
        for key, weight in weights.items()
        if key in dimensions and isinstance(dimensions[key], dict) and dimensions[key].get("score") is not None and dimensions[key].get("available") is not False
    )


def clamp_score(value: float) -> float:
    return max(0.0, min(10.0, value))


def score_formula_description() -> str:
    return (
        "Overall score = weighted positive communication dimensions minus 45% of weighted risk dimensions, clamped to 0-10. "
        "It describes visible communication quality only, not feelings, compatibility, truthfulness, or mental health."
    )


def local_fallback_analysis(
    *,
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
    period_label: str,
    chat_type: str = "one_to_one",
) -> dict[str, Any]:
    metrics = summarize(messages, "chat")
    event_counts = summarize_events(events)
    message_count = int(metrics.get("message_count") or 0)
    unanswered = len(metrics.get("unanswered_questions") or [])
    dimensions = build_deterministic_dimensions(messages, events, chat_type=chat_type)
    confidence = "low" if message_count < 30 else "medium"
    follow_up_count = int(event_counts.get("follow_up_candidate", 0) or 0)
    plan_count = int(event_counts.get("plan_candidate", 0) or 0)
    positive_patterns = local_positive_patterns(message_count, metrics, chat_type)
    problem_patterns = local_problem_patterns(unanswered, follow_up_count, chat_type)
    result = {
        "summary": local_summary_sentence(chat_type, message_count, unanswered),
        "conversation_state": "needs_follow_up" if unanswered or follow_up_count else ("casual" if message_count >= 10 else "insufficient_data"),
        "confidence": confidence,
        "participant_analysis": {
            "you": {
                "summary": local_participant_summary(messages, outgoing=True),
                "observable_patterns": local_participant_patterns(messages, outgoing=True),
                "strengths": ["Keeps visible conversation activity available for analysis."] if message_count else [],
                "possible_improvements": ["Ask one clear question at a time when you need a direct answer."] if unanswered else [],
            },
            "other": {
                "summary": local_participant_summary(messages, outgoing=False),
                "observable_patterns": local_participant_patterns(messages, outgoing=False),
                "strengths": ["Replies appear in the selected period."] if any(not message.is_outgoing for message in messages) else [],
                "possible_improvements": ["Some visible questions may need clearer follow-up."] if unanswered else [],
            },
        },
        "positive_patterns": positive_patterns,
        "problem_patterns": problem_patterns,
        "weak_reply_patterns": local_weak_reply_patterns(unanswered),
        "advice": local_advice(unanswered=unanswered, follow_up_count=follow_up_count, plan_count=plan_count),
        "limitations": [
            f"Used local deterministic metrics for {period_label}.",
            "No AI text interpretation was used.",
        ],
    }
    coverage = {
        "requested_period": period_label,
        "available_messages": message_count,
        "sent_messages": 0,
        "char_count": 0,
        "partial": False,
        "local_metrics_cover_full_period": True,
    }
    return validate_ai_result(result, dimensions=dimensions, message_count=message_count, coverage=coverage)


def local_summary_sentence(chat_type: str, message_count: int, unanswered: int) -> str:
    if message_count <= 0:
        return "There is not enough visible activity in the selected period."
    if chat_type == "group":
        return "Group activity was summarized from local message counts, questions, plans, and follow-up candidates."
    if chat_type == "channel":
        return "Channel activity was summarized from local posting cadence and quiet periods."
    if unanswered:
        return "The conversation has visible activity, with some questions or follow-ups that may need attention."
    return "The conversation has visible activity and no major local follow-up count in this period."


def local_positive_patterns(message_count: int, metrics: dict[str, Any], chat_type: str) -> list[dict[str, str]]:
    if message_count <= 0:
        return []
    if chat_type in {"group", "channel"}:
        return [{"title": "Visible activity", "explanation": "The selected period contains enough local activity to summarize basic patterns.", "evidence_type": "metric"}]
    senders = metrics.get("message_count_by_sender") or {}
    title = "Both sides participated" if len([value for value in senders.values() if value]) >= 2 else "Visible conversation activity"
    return [{"title": title, "explanation": "Local metrics found message activity in the selected period.", "evidence_type": "metric"}]


def local_problem_patterns(unanswered: int, follow_up_count: int, chat_type: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if unanswered:
        rows.append(
            {
                "title": "Unanswered questions",
                "explanation": f"{unanswered} question candidate(s) may still need a response.",
                "severity": "medium" if unanswered >= 3 else "low",
                "evidence_type": "event",
            }
        )
    if follow_up_count:
        rows.append(
            {
                "title": "Open follow-ups",
                "explanation": f"{follow_up_count} follow-up candidate(s) may need attention.",
                "severity": "medium" if follow_up_count >= 3 else "low",
                "evidence_type": "event",
            }
        )
    if chat_type != "one_to_one":
        return rows[:2]
    return rows


def local_weak_reply_patterns(unanswered: int) -> list[dict[str, str]]:
    if not unanswered:
        return []
    return [
        {
            "category": "ignored_question",
            "explanation": "At least one direct question candidate did not receive a visible response inside the local response window.",
            "severity": "medium" if unanswered >= 3 else "low",
            "anonymous_message_reference": "local-question-candidate",
        }
    ]


def local_advice(*, unanswered: int, follow_up_count: int, plan_count: int) -> list[dict[str, Any]]:
    rows = []
    if unanswered:
        rows.append(
            {
                "priority": 1,
                "title": "Ask one clear question",
                "explanation": "A single specific question is easier to answer and easier to follow up on.",
                "example": "Could you confirm the plan for Friday?",
            }
        )
    if follow_up_count or plan_count:
        rows.append(
            {
                "priority": len(rows) + 1,
                "title": "Clarify the next step",
                "explanation": "When plans or promises are open, a direct check-in is clearer than repeated reminders.",
                "example": "Is this still convenient for tomorrow?",
            }
        )
    if not rows:
        rows.append(
            {
                "priority": 1,
                "title": "Keep the next message simple",
                "explanation": "Continue with one clear topic so the other participant can respond without extra pressure.",
                "example": "How does Thursday evening work for you?",
            }
        )
    return rows[:3]


def local_participant_summary(messages: Sequence[Message], *, outgoing: bool) -> str:
    count = sum(1 for message in messages if message.is_outgoing is outgoing)
    if not messages:
        return "Not enough visible messages to summarize."
    if count <= 0:
        return "No visible messages from this side in the selected period."
    return f"{count} visible message(s) in the selected period."


def local_participant_patterns(messages: Sequence[Message], *, outgoing: bool) -> list[str]:
    count = sum(1 for message in messages if message.is_outgoing is outgoing)
    if count <= 0:
        return ["No visible messages from this side in the selected period."]
    total = max(1, len(messages))
    share = count / total
    if share >= 0.65:
        return ["Carries most visible message volume in this period."]
    if share <= 0.35:
        return ["Participates with fewer visible messages in this period."]
    return ["Participates at a similar visible message volume."]


def response_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {str(key): usage[key] for key in usage.keys() if isinstance(usage.get(key), (int, float, str, bool))}
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            result[key] = value
    return result


def ai_error_code(exc: Exception) -> str:
    if isinstance(exc, AIAnalysisError):
        return exc.code
    name = exc.__class__.__name__.lower()
    text = str(exc).casefold()
    if "rate" in name or "rate" in text:
        return "rate_limited"
    if "auth" in name or "unauthorized" in text or "api key" in text:
        return "invalid_api_key"
    if "timeout" in name or "timed out" in text:
        return "timeout"
    if "model" in text and ("not" in text or "unavailable" in text):
        return "model_unavailable"
    if "network" in text or "connection" in text:
        return "network_error"
    return "api_error"
