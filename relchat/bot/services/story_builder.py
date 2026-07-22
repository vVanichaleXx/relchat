from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.core.models import Message


def build_communication_story(
    *,
    messages: Sequence[Message],
    context_category: str,
    semantic_analysis: dict[str, Any] | None,
    evidence_findings: Sequence[dict[str, Any]],
    personal_profile: dict[str, Any] | None,
    period_label: str,
    language: str = "en",
) -> dict[str, Any]:
    semantic_analysis = semantic_analysis if isinstance(semantic_analysis, dict) else {}
    profile = personal_profile if isinstance(personal_profile, dict) else {}
    findings = [item for item in evidence_findings if isinstance(item, dict)]
    message_count = len(messages)
    main_friction = first_finding(findings, severities={"problem", "attention"})
    positive = first_finding(findings, severities={"positive", "neutral"})
    return {
        "story_id": "communication_story",
        "period_scope": period_label,
        "context_scope": context_category,
        "tone_mode": adaptive_tone(semantic_analysis, findings, message_count),
        "what_is_happening": what_happening(message_count, context_category, main_friction, language=language),
        "main_driver": main_driver(main_friction, positive, language=language),
        "how_you_communicate": profile.get("summary") or t(language, "story_user_limited"),
        "how_other_responds": other_response_summary(messages, language=language),
        "what_strengthens": [positive.get("title")] if positive else [],
        "what_creates_friction": [main_friction.get("title")] if main_friction else [],
        "semantic_dynamics": semantic_dynamics(semantic_analysis, language=language),
        "recurrence": t(language, "story_recurrence_limited"),
        "uncertainties": story_uncertainties(semantic_analysis, language=language),
        "limitations": [t(language, "semantic_scope_limitation")],
    }


def adaptive_tone(semantic_analysis: dict[str, Any], findings: Sequence[dict[str, Any]], message_count: int) -> str:
    aggression = semantic_analysis.get("aggression") if isinstance(semantic_analysis.get("aggression"), dict) else {}
    if aggression.get("status") == "available" and aggression.get("type") in {"verbal_aggression", "hostility"}:
        return "serious"
    if message_count < 10:
        return "neutral_limited"
    if any(item.get("severity") == "problem" for item in findings):
        return "direct"
    if any(item.get("severity") == "attention" for item in findings):
        return "calm"
    return "supportive"


def first_finding(findings: Sequence[dict[str, Any]], *, severities: set[str]) -> dict[str, Any]:
    for item in findings:
        if item.get("severity") in severities:
            return item
    return {}


def what_happening(message_count: int, context_category: str, finding: dict[str, Any], *, language: str) -> str:
    if message_count < 10:
        return t(language, "story_happening_limited")
    if finding:
        return t(language, "story_happening_with_friction", finding=finding.get("title") or "")
    if context_category == "family":
        return t(language, "story_happening_family")
    if context_category == "work":
        return t(language, "story_happening_work")
    return t(language, "story_happening_general")


def main_driver(problem: dict[str, Any], positive: dict[str, Any], *, language: str) -> str:
    if problem:
        return t(language, "story_driver_problem", finding=problem.get("title") or "")
    if positive:
        return t(language, "story_driver_positive", finding=positive.get("title") or "")
    return t(language, "story_driver_limited")


def other_response_summary(messages: Sequence[Message], *, language: str) -> str:
    incoming = sum(1 for message in messages if not message.is_outgoing)
    if not messages or incoming == 0:
        return t(language, "story_other_limited")
    share = incoming / max(1, len(messages))
    if share >= 0.45:
        return t(language, "story_other_participates")
    return t(language, "story_other_reacts_less")


def semantic_dynamics(semantic_analysis: dict[str, Any], *, language: str) -> list[str]:
    rows: list[str] = []
    for key in ("sarcasm", "aggression", "influence", "possible_interest"):
        item = semantic_analysis.get(key) if isinstance(semantic_analysis.get(key), dict) else {}
        if item.get("status") == "available" and item.get("summary"):
            rows.append(str(item.get("summary")))
    return rows[:4]


def story_uncertainties(semantic_analysis: dict[str, Any], *, language: str) -> list[str]:
    rows: list[str] = []
    for key in ("sarcasm", "aggression", "influence", "possible_interest"):
        item = semantic_analysis.get(key) if isinstance(semantic_analysis.get(key), dict) else {}
        if item.get("status") in {"ambiguous", "insufficient_data"}:
            rows.append(str(item.get("summary") or t(language, "semantic_insufficient_generic")))
    return rows[:4] or [t(language, "story_uncertainty_general")]


def validate_communication_story(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    tone = str(value.get("tone_mode") or "neutral_limited")
    if tone not in {"supportive", "calm", "direct", "serious", "neutral_limited"}:
        tone = "neutral_limited"
    return {
        "story_id": str(value.get("story_id") or "communication_story"),
        "period_scope": str(value.get("period_scope") or ""),
        "context_scope": str(value.get("context_scope") or ""),
        "tone_mode": tone,
        "what_is_happening": str(value.get("what_is_happening") or ""),
        "main_driver": str(value.get("main_driver") or ""),
        "how_you_communicate": str(value.get("how_you_communicate") or ""),
        "how_other_responds": str(value.get("how_other_responds") or ""),
        "what_strengthens": string_list(value.get("what_strengthens")),
        "what_creates_friction": string_list(value.get("what_creates_friction")),
        "semantic_dynamics": string_list(value.get("semantic_dynamics")),
        "recurrence": str(value.get("recurrence") or ""),
        "uncertainties": string_list(value.get("uncertainties")),
        "limitations": string_list(value.get("limitations")),
    }


def string_list(value: Any, *, limit: int = 8) -> list[str]:
    rows = value if isinstance(value, list) else []
    return [str(item) for item in rows[:limit] if str(item).strip()]
