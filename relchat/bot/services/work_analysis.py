from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.canonical_findings import finding_rank, visible_available_findings
from relchat.core.models import ConversationEvent, Message
from relchat.events.extractor import summarize_events


TASK_RE = re.compile(r"\b(task|todo|issue|bug|ticket|deploy|release|send|prepare|review|fix|задач|тикет|баг|релиз|отправ|подготов|проверь|исправ)\b", re.IGNORECASE)
OWNER_RE = re.compile(r"\b(owner|responsible|assignee|i will|i'll|you will|я сделаю|я отправлю|ты сделаешь|ответственн|исполнитель)\b", re.IGNORECASE)
DEADLINE_RE = re.compile(r"\b(deadline|due|by tomorrow|by friday|today|tomorrow|срок|дедлайн|до завтра|сегодня|завтра|к пятнице)\b", re.IGNORECASE)
DECISION_RE = re.compile(r"\b(decided|approved|confirmed|done|resolved|ship it|решили|подтверждено|готово|закрыто|согласовано)\b", re.IGNORECASE)
CLARIFICATION_RE = re.compile(r"\b(clarify|what exactly|which one|who owns|when is|не понял|уточни|что именно|кто делает|какой срок|когда нужно)\b", re.IGNORECASE)
STATUS_RE = re.compile(r"\b(status|update|progress|blocked|готовлю|в работе|статус|обновление|прогресс|заблокировано)\b", re.IGNORECASE)


