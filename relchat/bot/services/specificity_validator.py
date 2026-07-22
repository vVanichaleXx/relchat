from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from relchat.bot.localization import t
from relchat.bot.services.pattern_selector import is_generic_pattern, is_generic_text


PROHIBITED_GENERIC_PHRASES = (
    "your visible communication style can be described",
    "visible data show",
    "visible metrics show",
    "communication contains certain patterns",
    "there are several factors",
    "there are strengths and weaknesses",
    "communication requires effort",
    "clear communication is important",
    "try to express your thoughts openly",
    "the conversation contains a point of friction",
    "the recent rhythm is similar",
    "видимый стиль общения можно описать",
    "видимые данные показывают",
    "видимые метрики показывают",
    "переписка содержит определенные паттерны",
    "есть несколько факторов",
    "есть сильные и слабые стороны",
    "общение требует усилий",
    "важно общаться ясно",
    "старайтесь выражать мысли открыто",
    "в переписке есть заметная точка трения",
    "недавний ритм похож",
)


def validate_report_specificity(result: dict[str, Any], *, language: str = "en") -> dict[str, Any]:
    patterns = [row for row in result.get("selected_patterns") or [] if isinstance(row, dict)]
    fingerprint = result.get("conversation_fingerprint") if isinstance(result.get("conversation_fingerprint"), dict) else {}
    texts = visible_text_fragments(result)
    generic_count = sum(generic_phrase_hits(text) for text in texts)
    duplicate_count = semantic_duplicate_count(texts)
    distinctive_count = sum(1 for pattern in patterns if not is_generic_pattern(pattern) and float(pattern.get("specificity_score") or 0.0) >= 0.35)
    comparison_count = comparison_observation_count(patterns, fingerprint)
    advice_score = advice_specificity_score(result)
    coverage = fingerprint.get("evidence_coverage") if isinstance(fingerprint.get("evidence_coverage"), dict) else {}
    evidence_depth = evidence_depth_label(coverage)
    enough_evidence = evidence_depth in {"medium", "high"} and int((result.get("coverage") or {}).get("available_messages") or 0) >= 20
    passed = (
        generic_count == 0
        and duplicate_count <= 1
        and advice_score >= 0.45
        and (distinctive_count >= 2 or not enough_evidence)
        and context_specific_enough(result, patterns)
    )
    score = 0.25
    score += min(0.35, distinctive_count * 0.12)
    score += min(0.2, comparison_count * 0.07)
    score += min(0.2, advice_score * 0.2)
    score -= min(0.4, generic_count * 0.12 + duplicate_count * 0.04)
    return {
        "specificity_score": round(max(0.0, min(1.0, score)), 3),
        "generic_phrase_count": generic_count,
        "distinctive_finding_count": distinctive_count,
        "comparison_count": comparison_count,
        "duplicate_count": duplicate_count,
        "advice_specificity": round(advice_score, 3),
        "evidence_depth": evidence_depth,
        "passed": passed,
    }


def improve_report_specificity(result: dict[str, Any], *, specificity: dict[str, Any], language: str = "en") -> dict[str, Any]:
    data = dict(result)
    story = data.get("individualized_story") if isinstance(data.get("individualized_story"), dict) else {}
    if specificity.get("generic_phrase_count"):
        if is_generic_text(str(data.get("summary") or "")) and story.get("overall_picture"):
            data["summary"] = story["overall_picture"]
        verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else {}
        if verdict and is_generic_text(str(verdict.get("headline") or "")) and story.get("headline"):
            verdict = dict(verdict)
            verdict["headline"] = story["headline"]
            data["verdict"] = verdict
        data["positive_patterns"] = remove_generic_patterns(data.get("positive_patterns"))
        data["problem_patterns"] = remove_generic_patterns(data.get("problem_patterns"))
    feedback = data.get("personalized_feedback") if isinstance(data.get("personalized_feedback"), dict) else {}
    if not feedback.get("action_needed") and feedback.get("omitted_reason"):
        if data.get("canonical_findings") or not data.get("advice"):
            data["advice"] = []
            data["recommended_action"] = {
                "action": "no_action",
                "explanation": str(feedback.get("recommendation") or t(language, "feedback_no_action_general")),
            }
    elif specificity.get("advice_specificity", 0.0) < 0.45:
        data["advice"] = []
    data["specificity"] = validate_report_specificity(data, language=language)
    return data


