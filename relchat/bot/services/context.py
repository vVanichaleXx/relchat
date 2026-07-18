from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from relchat.bot.localization import t
from relchat.core.models import Message


ANALYSIS_FRAMEWORK_VERSION = "context_aware_v1"
CONTEXT_CATEGORIES = {
    "romantic",
    "friendship",
    "family",
    "work",
    "customer_or_service",
    "group_social",
    "channel_or_broadcast",
    "mixed",
    "unknown",
}
CONFIDENCE_VALUES = {"low", "medium", "high"}
USER_CONTEXT_OPTIONS = {
    "romantic": "romantic",
    "friendship": "friendship",
    "family": "family",
    "work": "work",
    "other": "unknown",
    "unknown": "unknown",
}

KEYWORDS = {
    "romantic": {
        "date",
        "dating",
        "kiss",
        "miss you",
        "love you",
        "sweetheart",
        "darling",
        "babe",
        "romantic",
        "свидание",
        "целую",
        "поцелуй",
        "скучаю",
        "люблю",
        "милый",
        "милая",
        "романтик",
    },
    "friendship": {
        "friend",
        "friends",
        "buddy",
        "hang out",
        "classmate",
        "party",
        "weekend",
        "друг",
        "друзья",
        "подруга",
        "приятель",
        "однокласс",
        "погулять",
        "вечерин",
    },
    "family": {
        "mom",
        "mother",
        "dad",
        "father",
        "sister",
        "brother",
        "family",
        "daughter",
        "son",
        "grandma",
        "grandpa",
        "мама",
        "папа",
        "мать",
        "отец",
        "сестра",
        "брат",
        "семья",
        "сын",
        "дочь",
        "бабушка",
        "дедушка",
    },
    "work": {
        "work",
        "project",
        "deadline",
        "meeting",
        "task",
        "client",
        "sprint",
        "ticket",
        "deploy",
        "invoice",
        "contract",
        "manager",
        "team",
        "работа",
        "проект",
        "дедлайн",
        "встреча",
        "задача",
        "спринт",
        "тикет",
        "релиз",
        "счет",
        "договор",
        "команда",
    },
    "customer_or_service": {
        "support",
        "order",
        "delivery",
        "refund",
        "service",
        "subscription",
        "booking",
        "reservation",
        "warranty",
        "complaint",
        "поддержка",
        "заказ",
        "доставка",
        "возврат",
        "сервис",
        "подписка",
        "бронь",
        "гарантия",
        "жалоба",
    },
}


@dataclass(frozen=True)
class ContextClassification:
    category: str
    confidence: str
    evidence_types: tuple[str, ...]
    source: str
    user_confirmed: bool = False
    classified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "evidence_types": list(self.evidence_types),
            "source": self.source,
            "user_confirmed": self.user_confirmed,
            "classified_at": self.classified_at,
        }


def classify_context(
    *,
    chat: dict[str, Any] | None,
    messages: list[Message] | tuple[Message, ...] = (),
    saved: dict[str, Any] | None = None,
) -> ContextClassification:
    chat = chat or {}
    confirmed = confirmed_context_from_chat(chat) or confirmed_context_from_saved(saved)
    if confirmed and confirmed.user_confirmed:
        return confirmed

    chat_type = str(chat.get("chat_type") or "")
    if chat_type == "channel":
        return ContextClassification(
            category="channel_or_broadcast",
            confidence="high",
            evidence_types=("chat_type",),
            source="automatic",
            classified_at=now_iso(),
        )
    if chat_type == "group":
        return ContextClassification(
            category="group_social",
            confidence="medium",
            evidence_types=("chat_type",),
            source="automatic",
            classified_at=now_iso(),
        )

    scores: dict[str, int] = {category: 0 for category in KEYWORDS}
    evidence: set[str] = set()
    title = str(chat.get("title") or chat.get("display_title") or chat.get("local_title") or "")
    apply_text_signals(title, scores, evidence, evidence_type="title")
    for message in representative_text_messages(messages):
        apply_text_signals(message.text or "", scores, evidence, evidence_type="message_topic_signal")

    if confirmed and confirmed.category in CONTEXT_CATEGORIES:
        scores[confirmed.category] = scores.get(confirmed.category, 0) + 2
        evidence.add("saved_category")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_category, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    if top_score <= 0:
        return ContextClassification(
            category="unknown",
            confidence="low",
            evidence_types=tuple(sorted(evidence)) or ("insufficient_signals",),
            source="automatic",
            classified_at=now_iso(),
        )
    if second_score and top_score == second_score:
        return ContextClassification(
            category="mixed",
            confidence="low",
            evidence_types=tuple(sorted(evidence)),
            source="automatic",
            classified_at=now_iso(),
        )
    confidence = "high" if top_score >= 4 and top_score - second_score >= 2 else ("medium" if top_score >= 2 else "low")
    return ContextClassification(
        category=top_category,
        confidence=confidence,
        evidence_types=tuple(sorted(evidence)) or ("message_topic_signal",),
        source="automatic",
        classified_at=now_iso(),
    )


