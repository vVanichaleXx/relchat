from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.advice_routing import build_advice_for_finding
from relchat.bot.services.canonical_findings import SEVERITY_ORDER, finding_by_id
from relchat.bot.services.pattern_selector import is_generic_pattern


ACTIONABLE_TYPES = {
    "unanswered_questions",
    "work_unanswered_questions",
    "work_task_ambiguity",
    "work_repeated_clarification",
    "work_answer_completeness",
    "work_owner_clarity",
    "work_deadline_clarity",
    "sarcasm",
    "aggression",
    "influence",
    "possible_interest",
}


def build_personalized_feedback(
    *,
    selected_patterns: Sequence[dict[str, Any]],
    canonical_findings: Sequence[dict[str, Any]],
    personal_profile: dict[str, Any] | None = None,
    context_category: str = "unknown",
    language: str = "en",
) -> dict[str, Any]:
    profile = personal_profile if isinstance(personal_profile, dict) else {}
    finding = strongest_actionable_finding(canonical_findings, selected_patterns)
    if not finding:
        return no_action_feedback(
            context_category=context_category,
            reason=t(language, "feedback_omitted_no_actionable_finding"),
            language=language,
        )
    if is_weak_ambiguous_semantic(finding):
        return no_action_feedback(
            context_category=context_category,
            reason=t(language, "feedback_omitted_weak_semantic"),
            related_finding_id=str(finding.get("finding_id") or ""),
            language=language,
        )
    category = advice_category(finding, context_category=context_category)
    style_hint = user_style_hint(selected_patterns, profile=profile, context_category=context_category, language=language)
    recommendation, explanation, example = feedback_text(
        finding,
        category=category,
        context_category=context_category,
        style_hint=style_hint,
        language=language,
    )
    return {
        "action_needed": True,
        "finding_id": str(finding.get("finding_id") or ""),
        "finding_type": str(finding.get("finding_type") or ""),
        "category": category,
        "severity": str(finding.get("severity") or "neutral"),
        "recommendation": recommendation,
        "reason": explanation,
        "example": example,
        "style_fit": style_hint,
        "omitted_reason": "",
    }


def validate_personalized_feedback(value: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    row = value if isinstance(value, dict) else fallback or {}
    return {
        "action_needed": bool(row.get("action_needed")),
        "finding_id": str(row.get("finding_id") or ""),
        "finding_type": str(row.get("finding_type") or ""),
        "category": str(row.get("category") or ""),
        "severity": normalize_severity(row.get("severity")),
        "recommendation": clean(row.get("recommendation"), 360),
        "reason": clean(row.get("reason"), 520),
        "example": clean(row.get("example"), 260),
        "style_fit": clean(row.get("style_fit"), 360),
        "omitted_reason": clean(row.get("omitted_reason"), 260),
    }


def feedback_to_advice(
    feedback: dict[str, Any],
    canonical_findings: Sequence[dict[str, Any]],
    *,
    context_category: str,
    language: str = "en",
) -> list[dict[str, Any]]:
    if not isinstance(feedback, dict) or not feedback.get("action_needed"):
        return []
    findings = finding_by_id(canonical_findings)
    finding = findings.get(str(feedback.get("finding_id") or ""))
    if not finding:
        return []
    category = str(feedback.get("category") or advice_category(finding, context_category=context_category))
    base = build_advice_for_finding(
        finding,
        category=category,
        context_category=context_category,
        priority=1,
        language=language,
    )
    return [
        {
            **base,
            "title": feedback.get("recommendation") or base["title"],
            "explanation": feedback.get("reason") or base["explanation"],
            "example": feedback.get("example") or base["example"],
            "category": category,
        }
    ]


def strongest_actionable_finding(canonical_findings: Sequence[dict[str, Any]], selected_patterns: Sequence[dict[str, Any]]) -> dict[str, Any]:
    selected_ids = [str(pattern.get("finding_id") or "") for pattern in selected_patterns if isinstance(pattern, dict) and pattern.get("finding_id")]
    by_id = finding_by_id(canonical_findings)
    candidates = []
    for finding in canonical_findings:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("status") or "") not in {"available", "ambiguous"}:
            continue
        if str(finding.get("finding_type") or "") not in ACTIONABLE_TYPES:
            continue
        bonus = 0.25 if str(finding.get("finding_id") or "") in selected_ids else 0.0
        candidates.append((finding_score(finding) + bonus, finding))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def finding_score(finding: dict[str, Any]) -> float:
    return (
        SEVERITY_ORDER.get(str(finding.get("severity") or "neutral"), 1) * 0.3
        + {"low": 0.0, "medium": 0.15, "high": 0.25}.get(str(finding.get("confidence") or "low"), 0.0)
        + min(0.25, int(finding.get("evidence_count") or 0) / 20.0)
    )


