from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from relchat.analytics.metrics import summarize
from relchat.config import Settings
from relchat.core.models import ConversationEvent, Message
from relchat.events.extractor import summarize_events


CONSENT_VERSION = "v1"
POSITIVE_DIMENSIONS = {
    "reciprocity": 0.18,
    "initiative_balance": 0.12,
    "reply_quality": 0.17,
    "respectfulness": 0.18,
    "topic_continuation": 0.12,
    "support_attention": 0.12,
    "planning_cooperation": 0.11,
}
RISK_DIMENSIONS = {
    "pressure_risk": 0.20,
    "hostility": 0.20,
    "dismissiveness": 0.15,
    "unresolved_question_rate": 0.15,
    "sarcasm_intensity": 0.10,
}
DIMENSION_IDS = tuple(POSITIVE_DIMENSIONS.keys() | RISK_DIMENSIONS.keys())
CONFIDENCE_VALUES = {"low", "medium", "high"}
WEAK_REPLY_CATEGORIES = {
    "ignored_question",
    "abrupt_reply",
    "sarcasm",
    "dismissive",
    "topic_switch",
    "low_effort",
    "hostile",
    "pressure",
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
    "make them chase",
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
        "overall_score",
        "score_confidence",
        "participants",
        "dimensions",
        "positive_patterns",
        "problem_patterns",
        "weak_reply_patterns",
        "advice",
        "limitations",
    ],
    "properties": {
        "summary": {"type": "string"},
        "overall_score": {"type": "number", "minimum": 0, "maximum": 10},
        "score_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "participants": {
            "type": "object",
            "additionalProperties": False,
            "required": ["you", "other"],
            "properties": {
                "you": {"$ref": "#/$defs/participant"},
                "other": {"$ref": "#/$defs/participant"},
            },
        },
        "dimensions": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {"$ref": "#/$defs/dimension"},
        },
        "positive_patterns": {"type": "array", "items": {"type": "string"}},
        "problem_patterns": {"type": "array", "items": {"type": "string"}},
        "weak_reply_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "explanation", "severity", "message_reference"],
                "properties": {
                    "category": {"type": "string", "enum": sorted(WEAK_REPLY_CATEGORIES)},
                    "explanation": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "message_reference": {"type": "string"},
                },
            },
        },
        "advice": {
            "type": "array",
            "maxItems": 5,
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
            "required": ["communication_style", "strengths", "problems"],
            "properties": {
                "communication_style": {"type": "array", "items": {"type": "string"}},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "problems": {"type": "array", "items": {"type": "string"}},
            },
        },
        "dimension": {
            "type": "object",
            "additionalProperties": False,
            "required": ["score", "explanation"],
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 10},
                "explanation": {"type": "string"},
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
    result = validate_ai_result(extract_response_text(response))
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
    return (
        "You create evidence-based communication analysis from anonymized message data. "
        "Describe only visible messaging behavior. Do not infer feelings, attraction, love, hidden motives, diagnoses, "
        "attachment styles, or mental health. Do not provide manipulation tactics. Return only schema-valid JSON. "
        "Do not quote private message text; use anonymous message references."
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
    limited_by_message = ordered[-settings.ai_max_messages :]
    char_count = 0
    sender_labels = sender_label_map(limited_by_message, chat_type=chat.get("chat_type"))
    selected_messages: list[Message] = []
    for message in reversed(limited_by_message):
        text = minimize_text(message.text or "")
        entry = {
            "sender": sender_labels.get(message.sender_id or "", "Other person"),
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
            "sender": sender_labels.get(message.sender_id or "", "Other person"),
            "timestamp": message.timestamp,
            "type": message.message_type,
            "text": minimize_text(message.text or ""),
        }
        if message.reply_to_message_id in id_to_ref:
            entry["reply_to"] = id_to_ref[message.reply_to_message_id]
        rendered.append(entry)
    metrics = summarize(limited_by_message, "conversation")
    metric_labels = {
        metric_sender_key(message): sender_labels.get(message.sender_id or "", "Other person")
        for message in limited_by_message
    }
    coverage = {
        "requested_period": period_label,
        "available_messages": len(ordered),
        "sent_messages": len(rendered),
        "char_count": char_count,
        "partial": len(rendered) < len(ordered),
        "limits": {"max_messages": settings.ai_max_messages, "max_chars": settings.ai_max_chars},
    }
    payload = {
        "task": "Communication analysis",
        "chat_type": safe_chat_type(chat.get("chat_type")),
        "period": period_label,
        "scoring_formula": score_formula_description(),
        "local_summary": local_summary(anonymize_metrics(metrics, metric_labels), events),
        "coverage": coverage,
        "messages": rendered,
    }
    return AIInputBundle(payload=payload, message_count_sent=len(rendered), char_count_sent=char_count, coverage=coverage)


def sender_label_map(messages: Sequence[Message], *, chat_type: str | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    other_index = 1
    for message in messages:
        sender_id = message.sender_id or ""
        if sender_id in labels:
            continue
        if chat_type == "one_to_one":
            labels[sender_id] = "You" if message.is_outgoing else "Other person"
        else:
            labels[sender_id] = "You" if message.is_outgoing else f"Participant {other_index}"
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


def validate_ai_result(value: str | dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(value) if isinstance(value, str) else dict(value)
    except Exception as exc:
        raise AIAnalysisError("malformed_output") from exc
    required = {"summary", "score_confidence", "participants", "dimensions", "positive_patterns", "problem_patterns", "weak_reply_patterns", "advice", "limitations"}
    missing = required - data.keys()
    if missing:
        raise AIAnalysisError("malformed_output")
    dimensions = validate_dimensions(data.get("dimensions"))
    data["overall_score"] = derive_overall_score(dimensions)
    confidence = str(data.get("score_confidence") or "low")
    data["score_confidence"] = confidence if confidence in CONFIDENCE_VALUES else "low"
    data["participants"] = validate_participants(data.get("participants"))
    data["weak_reply_patterns"] = validate_weak_replies(data.get("weak_reply_patterns"))
    data["advice"] = validate_advice(data.get("advice"))
    for key in ("summary", "positive_patterns", "problem_patterns", "limitations"):
        data[key] = sanitize_ai_output(data.get(key))
    if contains_forbidden_claims(data):
        raise AIAnalysisError("unsafe_output")
    return data


def validate_dimensions(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        raise AIAnalysisError("missing_dimensions")
    result: dict[str, dict[str, Any]] = {}
    for key, row in value.items():
        if not isinstance(row, dict):
            continue
        try:
            score = clamp_score(float(row.get("score")))
        except (TypeError, ValueError):
            continue
        result[str(key)] = {"score": score, "explanation": sanitize_ai_text(row.get("explanation"), limit=600)}
    if not result:
        raise AIAnalysisError("missing_dimensions")
    return result


def validate_participants(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "you": participant_block(value.get("you")),
        "other": participant_block(value.get("other")),
    }


def participant_block(value: Any) -> dict[str, list[str]]:
    row = value if isinstance(value, dict) else {}
    return {
        "communication_style": string_list(row.get("communication_style")),
        "strengths": string_list(row.get("strengths")),
        "problems": string_list(row.get("problems")),
    }


def validate_weak_replies(value: Any) -> list[dict[str, str]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "")
        severity = str(row.get("severity") or "low")
        result.append(
            {
                "category": category if category in WEAK_REPLY_CATEGORIES else "low_effort",
                "explanation": sanitize_ai_text(row.get("explanation"), limit=600),
                "severity": severity if severity in SEVERITY_VALUES else "low",
                "message_reference": sanitize_ai_text(row.get("message_reference"), limit=40),
            }
        )
    return result


def validate_advice(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for index, row in enumerate(rows[:5], start=1):
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
    return sorted(result, key=lambda item: int(item.get("priority") or 99))


def string_list(value: Any, *, limit: int = 8) -> list[str]:
    rows = value if isinstance(value, list) else []
    return [sanitize_ai_text(item, limit=240) for item in rows[:limit] if str(item).strip()]


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
    if not dimensions:
        raise AIAnalysisError("missing_dimensions")
    positive = weighted_average(dimensions, POSITIVE_DIMENSIONS)
    risk = weighted_average(dimensions, RISK_DIMENSIONS) or 0.0
    if positive is None:
        positive = 10.0 - risk
    return round(clamp_score(positive - risk * 0.45), 1)


def weighted_average(dimensions: dict[str, dict[str, Any]], weights: dict[str, float]) -> float | None:
    total = 0.0
    weight_total = 0.0
    for key, weight in weights.items():
        if key not in dimensions:
            continue
        total += float(dimensions[key]["score"]) * weight
        weight_total += weight
    if weight_total <= 0:
        return None
    return total / weight_total


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
    reply_counts = sum(int(row.get("count") or 0) for row in (metrics.get("response_times") or {}).values())
    dimensions = {
        "reciprocity": {"score": 5.0 if message_count < 10 else 6.0, "explanation": "Estimated from local message balance."},
        "reply_quality": {"score": 4.0 if reply_counts < 3 else 6.0, "explanation": "Estimated from local reply timing and reply opportunities."},
        "respectfulness": {"score": 6.0, "explanation": "Local deterministic analysis does not detect strong disrespect signals."},
        "unresolved_question_rate": {"score": min(10.0, unanswered * 2.0), "explanation": "Estimated from unanswered-question candidates."},
        "pressure_risk": {"score": min(10.0, float(event_counts.get("promise_candidate", 0) + event_counts.get("follow_up_candidate", 0))), "explanation": "Estimated from follow-up and promise candidates."},
    }
    confidence = "low" if message_count < 30 else "medium"
    result = {
        "summary": local_summary_sentence(chat_type, message_count, unanswered),
        "overall_score": 0.0,
        "score_confidence": confidence,
        "participants": {
            "you": {"communication_style": ["Visible local patterns only"], "strengths": [], "problems": []},
            "other": {"communication_style": ["Visible local patterns only"], "strengths": [], "problems": []},
        },
        "dimensions": dimensions,
        "positive_patterns": ["Local metrics found enough activity to summarize." if message_count else "No analyzed messages."],
        "problem_patterns": [f"{unanswered} unanswered question candidates."] if unanswered else [],
        "weak_reply_patterns": [],
        "advice": [
            {
                "priority": 1,
                "title": "Ask one clear question at a time",
                "explanation": "This keeps the next response easier to give and easier to evaluate.",
                "example": "Could you confirm the plan for Friday?",
            }
        ],
        "limitations": [f"Used local deterministic metrics for {period_label}.", "No AI text analysis was used."],
    }
    return validate_ai_result(result)


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
