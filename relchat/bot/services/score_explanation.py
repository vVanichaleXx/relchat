from __future__ import annotations

from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.canonical_findings import SEVERITY_ORDER, finding_by_id


POSITIVE_DIMENSION_KEYS = {
    "reciprocity",
    "initiative_balance",
    "reply_consistency",
    "reply_quality",
    "respectfulness",
    "topic_continuation",
    "question_engagement",
    "planning_cooperation",
    "emotional_acknowledgement",
}
RISK_DIMENSION_KEYS = {
    "pressure_risk",
    "hostility",
    "dismissiveness",
    "unanswered_question_rate",
    "sarcasm_intensity",
}


def build_score_explanation(
    *,
    dimensions: dict[str, Any],
    score_state: dict[str, Any],
    language: str = "en",
    semantic_mode: str = "local",
    historical_adjustment: str | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    score = score_state.get("score")
    positive = positive_contributors(dimensions, language=language)
    negative = negative_contributors_from_findings(findings or [], language=language) if findings is not None else negative_contributors(dimensions, language=language)
    unavailable = unavailable_dimensions(dimensions, language=language)
    return {
        "title": t(language, "score_explanation_title", score=f"{float(score):.1f}") if isinstance(score, (int, float)) else t(language, "score_explanation_title_unavailable"),
        "positive_contributors": positive,
        "negative_contributors": negative,
        "unavailable_dimensions": unavailable,
        "confidence_cap": score_cap_text(score_state, language=language),
        "semantic_mode_cap": semantic_mode_cap_text(score_state, semantic_mode=semantic_mode, language=language),
        "historical_adjustment": historical_adjustment or "",
        "balance_note": t(language, "score_explanation_balance_note") if reciprocity_without_semantics(dimensions) else "",
        "formula_hidden": True,
    }


def validate_score_explanation_against_findings(value: dict[str, Any], findings: list[dict[str, Any]], *, language: str = "en") -> dict[str, Any]:
    row = dict(value or {})
    valid = finding_by_id(findings)
    cleaned = []
    for item in row.get("negative_contributors") if isinstance(row.get("negative_contributors"), list) else []:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        finding_id = str(item.get("finding_id") or "")
        finding = valid.get(finding_id)
        if not finding or finding.get("status") != "available":
            continue
        if int(finding.get("evidence_count") or 0) <= 0:
            continue
        severity = str(item.get("severity") or finding.get("severity") or "neutral")
        if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(str(finding.get("severity") or "neutral"), 0):
            severity = str(finding.get("severity") or "neutral")
        cleaned.append(
            {
                "text": str(item.get("text") or score_text_for_finding(finding, language=language)),
                "finding_id": finding_id,
                "finding_type": str(finding.get("finding_type") or ""),
                "severity": severity,
                "score_effect": float(finding.get("score_effect") or 0.0),
            }
        )
    rebuilt = negative_contributors_from_findings(findings, language=language)
    row["negative_contributors"] = cleaned or rebuilt
    return row


def positive_contributors(dimensions: dict[str, Any], *, language: str) -> list[str]:
    rows: list[tuple[float, str]] = []
    for key, row in dimensions.items():
        if key not in POSITIVE_DIMENSION_KEYS or not isinstance(row, dict):
            continue
        score = row.get("score")
        if not isinstance(score, (int, float)) or float(score) < 6.5:
            continue
        if key == "reciprocity" and only_volume_balance_available(dimensions):
            continue
        rows.append((float(score), t(language, f"score_positive_{key}")))
    return [text for _, text in sorted(rows, reverse=True)[:3]]


def negative_contributors(dimensions: dict[str, Any], *, language: str) -> list[str]:
    rows: list[tuple[float, str]] = []
    for key, row in dimensions.items():
        if not isinstance(row, dict):
            continue
        score = row.get("score")
        if not isinstance(score, (int, float)):
            continue
        if key in RISK_DIMENSION_KEYS and float(score) >= 3.0:
            rows.append((float(score), t(language, f"score_negative_{key}")))
        elif key in POSITIVE_DIMENSION_KEYS and key != "reciprocity" and float(score) <= 4.5:
            rows.append((10.0 - float(score), t(language, f"score_low_{key}")))
    return [text for _, text in sorted(rows, reverse=True)[:4]]


def negative_contributors_from_findings(findings: list[dict[str, Any]], *, language: str) -> list[dict[str, Any]]:
    rows: list[tuple[float, dict[str, Any]]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if finding.get("status") != "available":
            continue
        effect = float(finding.get("score_effect") or 0.0)
        if effect > -0.25:
            continue
        if int(finding.get("evidence_count") or 0) <= 0:
            continue
        rows.append(
            (
                abs(effect),
                {
                    "text": score_text_for_finding(finding, language=language),
                    "finding_id": str(finding.get("finding_id") or ""),
                    "finding_type": str(finding.get("finding_type") or ""),
                    "severity": str(finding.get("severity") or "neutral"),
                    "score_effect": round(effect, 2),
                },
            )
        )
    return [item for _, item in sorted(rows, key=lambda row: row[0], reverse=True)[:4]]


def score_text_for_finding(finding: dict[str, Any], *, language: str) -> str:
    finding_type = str(finding.get("finding_type") or "")
    advice_category = str(finding.get("advice_category") or "")
    if finding_type in {"work_task_ambiguity", "work_owner_clarity", "work_deadline_clarity"}:
        return t(language, "score_negative_work_task_clarity")
    if finding_type in {"work_unanswered_questions", "unanswered_questions"}:
        return t(language, "score_negative_work_questions" if str(finding.get("context_scope")) == "work" else "score_negative_unanswered_question_rate")
    if finding_type == "work_repeated_clarification":
        return t(language, "score_negative_work_clarification")
    if finding_type == "work_answer_completeness":
        return t(language, "score_negative_work_answer_completeness")
    if finding_type == "sarcasm":
        if advice_category == "hostile_sarcasm":
            return t(language, "score_negative_hostile_sarcasm")
        return t(language, "score_negative_supported_sarcasm")
    if finding_type == "aggression":
        return t(language, "score_negative_aggression")
    if finding_type == "influence":
        return t(language, "score_negative_pressure_risk")
    title = str(finding.get("title") or "")
    return title or t(language, "score_negative_supported_finding")


def unavailable_dimensions(dimensions: dict[str, Any], *, language: str) -> list[str]:
    important = []
    for key in ("respectfulness", "emotional_acknowledgement", "sarcasm_intensity", "hostility", "dismissiveness"):
        row = dimensions.get(key)
        if isinstance(row, dict) and row.get("score") is None:
            important.append(t(language, f"score_unavailable_{key}"))
    return important[:4]


def score_cap_text(score_state: dict[str, Any], *, language: str) -> str:
    reason = str(score_state.get("cap_reason") or "")
    key = {
        "shallow_local_metrics": "ai_score_cap_shallow",
        "deterministic_without_text_interpretation": "ai_score_cap_deterministic",
        "sampled_ai_text_coverage": "ai_score_cap_sampled_ai",
        "low_context_confidence": "ai_score_cap_context",
        "limited_independent_dimensions": "ai_score_cap_limited_dimensions",
        "work_local_effectiveness_cap": "score_explanation_work_local_cap",
        "work_semantic_effectiveness": "score_explanation_work_semantic_cap",
        "too_few_supported_dimensions": "score_explanation_low_independence",
        "too_few_messages": "ai_score_insufficient_explanation",
    }.get(reason)
    return t(language, key) if key else ""


def semantic_mode_cap_text(score_state: dict[str, Any], *, semantic_mode: str, language: str) -> str:
    if semantic_mode == "ai":
        return t(language, "score_explanation_ai_semantic_mode")
    if str(score_state.get("cap_reason") or "") in {"shallow_local_metrics", "deterministic_without_text_interpretation", "work_local_effectiveness_cap"}:
        return t(language, "score_explanation_local_semantic_mode")
    return ""


def only_volume_balance_available(dimensions: dict[str, Any]) -> bool:
    available_positive = [
        key
        for key in POSITIVE_DIMENSION_KEYS
        if isinstance(dimensions.get(key), dict)
        and dimensions[key].get("score") is not None
        and dimensions[key].get("available") is not False
    ]
    return available_positive == ["reciprocity"] or set(available_positive) <= {"reciprocity", "reply_consistency", "topic_continuation"}


def reciprocity_without_semantics(dimensions: dict[str, Any]) -> bool:
    reciprocity = dimensions.get("reciprocity")
    if not isinstance(reciprocity, dict) or reciprocity.get("score") is None:
        return False
    semantic_available = any(
        isinstance(dimensions.get(key), dict) and dimensions[key].get("score") is not None
        for key in ("respectfulness", "emotional_acknowledgement", "hostility", "dismissiveness", "sarcasm_intensity")
    )
    return not semantic_available
