from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.services.advice_routing import advice_category_for_finding, build_advice_for_finding, leading_advice_finding, route_advice, validate_advice_routes
from relchat.bot.services.canonical_findings import SEVERITY_ORDER, finding_by_id, visible_available_findings
from relchat.bot.services.score_explanation import validate_score_explanation_against_findings


HOSTILITY_TERMS = (
    "hostil",
    "aggression",
    "aggressive",
    "insult",
    "threat",
    "вражд",
    "агресс",
    "оскорб",
    "угроз",
)
DEVALUATION_TERMS = ("devaluation", "devalu", "обесцен")
PSYCHOLOGICAL_LABEL_TERMS = (
    "manipulative",
    "toxic",
    "abusive",
    "narcissistic",
    "controlling",
    "манипулятив",
    "токсич",
    "абьюз",
    "нарцисс",
    "контролир",
)
SARCASM_TERMS = ("sarcasm", "сарказ", "ирон")
TECHNICAL_REPORT_TERMS = (
    "direct candidate",
    "question candidate",
    "local window",
    "framework confidence",
    "visible communication",
    "visible style",
    "visible volume",
    "кандидат на вопрос",
    "кандидата на вопрос",
    "локальном окне",
    "видимое общение",
    "видимый стиль",
    "видимый объем",
)


def validate_report_consistency(result: dict[str, Any], *, language: str = "en") -> dict[str, Any]:
    data = dict(result)
    canonical = [finding for finding in data.get("canonical_findings") or [] if isinstance(finding, dict)]
    available = visible_available_findings(canonical)

    data["score_explanation"] = validate_score_explanation_against_findings(
        data.get("score_explanation") if isinstance(data.get("score_explanation"), dict) else {},
        canonical,
        language=language,
    )
    allow_empty_advice = bool(
        isinstance(data.get("personalized_feedback"), dict)
        and data["personalized_feedback"].get("action_needed") is False
        and data["personalized_feedback"].get("omitted_reason")
    )
    context_category = str((data.get("context") or {}).get("category") or "unknown")
    leading = leading_advice_finding(canonical)
    data["leading_finding_id"] = str(leading.get("finding_id") or "")
    data["advice"] = repaired_advice(
        data.get("advice"),
        canonical,
        leading_finding=leading,
        context_category=context_category,
        language=language,
        allow_empty=allow_empty_advice,
    )
    data["advice_target_id"] = str(data["advice"][0].get("finding_id") or "") if data["advice"] else ""
    data["recommended_action"] = repair_recommended_action(data.get("recommended_action"), data.get("advice"))
    data["adaptive_tone"] = repair_tone(str(data.get("adaptive_tone") or "neutral_limited"), canonical)
    if isinstance(data.get("communication_story"), dict):
        story = dict(data["communication_story"])
        story["tone_mode"] = repair_tone(str(story.get("tone_mode") or data["adaptive_tone"]), canonical)
        story["semantic_dynamics"] = filter_unsupported_strings(story.get("semantic_dynamics"), available)
        story["what_creates_friction"] = filter_unsupported_strings(story.get("what_creates_friction"), available)
        data["communication_story"] = story
    data["problem_patterns"] = filter_unsupported_patterns(data.get("problem_patterns"), available)
    data["weak_reply_patterns"] = filter_unsupported_weak_replies(data.get("weak_reply_patterns"), available)
    data["direct_findings"] = filter_unsupported_direct_findings(data.get("direct_findings"), available)
    data["positive_patterns"] = filter_generic_strengths(data.get("positive_patterns"))
    data["canonical_findings"] = sanitize_finding_labels(canonical)
    data["evidence_findings"] = sanitize_finding_labels(data.get("evidence_findings") if isinstance(data.get("evidence_findings"), list) else [])
    if isinstance(data.get("individualized_story"), dict):
        data["individualized_story"] = sanitize_story_labels(data["individualized_story"])
    if isinstance(data.get("personalized_feedback"), dict):
        data["personalized_feedback"] = sanitize_mapping_labels(data["personalized_feedback"])
    data["summary"] = behavior_first_text(str(data.get("summary") or ""))
    data["limitations"] = dedupe_strings(data.get("limitations"))
    if isinstance(data.get("history_segments"), dict):
        data["history_segments"] = dedupe_history_summary(data["history_segments"])
    return data


