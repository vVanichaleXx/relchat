from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.services.canonical_findings import CONFIDENCE_ORDER, SEVERITY_ORDER, finding_rank


GENERIC_KEYS = {
    "balanced_activity",
    "both_participated",
    "participation_balance",
    "similar_visible_volume",
    "volume:balanced",
}


GENERIC_FRAGMENTS = (
    "both sides participate",
    "both sides participated",
    "visible communication",
    "visible data",
    "visible metrics",
    "your visible communication style",
    "several observable signals",
    "certain patterns",
    "точка трения",
    "видимые данные",
    "видимые метрики",
    "видимый стиль",
    "несколько наблюдаемых признаков",
    "обе стороны участв",
)


def select_distinctive_patterns(
    *,
    fingerprint: dict[str, Any],
    canonical_findings: Sequence[dict[str, Any]] | None = None,
    context_category: str = "unknown",
    report_scope: str = "full",
    language: str = "en",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    del language
    cap = limit if limit is not None else (4 if report_scope == "short" else 8)
    features = fingerprint_features(fingerprint)
    features.extend(features_from_findings(canonical_findings or []))
    ranked: list[tuple[float, dict[str, Any]]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        pattern = pattern_from_feature(feature, context_category=context_category)
        if not pattern.get("observation"):
            continue
        ranked.append((pattern["specificity_score"], pattern))
    ranked.sort(key=lambda item: (item[0], int(item[1].get("evidence_count") or 0), str(item[1].get("pattern_id"))), reverse=True)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, pattern in ranked:
        key = independent_key(pattern)
        if key in seen:
            continue
        if is_generic_pattern(pattern) and count_non_generic_available(ranked) >= 2:
            continue
        seen.add(key)
        selected.append(pattern)
        if len(selected) >= cap:
            break
    return selected


def validate_selected_patterns(value: Any, *, fallback: Sequence[dict[str, Any]] | None = None, limit: int = 8) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else list(fallback or [])
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        pattern = validate_pattern(row, fallback_index=len(result) + 1)
        if not pattern["observation"]:
            continue
        key = independent_key(pattern)
        if key in seen:
            continue
        seen.add(key)
        result.append(pattern)
        if len(result) >= limit:
            break
    return result


def fingerprint_features(fingerprint: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(fingerprint, dict):
        return result
    for key in (
        "distinctive_features",
        "asymmetries",
        "topic_differences",
        "recent_changes",
        "recurring_patterns",
        "dominant_patterns",
        "cross_chat_features",
    ):
        rows = fingerprint.get(key) if isinstance(fingerprint.get(key), list) else []
        result.extend(row for row in rows if isinstance(row, dict))
    return result


def features_from_findings(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for finding in sorted([item for item in findings if isinstance(item, dict)], key=finding_rank, reverse=True):
        if str(finding.get("status") or "") not in {"available", "ambiguous"}:
            continue
        result.append(
            {
                "feature_id": str(finding.get("finding_id") or ""),
                "role": "finding",
                "text": str(finding.get("title") or finding.get("observation") or ""),
                "semantic_key": str(finding.get("summary_key") or finding.get("finding_id") or ""),
                "participant_scope": str(finding.get("participant_scope") or "interaction"),
                "finding_id": str(finding.get("finding_id") or ""),
                "finding_type": str(finding.get("finding_type") or ""),
                "severity": str(finding.get("severity") or "neutral"),
                "evidence_count": int(finding.get("evidence_count") or 0),
                "confidence": str(finding.get("confidence") or "low"),
                "practical_consequence": str(finding.get("interpretation") or ""),
                "semantic_source": str(finding.get("semantic_source") or ""),
                "semantic_depth": str(finding.get("semantic_depth") or ""),
                "comparison_type": "finding",
            }
        )
    return result


def pattern_from_feature(feature: dict[str, Any], *, context_category: str) -> dict[str, Any]:
    confidence = normalize_confidence(feature.get("confidence"))
    severity = normalize_severity(feature.get("severity"))
    evidence_count = safe_int(feature.get("evidence_count"))
    context_relevance = relevance_for_context(feature, context_category=context_category)
    specificity = pattern_specificity_score(
        feature,
        confidence=confidence,
        severity=severity,
        evidence_count=evidence_count,
        context_relevance=context_relevance,
    )
    return {
        "pattern_id": str(feature.get("feature_id") or feature.get("finding_id") or stable_pattern_id(feature)),
        "role": str(feature.get("role") or "finding"),
        "title": clean_text(feature.get("text") or feature.get("title") or feature.get("observation")),
        "observation": clean_text(feature.get("text") or feature.get("observation") or feature.get("title")),
        "consequence": clean_text(feature.get("practical_consequence") or feature.get("interpretation")),
        "semantic_key": str(feature.get("semantic_key") or feature.get("summary_key") or feature.get("finding_id") or ""),
        "finding_id": str(feature.get("finding_id") or ""),
        "finding_type": str(feature.get("finding_type") or ""),
        "participant_scope": normalize_scope(feature.get("participant_scope")),
        "confidence": confidence,
        "severity": severity,
        "evidence_count": evidence_count,
        "comparison_type": str(feature.get("comparison_type") or ""),
        "topic": str(feature.get("topic") or ""),
        "semantic_source": str(feature.get("semantic_source") or feature.get("source") or ""),
        "semantic_depth": str(feature.get("semantic_depth") or ""),
        "context_relevance": round(context_relevance, 2),
        "specificity_score": round(specificity, 3),
        "generic": is_generic_feature(feature),
    }


def pattern_specificity_score(
    feature: dict[str, Any],
    *,
    confidence: str,
    severity: str,
    evidence_count: int,
    context_relevance: float,
) -> float:
    score = 0.15
    score += min(0.25, evidence_count / 20.0)
    score += {"low": 0.0, "medium": 0.12, "high": 0.18}[confidence]
    score += min(0.2, context_relevance)
    role = str(feature.get("role") or "")
    if role == "asymmetry":
        score += 0.18
    if role == "topic":
        score += 0.14
    if role == "recent_change":
        score += 0.14
    if role == "recurring":
        score += 0.12
    if str(feature.get("comparison_type") or "") in {"participant", "period", "topic", "cross_chat", "recurrence"}:
        score += 0.12
    if str(feature.get("practical_consequence") or "").strip():
        score += 0.08
    if severity in {"attention", "problem", "serious", "positive"}:
        score += 0.08
    if is_generic_feature(feature):
        score -= 0.35
    if str(feature.get("semantic_source") or "") == "local_pattern" and str(feature.get("semantic_depth") or "") == "suggestive":
        score -= 0.12
    return max(0.0, min(1.0, score))


def relevance_for_context(feature: dict[str, Any], *, context_category: str) -> float:
    finding_type = str(feature.get("finding_type") or "")
    semantic_key = str(feature.get("semantic_key") or "")
    topic = str(feature.get("topic") or "")
    if context_category == "work":
        if finding_type.startswith("work_") or topic in {"work_tasks", "technical", "planning"}:
            return 0.2
        if any(token in semantic_key for token in ("task", "decision", "deadline", "question", "clarification")):
            return 0.18
        return 0.05
    if context_category == "romantic":
        if finding_type in {"possible_interest", "influence", "sarcasm"}:
            return 0.18
        if topic in {"planning", "personal", "support"}:
            return 0.16
    if context_category == "family":
        if topic in {"family_obligations", "support", "planning", "conflict"}:
            return 0.18
        if finding_type in {"aggression", "sarcasm", "unanswered_questions"}:
            return 0.16
    if context_category == "friendship":
        if topic in {"personal", "support", "planning"}:
            return 0.18
        if finding_type in {"sarcasm", "possible_interest"}:
            return 0.12
    return 0.08


def count_non_generic_available(ranked: Sequence[tuple[float, dict[str, Any]]]) -> int:
    return sum(1 for _, pattern in ranked if not is_generic_pattern(pattern) and float(pattern.get("specificity_score") or 0.0) >= 0.35)


def is_generic_pattern(pattern: dict[str, Any]) -> bool:
    return bool(pattern.get("generic")) or is_generic_text(str(pattern.get("observation") or "")) or generic_semantic_key(str(pattern.get("semantic_key") or ""))


def is_generic_feature(feature: dict[str, Any]) -> bool:
    return is_generic_text(str(feature.get("text") or feature.get("title") or feature.get("observation") or "")) or generic_semantic_key(str(feature.get("semantic_key") or ""))


def is_generic_text(text: str) -> bool:
    lowered = " ".join(text.casefold().split())
    return any(fragment in lowered for fragment in GENERIC_FRAGMENTS)


def generic_semantic_key(key: str) -> bool:
    lowered = key.casefold()
    return any(fragment in lowered for fragment in GENERIC_KEYS) or lowered in {"volume:similar", "participation_balance:symmetric_volume_length"}


def independent_key(pattern: dict[str, Any]) -> str:
    semantic = str(pattern.get("semantic_key") or pattern.get("observation") or "").casefold()
    consequence = str(pattern.get("consequence") or "").casefold()[:80]
    return f"{pattern.get('participant_scope')}:{pattern.get('finding_type')}:{semantic}:{consequence}"


def stable_pattern_id(feature: dict[str, Any]) -> str:
    text = f"{feature.get('role')}:{feature.get('semantic_key')}:{feature.get('text') or feature.get('title') or feature.get('observation')}"
    cleaned = "".join(char if char.isalnum() else "_" for char in text.casefold()).strip("_")
    return f"pattern_{cleaned[:48] or '1'}"


def validate_pattern(row: dict[str, Any], *, fallback_index: int) -> dict[str, Any]:
    return {
        "pattern_id": str(row.get("pattern_id") or row.get("feature_id") or f"pattern_{fallback_index}"),
        "role": str(row.get("role") or "finding"),
        "title": clean_text(row.get("title") or row.get("observation")),
        "observation": clean_text(row.get("observation") or row.get("title")),
        "consequence": clean_text(row.get("consequence")),
        "semantic_key": str(row.get("semantic_key") or ""),
        "finding_id": str(row.get("finding_id") or ""),
        "finding_type": str(row.get("finding_type") or ""),
        "participant_scope": normalize_scope(row.get("participant_scope")),
        "confidence": normalize_confidence(row.get("confidence")),
        "severity": normalize_severity(row.get("severity")),
        "evidence_count": safe_int(row.get("evidence_count")),
        "comparison_type": str(row.get("comparison_type") or ""),
        "topic": str(row.get("topic") or ""),
        "semantic_source": str(row.get("semantic_source") or ""),
        "semantic_depth": str(row.get("semantic_depth") or ""),
        "context_relevance": clamp_float(row.get("context_relevance")),
        "specificity_score": clamp_float(row.get("specificity_score")),
        "generic": bool(row.get("generic")) or is_generic_text(str(row.get("observation") or row.get("title") or "")),
    }


def normalize_confidence(value: Any) -> str:
    text = str(value or "low")
    return text if text in CONFIDENCE_ORDER else "low"


def normalize_severity(value: Any) -> str:
    text = str(value or "neutral")
    return text if text in SEVERITY_ORDER else "neutral"


def normalize_scope(value: Any) -> str:
    text = str(value or "interaction")
    return text if text in {"you", "other", "both", "interaction"} else "interaction"


def clean_text(value: Any, *, limit: int = 360) -> str:
    return " ".join(str(value or "").split())[:limit]


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def clamp_float(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value or 0.0))), 3)
    except (TypeError, ValueError):
        return 0.0
