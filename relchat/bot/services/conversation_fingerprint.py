from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from relchat.analytics.metrics import summarize
from relchat.bot.localization import t
from relchat.bot.services.canonical_findings import finding_rank
from relchat.bot.services.participation import interpret_participation_counts
from relchat.core.models import Message


TOPIC_TERMS = {
    "work_tasks": ("task", "ticket", "deploy", "deadline", "review", "fix", "задач", "тикет", "срок", "проверь", "исправ"),
    "planning": ("meet", "plan", "tomorrow", "friday", "when", "встретим", "план", "завтра", "пятниц", "когда"),
    "daily": ("today", "morning", "evening", "как день", "доброе", "вечер", "сегодня"),
    "personal": ("feel", "miss", "love", "как ты", "скуч", "люблю", "личн"),
    "support": ("sorry", "help", "support", "спасибо", "помоги", "поддерж"),
    "conflict": ("stop", "wrong", "annoy", "не соглас", "хватит", "раздраж"),
    "money": ("pay", "price", "invoice", "деньг", "оплат", "счет", "счёт"),
    "family_obligations": ("family", "parents", "kids", "дом", "семь", "родител", "дет"),
    "technical": ("api", "code", "server", "bug", "python", "лог", "сервер", "код"),
}


def build_conversation_fingerprint(
    *,
    messages: Sequence[Message],
    canonical_findings: Sequence[dict[str, Any]],
    context_category: str,
    period_scope: str,
    question_metrics: dict[str, Any] | None = None,
    history_segments: dict[str, Any] | None = None,
    cross_chat_profile: dict[str, Any] | None = None,
    language: str = "en",
) -> dict[str, Any]:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    metrics = summarize(ordered, "conversation") if ordered else {}
    question_metrics = question_metrics if isinstance(question_metrics, dict) else {}
    history_segments = history_segments if isinstance(history_segments, dict) else {}
    features: list[dict[str, Any]] = []
    asymmetries = participant_asymmetries(ordered, metrics, question_metrics, context_category=context_category, language=language)
    dominant = dominant_patterns(canonical_findings, language=language)
    recurring = recurring_patterns(canonical_findings, language=language)
    recent = recent_changes(history_segments, context_category=context_category, language=language)
    topics = topic_differences(ordered, context_category=context_category, language=language)
    cross_chat = cross_chat_features(cross_chat_profile, context_category=context_category, language=language)
    for group in (asymmetries, dominant, recurring, topics, recent, cross_chat):
        features.extend(group)
    distinctive = dedupe_features(features)[:5]
    uncertainties = fingerprint_uncertainties(ordered, canonical_findings, distinctive, history_segments, language=language)
    return {
        "context_category": context_category,
        "period_scope": period_scope,
        "participant_mapping_confidence": participant_mapping_confidence(ordered),
        "dominant_patterns": dominant[:5],
        "asymmetries": asymmetries[:5],
        "recurring_patterns": recurring[:5],
        "topic_differences": topics[:5],
        "recent_changes": recent[:4],
        "cross_chat_features": cross_chat[:3],
        "distinctive_features": distinctive,
        "uncertainties": uncertainties,
        "evidence_coverage": evidence_coverage(ordered, canonical_findings, history_segments),
    }


def fingerprint_from_result(result: dict[str, Any], *, language: str = "en") -> dict[str, Any]:
    context = result.get("context") if isinstance(result.get("context"), dict) else {}
    context_category = str(context.get("category") or "unknown")
    canonical = result.get("canonical_findings") if isinstance(result.get("canonical_findings"), list) else []
    history = result.get("history_segments") if isinstance(result.get("history_segments"), dict) else {}
    features: list[dict[str, Any]] = []
    features.extend(dominant_patterns(canonical, language=language))
    features.extend(recurring_patterns(canonical, language=language))
    features.extend(recent_changes(history, context_category=context_category, language=language))
    participation = result.get("participation_balance") if isinstance(result.get("participation_balance"), dict) else {}
    if participation.get("summary"):
        features.append(
            feature(
                "participation_balance",
                "asymmetry",
                str(participation["summary"]),
                semantic_key="participation_balance",
                evidence_count=int((result.get("coverage") or {}).get("available_messages") or 0),
                confidence=str(participation.get("confidence") or "medium"),
                participant_scope="both",
                comparison_type="participant",
                practical_consequence=t(language, "fingerprint_consequence_balance_limited"),
            )
        )
    distinctive = dedupe_features(features)[:5]
    return {
        "context_category": context_category,
        "period_scope": str((result.get("coverage") or {}).get("requested_period") or ""),
        "participant_mapping_confidence": "medium",
        "dominant_patterns": dominant_patterns(canonical, language=language)[:5],
        "asymmetries": [item for item in distinctive if item.get("role") == "asymmetry"][:5],
        "recurring_patterns": recurring_patterns(canonical, language=language)[:5],
        "topic_differences": [],
        "recent_changes": recent_changes(history, context_category=context_category, language=language)[:4],
        "cross_chat_features": [],
        "distinctive_features": distinctive,
        "uncertainties": [t(language, "fingerprint_uncertainty_rebuilt_without_messages")],
        "evidence_coverage": {"structural": 0.5, "semantic": semantic_coverage(canonical), "historical": historical_coverage(history)},
    }