def build_work_findings(
    *,
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
    question_metrics: dict[str, Any],
    unanswered_count: int,
    history_segments: dict[str, Any] | None,
    period_label: str,
    language: str = "en",
) -> list[dict[str, Any]]:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    text_messages = [message for message in ordered if (message.text or "").strip()]
    event_counts = summarize_events(events)
    counts = work_signal_counts(text_messages)
    rows: list[dict[str, Any]] = []

    if unanswered_count >= 2:
        rows.append(work_unanswered_questions_finding(question_metrics, unanswered_count=unanswered_count, period_label=period_label, language=language))

    if counts["clarification"] >= 3 and counts["task"] >= 2:
        rows.append(
            work_finding(
                finding_id="work_clarification_1",
                finding_type="work_repeated_clarification",
                severity="attention" if counts["clarification"] < 8 else "problem",
                confidence="medium" if counts["clarification"] >= 4 else "low",
                score_effect=-0.55 if counts["clarification"] < 8 else -0.95,
                title=t(language, "work_finding_repeated_clarification_title"),
                observation=t(language, "work_finding_repeated_clarification_observation", count=counts["clarification"]),
                interpretation=t(language, "work_finding_repeated_clarification_interpretation"),
                evidence_count=counts["clarification"],
                evidence_description="work_repeated_clarification",
                period_label=period_label,
                language=language,
            )
        )

    task_count = counts["task"] + int(event_counts.get("plan_candidate", 0) or 0) + int(event_counts.get("promise_candidate", 0) or 0)
    clarity_signals = counts["owner"] + counts["deadline"] + counts["decision"]
    if task_count >= 4 and clarity_signals <= max(1, task_count // 5):
        rows.append(
            work_finding(
                finding_id="work_task_clarity_1",
                finding_type="work_task_ambiguity",
                severity="attention",
                confidence="medium",
                score_effect=-0.6,
                title=t(language, "work_finding_task_clarity_title"),
                observation=t(language, "work_finding_task_clarity_observation", tasks=task_count, clarity=clarity_signals),
                interpretation=t(language, "work_finding_task_clarity_interpretation"),
                evidence_count=task_count,
                evidence_description="work_task_without_clear_owner_or_deadline",
                period_label=period_label,
                language=language,
            )
        )

    if counts["decision"] >= 2:
        rows.append(
            work_finding(
                finding_id="work_decision_1",
                finding_type="work_decision_completion",
                severity="positive",
                confidence="medium" if counts["decision"] < 5 else "high",
                score_effect=0.45,
                title=t(language, "work_finding_decision_completion_title"),
                observation=t(language, "work_finding_decision_completion_observation", count=counts["decision"]),
                interpretation=t(language, "work_finding_decision_completion_interpretation"),
                evidence_count=counts["decision"],
                evidence_description="work_decision_completion",
                period_label=period_label,
                language=language,
            )
        )

    reply_pairs = alternating_reply_pairs(ordered)
    if reply_pairs >= 20:
        rows.append(
            work_finding(
                finding_id="work_response_rhythm_1",
                finding_type="work_response_consistency",
                severity="positive",
                confidence="medium",
                score_effect=0.25,
                title=t(language, "work_finding_response_consistency_title"),
                observation=t(language, "work_finding_response_consistency_observation", count=reply_pairs),
                interpretation=t(language, "work_finding_response_consistency_interpretation"),
                evidence_count=reply_pairs,
                evidence_description="work_response_consistency",
                period_label=period_label,
                language=language,
            )
        )

    recent_change = str((history_segments or {}).get("recent_change") or "")
    if recent_change and rows:
        for row in rows:
            row.setdefault("limitations", []).append(t(language, "work_finding_history_scope_limitation"))
    return sorted(rows, key=finding_rank, reverse=True)[:8]


def work_signal_counts(messages: Sequence[Message]) -> dict[str, int]:
    counts = {"task": 0, "owner": 0, "deadline": 0, "decision": 0, "clarification": 0, "status": 0}
    for message in messages:
        text = message.text or ""
        if TASK_RE.search(text):
            counts["task"] += 1
        if OWNER_RE.search(text):
            counts["owner"] += 1
        if DEADLINE_RE.search(text):
            counts["deadline"] += 1
        if DECISION_RE.search(text):
            counts["decision"] += 1
        if CLARIFICATION_RE.search(text):
            counts["clarification"] += 1
        if STATUS_RE.search(text):
            counts["status"] += 1
    return counts


def work_unanswered_questions_finding(question_metrics: dict[str, Any], *, unanswered_count: int, period_label: str, language: str) -> dict[str, Any]:
    by_participant = question_metrics.get("by_participant") if isinstance(question_metrics.get("by_participant"), dict) else {}
    you = by_participant.get("you") if isinstance(by_participant.get("you"), dict) else {}
    direct_count = int(you.get("direct_question_count") or 0)
    denominator = int(you.get("text_messages") or 0)
    rate = float(you.get("per_100_messages") or 0.0)
    return work_finding(
        finding_id="work_questions_1",
        finding_type="work_unanswered_questions",
        severity="problem" if unanswered_count >= 8 and rate >= 6.0 else "attention",
        confidence="medium" if denominator >= 30 else "low",
        score_effect=-0.75 if unanswered_count >= 8 else -0.45,
        title=t(language, "work_finding_unanswered_questions_title"),
        observation=t(language, "work_finding_unanswered_questions_observation", unanswered=unanswered_count, count=direct_count, denominator=denominator, rate=f"{rate:.1f}"),
        interpretation=t(language, "work_finding_unanswered_questions_interpretation"),
        evidence_count=max(1, unanswered_count),
        evidence_description="work_unanswered_actionable_questions",
        period_label=period_label,
        language=language,
    )


def work_finding(
    *,
    finding_id: str,
    finding_type: str,
    severity: str,
    confidence: str,
    score_effect: float,
    title: str,
    observation: str,
    interpretation: str,
    evidence_count: int,
    evidence_description: str,
    period_label: str,
    language: str,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "participant_scope": "interaction",
        "status": "available",
        "severity": severity,
        "semantic_source": "local_pattern",
        "semantic_depth": "direct",
        "confidence": confidence,
        "evidence_count": evidence_count,
        "score_effect": score_effect,
        "advice_category": "task_clarity" if severity != "positive" else "clarity",
        "summary_key": f"{finding_type}:{evidence_description}",
        "title": title,
        "observation": observation,
        "interpretation": interpretation,
        "evidence": [
            {
                "evidence_id": f"ev_{finding_id}",
                "evidence_type": "event_pattern",
                "source": "local_pattern",
                "semantic_depth": "direct",
                "message_ref": "",
                "sender": "YOU",
                "description": evidence_description,
            }
        ],
        "alternative_interpretations": [t(language, "work_finding_alternative")],
        "limitations": [t(language, "work_finding_local_limitation")],
        "period_scope": period_label,
        "context_scope": "work",
    }


def work_effectiveness_score(
    *,
    canonical_findings: Sequence[dict[str, Any]],
    dimensions: dict[str, Any],
    message_count: int,
    coverage: dict[str, Any] | None = None,
    context_confidence: str | None = None,
    local_only: bool = True,
) -> dict[str, Any]:
    if message_count < 10:
        return {
            "score": None,
            "confidence": "low",
            "insufficient_data": True,
            "explanation": "Not enough messages for a stable work-effectiveness score.",
            "available_positive_weight": 0.0,
            "evidence_quality": "insufficient",
            "cap": None,
            "cap_reason": "too_few_messages",
            "score_model": "work_effectiveness_v1",
        }
    available = visible_available_findings(canonical_findings)
    work_available = [finding for finding in available if str(finding.get("finding_type") or "").startswith("work_")]
    negative_effect = sum(float(finding.get("score_effect") or 0.0) for finding in work_available if float(finding.get("score_effect") or 0.0) < 0)
    positive_effect = sum(float(finding.get("score_effect") or 0.0) for finding in work_available if float(finding.get("score_effect") or 0.0) > 0)
    semantic_effect = sum(
        max(-0.25, float(finding.get("score_effect") or 0.0))
        for finding in canonical_findings
        if str(finding.get("finding_type")) in {"sarcasm", "influence", "aggression"} and float(finding.get("score_effect") or 0.0) < 0
    )
    structural_positive = structural_work_positive(dimensions)
    base = 5.6
    if work_available:
        base = 5.8
    score = max(1.0, min(10.0, base + structural_positive + positive_effect + negative_effect + semantic_effect))
    cap = 6.4 if local_only else 8.5 if (coverage or {}).get("partial") else 10.0
    if context_confidence == "low":
        cap = min(cap, 8.0)
    if not work_available and local_only:
        cap = min(cap, 6.0)
    score = round(min(score, cap), 1)
    negative_count = sum(1 for finding in work_available if float(finding.get("score_effect") or 0.0) < 0)
    confidence = "medium" if message_count >= 80 else "low"
    if local_only and not work_available:
        confidence = "low" if message_count < 80 else "medium"
    if negative_count >= 2 and message_count >= 80:
        confidence = "medium"
    return {
        "score": score,
        "confidence": confidence,
        "insufficient_data": False,
        "explanation": "Work score is based on task clarity, answer completion, decisions, follow-through, and only small structural positives for reply rhythm.",
        "available_positive_weight": 0.0,
        "risk_penalty": round(abs(negative_effect + semantic_effect), 2),
        "raw_score": score,
        "evidence_quality": "local_work_structural" if local_only else "work_semantic",
        "available_dimension_count": len(work_available),
        "independent_dimension_count": len({finding.get("finding_type") for finding in work_available}),
        "cap": cap,
        "cap_reason": "work_local_effectiveness_cap" if local_only else "work_semantic_effectiveness",
        "score_model": "work_effectiveness_v1",
    }


def structural_work_positive(dimensions: dict[str, Any]) -> float:
    positive = 0.0
    reply = dimensions.get("reply_consistency") if isinstance(dimensions.get("reply_consistency"), dict) else {}
    if isinstance(reply.get("score"), (int, float)) and float(reply["score"]) >= 6.5:
        positive += 0.25
    planning = dimensions.get("planning_cooperation") if isinstance(dimensions.get("planning_cooperation"), dict) else {}
    if isinstance(planning.get("score"), (int, float)) and float(planning["score"]) >= 6.5:
        positive += 0.2
    question = dimensions.get("question_engagement") if isinstance(dimensions.get("question_engagement"), dict) else {}
    if isinstance(question.get("score"), (int, float)) and float(question["score"]) >= 7.0:
        positive += 0.2
    return min(0.6, positive)


def alternating_reply_pairs(messages: Sequence[Message]) -> int:
    count = 0
    previous: bool | None = None
    for message in messages:
        if previous is not None and message.is_outgoing is not previous:
            count += 1
        previous = message.is_outgoing
    return count
