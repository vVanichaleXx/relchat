from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.canonical_findings import SEVERITY_ORDER, has_threat_evidence


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
TYPE_CATEGORY = {
    "sarcasm": "sarcasm",
    "aggression": "aggression",
    "influence": "pressure",
    "unanswered_questions": "question",
    "work_task_ambiguity": "task_clarity",
    "possible_interest": "interest",
}
ACTIONABLE_TYPES = {
    "sarcasm",
    "aggression",
    "influence",
    "unanswered_questions",
    "work_unanswered_questions",
    "work_task_ambiguity",
    "work_owner_clarity",
    "work_deadline_clarity",
    "work_answer_completeness",
    "work_repeated_clarification",
    "work_follow_through",
    "work_status_update_quality",
    "possible_interest",
}


def route_advice(
    findings: Sequence[dict[str, Any]],
    *,
    context_category: str,
    language: str = "en",
    fallback: Sequence[dict[str, Any]] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    ranked = ranked_actionable_findings(findings)
    rows: list[dict[str, Any]] = []
    used_targets: set[str] = set()
    for finding in ranked:
        category = advice_category_for_finding(finding, context_category=context_category)
        target = f"{finding.get('finding_type')}:{category}"
        if target in used_targets:
            continue
        used_targets.add(target)
        rows.append(build_advice_for_finding(finding, category=category, context_category=context_category, priority=len(rows) + 1, language=language))
        if len(rows) >= limit:
            break
    if rows:
        return validate_advice_routes(rows, ranked, language=language)[:limit]
    neutral = list(fallback or [])
    if neutral:
        normalized = []
        for index, item in enumerate(neutral[:limit], start=1):
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "priority": index,
                    "finding_id": str(item.get("finding_id") or "general"),
                    "finding_type": str(item.get("finding_type") or "general"),
                    "finding_severity": "neutral",
                    "evidence_source": str(item.get("evidence_source") or "local_pattern"),
                    "context_category": context_category,
                    "category": str(item.get("category") or "clarity"),
                    "severity": "neutral",
                    "title": str(item.get("title") or t(language, "advice_clarity_title")),
                    "explanation": str(item.get("explanation") or t(language, "advice_clarity_explanation")),
                    "example": str(item.get("example") or ""),
                }
            )
        if normalized:
            return normalized
    return [
        {
            "priority": 1,
            "finding_id": "general",
            "finding_type": "general",
            "finding_severity": "neutral",
            "evidence_source": "local_pattern",
            "context_category": context_category,
            "category": "clarity",
            "severity": "neutral",
            "title": t(language, "advice_clarity_title"),
            "explanation": t(language, "advice_clarity_explanation"),
            "example": "",
        }
    ]


def leading_advice_finding(findings: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ranked = ranked_actionable_findings(findings)
    return ranked[0] if ranked else {}


def ranked_actionable_findings(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            finding
            for finding in findings
            if isinstance(finding, dict)
            and str(finding.get("finding_type") or "") in ACTIONABLE_TYPES
            and str(finding.get("status") or "available") in {"available", "ambiguous"}
        ],
        key=finding_rank,
        reverse=True,
    )


def weak_ambiguous_semantic(finding: dict[str, Any]) -> bool:
    return (
        str(finding.get("status") or "") == "ambiguous"
        and str(finding.get("semantic_source") or "") == "local_pattern"
        and str(finding.get("finding_type") or "") in {"sarcasm", "influence", "possible_interest"}
    )


def finding_rank(finding: dict[str, Any]) -> tuple[int, int, int]:
    return (
        SEVERITY_ORDER.get(str(finding.get("severity") or "neutral"), 0),
        CONFIDENCE_ORDER.get(str(finding.get("confidence") or "low"), 0),
        len(finding.get("evidence") or []),
    )


def advice_category_for_finding(finding: dict[str, Any], *, context_category: str) -> str:
    explicit = str(finding.get("advice_category") or "")
    if explicit:
        return explicit
    finding_type = str(finding.get("finding_type") or "general")
    if finding_type == "influence":
        title = f"{finding.get('title') or ''} {finding.get('interpretation') or ''}".casefold()
        if "persuasion" in title or "убежден" in title or "убеждение" in title:
            return "persuasion"
        return "pressure"
    if finding_type == "general" and context_category == "work":
        return "task_clarity"
    return TYPE_CATEGORY.get(finding_type, "clarity")


