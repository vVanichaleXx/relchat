from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from relchat.analytics.metrics import summarize
from relchat.bot.localization import t
from relchat.bot.services.participation import interpret_participation_counts
from relchat.bot.services.question_metrics import build_question_metrics
from relchat.core.models import Message


PROFILE_DIMENSIONS = (
    "warmth",
    "directness",
    "initiative",
    "responsiveness",
    "question_engagement",
    "topic_continuation",
    "message_detail",
    "emotional_acknowledgement",
    "humour",
    "sarcasm",
    "planning_clarity",
    "conflict_style",
    "repair_attempts",
    "pressure_risk",
    "persuasion_style",
    "boundary_respect",
)


def build_personal_profile(
    *,
    messages: Sequence[Message],
    semantic_analysis: dict[str, Any] | None,
    context_category: str,
    period_label: str,
    language: str = "en",
) -> dict[str, Any]:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    user_messages = [message for message in ordered if message.is_outgoing]
    other_messages = [message for message in ordered if not message.is_outgoing]
    metrics = summarize(ordered, "conversation") if ordered else {}
    question_metrics = build_question_metrics(ordered, language=language)
    user_question_count = int((((question_metrics.get("by_participant") or {}).get("you") or {}).get("direct_question_count")) or 0)
    profile_rows = [
        profile_row(
            "initiative",
            initiative_observation(ordered, metrics, language=language),
            confidence="medium" if len(ordered) >= 20 else "low",
            evidence_types=["participant_comparison", "response_behavior"],
        ),
        profile_row(
            "message_detail",
            detail_observation(user_messages, other_messages, language=language),
            confidence="medium" if len(user_messages) >= 8 else "low",
            evidence_types=["participant_comparison"],
        ),
        profile_row(
            "question_engagement",
            question_observation(user_question_count, language=language),
            confidence="medium" if len(user_messages) >= 8 else "low",
            evidence_types=["semantic_pattern"],
        ),
        profile_row(
            "planning_clarity",
            planning_observation(user_messages, context_category=context_category, language=language),
            confidence="medium" if user_messages else "low",
            evidence_types=["semantic_pattern", "event_pattern"],
        ),
    ]
    semantic_analysis = semantic_analysis if isinstance(semantic_analysis, dict) else {}
    sarcasm = semantic_analysis.get("sarcasm") if isinstance(semantic_analysis.get("sarcasm"), dict) else {}
    influence = semantic_analysis.get("influence") if isinstance(semantic_analysis.get("influence"), dict) else {}
    aggression = semantic_analysis.get("aggression") if isinstance(semantic_analysis.get("aggression"), dict) else {}
    if sarcasm.get("status") == "available":
        profile_rows.append(
            profile_row(
                "sarcasm",
                t(language, "profile_sarcasm_observation", direction=t(language, f"sarcasm_direction_{sarcasm.get('direction') or 'mixed'}")),
                confidence=str(sarcasm.get("confidence") or "low"),
                evidence_types=["semantic_pattern"],
            )
        )
    if influence.get("status") == "available":
        profile_rows.append(
            profile_row(
                "persuasion_style",
                t(language, "profile_influence_observation", category=t(language, f"influence_category_{influence.get('category') or 'persuasion'}")),
                confidence=str(influence.get("confidence") or "low"),
                evidence_types=["semantic_pattern", "contextual_sequence"],
            )
        )
    if aggression.get("status") == "available":
        profile_rows.append(
            profile_row(
                "conflict_style",
                t(language, "profile_conflict_observation", kind=t(language, f"aggression_type_{aggression.get('type') or 'mixed'}")),
                confidence=str(aggression.get("confidence") or "low"),
                evidence_types=["explicit_wording"],
            )
        )
    return {
        "profile_id": "period_user_profile",
        "title": t(language, "personal_profile_title"),
        "scope": {
            "period": period_label,
            "context": context_category,
            "message_count": len(ordered),
            "user_message_count": len(user_messages),
        },
        "summary": profile_summary(profile_rows, language=language),
        "dimensions": profile_rows[:10],
        "limitations": [t(language, "profile_period_limitation"), t(language, "profile_not_personality")],
    }


def build_cross_chat_profile(
    analyses: Sequence[dict[str, Any]],
    *,
    language: str = "en",
    min_coverage: int = 3,
) -> dict[str, Any]:
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    chat_count = 0
    for analysis in analyses:
        result = analysis.get("result") if isinstance(analysis.get("result"), dict) else analysis
        profile = result.get("personal_profile") if isinstance(result, dict) else {}
        context = ((result.get("context") or {}) if isinstance(result, dict) else {}).get("category") or "unknown"
        if not isinstance(profile, dict):
            continue
        chat_count += 1
        for row in profile.get("dimensions") or []:
            if isinstance(row, dict) and row.get("confidence") in {"medium", "high"}:
                counters[str(row.get("dimension") or "unknown")][context] += 1
    observations: list[dict[str, Any]] = []
    for dimension, by_context in counters.items():
        total = sum(by_context.values())
        if total < min_coverage:
            continue
        context, count = by_context.most_common(1)[0]
        observations.append(
            {
                "dimension": dimension,
                "context": context,
                "observation": t(language, "cross_chat_observation", dimension=t(language, f"profile_dimension_{dimension}"), context=t(language, f"context_{context}"), count=count),
                "confidence": "medium" if count >= min_coverage else "low",
                "evidence_count": count,
                "limitations": [t(language, "cross_chat_no_raw_text")],
            }
        )
    return {
        "profile_id": "cross_chat_user_profile",
        "status": "available" if observations else "insufficient_data",
        "chat_count": chat_count,
        "observations": observations,
        "limitations": [t(language, "cross_chat_aggregate_only")],
    }