def validate_conversation_fingerprint(value: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    row = value if isinstance(value, dict) else fallback or {}
    return {
        "context_category": str(row.get("context_category") or "unknown"),
        "period_scope": str(row.get("period_scope") or ""),
        "participant_mapping_confidence": normalize_confidence(row.get("participant_mapping_confidence")),
        "dominant_patterns": validate_features(row.get("dominant_patterns"), limit=8),
        "asymmetries": validate_features(row.get("asymmetries"), limit=8),
        "recurring_patterns": validate_features(row.get("recurring_patterns"), limit=8),
        "topic_differences": validate_features(row.get("topic_differences"), limit=8),
        "recent_changes": validate_features(row.get("recent_changes"), limit=8),
        "cross_chat_features": validate_features(row.get("cross_chat_features"), limit=5),
        "distinctive_features": validate_features(row.get("distinctive_features"), limit=8),
        "uncertainties": string_list(row.get("uncertainties"), limit=6),
        "evidence_coverage": validate_coverage(row.get("evidence_coverage")),
    }


def participant_asymmetries(
    messages: Sequence[Message],
    metrics: dict[str, Any],
    question_metrics: dict[str, Any],
    *,
    context_category: str,
    language: str,
) -> list[dict[str, Any]]:
    if len(messages) < 12:
        return []
    outgoing = [message for message in messages if message.is_outgoing]
    incoming = [message for message in messages if not message.is_outgoing]
    total = max(1, len(messages))
    rows: list[dict[str, Any]] = []
    participation = interpret_participation_counts(len(outgoing), len(incoming), scope="selected_period", language=language)
    if participation["status"] == "you_more":
        rows.append(feature("you_more_volume", "asymmetry", t(language, "fingerprint_you_more_volume"), semantic_key="volume:you_more", participant_scope="you", evidence_count=len(outgoing), comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_you_carry")))
    elif participation["status"] == "other_more":
        rows.append(feature("other_more_volume", "asymmetry", t(language, "fingerprint_other_more_volume"), semantic_key="volume:other_more", participant_scope="other", evidence_count=len(incoming), comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_other_carry")))

    user_avg = average_length(outgoing)
    other_avg = average_length(incoming)
    if user_avg and other_avg and user_avg >= other_avg * 1.35:
        rows.append(feature("you_more_detail", "asymmetry", t(language, "fingerprint_you_more_detail"), semantic_key="detail:you_more", participant_scope="you", evidence_count=len(outgoing), comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_detail_work" if context_category == "work" else "fingerprint_consequence_detail_general")))
    elif user_avg and other_avg and other_avg >= user_avg * 1.35:
        rows.append(feature("other_more_detail", "asymmetry", t(language, "fingerprint_other_more_detail"), semantic_key="detail:other_more", participant_scope="other", evidence_count=len(incoming), comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_other_detail")))

    starts = session_starts(messages)
    if len(starts) >= 4:
        user_starts = sum(1 for item in starts if item == "you")
        other_starts = len(starts) - user_starts
        if user_starts >= other_starts * 1.6:
            rows.append(feature("you_more_starts", "asymmetry", t(language, "fingerprint_you_more_starts"), semantic_key="initiative:you_starts", participant_scope="you", evidence_count=user_starts, comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_initiative_you")))
        elif other_starts >= user_starts * 1.6:
            rows.append(feature("other_more_starts", "asymmetry", t(language, "fingerprint_other_more_starts"), semantic_key="initiative:other_starts", participant_scope="other", evidence_count=other_starts, comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_initiative_other")))

    returns = returns_after_pauses(messages)
    if sum(returns.values()) >= 2:
        if returns["you"] >= max(1, returns["other"] * 2):
            rows.append(feature("you_returns_after_pauses", "asymmetry", t(language, "fingerprint_you_returns_after_pauses"), semantic_key="pauses:you_returns", participant_scope="you", evidence_count=returns["you"], comparison_type="period", practical_consequence=t(language, "fingerprint_consequence_user_continuity")))
        elif returns["other"] >= max(1, returns["you"] * 2):
            rows.append(feature("other_returns_after_pauses", "asymmetry", t(language, "fingerprint_other_returns_after_pauses"), semantic_key="pauses:other_returns", participant_scope="other", evidence_count=returns["other"], comparison_type="period", practical_consequence=t(language, "fingerprint_consequence_other_continuity")))

    by_participant = question_metrics.get("by_participant") if isinstance(question_metrics.get("by_participant"), dict) else {}
    you_q = by_participant.get("you") if isinstance(by_participant.get("you"), dict) else {}
    other_q = by_participant.get("other") if isinstance(by_participant.get("other"), dict) else {}
    user_rate = float(you_q.get("per_100_messages") or 0.0)
    other_rate = float(other_q.get("per_100_messages") or 0.0)
    if max(user_rate, other_rate) >= 3.0 and abs(user_rate - other_rate) >= 3.0:
        if user_rate > other_rate:
            rows.append(feature("you_more_questions", "asymmetry", t(language, "fingerprint_you_more_questions", rate=f"{user_rate:.1f}", other_rate=f"{other_rate:.1f}"), semantic_key="questions:you_more", participant_scope="you", evidence_count=int(you_q.get("direct_question_count") or 0), comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_questions_work" if context_category == "work" else "fingerprint_consequence_questions_general")))
        else:
            rows.append(feature("other_more_questions", "asymmetry", t(language, "fingerprint_other_more_questions", rate=f"{other_rate:.1f}", user_rate=f"{user_rate:.1f}"), semantic_key="questions:other_more", participant_scope="other", evidence_count=int(other_q.get("direct_question_count") or 0), comparison_type="participant", practical_consequence=t(language, "fingerprint_consequence_other_questions")))
    return rows


def dominant_patterns(findings: Sequence[dict[str, Any]], *, language: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in sorted([item for item in findings if isinstance(item, dict)], key=finding_rank, reverse=True):
        if finding.get("status") not in {"available", "ambiguous"}:
            continue
        if finding.get("status") == "ambiguous" and str(finding.get("semantic_source")) == "local_pattern":
            text = str(finding.get("interpretation") or finding.get("title") or "")
        else:
            text = str(finding.get("title") or finding.get("interpretation") or "")
        if not text:
            continue
        rows.append(
            feature(
                str(finding.get("finding_id") or "finding"),
                "finding",
                text,
                semantic_key=str(finding.get("summary_key") or finding.get("semantic_key") or finding.get("finding_id") or ""),
                participant_scope=str(finding.get("participant_scope") or "interaction"),
                evidence_count=int(finding.get("evidence_count") or len(finding.get("evidence") or [])),
                confidence=str(finding.get("confidence") or "low"),
                finding_id=str(finding.get("finding_id") or ""),
                finding_type=str(finding.get("finding_type") or ""),
                practical_consequence=str(finding.get("interpretation") or ""),
                severity=str(finding.get("severity") or "neutral"),
            )
        )
    return rows[:8]


def recurring_patterns(findings: Sequence[dict[str, Any]], *, language: str) -> list[dict[str, Any]]:
    rows = []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("status") != "available":
            continue
        evidence_count = int(finding.get("evidence_count") or 0)
        if evidence_count < 3:
            continue
        rows.append(
            feature(
                f"recurring_{finding.get('finding_id')}",
                "recurring",
                t(language, "fingerprint_recurring_finding", finding=finding.get("title") or finding.get("interpretation") or ""),
                semantic_key=f"recurring:{finding.get('summary_key') or finding.get('finding_id')}",
                evidence_count=evidence_count,
                confidence=str(finding.get("confidence") or "medium"),
                participant_scope=str(finding.get("participant_scope") or "interaction"),
                finding_id=str(finding.get("finding_id") or ""),
                finding_type=str(finding.get("finding_type") or ""),
                practical_consequence=str(finding.get("interpretation") or ""),
                comparison_type="recurrence",
            )
        )
    return rows


def recent_changes(history_segments: dict[str, Any], *, context_category: str, language: str) -> list[dict[str, Any]]:
    text = str(history_segments.get("recent_change") or "").strip()
    if not text:
        return []
    return [
        feature(
            "recent_change_1",
            "recent_change",
            text,
            semantic_key="recent:no_meaningful_change" if is_no_change(text) else f"recent:{text.casefold()[:40]}",
            evidence_count=int(history_segments.get("window_count") or 0),
            confidence="medium" if int(history_segments.get("window_count") or 0) >= 2 else "low",
            participant_scope="interaction",
            comparison_type="period",
            practical_consequence=t(language, "fingerprint_consequence_recent_stability" if is_no_change(text) else "fingerprint_consequence_recent_change"),
        )
    ]


def topic_differences(messages: Sequence[Message], *, context_category: str, language: str) -> list[dict[str, Any]]:
    if len(messages) < 20:
        return []
    counts = Counter()
    user_counts = Counter()
    other_counts = Counter()
    for message in messages:
        text = (message.text or "").casefold()
        for topic, terms in TOPIC_TERMS.items():
            if any(term in text for term in terms):
                counts[topic] += 1
                if message.is_outgoing:
                    user_counts[topic] += 1
                else:
                    other_counts[topic] += 1
    rows: list[dict[str, Any]] = []
    for topic, count in counts.most_common(3):
        if count < 3:
            continue
        if context_category == "work" and topic in {"work_tasks", "technical", "planning"}:
            rows.append(feature(f"topic_{topic}", "topic", t(language, f"fingerprint_topic_{topic}_work", count=count), semantic_key=f"topic:{topic}", evidence_count=count, confidence="medium", topic=topic, comparison_type="topic", practical_consequence=t(language, "fingerprint_consequence_topic_work")))
        elif context_category in {"friendship", "romantic", "family", "mixed"} and topic in {"planning", "personal", "support", "family_obligations"}:
            rows.append(feature(f"topic_{topic}", "topic", t(language, f"fingerprint_topic_{topic}", count=count), semantic_key=f"topic:{topic}", evidence_count=count, confidence="medium", topic=topic, comparison_type="topic", practical_consequence=t(language, "fingerprint_consequence_topic_general")))
    return rows


def cross_chat_features(cross_chat_profile: dict[str, Any] | None, *, context_category: str, language: str) -> list[dict[str, Any]]:
    profile = cross_chat_profile if isinstance(cross_chat_profile, dict) else {}
    if profile.get("status") != "available":
        return []
    rows = []
    for item in profile.get("observations") or []:
        if not isinstance(item, dict) or item.get("context") != context_category:
            continue
        rows.append(feature(f"cross_{item.get('dimension')}", "cross_chat", str(item.get("observation") or ""), semantic_key=f"cross:{item.get('dimension')}:{context_category}", evidence_count=int(item.get("evidence_count") or 0), confidence=str(item.get("confidence") or "low"), comparison_type="cross_chat", practical_consequence=t(language, "fingerprint_consequence_cross_chat")))
    return rows[:3]


def feature(
    feature_id: str,
    role: str,
    text: str,
    *,
    semantic_key: str,
    evidence_count: int,
    confidence: str = "medium",
    participant_scope: str = "interaction",
    finding_id: str = "",
    finding_type: str = "",
    practical_consequence: str = "",
    topic: str = "",
    comparison_type: str = "",
    severity: str = "neutral",
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "role": role,
        "text": text,
        "semantic_key": semantic_key,
        "participant_scope": participant_scope if participant_scope in {"you", "other", "both", "interaction"} else "interaction",
        "finding_id": finding_id,
        "finding_type": finding_type,
        "severity": severity,
        "evidence_count": max(0, int(evidence_count)),
        "confidence": normalize_confidence(confidence),
        "practical_consequence": practical_consequence,
        "topic": topic,
        "comparison_type": comparison_type,
    }


def dedupe_features(features: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in features:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        key = str(item.get("semantic_key") or item.get("text") or "").casefold()
        consequence = str(item.get("practical_consequence") or "").casefold()[:80]
        compound = f"{item.get('participant_scope')}:{key}:{consequence}"
        if compound in seen:
            continue
        seen.add(compound)
        result.append(item)
    return result


def fingerprint_uncertainties(messages: Sequence[Message], findings: Sequence[dict[str, Any]], features: Sequence[dict[str, Any]], history_segments: dict[str, Any], *, language: str) -> list[str]:
    rows: list[str] = []
    if len(messages) < 20:
        rows.append(t(language, "fingerprint_uncertainty_low_messages"))
    if not any(item.get("semantic_source") in {"ai_interpretation", "explicit_rule", "combined"} and item.get("status") == "available" for item in findings):
        rows.append(t(language, "fingerprint_uncertainty_local_semantics"))
    if len(features) < 2:
        rows.append(t(language, "fingerprint_uncertainty_not_enough_distinctive"))
    if not history_segments.get("segmented"):
        rows.append(t(language, "fingerprint_uncertainty_no_history_comparison"))
    return rows[:4]


def evidence_coverage(messages: Sequence[Message], findings: Sequence[dict[str, Any]], history_segments: dict[str, Any]) -> dict[str, float]:
    return {
        "structural": round(min(1.0, len(messages) / 100.0), 2),
        "semantic": round(semantic_coverage(findings), 2),
        "historical": round(historical_coverage(history_segments), 2),
    }


def semantic_coverage(findings: Sequence[dict[str, Any]]) -> float:
    available = [item for item in findings if isinstance(item, dict) and item.get("status") == "available" and item.get("finding_type") in {"sarcasm", "aggression", "influence", "possible_interest"}]
    return min(1.0, len(available) / 3.0)


def historical_coverage(history_segments: dict[str, Any]) -> float:
    if not isinstance(history_segments, dict) or not history_segments.get("segmented"):
        return 0.0
    return min(1.0, int(history_segments.get("window_count") or 0) / 6.0)


def session_starts(messages: Sequence[Message], *, gap_hours: int = 12) -> list[str]:
    starts: list[str] = []
    previous_time: datetime | None = None
    for message in messages:
        current = parse_datetime(message.timestamp)
        if previous_time is None or current - previous_time >= timedelta(hours=gap_hours):
            starts.append("you" if message.is_outgoing else "other")
        previous_time = current
    return starts


def returns_after_pauses(messages: Sequence[Message], *, gap_days: int = 2) -> dict[str, int]:
    counts = {"you": 0, "other": 0}
    previous_time: datetime | None = None
    for message in messages:
        current = parse_datetime(message.timestamp)
        if previous_time is not None and current - previous_time >= timedelta(days=gap_days):
            counts["you" if message.is_outgoing else "other"] += 1
        previous_time = current
    return counts


def average_length(messages: Sequence[Message]) -> float:
    lengths = [len(message.text or "") for message in messages if message.text]
    return sum(lengths) / len(lengths) if lengths else 0.0


def parse_datetime(value: str) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def participant_mapping_confidence(messages: Sequence[Message]) -> str:
    senders = {message.sender_id for message in messages if message.sender_id}
    if len(messages) >= 20 and len(senders) == 2:
        return "high"
    if len(messages) >= 8:
        return "medium"
    return "low"


def is_no_change(text: str) -> bool:
    lowered = text.casefold()
    return "no meaningful change" in lowered or "существенных изменений нет" in lowered or "похож" in lowered


def validate_features(value: Any, *, limit: int) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        result.append(
            feature(
                str(row.get("feature_id") or f"feature_{len(result) + 1}"),
                str(row.get("role") or "finding"),
                str(row.get("text") or ""),
                semantic_key=str(row.get("semantic_key") or row.get("text") or ""),
                evidence_count=safe_int(row.get("evidence_count")),
                confidence=str(row.get("confidence") or "low"),
                participant_scope=str(row.get("participant_scope") or "interaction"),
                finding_id=str(row.get("finding_id") or ""),
                finding_type=str(row.get("finding_type") or ""),
                practical_consequence=str(row.get("practical_consequence") or ""),
                topic=str(row.get("topic") or ""),
                comparison_type=str(row.get("comparison_type") or ""),
                severity=str(row.get("severity") or "neutral"),
            )
        )
    return dedupe_features(result)


def validate_coverage(value: Any) -> dict[str, float]:
    row = value if isinstance(value, dict) else {}
    return {key: clamp_float(row.get(key)) for key in ("structural", "semantic", "historical")}


def normalize_confidence(value: Any) -> str:
    text = str(value or "low")
    return text if text in {"low", "medium", "high"} else "low"


def string_list(value: Any, *, limit: int) -> list[str]:
    rows = value if isinstance(value, list) else []
    return [str(item) for item in rows[:limit] if str(item).strip()]


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def clamp_float(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value or 0.0))), 2)
    except (TypeError, ValueError):
        return 0.0