def build_advice_for_finding(
    finding: dict[str, Any],
    *,
    category: str,
    context_category: str,
    priority: int,
    language: str,
) -> dict[str, Any]:
    key = {
        "ambiguous_sarcasm": "advice_route_ambiguous_sarcasm",
        "sarcasm": "advice_route_sarcasm",
        "hostile_sarcasm": "advice_route_hostile_sarcasm",
        "aggression": "advice_route_aggression",
        "threat": "advice_route_threat",
        "pressure": "advice_route_pressure",
        "persuasion": "advice_route_persuasion",
        "question": "advice_route_question",
        "task_clarity": "advice_route_work",
        "interest": "advice_route_interest",
    }.get(category, "advice_route_clarity")
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), list) else []
    source = str(finding.get("semantic_source") or finding.get("evidence_source") or (evidence[0].get("source") if evidence else "local_pattern"))
    severity = str(finding.get("severity") or "neutral")
    return {
        "priority": priority,
        "finding_id": str(finding.get("finding_id") or "general"),
        "finding_type": str(finding.get("finding_type") or "general"),
        "finding_severity": severity if severity in SEVERITY_ORDER else "neutral",
        "evidence_source": source,
        "context_category": context_category,
        "category": category,
        "severity": severity if severity in SEVERITY_ORDER else "neutral",
        "title": t(language, f"{key}_title"),
        "explanation": t(language, f"{key}_explanation"),
        "example": t(language, f"{key}_example"),
    }


def validate_advice_routes(
    advice: Sequence[dict[str, Any]],
    findings: Sequence[dict[str, Any]],
    *,
    language: str = "en",
) -> list[dict[str, Any]]:
    finding_by_id = {str(finding.get("finding_id") or ""): finding for finding in findings if isinstance(finding, dict)}
    result: list[dict[str, Any]] = []
    for index, item in enumerate(advice[:3], start=1):
        if not isinstance(item, dict):
            continue
        finding_id = str(item.get("finding_id") or "")
        if finding_by_id and finding_id not in finding_by_id:
            continue
        finding = finding_by_id.get(finding_id) or {}
        finding_type = str(item.get("finding_type") or finding.get("finding_type") or "general")
        category = str(item.get("category") or advice_category_for_finding(finding, context_category=str(item.get("context_category") or "unknown")))
        if finding and not category_supports_finding(category, finding_type):
            continue
        if category == "threat" and not has_threat_evidence(finding.get("evidence") if isinstance(finding.get("evidence"), list) else []):
            continue
        if category == "aggression" and finding_type != "aggression":
            continue
        evidence_severity = str(finding.get("severity") or item.get("finding_severity") or "neutral")
        severity = clamp_advice_severity(str(item.get("severity") or evidence_severity), evidence_severity)
        result.append(
            {
                "priority": safe_priority(item.get("priority"), fallback=index),
                "finding_id": finding_id or "general",
                "finding_type": finding_type,
                "finding_severity": evidence_severity if evidence_severity in SEVERITY_ORDER else "neutral",
                "evidence_source": str(item.get("evidence_source") or "local_pattern"),
                "context_category": str(item.get("context_category") or ""),
                "category": category,
                "severity": severity,
                "title": str(item.get("title") or t(language, "advice_clarity_title")),
                "explanation": str(item.get("explanation") or t(language, "advice_clarity_explanation")),
                "example": str(item.get("example") or ""),
            }
        )
    return sorted(result, key=lambda row: int(row.get("priority") or 99))[:3]


def category_supports_finding(category: str, finding_type: str) -> bool:
    allowed = {
        "ambiguous_sarcasm": {"sarcasm"},
        "sarcasm": {"sarcasm"},
        "hostile_sarcasm": {"sarcasm"},
        "aggression": {"aggression"},
        "threat": {"aggression"},
        "pressure": {"influence"},
        "persuasion": {"influence"},
        "question": {"unanswered_questions", "work_unanswered_questions"},
        "task_clarity": {
            "work_task_ambiguity",
            "work_owner_clarity",
            "work_deadline_clarity",
            "work_answer_completeness",
            "work_repeated_clarification",
            "work_unanswered_questions",
            "work_follow_through",
            "work_status_update_quality",
            "general",
        },
        "interest": {"possible_interest"},
        "clarity": {"general", "unanswered_questions", "work_task_ambiguity", "work_decision_completion", "work_response_consistency"},
    }
    return finding_type in allowed.get(category, {"general"})


def clamp_advice_severity(value: str, evidence_severity: str) -> str:
    if value not in SEVERITY_ORDER:
        value = evidence_severity if evidence_severity in SEVERITY_ORDER else "neutral"
    if evidence_severity not in SEVERITY_ORDER:
        return value
    if SEVERITY_ORDER[value] > SEVERITY_ORDER[evidence_severity]:
        return evidence_severity
    return value


def safe_priority(value: Any, *, fallback: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return fallback