def visible_text_fragments(result: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for key in ("summary", "adaptive_tone"):
        if result.get(key):
            fields.append(str(result[key]))
    verdict = result.get("verdict") if isinstance(result.get("verdict"), dict) else {}
    fields.extend(str(verdict.get(key) or "") for key in ("headline", "explanation"))
    story = result.get("individualized_story") if isinstance(result.get("individualized_story"), dict) else {}
    fields.extend(str(story.get(key) or "") for key in ("headline", "overall_picture", "distinctive_dynamic", "user_role", "other_role", "main_friction", "main_strength", "historical_note"))
    if not story:
        old_story = result.get("communication_story") if isinstance(result.get("communication_story"), dict) else {}
        fields.extend(str(old_story.get(key) or "") for key in ("what_is_happening", "main_driver", "how_you_communicate", "how_other_responds"))
    profile = result.get("personal_profile") if isinstance(result.get("personal_profile"), dict) else {}
    fields.append(str(profile.get("summary") or ""))
    for collection_key in ("positive_patterns", "problem_patterns", "direct_findings", "advice"):
        for row in result.get(collection_key) if isinstance(result.get(collection_key), list) else []:
            if isinstance(row, dict):
                fields.append(" ".join(str(row.get(name) or "") for name in ("title", "explanation", "finding", "example")))
            else:
                fields.append(str(row))
    return [text for text in fields if text.strip()]


def generic_phrase_hits(text: str) -> int:
    lowered = " ".join(text.casefold().split())
    return sum(1 for phrase in PROHIBITED_GENERIC_PHRASES if phrase in lowered)


def semantic_duplicate_count(texts: Iterable[str]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for text in texts:
        key = semantic_key(text)
        if not key or key == "too_short":
            continue
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
    return duplicates


def semantic_key(text: str) -> str:
    lowered = re.sub(r"\s+", " ", text.casefold()).strip()
    if len(lowered) < 18:
        return "too_short"
    if any(fragment in lowered for fragment in ("примерно равномер", "roughly even", "balanced by volume", "balance of activity")):
        return "balanced_activity"
    if any(fragment in lowered for fragment in ("существенных изменений нет", "no meaningful change")):
        return "no_meaningful_change"
    if any(fragment in lowered for fragment in ("рабочие вопросы", "work questions")) and any(fragment in lowered for fragment in ("не закры", "lack visible completion", "remain open")):
        return "work_questions_open"
    if any(fragment in lowered for fragment in ("задач", "task")) and any(fragment in lowered for fragment in ("срок", "deadline", "ответствен", "owner")):
        return "work_task_clarity"
    return lowered[:90]


def comparison_observation_count(patterns: list[dict[str, Any]], fingerprint: dict[str, Any]) -> int:
    count = sum(1 for pattern in patterns if str(pattern.get("comparison_type") or "") in {"participant", "period", "topic", "cross_chat", "recurrence"})
    if isinstance(fingerprint.get("topic_differences"), list):
        count += min(1, len(fingerprint["topic_differences"]))
    if isinstance(fingerprint.get("recent_changes"), list):
        count += min(1, len(fingerprint["recent_changes"]))
    return count


def advice_specificity_score(result: dict[str, Any]) -> float:
    feedback = result.get("personalized_feedback") if isinstance(result.get("personalized_feedback"), dict) else {}
    advice = result.get("advice") if isinstance(result.get("advice"), list) else []
    if not advice:
        return 0.8 if not feedback.get("action_needed") else 0.2
    first = advice[0] if isinstance(advice[0], dict) else {}
    score = 0.1
    if first.get("finding_id") and str(first.get("finding_id")) != "general":
        score += 0.25
    if first.get("category") and str(first.get("category")) not in {"clarity", "general"}:
        score += 0.2
    text = " ".join(str(first.get(key) or "") for key in ("title", "explanation", "example"))
    if not is_generic_text(text) and len(text) >= 50:
        score += 0.25
    if any(token in text.casefold() for token in ("work", "task", "question", "deadline", "шут", "вопрос", "задач", "срок", "решен")):
        score += 0.2
    return min(1.0, score)


def context_specific_enough(result: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    context = (result.get("context") or {}).get("category") if isinstance(result.get("context"), dict) else "unknown"
    if context == "work":
        text = " ".join(visible_text_fragments(result)).casefold()
        return any(token in text for token in ("work", "task", "deadline", "decision", "рабоч", "задач", "срок", "решен"))
    if context in {"family", "friendship", "romantic"}:
        return bool(patterns) or int((result.get("coverage") or {}).get("available_messages") or 0) < 20
    return True


def evidence_depth_label(coverage: dict[str, Any]) -> str:
    structural = float(coverage.get("structural") or 0.0)
    semantic = float(coverage.get("semantic") or 0.0)
    historical = float(coverage.get("historical") or 0.0)
    if semantic >= 0.6 or (structural >= 0.7 and historical >= 0.4):
        return "high"
    if structural >= 0.3 or semantic >= 0.2 or historical >= 0.2:
        return "medium"
    return "low"


def remove_generic_patterns(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get(key) or "") for key in ("title", "explanation"))
        if is_generic_text(text):
            continue
        result.append(row)
    return result
