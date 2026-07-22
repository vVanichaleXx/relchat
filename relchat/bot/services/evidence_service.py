from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.semantic_interpretation import validate_evidence_finding


def validate_evidence_findings(value: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    return [validate_evidence_finding(row) for row in rows[:limit] if isinstance(row, dict)]


def build_why_conclusion(finding: dict[str, Any], *, language: str = "en") -> dict[str, Any]:
    item = validate_evidence_finding(finding)
    evidence = item.get("evidence") or []
    return {
        "title": item.get("title") or t(language, "why_conclusion_title"),
        "observed": item.get("observation") or t(language, "why_observed_limited"),
        "interpretation": item.get("interpretation") or t(language, "why_interpretation_limited"),
        "supporting_evidence": [evidence_line(row, language=language) for row in evidence[:6]],
        "contradicting_evidence": [],
        "alternative_interpretations": item.get("alternative_interpretations") or [],
        "confidence": item.get("confidence") or "low",
        "evidence_scope": item.get("evidence_scope") or "selected_period",
        "limitations": item.get("limitations") or [t(language, "semantic_scope_limitation")],
    }


def build_why_conclusion_panels(result: dict[str, Any], *, language: str = "en", limit: int = 5) -> list[dict[str, Any]]:
    findings = validate_evidence_findings(result.get("evidence_findings") or (result.get("semantic_analysis") or {}).get("findings"), limit=limit)
    return [build_why_conclusion(finding, language=language) for finding in findings if finding.get("title")]


def evidence_line(row: dict[str, Any], *, language: str) -> str:
    evidence_type = t(language, f"evidence_type_{row.get('evidence_type') or 'semantic_pattern'}")
    sender = t(language, "participant_you") if row.get("sender") == "YOU" else t(language, "participant_other")
    description = localized_evidence_description(str(row.get("description") or ""), language=language)
    if description:
        return t(language, "evidence_line", evidence_type=evidence_type, sender=sender, description=description)
    return t(language, "evidence_line_without_description", evidence_type=evidence_type, sender=sender)


def localized_evidence_description(value: str, *, language: str) -> str:
    if not value:
        return ""
    key = f"evidence_desc_{value}"
    translated = t(language, key)
    return translated if translated != key else value.replace("_", " ")


def strongest_evidence_advice(findings: Sequence[dict[str, Any]]) -> dict[str, str] | None:
    severity_order = {"problem": 3, "attention": 2, "neutral": 1, "positive": 0}
    confidence_order = {"high": 2, "medium": 1, "low": 0}
    best: dict[str, Any] | None = None
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        advice = finding.get("advice") if isinstance(finding.get("advice"), dict) else {}
        if not advice.get("title") and not advice.get("explanation"):
            continue
        if best is None:
            best = finding
            continue
        current_key = (
            severity_order.get(str(finding.get("severity") or "neutral"), 0),
            confidence_order.get(str(finding.get("confidence") or "low"), 0),
            len(finding.get("evidence") or []),
        )
        best_key = (
            severity_order.get(str(best.get("severity") or "neutral"), 0),
            confidence_order.get(str(best.get("confidence") or "low"), 0),
            len(best.get("evidence") or []),
        )
        if current_key > best_key:
            best = finding
    if not best:
        return None
    advice = best.get("advice") if isinstance(best.get("advice"), dict) else {}
    return {
        "title": str(advice.get("title") or ""),
        "explanation": str(advice.get("explanation") or ""),
    }
