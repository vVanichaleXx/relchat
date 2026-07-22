from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t


FINDING_STATUSES = {"available", "ambiguous", "insufficient_data", "not_applicable"}
FINDING_SEVERITIES = {"positive", "neutral", "attention", "problem", "serious"}
SEVERITY_ORDER = {"positive": 0, "neutral": 1, "attention": 2, "problem": 3, "serious": 4}
CONFIDENCE_VALUES = {"low", "medium", "high"}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
SEMANTIC_SOURCES = {"explicit_rule", "local_pattern", "ai_interpretation", "historical_pattern", "combined", "unknown", "deterministic_metric"}
SEMANTIC_DEPTHS = {"direct", "suggestive", "contextual"}

SEMANTIC_TYPES = {"sarcasm", "aggression", "influence", "possible_interest"}
WORK_TYPES = {
    "work_task_ambiguity",
    "work_owner_clarity",
    "work_deadline_clarity",
    "work_answer_completeness",
    "work_unanswered_questions",
    "work_repeated_clarification",
    "work_decision_completion",
    "work_follow_through",
    "work_status_update_quality",
    "work_response_consistency",
    "work_topic_switching",
}


def build_canonical_findings(
    *,
    evidence_findings: Sequence[dict[str, Any]] | None = None,
    semantic_analysis: dict[str, Any] | None = None,
    work_findings: Sequence[dict[str, Any]] | None = None,
    context_category: str = "unknown",
    period_label: str = "",
    language: str = "en",
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(item for item in (evidence_findings or []) if isinstance(item, dict))
    rows.extend(ambiguous_semantic_findings(semantic_analysis or {}, context_category=context_category, period_label=period_label, language=language))
    rows.extend(item for item in (work_findings or []) if isinstance(item, dict))

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = validate_canonical_finding(row, context_category=context_category, period_label=period_label, language=language)
        key = item.get("summary_key") or f"{item['finding_type']}:{item['participant_scope']}:{item['finding_id']}"
        if key in seen:
            existing = next((candidate for candidate in result if candidate.get("summary_key") == key), None)
            if existing and finding_rank(item) > finding_rank(existing):
                result[result.index(existing)] = item
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def validate_canonical_finding(
    row: dict[str, Any],
    *,
    context_category: str = "unknown",
    period_label: str = "",
    language: str = "en",
) -> dict[str, Any]:
    finding_type = str(row.get("finding_type") or "general")
    status = normalize_status(row.get("status") or ("available" if row.get("evidence") or row.get("evidence_count") else "ambiguous"))
    semantic_source = normalize_source(row.get("semantic_source") or row.get("source") or row.get("evidence_source"))
    semantic_depth = normalize_depth(row.get("semantic_depth"))
    confidence = normalize_confidence(row.get("confidence"))
    evidence = validate_evidence(row.get("evidence"))
    evidence_count = safe_int(row.get("evidence_count"))
    if evidence_count <= 0:
        evidence_count = len(evidence)
    participant_scope = str(row.get("participant_scope") or infer_participant_scope(evidence))
    if participant_scope not in {"you", "other", "both", "interaction"}:
        participant_scope = "interaction"

    severity = normalize_severity(row.get("severity"))
    status, severity, confidence = gate_status_and_severity(
        finding_type=finding_type,
        status=status,
        severity=severity,
        confidence=confidence,
        semantic_source=semantic_source,
        semantic_depth=semantic_depth,
        evidence=evidence,
        evidence_count=evidence_count,
    )
    score_effect = allowed_score_effect(
        row.get("score_effect"),
        finding_type=finding_type,
        status=status,
        severity=severity,
        semantic_source=semantic_source,
        semantic_depth=semantic_depth,
        evidence_count=evidence_count,
        evidence=evidence,
    )
    advice_category = str(row.get("advice_category") or advice_category_for_canonical_type(finding_type, row, evidence=evidence))
    summary_key = str(row.get("summary_key") or row.get("semantic_key") or f"{finding_type}:{participant_scope}:{advice_category}")
    finding_id = str(row.get("finding_id") or stable_finding_id(finding_type, summary_key))
    limitations = string_list(row.get("limitations"), limit=5)
    if status != "available" and semantic_source == "local_pattern":
        cautious = t(language, "canonical_local_semantic_limitation")
        if cautious not in limitations:
            limitations.append(cautious)
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "participant_scope": participant_scope,
        "status": status,
        "severity": severity,
        "semantic_source": semantic_source,
        "semantic_depth": semantic_depth,
        "confidence": confidence,
        "evidence_count": evidence_count,
        "evidence_ids": [str(item.get("evidence_id") or "") for item in evidence if item.get("evidence_id")],
        "score_effect": score_effect,
        "advice_category": advice_category,
        "memory_eligible": memory_eligible(status=status, severity=severity, confidence=confidence, semantic_source=semantic_source, semantic_depth=semantic_depth, evidence_count=evidence_count),
        "summary_key": summary_key,
        "title": behavior_first_text(str(row.get("title") or default_title(finding_type, status=status, advice_category=advice_category, language=language))),
        "observation": behavior_first_text(str(row.get("observation") or default_observation(finding_type, evidence_count=evidence_count, language=language))),
        "interpretation": behavior_first_text(str(row.get("interpretation") or row.get("summary") or default_interpretation(finding_type, status=status, semantic_source=semantic_source, language=language))),
        "evidence": evidence,
        "alternative_interpretations": string_list(row.get("alternative_interpretations"), limit=4),
        "limitations": limitations or [t(language, "semantic_scope_limitation")],
        "period_scope": str(row.get("period_scope") or period_label),
        "context_scope": str(row.get("context_scope") or context_category),
        "evidence_scope": normalize_evidence_scope(row.get("evidence_scope") or row.get("scope") or period_label),
    }


