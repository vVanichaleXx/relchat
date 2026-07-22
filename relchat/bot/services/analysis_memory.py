from __future__ import annotations

from collections.abc import Sequence
from typing import Any


PROMOTABLE_TYPES = {"sarcasm", "aggression", "influence", "possible_interest", "profile"}


def memory_candidates_from_analysis(result: dict[str, Any]) -> list[dict[str, Any]]:
    findings = result.get("canonical_findings") if isinstance(result.get("canonical_findings"), list) else result.get("evidence_findings")
    findings = findings if isinstance(findings, list) else []
    candidates: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_type = str(finding.get("finding_type") or "")
        confidence = str(finding.get("confidence") or "low")
        evidence = finding.get("evidence") if isinstance(finding.get("evidence"), list) else []
        semantic_source = str(finding.get("semantic_source") or finding.get("source") or "")
        semantic_depth = str(finding.get("semantic_depth") or "")
        if finding.get("memory_eligible") is False:
            continue
        if str(finding.get("status") or "available") != "available":
            continue
        if finding_type not in PROMOTABLE_TYPES or confidence not in {"medium", "high"}:
            continue
        if semantic_source == "local_pattern" and semantic_depth != "direct":
            continue
        if confidence == "medium" and len(evidence) < 2:
            continue
        candidates.append(
            {
                "memory_key": memory_key_for_finding(finding),
                "category": finding_type,
                "summary": str(finding.get("title") or finding.get("interpretation") or ""),
                "confidence": confidence,
                "evidence_count": len(evidence),
                "status": "active",
                "source": "validated_finding",
                "metadata": {
                    "finding_id": finding.get("finding_id"),
                    "severity": finding.get("severity"),
                    "period_scope": finding.get("period_scope"),
                    "context_scope": finding.get("context_scope"),
                },
            }
        )
    return candidates


def memory_key_for_finding(finding: dict[str, Any]) -> str:
    finding_type = str(finding.get("finding_type") or "general")
    title = str(finding.get("title") or "").casefold()
    if "playful" in title or "игров" in title:
        subtype = "playful"
    elif "dismissive" in title or "обесцен" in title:
        subtype = "dismissive"
    elif "pressure" in title or "давлен" in title:
        subtype = "pressure"
    elif "interest" in title or "заинтерес" in title:
        subtype = "interest"
    elif "aggression" in title or "агресс" in title:
        subtype = "aggression"
    else:
        subtype = "general"
    return f"{finding_type}:{subtype}"


def merge_memory(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return {
            **candidate,
            "occurrence_count": 1,
            "active": should_promote_candidate(candidate, occurrence_count=1),
            "contradiction_count": 0,
        }
    contradiction = is_contradictory(existing, candidate)
    occurrence_count = int(existing.get("occurrence_count") or 0)
    contradiction_count = int(existing.get("contradiction_count") or 0)
    if contradiction:
        contradiction_count += 1
        active = contradiction_count < max(1, occurrence_count)
        return {
            **existing,
            "confidence": weaken_confidence(str(existing.get("confidence") or "low")),
            "active": active,
            "contradiction_count": contradiction_count,
            "metadata": {**(existing.get("metadata") or {}), "last_contradiction": candidate.get("memory_key")},
        }
    occurrence_count += 1
    confidence = stronger_confidence(str(existing.get("confidence") or "low"), str(candidate.get("confidence") or "low"))
    return {
        **existing,
        "summary": candidate.get("summary") or existing.get("summary"),
        "confidence": confidence,
        "evidence_count": int(existing.get("evidence_count") or 0) + int(candidate.get("evidence_count") or 0),
        "occurrence_count": occurrence_count,
        "active": should_promote_candidate(candidate, occurrence_count=occurrence_count),
        "contradiction_count": contradiction_count,
        "metadata": {**(existing.get("metadata") or {}), **(candidate.get("metadata") or {})},
    }


def should_promote_candidate(candidate: dict[str, Any], *, occurrence_count: int) -> bool:
    confidence = str(candidate.get("confidence") or "low")
    evidence_count = int(candidate.get("evidence_count") or 0)
    return confidence == "high" and evidence_count >= 2 or confidence == "medium" and occurrence_count >= 2 and evidence_count >= 2


def is_contradictory(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    old_key = str(existing.get("memory_key") or "")
    new_key = str(candidate.get("memory_key") or "")
    pairs = {
        ("sarcasm:playful", "sarcasm:dismissive"),
        ("sarcasm:dismissive", "sarcasm:playful"),
        ("influence:pressure", "influence:general"),
        ("possible_interest:interest", "possible_interest:general"),
    }
    return (old_key, new_key) in pairs


def weaken_confidence(value: str) -> str:
    if value == "high":
        return "medium"
    if value == "medium":
        return "low"
    return "low"


def stronger_confidence(first: str, second: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    value = first if order.get(first, 0) >= order.get(second, 0) else second
    return value if value in order else "low"


def persist_analysis_artifacts(conn: Any, *, analysis: dict[str, Any], result: dict[str, Any]) -> None:
    from relchat.database.repositories import (
        create_communication_profile_snapshot,
        create_communication_timeline_event,
        get_communication_memory,
        list_interpretation_findings,
        upsert_communication_memory,
        create_interpretation_finding,
    )

    bot_user_id = int(analysis["bot_user_id"])
    source = analysis.get("source") or "telegram"
    chat_id = analysis["chat_id"]
    analysis_id = analysis.get("analysis_id")
    report_id = analysis.get("report_id")
    profile = result.get("personal_profile") if isinstance(result.get("personal_profile"), dict) else None
    if profile:
        create_communication_profile_snapshot(
            conn,
            bot_user_id=bot_user_id,
            source=source,
            chat_id=chat_id,
            analysis_id=analysis_id,
            report_id=report_id,
            profile=profile,
        )
    for finding in result.get("evidence_findings") or []:
        if isinstance(finding, dict):
            create_interpretation_finding(
                conn,
                bot_user_id=bot_user_id,
                source=source,
                chat_id=chat_id,
                analysis_id=analysis_id,
                report_id=report_id,
                finding=finding,
            )
    for event in result.get("communication_timeline_events") or []:
        if isinstance(event, dict):
            create_communication_timeline_event(
                conn,
                bot_user_id=bot_user_id,
                source=source,
                chat_id=chat_id,
                analysis_id=analysis_id,
                report_id=report_id,
                event=event,
            )
    for candidate in memory_candidates_from_analysis(result):
        existing = get_communication_memory(conn, bot_user_id, source, chat_id, candidate["memory_key"])
        merged = merge_memory(existing, candidate)
        upsert_communication_memory(conn, bot_user_id=bot_user_id, source=source, chat_id=chat_id, memory=merged)


def active_memory_summaries(memories: Sequence[dict[str, Any]]) -> list[str]:
    return [str(memory.get("summary") or "") for memory in memories if memory.get("active") and str(memory.get("summary") or "").strip()]