def is_weak_ambiguous_semantic(finding: dict[str, Any]) -> bool:
    return (
        str(finding.get("status") or "") == "ambiguous"
        and str(finding.get("semantic_source") or "") == "local_pattern"
        and str(finding.get("finding_type") or "") in {"sarcasm", "influence", "possible_interest"}
    )


def advice_category(finding: dict[str, Any], *, context_category: str) -> str:
    explicit = str(finding.get("advice_category") or "")
    if explicit:
        return explicit
    finding_type = str(finding.get("finding_type") or "")
    if finding_type.startswith("work_"):
        return "task_clarity"
    if finding_type in {"unanswered_questions", "work_unanswered_questions"}:
        return "question"
    if finding_type == "sarcasm":
        return "sarcasm"
    if finding_type == "aggression":
        return "aggression"
    if finding_type == "influence":
        return "pressure"
    if finding_type == "possible_interest":
        return "interest"
    return "task_clarity" if context_category == "work" else "clarity"


def user_style_hint(
    selected_patterns: Sequence[dict[str, Any]],
    *,
    profile: dict[str, Any],
    context_category: str,
    language: str,
) -> str:
    for pattern in selected_patterns:
        if isinstance(pattern, dict) and pattern.get("participant_scope") == "you" and not is_generic_pattern(pattern):
            return str(pattern.get("observation") or "")
    for row in profile.get("dimensions") if isinstance(profile.get("dimensions"), list) else []:
        if not isinstance(row, dict):
            continue
        observation = str(row.get("observation") or "")
        if observation:
            return observation
    if context_category == "work":
        return t(language, "feedback_style_fit_work_limited")
    return t(language, "feedback_style_fit_limited")


def feedback_text(
    finding: dict[str, Any],
    *,
    category: str,
    context_category: str,
    style_hint: str,
    language: str,
) -> tuple[str, str, str]:
    finding_type = str(finding.get("finding_type") or "")
    if context_category == "work" and finding_type in {"work_task_ambiguity", "work_owner_clarity", "work_deadline_clarity"}:
        if "длин" in style_hint.casefold() or "detail" in style_hint.casefold() or "подробнее" in style_hint.casefold():
            return (
                t(language, "feedback_work_action_first_title"),
                t(language, "feedback_work_action_first_reason"),
                t(language, "feedback_work_action_first_example"),
            )
        return (
            t(language, "feedback_work_task_title"),
            t(language, "feedback_work_task_reason"),
            t(language, "feedback_work_task_example"),
        )
    if finding_type in {"work_unanswered_questions", "unanswered_questions"}:
        key = "feedback_work_question" if context_category == "work" else "feedback_question"
        return (t(language, f"{key}_title"), t(language, f"{key}_reason"), t(language, f"{key}_example"))
    if finding_type == "work_repeated_clarification":
        return (
            t(language, "feedback_work_clarification_title"),
            t(language, "feedback_work_clarification_reason"),
            t(language, "feedback_work_clarification_example"),
        )
    if finding_type == "sarcasm":
        return (
            t(language, "feedback_sarcasm_title"),
            t(language, "feedback_sarcasm_reason"),
            t(language, "feedback_sarcasm_example"),
        )
    if finding_type == "aggression":
        return (
            t(language, "feedback_aggression_title"),
            t(language, "feedback_aggression_reason"),
            t(language, "feedback_aggression_example"),
        )
    if finding_type == "influence":
        return (
            t(language, "feedback_pressure_title"),
            t(language, "feedback_pressure_reason"),
            t(language, "feedback_pressure_example"),
        )
    if finding_type == "possible_interest":
        return (
            t(language, "feedback_interest_title"),
            t(language, "feedback_interest_reason"),
            t(language, "feedback_interest_example"),
        )
    return (
        t(language, "feedback_clarity_title"),
        t(language, "feedback_clarity_reason"),
        t(language, "feedback_clarity_example"),
    )


def no_action_feedback(*, context_category: str, reason: str, language: str, related_finding_id: str = "") -> dict[str, Any]:
    recommendation = (
        t(language, "feedback_no_action_work") if context_category == "work" else t(language, "feedback_no_action_general")
    )
    return {
        "action_needed": False,
        "finding_id": related_finding_id,
        "finding_type": "",
        "category": "",
        "severity": "neutral",
        "recommendation": recommendation,
        "reason": reason,
        "example": "",
        "style_fit": "",
        "omitted_reason": reason,
    }


def normalize_severity(value: Any) -> str:
    text = str(value or "neutral")
    return text if text in SEVERITY_ORDER else "neutral"


def clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]