def ambiguous_semantic_findings(semantic_analysis: dict[str, Any], *, context_category: str, period_label: str, language: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sarcasm = semantic_analysis.get("sarcasm") if isinstance(semantic_analysis.get("sarcasm"), dict) else {}
    if sarcasm.get("status") == "ambiguous" and safe_int(sarcasm.get("evidence_count")) > 0:
        rows.append(
            {
                "finding_id": "sarcasm_ambiguous_1",
                "finding_type": "sarcasm",
                "participant_scope": "interaction",
                "status": "ambiguous",
                "severity": "neutral",
                "confidence": "low",
                "semantic_source": sarcasm.get("semantic_source") or "local_pattern",
                "semantic_depth": sarcasm.get("semantic_depth") or "suggestive",
                "evidence_count": safe_int(sarcasm.get("evidence_count")),
                "score_effect": -0.1,
                "advice_category": "ambiguous_sarcasm",
                "summary_key": "sarcasm:ambiguous_local",
                "title": t(language, "canonical_title_ambiguous_sarcasm"),
                "observation": t(language, "canonical_observation_ambiguous_sarcasm", count=safe_int(sarcasm.get("evidence_count"))),
                "interpretation": t(language, "canonical_interpretation_ambiguous_sarcasm"),
                "evidence": sarcasm.get("evidence") if isinstance(sarcasm.get("evidence"), list) else [],
                "alternative_interpretations": sarcasm.get("alternative_interpretations") or [t(language, "alternative_shared_humour")],
                "limitations": sarcasm.get("limitations") or [t(language, "canonical_local_semantic_limitation")],
                "period_scope": period_label,
                "context_scope": context_category,
            }
        )
    influence = semantic_analysis.get("influence") if isinstance(semantic_analysis.get("influence"), dict) else {}
    if influence.get("status") == "ambiguous" and safe_int(influence.get("evidence_count")) > 0:
        rows.append(
            {
                "finding_id": "influence_ambiguous_1",
                "finding_type": "influence",
                "participant_scope": "interaction",
                "status": "ambiguous",
                "severity": "neutral",
                "confidence": "low",
                "semantic_source": influence.get("semantic_source") or "local_pattern",
                "semantic_depth": influence.get("semantic_depth") or "suggestive",
                "evidence_count": safe_int(influence.get("evidence_count")),
                "score_effect": -0.1,
                "advice_category": "clarity",
                "summary_key": "influence:ambiguous_local",
                "title": t(language, "canonical_title_ambiguous_influence"),
                "observation": t(language, "canonical_observation_ambiguous_influence", count=safe_int(influence.get("evidence_count"))),
                "interpretation": t(language, "canonical_interpretation_ambiguous_influence"),
                "evidence": influence.get("evidence") if isinstance(influence.get("evidence"), list) else [],
                "alternative_interpretations": influence.get("alternative_interpretations") or [],
                "limitations": influence.get("limitations") or [t(language, "canonical_local_semantic_limitation")],
                "period_scope": period_label,
                "context_scope": context_category,
            }
        )
    return rows


def evidence_findings_from_canonical(findings: Sequence[dict[str, Any]], *, include_ambiguous: bool = True, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        status = str(finding.get("status") or "")
        if status != "available" and not (include_ambiguous and status == "ambiguous"):
            continue
        if status == "ambiguous" and str(finding.get("finding_type")) not in {"sarcasm", "influence"}:
            continue
        rows.append(
            {
                "finding_id": finding.get("finding_id"),
                "finding_type": finding.get("finding_type"),
                "title": finding.get("title"),
                "observation": finding.get("observation"),
                "interpretation": finding.get("interpretation"),
                "confidence": finding.get("confidence"),
                "severity": finding.get("severity"),
                "semantic_key": finding.get("summary_key"),
                "semantic_source": finding.get("semantic_source"),
                "semantic_depth": finding.get("semantic_depth"),
                "evidence": finding.get("evidence") or [],
                "alternative_interpretations": finding.get("alternative_interpretations") or [],
                "limitations": finding.get("limitations") or [],
                "period_scope": finding.get("period_scope"),
                "context_scope": finding.get("context_scope"),
                "evidence_scope": finding.get("evidence_scope"),
                "status": finding.get("status"),
                "score_effect": finding.get("score_effect"),
                "advice_category": finding.get("advice_category"),
                "memory_eligible": finding.get("memory_eligible"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def visible_available_findings(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finding for finding in findings if isinstance(finding, dict) and finding.get("status") == "available"]


def finding_by_id(findings: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(finding.get("finding_id") or ""): finding for finding in findings if isinstance(finding, dict) and finding.get("finding_id")}


def finding_rank(finding: dict[str, Any]) -> tuple[int, int, int, float]:
    return (
        SEVERITY_ORDER.get(str(finding.get("severity") or "neutral"), 0),
        CONFIDENCE_ORDER.get(str(finding.get("confidence") or "low"), 0),
        int(finding.get("evidence_count") or 0),
        abs(float(finding.get("score_effect") or 0.0)),
    )


def gate_status_and_severity(
    *,
    finding_type: str,
    status: str,
    severity: str,
    confidence: str,
    semantic_source: str,
    semantic_depth: str,
    evidence: Sequence[dict[str, Any]],
    evidence_count: int,
) -> tuple[str, str, str]:
    if status in {"insufficient_data", "not_applicable"}:
        return status, "neutral", "low"
    if evidence_count <= 0 and finding_type != "general":
        status = "ambiguous"
        severity = "neutral"
        confidence = "low"
    if status == "ambiguous" and SEVERITY_ORDER.get(severity, 1) > SEVERITY_ORDER["attention"]:
        severity = "attention"
        confidence = "low"
    if semantic_source == "local_pattern" and semantic_depth != "direct" and finding_type in SEMANTIC_TYPES:
        if evidence_count < 2:
            status = "ambiguous"
            severity = "neutral"
            confidence = "low"
        elif SEVERITY_ORDER.get(severity, 1) > SEVERITY_ORDER["attention"]:
            severity = "attention"
            if confidence == "high":
                confidence = "medium"
    if finding_type == "aggression" and not has_aggression_evidence(evidence):
        if severity in {"problem", "serious"}:
            severity = "attention"
        if confidence == "high":
            confidence = "medium"
    if finding_type == "sarcasm" and not has_hostile_sarcasm_evidence(evidence) and "hostile" in " ".join(str(item.get("description") or "") for item in evidence):
        severity = "attention"
    return status, severity, confidence


def allowed_score_effect(
    requested: Any,
    *,
    finding_type: str,
    status: str,
    severity: str,
    semantic_source: str,
    semantic_depth: str,
    evidence_count: int,
    evidence: Sequence[dict[str, Any]],
) -> float:
    if status in {"insufficient_data", "not_applicable"}:
        return 0.0
    default = default_score_effect(finding_type, severity=severity)
    try:
        effect = float(requested) if requested is not None else default
    except (TypeError, ValueError):
        effect = default
    if status == "ambiguous":
        return round(max(-0.2, min(0.1, effect)), 2)
    if finding_type == "sarcasm":
        if semantic_source == "local_pattern" and semantic_depth != "direct":
            effect = max(effect, -0.4)
        if not has_hostile_sarcasm_evidence(evidence):
            effect = max(effect, -0.6)
    if finding_type == "aggression" and not has_aggression_evidence(evidence):
        effect = max(effect, -0.3)
    if semantic_source == "local_pattern" and semantic_depth != "direct" and finding_type in SEMANTIC_TYPES:
        effect = max(effect, -0.4)
    if evidence_count <= 0:
        effect = max(effect, 0.0)
    return round(max(-2.0, min(1.0, effect)), 2)


def default_score_effect(finding_type: str, *, severity: str) -> float:
    if severity == "positive":
        return 0.35
    if severity == "neutral":
        return 0.0
    base = {"attention": -0.35, "problem": -0.85, "serious": -1.4}.get(severity, 0.0)
    if finding_type in {"unanswered_questions", "work_unanswered_questions", "work_repeated_clarification", "work_task_ambiguity", "work_answer_completeness"}:
        return base - 0.15
    if finding_type == "aggression":
        return base - 0.25
    if finding_type == "sarcasm":
        return max(base, -0.6)
    return base


def memory_eligible(*, status: str, severity: str, confidence: str, semantic_source: str, semantic_depth: str, evidence_count: int) -> bool:
    if status != "available" or confidence not in {"medium", "high"} or evidence_count < 2:
        return False
    if semantic_source == "local_pattern" and semantic_depth != "direct":
        return False
    return severity in {"positive", "attention", "problem", "serious", "neutral"}


def advice_category_for_canonical_type(finding_type: str, row: dict[str, Any], *, evidence: Sequence[dict[str, Any]]) -> str:
    if finding_type == "sarcasm":
        text = " ".join(str(row.get(key) or "") for key in ("title", "interpretation", "summary_key")).casefold()
        if "hostile" in text or "вражд" in text:
            return "hostile_sarcasm"
        if str(row.get("status") or "") == "ambiguous":
            return "ambiguous_sarcasm"
        return "sarcasm"
    if finding_type == "aggression":
        return "threat" if has_threat_evidence(evidence) else "aggression"
    if finding_type == "influence":
        text = " ".join(str(row.get(key) or "") for key in ("title", "interpretation", "summary_key")).casefold()
        return "persuasion" if "persuasion" in text or "убежден" in text or "убеждение" in text else "pressure"
    if finding_type in {"unanswered_questions", "work_unanswered_questions"}:
        return "question"
    if finding_type in WORK_TYPES:
        return "task_clarity"
    if finding_type == "possible_interest":
        return "interest"
    return "clarity"


def has_threat_evidence(evidence: Sequence[dict[str, Any]]) -> bool:
    return any("threat" in str(item.get("description") or "").casefold() for item in evidence)


def has_aggression_evidence(evidence: Sequence[dict[str, Any]]) -> bool:
    descriptions = " ".join(str(item.get("description") or "") for item in evidence).casefold()
    return any(token in descriptions for token in ("insult", "threat", "aggressive_command", "urgent_repeated_command"))


def has_hostile_sarcasm_evidence(evidence: Sequence[dict[str, Any]]) -> bool:
    descriptions = " ".join(str(item.get("description") or "") for item in evidence).casefold()
    return "hostile_sarcasm" in descriptions or ("sarcasm" in descriptions and has_aggression_evidence(evidence))


def validate_evidence(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:12], start=1):
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "evidence_id": str(row.get("evidence_id") or f"ev_{index}"),
                "evidence_type": str(row.get("evidence_type") or "semantic_pattern"),
                "source": normalize_source(row.get("source")),
                "semantic_depth": normalize_depth(row.get("semantic_depth")),
                "message_ref": str(row.get("message_ref") or ""),
                "sender": str(row.get("sender") or ""),
                "description": str(row.get("description") or ""),
            }
        )
    return result


def infer_participant_scope(evidence: Sequence[dict[str, Any]]) -> str:
    senders = {str(item.get("sender") or "") for item in evidence if item.get("sender")}
    if senders == {"YOU"}:
        return "you"
    if senders == {"OTHER"}:
        return "other"
    if len(senders) > 1:
        return "both"
    return "interaction"


def stable_finding_id(finding_type: str, summary_key: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in summary_key.casefold()).strip("_")[:40]
    return f"{finding_type}_{cleaned or '1'}"


def normalize_status(value: Any) -> str:
    text = str(value or "insufficient_data")
    return text if text in FINDING_STATUSES else "insufficient_data"


def normalize_severity(value: Any) -> str:
    text = str(value or "neutral")
    return text if text in FINDING_SEVERITIES else "neutral"


def normalize_confidence(value: Any) -> str:
    text = str(value or "low")
    return text if text in CONFIDENCE_VALUES else "low"


def normalize_source(value: Any) -> str:
    text = str(value or "unknown")
    return text if text in SEMANTIC_SOURCES else "unknown"


def normalize_depth(value: Any) -> str:
    text = str(value or "suggestive")
    return text if text in SEMANTIC_DEPTHS else "suggestive"


def normalize_evidence_scope(value: Any) -> str:
    text = str(value or "selected_period").casefold()
    if text in {"full_history", "recent_window", "recurring_across_periods", "selected_period"}:
        return text
    if "full" in text or "вся" in text:
        return "full_history"
    if "recent" in text or "недав" in text:
        return "recent_window"
    if "recurring" in text or "повтор" in text:
        return "recurring_across_periods"
    return "selected_period"


def default_title(finding_type: str, *, status: str, advice_category: str, language: str) -> str:
    key = f"canonical_title_{finding_type}"
    if finding_type == "sarcasm" and advice_category == "ambiguous_sarcasm":
        key = "canonical_title_ambiguous_sarcasm"
    translated = t(language, key)
    return translated if translated != key else t(language, "canonical_title_general")


def default_observation(finding_type: str, *, evidence_count: int, language: str) -> str:
    return t(language, "canonical_observation_count", count=evidence_count)


def default_interpretation(finding_type: str, *, status: str, semantic_source: str, language: str) -> str:
    if status == "ambiguous" and semantic_source == "local_pattern":
        return t(language, "canonical_interpretation_local_ambiguous")
    return t(language, "canonical_interpretation_limited")


def behavior_first_text(text: str) -> str:
    replacements = {
        "possible manipulative pattern": "possible pressure through obligation",
        "clear manipulative pattern": "repeated pressure on choice",
        "manipulative pattern": "pressure pattern",
        "manipulative": "pressure-based",
        "toxic": "harmful",
        "abusive": "aggressive",
        "narcissistic": "self-focused",
        "controlling": "restricting choice",
        "возможный манипулятивный паттерн": "возможное давление через обязательство",
        "ясный манипулятивный паттерн": "повторяющееся давление на возможность выбора",
        "манипулятивный паттерн": "паттерн давления",
        "манипулятивным": "связанным с давлением",
        "манипулятивный": "связанный с давлением",
        "токсичный": "резкий",
        "токсичная": "резкая",
        "абьюзивный": "агрессивный",
        "нарциссический": "эгоцентричный",
        "контролирующий": "ограничивающий выбор",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
        result = result.replace(old.capitalize(), new.capitalize())
    return result


def string_list(value: Any, *, limit: int = 8) -> list[str]:
    rows = value if isinstance(value, list) else []
    return [str(item) for item in rows[:limit] if str(item).strip()]


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
