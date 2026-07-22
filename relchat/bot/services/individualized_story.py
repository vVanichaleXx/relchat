from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.pattern_selector import is_generic_pattern


def build_individualized_story(
    *,
    fingerprint: dict[str, Any],
    selected_patterns: Sequence[dict[str, Any]],
    personal_profile: dict[str, Any] | None = None,
    context_category: str = "unknown",
    score_state: dict[str, Any] | None = None,
    history_segments: dict[str, Any] | None = None,
    participation: dict[str, Any] | None = None,
    language: str = "en",
) -> dict[str, Any]:
    patterns = [pattern for pattern in selected_patterns if isinstance(pattern, dict)]
    profile = personal_profile if isinstance(personal_profile, dict) else {}
    history = history_segments if isinstance(history_segments, dict) else {}
    coverage = fingerprint.get("evidence_coverage") if isinstance(fingerprint, dict) else {}
    headline = individualized_headline(patterns, context_category=context_category, score_state=score_state or {}, language=language)
    return {
        "story_id": "individualized_story_v1",
        "context_scope": context_category,
        "period_scope": str((fingerprint or {}).get("period_scope") or ""),
        "headline": headline,
        "overall_picture": overall_picture(patterns, context_category=context_category, coverage=coverage if isinstance(coverage, dict) else {}, participation=participation if isinstance(participation, dict) else {}, language=language),
        "distinctive_dynamic": distinctive_dynamic(patterns, context_category=context_category, language=language),
        "user_role": user_role(patterns, profile=profile, context_category=context_category, language=language),
        "other_role": other_role(patterns, context_category=context_category, language=language),
        "main_friction": main_friction(patterns, language=language),
        "main_strength": main_strength(patterns, language=language),
        "historical_note": historical_note(patterns, history, language=language),
        "uncertainty": primary_uncertainty(fingerprint, language=language),
        "story_arc_keys": story_arc_keys(patterns),
        "tone_mode": tone_mode(patterns, score_state or {}),
    }