def sanitize_finding_labels(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        item = dict(finding)
        for key in ("title", "observation", "interpretation"):
            item[key] = behavior_first_text(str(item.get(key) or ""))
        result.append(item)
    return result


def sanitize_story_labels(story: dict[str, Any]) -> dict[str, Any]:
    return sanitize_mapping_labels(story)


def sanitize_mapping_labels(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, str):
            result[key] = behavior_first_text(value)
    return result


def repaired_advice(value: Any, canonical_findings: Sequence[dict[str, Any]], *, leading_finding: dict[str, Any] | None = None, context_category: str, language: str, allow_empty: bool = False) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    validated = validate_advice_routes(rows, canonical_findings, language=language)
    leading = leading_finding if isinstance(leading_finding, dict) else {}
    if leading and validated:
        leading_id = str(leading.get("finding_id") or "")
        if str(validated[0].get("finding_id") or "") != leading_id:
            category = str(leading.get("advice_category") or "") or advice_category_for_finding(leading, context_category=context_category)
            validated = [
                build_advice_for_finding(
                    leading,
                    category=category,
                    context_category=context_category,
                    priority=1,
                    language=language,
                )
            ]
    if validated:
        return validated
    if allow_empty:
        return []
    return route_advice(canonical_findings, context_category=context_category, language=language)


def repair_recommended_action(value: Any, advice: Any) -> dict[str, str]:
    first = advice[0] if isinstance(advice, list) and advice and isinstance(advice[0], dict) else {}
    if isinstance(value, dict):
        action = str(value.get("action") or "clarify")
    else:
        action = "clarify"
    if first.get("category") in {"aggression", "hostile_sarcasm", "pressure"}:
        action = "clarify"
    if first.get("category") == "question":
        action = "clarify"
    return {
        "action": action,
        "explanation": str(first.get("explanation") or (value.get("explanation") if isinstance(value, dict) else "") or ""),
    }


def repair_tone(tone: str, canonical_findings: Sequence[dict[str, Any]]) -> str:
    available = visible_available_findings(canonical_findings)
    if not available:
        return "neutral_limited" if tone in {"direct", "serious"} else tone
    max_severity = max(SEVERITY_ORDER.get(str(finding.get("severity") or "neutral"), 1) for finding in available)
    has_explicit_aggression = any(str(finding.get("finding_type")) == "aggression" and str(finding.get("severity")) in {"problem", "serious"} for finding in available)
    if tone == "serious" and not has_explicit_aggression:
        return "direct" if max_severity >= SEVERITY_ORDER["problem"] else "calm"
    if tone == "direct" and max_severity < SEVERITY_ORDER["attention"]:
        return "neutral_limited"
    return tone if tone in {"supportive", "calm", "direct", "serious", "neutral_limited"} else "neutral_limited"


def filter_unsupported_patterns(value: Any, available_findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict) or not supported_text(row_text(row), available_findings) or technical_text(row_text(row)):
            continue
        item = dict(row)
        for key in ("title", "explanation"):
            item[key] = behavior_first_text(str(item.get(key) or ""))
        result.append(item)
    return result


def filter_unsupported_weak_replies(value: Any, available_findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "")
        text = row_text(row)
        if category in {"hostile", "pressure"} and not supported_text(text, available_findings):
            continue
        if category == "sarcasm_instead_of_answer" and not any(finding.get("finding_type") == "sarcasm" for finding in available_findings):
            continue
        if not technical_text(text):
            result.append(row)
    return result


def filter_unsupported_direct_findings(value: Any, available_findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = row_text(row)
        if not supported_text(text, available_findings):
            continue
        if technical_text(text):
            row = dict(row)
            row["finding"] = naturalize_text(str(row.get("finding") or ""))
        row = dict(row)
        row["finding"] = behavior_first_text(str(row.get("finding") or ""))
        result.append(row)
    return dedupe_dicts(result, key_name="finding")


def filter_unsupported_strings(value: Any, available_findings: Sequence[dict[str, Any]]) -> list[str]:
    rows = [str(item) for item in (value if isinstance(value, list) else []) if str(item).strip()]
    return [row for row in dedupe_strings(rows) if supported_text(row, available_findings) and not technical_text(row)]


def supported_text(text: str, available_findings: Sequence[dict[str, Any]]) -> bool:
    lowered = text.casefold()
    if any(term in lowered for term in PSYCHOLOGICAL_LABEL_TERMS):
        return repeated_influence_evidence(available_findings)
    if any(term in lowered for term in HOSTILITY_TERMS):
        return any(str(finding.get("finding_type")) == "aggression" and str(finding.get("status")) == "available" for finding in available_findings)
    if any(term in lowered for term in DEVALUATION_TERMS):
        return any(str(finding.get("finding_type")) in {"sarcasm", "aggression"} and str(finding.get("status")) == "available" for finding in available_findings)
    if any(term in lowered for term in SARCASM_TERMS):
        return any(str(finding.get("finding_type")) == "sarcasm" and str(finding.get("status")) == "available" for finding in available_findings)
    return True


def repeated_influence_evidence(available_findings: Sequence[dict[str, Any]]) -> bool:
    return any(
        str(finding.get("finding_type")) == "influence"
        and str(finding.get("status")) == "available"
        and int(finding.get("evidence_count") or 0) >= 3
        for finding in available_findings
    )


def behavior_first_text(text: str) -> str:
    replacements = {
        "possible manipulative pattern": "possible pressure through obligation",
        "clear manipulative pattern": "repeated pressure on choice",
        "manipulative pattern": "pressure pattern",
        "manipulative": "pressure-based",
        "toxic": "harmful",
        "abusive": "aggressive",
        "narcissistic": "self-focused",
        "controlling": "restricting choice",
        "возможный манипулятивный паттерн": "возможное давление через обязательство",
        "ясный манипулятивный паттерн": "повторяющееся давление на возможность выбора",
        "манипулятивный паттерн": "паттерн давления",
        "манипулятивным": "связанным с давлением",
        "манипулятивный": "связанный с давлением",
        "токсичный": "резкий",
        "токсичная": "резкая",
        "абьюзивный": "агрессивный",
        "нарциссический": "эгоцентричный",
        "контролирующий": "ограничивающий выбор",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
        result = result.replace(old.capitalize(), new.capitalize())
    return result


def technical_text(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in TECHNICAL_REPORT_TERMS)


def naturalize_text(text: str) -> str:
    replacements = {
        "direct question candidate(s)": "direct questions",
        "direct question candidate": "direct question",
        "кандидата на вопрос": "вопроса",
        "кандидатов на вопросы": "вопросов",
        "локальном окне ответа": "выбранном периоде",
        "видимое общение": "общение",
        "видимый объем": "объем",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def filter_generic_strengths(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = row_text(row).casefold()
        if any(fragment in text for fragment in ("both sides participated", "activity exists", "messages were found", "обе стороны участв", "видимая активность", "сообщения найдены")):
            continue
        result.append(row)
    return result


def dedupe_history_summary(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    seen: set[str] = set()
    for key in ("current_picture", "long_term_pattern", "recent_change"):
        text = str(result.get(key) or "").strip()
        normalized = semantic_key(text)
        if text and normalized in seen:
            result[key] = ""
        elif text:
            seen.add(normalized)
    return result


def dedupe_strings(value: Any) -> list[str]:
    rows = [str(item) for item in (value if isinstance(value, list) else []) if str(item).strip()]
    result: list[str] = []
    seen: set[str] = set()
    for row in rows:
        key = semantic_key(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def dedupe_dicts(rows: Sequence[dict[str, Any]], *, key_name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = semantic_key(str(row.get(key_name) or row_text(row)))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def row_text(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(key) or "") for key in ("title", "explanation", "finding", "interpretation", "summary"))


def semantic_key(text: str) -> str:
    lowered = " ".join(text.casefold().split())
    if any(fragment in lowered for fragment in ("no meaningful change", "существенных изменений нет", "нет значимых изменений", "похож на предыдущ")):
        return "no_meaningful_change"
    if any(fragment in lowered for fragment in ("balanced activity", "примерно равномер", "примерно одинаков")):
        return "balanced_activity"
    return lowered[:120]