def confirmed_context_from_chat(chat: dict[str, Any] | None) -> ContextClassification | None:
    if not isinstance(chat, dict):
        return None
    category = normalize_context_category(chat.get("confirmed_context_category") or chat.get("context_category"))
    source = str(chat.get("context_classification_source") or chat.get("context_source") or "")
    if not category:
        return None
    confidence = normalize_confidence(chat.get("context_classification_confidence") or chat.get("context_confidence"), fallback="high" if source == "user_confirmed" else "medium")
    evidence = chat.get("context_classification_evidence") or chat.get("context_evidence_types") or []
    return ContextClassification(
        category=category,
        confidence=confidence,
        evidence_types=tuple(str(item) for item in evidence if str(item).strip()) or ("saved_category",),
        source=source or "saved",
        user_confirmed=source == "user_confirmed",
        classified_at=chat.get("context_classification_at"),
    )


def confirmed_context_from_saved(saved: dict[str, Any] | None) -> ContextClassification | None:
    if not isinstance(saved, dict):
        return None
    category = normalize_context_category(saved.get("category"))
    if not category:
        return None
    source = str(saved.get("source") or "")
    return ContextClassification(
        category=category,
        confidence=normalize_confidence(saved.get("confidence"), fallback="high" if source == "user_confirmed" else "medium"),
        evidence_types=tuple(str(item) for item in (saved.get("evidence_types") or []) if str(item).strip()) or ("saved_category",),
        source=source or "saved",
        user_confirmed=bool(saved.get("user_confirmed")) or source == "user_confirmed",
        classified_at=saved.get("classified_at"),
    )


def context_from_dict(value: dict[str, Any] | None) -> ContextClassification:
    if not isinstance(value, dict):
        return ContextClassification("unknown", "low", ("insufficient_signals",), "automatic", classified_at=now_iso())
    return ContextClassification(
        category=normalize_context_category(value.get("category")) or "unknown",
        confidence=normalize_confidence(value.get("confidence")),
        evidence_types=tuple(str(item) for item in (value.get("evidence_types") or []) if str(item).strip()) or ("insufficient_signals",),
        source=str(value.get("source") or "automatic"),
        user_confirmed=bool(value.get("user_confirmed")) or value.get("source") == "user_confirmed",
        classified_at=value.get("classified_at"),
    )


def normalize_context_category(value: Any) -> str | None:
    text = str(value or "")
    if text in USER_CONTEXT_OPTIONS:
        text = USER_CONTEXT_OPTIONS[text]
    return text if text in CONTEXT_CATEGORIES else None


def normalize_confidence(value: Any, *, fallback: str = "low") -> str:
    text = str(value or fallback)
    return text if text in CONFIDENCE_VALUES else fallback


def apply_text_signals(text: str, scores: dict[str, int], evidence: set[str], *, evidence_type: str) -> None:
    normalized = f" {text.casefold()} "
    for category, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in normalized:
                scores[category] = scores.get(category, 0) + 1
                evidence.add(evidence_type)
                break


def representative_text_messages(messages: list[Message] | tuple[Message, ...], *, limit: int = 80) -> list[Message]:
    if len(messages) <= limit:
        return [message for message in messages if message.text]
    recent = [message for message in messages[-limit:] if message.text]
    if not recent:
        return []
    outgoing = [message for message in reversed(recent) if message.is_outgoing][: limit // 2]
    incoming = [message for message in reversed(recent) if not message.is_outgoing][: limit // 2]
    selected = {message.source_message_id: message for message in outgoing + incoming}
    return sorted(selected.values(), key=lambda message: (message.timestamp, message.source_message_id))


def context_label(category: str | None, *, language: str) -> str:
    normalized = normalize_context_category(category) or "unknown"
    return t(language, f"context_{normalized}")


def context_score_label(category: str | None, *, language: str) -> str:
    normalized = normalize_context_category(category) or "unknown"
    if normalized in {"work", "customer_or_service"}:
        return t(language, "ai_effectiveness_score")
    if normalized in {"group_social", "channel_or_broadcast"}:
        return t(language, "ai_activity_score")
    return t(language, "ai_communication_score")


def low_confidence_context_note(context: dict[str, Any] | ContextClassification, *, language: str) -> str:
    item = context_from_dict(context) if isinstance(context, dict) else context
    if item.confidence != "low":
        return ""
    return t(language, "context_low_confidence_note")


def user_context_category(value: str) -> str:
    return USER_CONTEXT_OPTIONS.get(value, "unknown")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