def validate_individualized_story(value: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    row = value if isinstance(value, dict) else fallback or {}
    return {
        "story_id": str(row.get("story_id") or "individualized_story_v1"),
        "context_scope": str(row.get("context_scope") or ""),
        "period_scope": str(row.get("period_scope") or ""),
        "headline": clean(row.get("headline"), 180),
        "overall_picture": clean(row.get("overall_picture"), 620),
        "distinctive_dynamic": clean(row.get("distinctive_dynamic"), 520),
        "user_role": clean(row.get("user_role"), 420),
        "other_role": clean(row.get("other_role"), 420),
        "main_friction": clean(row.get("main_friction"), 420),
        "main_strength": clean(row.get("main_strength"), 420),
        "historical_note": clean(row.get("historical_note"), 360),
        "uncertainty": clean(row.get("uncertainty"), 360),
        "story_arc_keys": [str(item) for item in (row.get("story_arc_keys") if isinstance(row.get("story_arc_keys"), list) else [])[:10] if str(item).strip()],
        "tone_mode": normalize_tone(row.get("tone_mode")),
    }


def individualized_headline(
    patterns: Sequence[dict[str, Any]],
    *,
    context_category: str,
    score_state: dict[str, Any],
    language: str,
) -> str:
    keys = {str(pattern.get("finding_type") or pattern.get("semantic_key") or "") for pattern in patterns}
    semantic_keys = " ".join(str(pattern.get("semantic_key") or "") for pattern in patterns)
    if context_category == "work":
        if "work_task_ambiguity" in keys and "work_response_consistency" in keys:
            return t(language, "individual_headline_work_regular_unclear")
        if "work_decision_completion" in keys:
            return t(language, "individual_headline_work_decisions")
        if "work_unanswered_questions" in keys or "work_repeated_clarification" in keys:
            return t(language, "individual_headline_work_questions_open")
        if "work_response_consistency" in keys or "response" in semantic_keys:
            return t(language, "individual_headline_work_regular_limited")
        return t(language, "individual_headline_work_limited")
    if "unanswered_questions" in keys:
        return t(language, "individual_headline_questions_open")
    if "possible_interest" in keys:
        return t(language, "individual_headline_interest_cautious")
    if "sarcasm" in keys:
        return t(language, "individual_headline_sarcasm")
    if "aggression" in keys:
        return t(language, "individual_headline_aggression")
    if "pauses:you_returns" in semantic_keys:
        return t(language, "individual_headline_you_resume")
    if "detail:you_more" in semantic_keys:
        return t(language, "individual_headline_you_detail")
    if score_state.get("insufficient_data"):
        return t(language, "individual_headline_limited")
    return t(language, f"individual_headline_{context_category}") if context_category in {"family", "friendship", "romantic"} else t(language, "individual_headline_general")


def overall_picture(patterns: Sequence[dict[str, Any]], *, context_category: str, coverage: dict[str, Any], participation: dict[str, Any] | None = None, language: str) -> str:
    non_generic = [pattern_sentence(pattern) for pattern in patterns if not is_generic_pattern(pattern)]
    structural = float(coverage.get("structural") or 0.0)
    semantic = float(coverage.get("semantic") or 0.0)
    participation_text = clean((participation or {}).get("summary"), 360)
    uncertainty = t(language, "fingerprint_uncertainty_local_semantics") if semantic <= 0.05 and structural >= 0.4 else ""
    if participation_text and non_generic:
        return t(language, "individual_opening_with_participation", participation=participation_text, quality=non_generic[0], uncertainty=uncertainty).strip()
    if context_category == "work" and semantic <= 0.05 and structural >= 0.4:
        first = non_generic[0] if non_generic else ""
        return t(language, "individual_overall_work_local", detail=first)
    if len(non_generic) >= 2:
        return t(language, "individual_overall_two_patterns", first=non_generic[0], second=non_generic[1])
    if len(non_generic) == 1:
        return non_generic[0]
    return t(language, "individual_overall_limited")


def distinctive_dynamic(patterns: Sequence[dict[str, Any]], *, context_category: str, language: str) -> str:
    if context_category == "work":
        for pattern in patterns:
            if is_generic_pattern(pattern):
                continue
            if pattern.get("topic") in {"work_tasks", "technical", "planning"} or str(pattern.get("finding_type") or "").startswith("work_"):
                return t(language, "individual_dynamic_work_topic", detail=pattern_sentence(pattern))
    for pattern in patterns:
        if is_generic_pattern(pattern):
            continue
        sentence = pattern_sentence(pattern)
        if sentence:
            return sentence
    return ""


def user_role(patterns: Sequence[dict[str, Any]], *, profile: dict[str, Any], context_category: str, language: str) -> str:
    for pattern in patterns:
        if pattern.get("participant_scope") == "you" and not is_generic_pattern(pattern):
            if context_category == "work":
                return t(language, "individual_user_role_work", detail=pattern_sentence(pattern))
            return t(language, "individual_user_role_general", detail=pattern_sentence(pattern))
    for row in profile.get("dimensions") if isinstance(profile.get("dimensions"), list) else []:
        if not isinstance(row, dict):
            continue
        observation = clean(row.get("observation"), 360)
        if observation and not generic_profile_observation(observation):
            return observation
    return ""


def other_role(patterns: Sequence[dict[str, Any]], *, context_category: str, language: str) -> str:
    for pattern in patterns:
        if pattern.get("participant_scope") == "other" and not is_generic_pattern(pattern):
            if context_category == "work":
                return t(language, "individual_other_role_work", detail=pattern_sentence(pattern))
            return t(language, "individual_other_role_general", detail=pattern_sentence(pattern))
    return ""


def main_friction(patterns: Sequence[dict[str, Any]], *, language: str) -> str:
    for pattern in patterns:
        if pattern.get("severity") in {"attention", "problem", "serious"} and not is_generic_pattern(pattern):
            return pattern_sentence(pattern)
    return ""


def main_strength(patterns: Sequence[dict[str, Any]], *, language: str) -> str:
    del language
    for pattern in patterns:
        if pattern.get("severity") == "positive" and not is_generic_pattern(pattern):
            return pattern_sentence(pattern)
    return ""


def historical_note(patterns: Sequence[dict[str, Any]], history: dict[str, Any], *, language: str) -> str:
    for pattern in patterns:
        if pattern.get("role") == "recent_change":
            return pattern_sentence(pattern)
    recent = clean(history.get("recent_change"), 320)
    if recent:
        return recent
    if history.get("segmented"):
        return t(language, "individual_history_segmented_limited", count=int(history.get("window_count") or 0))
    return ""


def primary_uncertainty(fingerprint: dict[str, Any], *, language: str) -> str:
    rows = fingerprint.get("uncertainties") if isinstance(fingerprint, dict) and isinstance(fingerprint.get("uncertainties"), list) else []
    for item in rows:
        text = clean(item, 320)
        if text:
            return text
    return t(language, "individual_uncertainty_default")


def story_arc_keys(patterns: Sequence[dict[str, Any]]) -> list[str]:
    keys = []
    for pattern in patterns:
        key = str(pattern.get("semantic_key") or pattern.get("finding_type") or pattern.get("pattern_id") or "")
        if key and key not in keys:
            keys.append(key)
    return keys[:10]


def tone_mode(patterns: Sequence[dict[str, Any]], score_state: dict[str, Any]) -> str:
    if score_state.get("insufficient_data"):
        return "neutral_limited"
    severities = {str(pattern.get("severity") or "neutral") for pattern in patterns}
    if "serious" in severities:
        return "serious"
    if "problem" in severities:
        return "direct"
    if "attention" in severities:
        return "calm"
    if "positive" in severities:
        return "supportive"
    return "neutral_limited"


def pattern_sentence(pattern: dict[str, Any]) -> str:
    observation = clean(pattern.get("observation"), 360)
    consequence = clean(pattern.get("consequence"), 260)
    if not observation:
        return ""
    if consequence and consequence.casefold() not in observation.casefold():
        return f"{observation} {consequence}"
    return observation


def generic_profile_observation(text: str) -> bool:
    lowered = text.casefold()
    return any(fragment in lowered for fragment in ("visible style", "видимый стиль", "several observable", "нескольким наблюдаем"))


def clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_tone(value: Any) -> str:
    text = str(value or "neutral_limited")
    return text if text in {"supportive", "calm", "direct", "serious", "neutral_limited"} else "neutral_limited"