def profile_row(dimension: str, observation: str, *, confidence: str, evidence_types: list[str]) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "observation": observation,
        "interpretation": "",
        "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
        "evidence_types": evidence_types,
        "limitations": [],
    }


def initiative_observation(messages: Sequence[Message], metrics: dict[str, Any], *, language: str) -> str:
    del metrics
    outgoing = sum(1 for message in messages if message.is_outgoing)
    incoming = sum(1 for message in messages if not message.is_outgoing)
    participation = interpret_participation_counts(outgoing, incoming, scope="selected_period", language=language)
    if participation["status"] == "you_more":
        return t(language, "profile_initiative_high")
    if participation["status"] == "other_more":
        return t(language, "profile_initiative_low")
    if participation["status"] == "insufficient_data":
        return t(language, "profile_summary_limited")
    return t(language, "profile_initiative_balanced")


def detail_observation(user_messages: Sequence[Message], other_messages: Sequence[Message], *, language: str) -> str:
    user_avg = average_length(user_messages)
    other_avg = average_length(other_messages)
    if user_avg and other_avg and user_avg >= other_avg * 1.4:
        return t(language, "profile_detail_user_longer")
    if user_avg and other_avg and user_avg <= other_avg * 0.7:
        return t(language, "profile_detail_user_shorter")
    return t(language, "profile_detail_similar")


def question_observation(questions: int, *, language: str) -> str:
    if questions >= 5:
        return t(language, "profile_questions_frequent", count=questions)
    if questions:
        return t(language, "profile_questions_some", count=questions)
    return t(language, "profile_questions_few")


def planning_observation(user_messages: Sequence[Message], *, context_category: str, language: str) -> str:
    text = " ".join((message.text or "").casefold() for message in user_messages)
    plan_terms = ("tomorrow", "friday", "deadline", "meet", "plan", "завтра", "пятниц", "срок", "встретим", "план")
    if any(term in text for term in plan_terms):
        return t(language, "profile_planning_visible")
    if context_category == "work":
        return t(language, "profile_planning_work_limited")
    return t(language, "profile_planning_limited")


def profile_summary(rows: Sequence[dict[str, Any]], *, language: str) -> str:
    confident = [row for row in rows if row.get("confidence") in {"medium", "high"}]
    if not confident:
        return t(language, "profile_summary_limited")
    for row in confident:
        observation = str(row.get("observation") or "").strip()
        if observation and not generic_profile_text(observation):
            return t(language, "profile_summary_from_observation", observation=observation)
    return ""


def generic_profile_text(text: str) -> bool:
    lowered = text.casefold()
    return any(
        fragment in lowered
        for fragment in (
            "several observable",
            "нескольким наблюдаем",
            "visible style",
            "видимый стиль",
            "activity is roughly balanced",
            "активность примерно сбалансирована",
            "roughly balanced with the other participant",
            "примерно сбалансирована с собеседником",
        )
    )


def average_length(messages: Sequence[Message]) -> float:
    lengths = [len(message.text or "") for message in messages if message.text]
    return sum(lengths) / len(lengths) if lengths else 0.0


def validate_personal_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    rows = value.get("dimensions") if isinstance(value.get("dimensions"), list) else []
    return {
        "profile_id": str(value.get("profile_id") or "period_user_profile"),
        "title": str(value.get("title") or ""),
        "scope": value.get("scope") if isinstance(value.get("scope"), dict) else {},
        "summary": str(value.get("summary") or ""),
        "dimensions": [validate_profile_dimension(row) for row in rows[:16] if isinstance(row, dict)],
        "limitations": [str(item) for item in (value.get("limitations") or [])[:8] if str(item).strip()],
    }


def validate_profile_dimension(value: dict[str, Any]) -> dict[str, Any]:
    confidence = str(value.get("confidence") or "low")
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    return {
        "dimension": str(value.get("dimension") or "unknown"),
        "observation": str(value.get("observation") or ""),
        "interpretation": str(value.get("interpretation") or ""),
        "confidence": confidence,
        "evidence_types": [str(item) for item in (value.get("evidence_types") or [])[:8] if str(item).strip()],
        "limitations": [str(item) for item in (value.get("limitations") or [])[:8] if str(item).strip()],
    }
