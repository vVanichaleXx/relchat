from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.semantic_interpretation import validate_evidence_finding


def timeline_events_from_result(result: dict[str, Any], *, language: str = "en") -> list[dict[str, Any]]:
    findings = result.get("canonical_findings") if isinstance(result.get("canonical_findings"), list) else result.get("evidence_findings")
    findings = findings if isinstance(findings, list) else []
    events: list[dict[str, Any]] = []
    for finding in findings[:8]:
        if not isinstance(finding, dict):
            continue
        item = validate_evidence_finding(finding)
        if item.get("status") != "available":
            continue
        event_type = timeline_event_type(item)
        if not event_type:
            continue
        events.append(
            {
                "event_id": f"tl_{item.get('finding_id') or len(events) + 1}",
                "event_type": event_type,
                "title": timeline_event_title(item, language=language),
                "summary": item.get("interpretation") or item.get("observation") or "",
                "confidence": item.get("confidence") or "low",
                "severity": item.get("severity") or "neutral",
                "period_scope": item.get("period_scope") or "",
                "context_scope": item.get("context_scope") or "",
                "evidence_count": len(item.get("evidence") or []),
                "source": "validated_finding",
                "limitations": item.get("limitations") or [],
            }
        )
    return validate_timeline_events(events)


def timeline_event_type(finding: dict[str, Any]) -> str:
    finding_type = str(finding.get("finding_type") or "")
    title = str(finding.get("title") or "").casefold()
    if finding_type == "sarcasm":
        if "playful" in title or "игров" in title:
            return "semantic_sarcasm_playful"
        if "dismissive" in title or "обесцен" in title:
            return "semantic_sarcasm_dismissive"
        return "semantic_sarcasm_changed"
    if finding_type == "aggression":
        return "semantic_aggression_visible"
    if finding_type == "influence":
        if "pressure" in title or "давлен" in title:
            return "semantic_pressure_pattern"
        if "manip" in title or "манип" in title:
            return "semantic_influence_pattern"
        return "semantic_persuasion_visible"
    if finding_type == "possible_interest":
        return "semantic_possible_interest"
    return ""


def timeline_event_title(finding: dict[str, Any], *, language: str) -> str:
    event_type = timeline_event_type(finding)
    key = f"timeline_story_{event_type}"
    translated = t(language, key)
    return translated if translated != key else str(finding.get("title") or t(language, "timeline_story_event"))


def validate_timeline_events(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        confidence = str(row.get("confidence") or "low")
        if confidence not in {"low", "medium", "high"}:
            confidence = "low"
        severity = str(row.get("severity") or "neutral")
        if severity not in {"positive", "neutral", "attention", "problem", "serious"}:
            severity = "neutral"
        result.append(
            {
                "event_id": str(row.get("event_id") or f"tl_{len(result) + 1}"),
                "event_type": str(row.get("event_type") or "semantic_event"),
                "title": str(row.get("title") or ""),
                "summary": str(row.get("summary") or ""),
                "confidence": confidence,
                "severity": severity,
                "period_scope": str(row.get("period_scope") or ""),
                "context_scope": str(row.get("context_scope") or ""),
                "evidence_count": safe_int(row.get("evidence_count")),
                "source": str(row.get("source") or "validated_finding"),
                "limitations": [str(item) for item in (row.get("limitations") or [])[:6] if str(item).strip()],
            }
        )
    return result


def build_communication_timeline(analyses: Sequence[dict[str, Any]], *, language: str = "en") -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for analysis in analyses:
        result = analysis.get("result") if isinstance(analysis.get("result"), dict) else analysis
        for event in result.get("communication_timeline_events") or []:
            if isinstance(event, dict):
                events.append(event)
    events = validate_timeline_events(events)
    return {
        "timeline_id": "communication_timeline",
        "status": "available" if events else "insufficient_data",
        "events": events,
        "limitations": [t(language, "timeline_privacy_note")],
    }


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
