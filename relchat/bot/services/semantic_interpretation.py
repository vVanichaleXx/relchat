from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from relchat.analytics.metrics import summarize
from relchat.bot.localization import t
from relchat.core.models import Message


INTERPRETATION_STATUSES = {"available", "insufficient_data", "ambiguous", "not_applicable"}
CONFIDENCE_VALUES = {"low", "medium", "high"}
SEMANTIC_SOURCES = {"explicit_rule", "local_pattern", "ai_interpretation", "historical_pattern", "combined", "unknown"}
SEMANTIC_DEPTHS = {"direct", "suggestive", "contextual"}
INTERPRETATION_LEVELS = {"directly_observed", "strongly_supported_interpretation", "unsupported_or_ambiguous"}
EVIDENCE_TYPES = {
    "explicit_wording",
    "contextual_sequence",
    "repeated_pattern",
    "participant_comparison",
    "period_comparison",
    "response_behavior",
    "event_pattern",
    "semantic_pattern",
    "historical_recurrence",
}

SARCASM_MARKERS = (
    "yeah right",
    "sure, great",
    "great job",
    "brilliant",
    "as if",
    "/s",
    "sarcasm",
    "obviously",
    "ну конечно",
    "ага, конечно",
    "прекрасно, опять",
    "сарказм",
    "ирония",
    "молодец",
)
PLAYFUL_MARKERS = ("haha", "lol", "lmao", "just kidding", "joking", "😂", "😄", "ахах", "лол", "шучу", "шутка", "))")
DISMISSIVE_MARKERS = ("whatever", "sure", "cool story", "if you say so", "неважно", "как скажешь", "ну да", "ясно всё")
INSULT_MARKERS = (
    "idiot",
    "stupid",
    "moron",
    "loser",
    "pathetic",
    "shut up",
    "worthless",
    "тупой",
    "тупая",
    "идиот",
    "дурак",
    "дура",
    "заткнись",
    "ничтож",
)
THREAT_MARKERS = ("or else", "i will hurt", "i'll hurt", "i will ruin", "i'll ruin", "убью", "пожалеешь", "сломаю")
FRUSTRATION_MARKERS = ("frustrated", "annoyed", "angry", "this is annoying", "раздраж", "злюсь", "устал от")
BOUNDARY_MARKERS = ("i don't agree", "i cannot", "i can't", "please stop", "no, i won't", "нет, я не", "я не соглас", "пожалуйста, не")
REFUSAL_MARKERS = ("no", "i can't", "i cannot", "not comfortable", "don't want", "нет", "не могу", "не хочу", "мне некомфортно")
REQUEST_MARKERS = ("please", "can you", "could you", "will you", "answer", "tell me", "пожалуйста", "можешь", "ответь", "скажи")
GUILT_MARKERS = (
    "if you cared",
    "after all i did",
    "you owe me",
    "because of you",
    "i guess i mean nothing",
    "если бы тебе было не всё равно",
    "если бы тебе было не все равно",
    "после всего",
    "ты должен",
    "ты должна",
    "из-за тебя",
)
URGENCY_MARKERS = ("now", "immediately", "right now", "urgent", "сейчас", "немедленно", "срочно")
PERSUASION_MARKERS = ("because", "reason", "would you consider", "you can decide", "option", "потому что", "аргумент", "можешь решить", "вариант")
AFFECTION_MARKERS = ("miss you", "love you", "i like you", "sweet", "cute", "люблю", "скучаю", "нравишься", "милый", "милая")
PERSONAL_QUESTION_MARKERS = ("how are you", "how was your day", "tell me about", "what do you feel", "как ты", "как день", "расскажи о себе", "что чувствуешь")
INVITATION_MARKERS = ("date", "just us", "dinner together", "meet just the two", "let's meet", "свидание", "вдвоём", "вдвоем", "увидимся", "встретимся")
TOPIC_SWITCH_MARKERS = ("anyway", "whatever", "forget it", "ладно", "проехали", "забей", "неважно")


@dataclass(frozen=True)
class Signal:
    signal_type: str
    message: Message
    evidence_type: str
    weight: int = 1
    source: str = "local_pattern"
    semantic_depth: str = "suggestive"


def analyze_semantics(
    *,
    messages: Sequence[Message],
    context_category: str = "unknown",
    period_label: str = "",
    language: str = "en",
    source: str = "explicit_deterministic_rule",
) -> dict[str, Any]:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    sarcasm_signals = detect_sarcasm_signals(ordered)
    aggression_signals = detect_aggression_signals(ordered)
    influence_signals = detect_influence_signals(ordered)
    interest_signals, interest_contradictions = detect_interest_signals(ordered)
    sarcasm = build_sarcasm_result(sarcasm_signals, messages=ordered, period_label=period_label, context_category=context_category, language=language, source=source)
    aggression = build_aggression_result(aggression_signals, messages=ordered, period_label=period_label, context_category=context_category, language=language, source=source)
    influence = build_influence_result(influence_signals, messages=ordered, period_label=period_label, context_category=context_category, language=language, source=source)
    possible_interest = build_possible_interest_result(
        interest_signals,
        interest_contradictions,
        messages=ordered,
        period_label=period_label,
        context_category=context_category,
        language=language,
        source=source,
    )
    findings = evidence_findings_from_semantics(
        sarcasm=sarcasm,
        aggression=aggression,
        influence=influence,
        possible_interest=possible_interest,
        language=language,
    )
    return {
        "model": "three_level_interpretation_v1",
        "levels": [
            {"level": "directly_observed", "description": t(language, "interpretation_level_observed")},
            {"level": "strongly_supported_interpretation", "description": t(language, "interpretation_level_supported")},
            {"level": "unsupported_or_ambiguous", "description": t(language, "interpretation_level_ambiguous")},
        ],
        "sarcasm": sarcasm,
        "aggression": aggression,
        "influence": influence,
        "possible_interest": possible_interest,
        "findings": findings,
    }


def detect_sarcasm_signals(messages: Sequence[Message]) -> list[Signal]:
    result: list[Signal] = []
    for index, message in enumerate(messages):
        text = normalized(message.text)
        if not text:
            continue
        marker_count = count_matches(text, SARCASM_MARKERS)
        playful_count = count_matches(text, PLAYFUL_MARKERS)
        dismissive_count = count_matches(text, DISMISSIVE_MARKERS)
        quote_signal = bool(re.search(r'["«»][^"«»]{2,30}["«»]', message.text or "")) and dismissive_count
        previous_question = index > 0 and "?" in (messages[index - 1].text or "")
        current_topic_switch = any(marker in text for marker in TOPIC_SWITCH_MARKERS)
        next_topic_switch = index + 1 < len(messages) and any(marker in normalized(messages[index + 1].text) for marker in TOPIC_SWITCH_MARKERS)
        explicit_label = "/s" in text or "sarcasm" in text or "сарказм" in text or "ирония" in text
        if explicit_label:
            result.append(Signal("explicit_sarcasm", message, "explicit_wording", 3, source="explicit_rule", semantic_depth="direct"))
        elif marker_count >= 1:
            result.append(Signal("sarcasm_marker", message, "semantic_pattern", 1, source="local_pattern", semantic_depth="suggestive"))
        if quote_signal:
            result.append(Signal("sarcasm_quotes", message, "semantic_pattern", 1, source="local_pattern", semantic_depth="suggestive"))
        if playful_count >= 1 and marker_count >= 1:
            result.append(Signal("playful_sarcasm", message, "semantic_pattern", 1, source="local_pattern", semantic_depth="suggestive"))
        if dismissive_count >= 1 and (previous_question or current_topic_switch or next_topic_switch or marker_count >= 1):
            result.append(Signal("dismissive_sarcasm", message, "contextual_sequence", 2, source="local_pattern", semantic_depth="suggestive"))
        if marker_count == 0 and playful_count == 1 and dismissive_count == 0:
            result.append(Signal("ambiguous_humour_marker", message, "semantic_pattern", 0, source="local_pattern", semantic_depth="suggestive"))
    return result


def detect_aggression_signals(messages: Sequence[Message]) -> list[Signal]:
    result: list[Signal] = []
    for message in messages:
        text = normalized(message.text)
        if not text:
            continue
        insults = count_matches(text, INSULT_MARKERS)
        threats = count_matches(text, THREAT_MARKERS)
        frustration = count_matches(text, FRUSTRATION_MARKERS)
        boundary = count_matches(text, BOUNDARY_MARKERS)
        if threats:
            result.append(Signal("threat", message, "explicit_wording", 3, source="explicit_rule", semantic_depth="direct"))
        if insults:
            result.append(Signal("insult", message, "explicit_wording", 2, source="explicit_rule", semantic_depth="direct"))
        if repeated_command(text):
            result.append(Signal("aggressive_command", message, "explicit_wording", 2, source="explicit_rule", semantic_depth="direct"))
        if frustration and not insults and not threats:
            result.append(Signal("frustration", message, "explicit_wording", 1, source="explicit_rule", semantic_depth="direct"))
        if boundary and not insults and not threats:
            result.append(Signal("assertive_boundary", message, "explicit_wording", 1, source="explicit_rule", semantic_depth="direct"))
    return result


def detect_influence_signals(messages: Sequence[Message]) -> list[Signal]:
    result: list[Signal] = []
    last_refusal_index: int | None = None
    for index, message in enumerate(messages):
        text = normalized(message.text)
        if not text:
            continue
        refusal = count_matches(text, REFUSAL_MARKERS)
        request = count_matches(text, REQUEST_MARKERS)
        guilt = count_matches(text, GUILT_MARKERS)
        urgency = count_matches(text, URGENCY_MARKERS)
        persuasion = count_matches(text, PERSUASION_MARKERS)
        if refusal:
            last_refusal_index = index
            result.append(Signal("refusal", message, "explicit_wording", 1, source="explicit_rule", semantic_depth="direct"))
        if persuasion and request:
            result.append(Signal("transparent_persuasion", message, "semantic_pattern", 1, source="local_pattern", semantic_depth="suggestive"))
        if guilt:
            result.append(Signal("guilt_pressure", message, "explicit_wording", 2, source="explicit_rule", semantic_depth="direct"))
        if urgency and request:
            result.append(Signal("urgency_pressure", message, "semantic_pattern", 1, source="local_pattern", semantic_depth="suggestive"))
        if request and last_refusal_index is not None and index > last_refusal_index:
            result.append(Signal("request_after_refusal", message, "contextual_sequence", 2, source="local_pattern", semantic_depth="suggestive"))
    return result


def detect_interest_signals(messages: Sequence[Message]) -> tuple[list[Signal], list[Signal]]:
    support: list[Signal] = []
    contradiction: list[Signal] = []
    for message in messages:
        text = normalized(message.text)
        if not text:
            continue
        if count_matches(text, AFFECTION_MARKERS):
            support.append(Signal("affectionate_language", message, "explicit_wording", 2, source="explicit_rule", semantic_depth="direct"))
        if count_matches(text, PERSONAL_QUESTION_MARKERS):
            support.append(Signal("personal_question", message, "semantic_pattern", 1, source="local_pattern", semantic_depth="suggestive"))
        if count_matches(text, INVITATION_MARKERS):
            support.append(Signal("private_invitation", message, "explicit_wording", 2, source="explicit_rule", semantic_depth="direct"))
        if count_matches(text, REFUSAL_MARKERS):
            contradiction.append(Signal("refusal_or_reluctance", message, "explicit_wording", 1, source="explicit_rule", semantic_depth="direct"))
    metrics = summarize(messages, "conversation") if messages else {}
    initiation = metrics.get("initiation_balance") or {}
    session_count = int(initiation.get("session_count") or 0)
    if session_count >= 4:
        support.append(Signal("reciprocal_initiation", messages[-1], "response_behavior", 1, source="local_pattern", semantic_depth="suggestive"))
    return support, contradiction


def build_sarcasm_result(
    signals: list[Signal],
    *,
    messages: Sequence[Message],
    period_label: str,
    context_category: str,
    language: str,
    source: str,
) -> dict[str, Any]:
    weighted = sum(max(0, signal.weight) for signal in signals if signal.signal_type != "ambiguous_humour_marker")
    direct_explicit = any(signal.signal_type == "explicit_sarcasm" and signal.weight > 0 for signal in signals)
    positive_signals = [signal for signal in signals if signal.weight > 0 and signal.signal_type != "ambiguous_humour_marker"]
    independent_types = {signal.signal_type for signal in positive_signals}
    repeated_messages = {signal.message.source_message_id for signal in positive_signals}
    ai_confirmed = source == "ai_interpretation" and weighted > 0
    repeated_local_support = weighted >= 4 and len(independent_types) >= 2 and len(repeated_messages) >= 2
    ambiguous = bool(signals) and not (direct_explicit or repeated_local_support or ai_confirmed)
    if not messages:
        status = "insufficient_data"
        presence = None
        direction = None
    elif ambiguous:
        status = "ambiguous"
        presence = None
        direction = None
    elif weighted <= 0:
        status = "insufficient_data"
        presence = None
        direction = None
    else:
        status = "available"
        presence = "frequent" if weighted >= 6 else ("recurring" if weighted >= 3 else "isolated")
        direction = sarcasm_direction(signals)
    confidence = sarcasm_confidence(status=status, weighted=weighted, direct_explicit=direct_explicit, repeated_local_support=repeated_local_support, ai_confirmed=ai_confirmed)
    metadata = semantic_source_metadata(signals, requested_source=source, status=status, direct=direct_explicit, contextual=ai_confirmed)
    evidence = evidence_from_signals(signals, limit=5, source=metadata["source"])
    return {
        "status": status,
        "presence": presence,
        "direction": direction,
        "confidence": confidence,
        **metadata,
        "evidence_count": evidence_count(signals),
        "summary": sarcasm_summary(status, direction, presence, semantic_source=metadata["source"], semantic_depth=metadata["semantic_depth"], language=language),
        "impact": sarcasm_impact(status, direction, language=language),
        "interpretation_level": interpretation_level(status, evidence_count(signals), direct=direct_explicit),
        "evidence": evidence,
        "alternative_interpretations": sarcasm_alternatives(status, direction, language=language),
        "limitations": [t(language, "semantic_scope_limitation")],
        "period_scope": period_label,
        "context_scope": context_category,
    }


def build_aggression_result(
    signals: list[Signal],
    *,
    messages: Sequence[Message],
    period_label: str,
    context_category: str,
    language: str,
    source: str,
) -> dict[str, Any]:
    direct_aggression = [signal for signal in signals if signal.signal_type in {"threat", "insult", "aggressive_command"}]
    frustration = [signal for signal in signals if signal.signal_type == "frustration"]
    boundary = [signal for signal in signals if signal.signal_type == "assertive_boundary"]
    if not messages:
        status = "insufficient_data"
        kind = None
        frequency = None
    elif direct_aggression:
        status = "available"
        kind = "hostility" if any(signal.signal_type == "threat" for signal in direct_aggression) or len(direct_aggression) >= 3 else "verbal_aggression"
        frequency = "frequent" if len(direct_aggression) >= 5 else ("recurring" if len(direct_aggression) >= 2 else "isolated")
    elif frustration:
        status = "available"
        kind = "frustration"
        frequency = "recurring" if len(frustration) >= 2 else "isolated"
    elif boundary:
        status = "available"
        kind = "assertiveness"
        frequency = "recurring" if len(boundary) >= 2 else "isolated"
    else:
        status = "insufficient_data"
        kind = None
        frequency = None
    confidence = "high" if direct_aggression and len(direct_aggression) >= 2 else ("medium" if direct_aggression or frustration or boundary else "low")
    metadata = semantic_source_metadata(signals, requested_source=source, status=status, direct=bool(direct_aggression or frustration or boundary), contextual=False)
    return {
        "status": status,
        "type": kind,
        "frequency": frequency,
        "confidence": confidence if status == "available" else "low",
        **metadata,
        "evidence_count": evidence_count(signals),
        "summary": aggression_summary(status, kind, frequency, language=language),
        "impact_on_dialogue": aggression_impact(status, kind, language=language),
        "interpretation_level": interpretation_level(status, evidence_count(direct_aggression or frustration or boundary), direct=has_direct_signal(signals)),
        "evidence": evidence_from_signals(signals, limit=5, source=metadata["source"]),
        "alternative_interpretations": aggression_alternatives(kind, language=language),
        "limitations": [t(language, "semantic_scope_limitation")],
        "period_scope": period_label,
        "context_scope": context_category,
    }


def build_influence_result(
    signals: list[Signal],
    *,
    messages: Sequence[Message],
    period_label: str,
    context_category: str,
    language: str,
    source: str,
) -> dict[str, Any]:
    repeated_after_refusal = [signal for signal in signals if signal.signal_type == "request_after_refusal"]
    guilt = [signal for signal in signals if signal.signal_type == "guilt_pressure"]
    urgency = [signal for signal in signals if signal.signal_type == "urgency_pressure"]
    persuasion = [signal for signal in signals if signal.signal_type == "transparent_persuasion"]
    if not messages:
        status = "insufficient_data"
        category = None
        strategy = ""
    elif guilt and (repeated_after_refusal or len(guilt) >= 2):
        status = "available"
        category = "possible_manipulation" if len(guilt) < 3 else "clear_manipulative_pattern"
        strategy = "guilt_induction_after_reluctance"
    elif repeated_after_refusal or len(urgency) >= 2:
        status = "available"
        category = "pressure"
        strategy = "repeated_request_after_refusal" if repeated_after_refusal else "urgency_pressure"
    elif persuasion:
        status = "available"
        category = "persuasion"
        strategy = "transparent_reason_giving"
    elif guilt or urgency:
        status = "ambiguous"
        category = None
        strategy = ""
    else:
        status = "insufficient_data"
        category = None
        strategy = ""
    strong_count = len(repeated_after_refusal) + len(guilt) + len(urgency) + len(persuasion)
    confidence = "high" if strong_count >= 4 else ("medium" if strong_count >= 2 or status == "available" else "low")
    metadata = semantic_source_metadata(signals, requested_source=source, status=status, direct=bool(guilt), contextual=bool(repeated_after_refusal))
    return {
        "status": status,
        "category": category,
        "strategy": strategy,
        "confidence": confidence if status == "available" else "low",
        **metadata,
        "evidence_count": evidence_count(signals),
        "summary": influence_summary(status, category, strategy, language=language),
        "effect": influence_effect(status, category, language=language),
        "interpretation_level": interpretation_level(status, evidence_count(signals), direct=has_direct_signal(signals)),
        "evidence": evidence_from_signals(signals, limit=6, source=metadata["source"]),
        "alternative_interpretations": influence_alternatives(status, category, language=language),
        "limitations": [t(language, "semantic_scope_limitation")],
        "period_scope": period_label,
        "context_scope": context_category,
    }


def build_possible_interest_result(
    supporting: list[Signal],
    contradicting: list[Signal],
    *,
    messages: Sequence[Message],
    period_label: str,
    context_category: str,
    language: str,
    source: str,
) -> dict[str, Any]:
    if context_category in {"work", "customer_or_service", "family", "group_social", "channel_or_broadcast"}:
        status = "not_applicable"
        strength = None
    elif not messages or len(messages) < 10:
        status = "insufficient_data"
        strength = None
    else:
        support_weight = sum(max(0, signal.weight) for signal in supporting)
        contradiction_weight = sum(max(0, signal.weight) for signal in contradicting)
        net = support_weight - contradiction_weight
        if support_weight >= 4 and net >= 2:
            status = "available"
            strength = "strong" if net >= 5 else "moderate"
        elif support_weight >= 2:
            status = "ambiguous"
            strength = "weak"
        else:
            status = "insufficient_data"
            strength = None
    confidence = "high" if status == "available" and strength == "strong" else ("medium" if status == "available" else "low")
    metadata = semantic_source_metadata(supporting + contradicting, requested_source=source, status=status, direct=has_direct_signal(supporting), contextual=status == "available")
    return {
        "status": status,
        "signal_strength": strength,
        "confidence": confidence,
        **metadata,
        "supporting_signals": signal_summaries(supporting, language=language),
        "contradicting_signals": signal_summaries(contradicting, language=language),
        "summary": interest_summary(status, strength, language=language),
        "interpretation_level": interpretation_level(status, len(supporting), direct=has_direct_signal(supporting)),
        "evidence_count": evidence_count(supporting) + evidence_count(contradicting),
        "evidence": evidence_from_signals(supporting + contradicting, limit=6, source=metadata["source"]),
        "alternative_interpretations": interest_alternatives(status, language=language),
        "limitations": [t(language, "interest_not_proven_limitation"), t(language, "semantic_scope_limitation")],
        "period_scope": period_label,
        "context_scope": context_category,
    }


def evidence_findings_from_semantics(
    *,
    sarcasm: dict[str, Any],
    aggression: dict[str, Any],
    influence: dict[str, Any],
    possible_interest: dict[str, Any],
    language: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for finding_type, result in [
        ("sarcasm", sarcasm),
        ("aggression", aggression),
        ("influence", influence),
        ("possible_interest", possible_interest),
    ]:
        if result.get("status") != "available":
            continue
        findings.append(
            {
                "finding_id": f"{finding_type}_1",
                "finding_type": finding_type,
                "title": finding_title(finding_type, result, language=language),
                "observation": finding_observation(finding_type, result, language=language),
                "interpretation": str(result.get("summary") or ""),
                "confidence": result.get("confidence") or "low",
                "severity": finding_severity(finding_type, result),
                "semantic_key": f"{finding_type}:{result.get('direction') or result.get('type') or result.get('category') or result.get('signal_strength') or 'general'}",
                "semantic_source": result.get("semantic_source") or result.get("source") or "unknown",
                "semantic_depth": result.get("semantic_depth") or "suggestive",
                "evidence": result.get("evidence") or [],
                "alternative_interpretations": result.get("alternative_interpretations") or [],
                "limitations": result.get("limitations") or [],
                "period_scope": result.get("period_scope"),
                "context_scope": result.get("context_scope"),
                "advice": evidence_linked_advice(finding_type, result, language=language),
            }
        )
    return findings[:6]


def normalized(value: str | None) -> str:
    return f" {(value or '').casefold()} "


def count_matches(text: str, markers: Sequence[str]) -> int:
    count = 0
    for marker in markers:
        normalized_marker = marker.casefold().strip()
        if not normalized_marker:
            continue
        if re.fullmatch(r"[\w-]+", normalized_marker):
            if re.search(rf"(?<!\w){re.escape(normalized_marker)}(?!\w)", text):
                count += 1
            continue
        if normalized_marker in text:
            count += 1
    return count


def repeated_command(text: str) -> bool:
    return ("answer" in text or "ответь" in text or "do it" in text or "сделай" in text) and count_matches(text, URGENCY_MARKERS) >= 1


def evidence_count(signals: Sequence[Signal]) -> int:
    return sum(1 for signal in signals if signal.weight > 0)


def has_direct_signal(signals: Sequence[Signal]) -> bool:
    return any(signal.evidence_type == "explicit_wording" and signal.weight > 0 for signal in signals)


def sarcasm_confidence(*, status: str, weighted: int, direct_explicit: bool, repeated_local_support: bool, ai_confirmed: bool) -> str:
    if status != "available":
        return "low"
    if direct_explicit and weighted >= 3:
        return "high"
    if ai_confirmed and weighted >= 2:
        return "medium"
    if repeated_local_support and weighted >= 5:
        return "medium"
    return "low"


def semantic_source_metadata(
    signals: Sequence[Signal],
    *,
    requested_source: str,
    status: str,
    direct: bool,
    contextual: bool,
) -> dict[str, str]:
    if requested_source == "ai_interpretation":
        source = "ai_interpretation"
    elif requested_source in {"historical_pattern", "combined"}:
        source = requested_source
    elif direct or any(signal.source == "explicit_rule" for signal in signals if signal.weight > 0):
        source = "explicit_rule"
    else:
        source = "local_pattern"
    if status != "available":
        depth = "suggestive"
    elif direct:
        depth = "direct"
    elif contextual or source == "ai_interpretation":
        depth = "contextual"
    else:
        depth = "suggestive"
    return {"source": source, "semantic_source": source, "semantic_depth": depth}


def evidence_from_signals(signals: Sequence[Signal], *, limit: int, source: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for signal in signals:
        if signal.weight <= 0:
            continue
        key = (signal.signal_type, signal.message.source_message_id)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(
            {
                "evidence_id": f"ev_{len(evidence) + 1}",
                "evidence_type": signal.evidence_type,
                "source": signal.source if source == "combined" else source,
                "semantic_depth": signal.semantic_depth,
                "message_ref": f"m{signal.message.source_message_id}",
                "sender": "YOU" if signal.message.is_outgoing else "OTHER",
                "description": signal_description(signal.signal_type),
            }
        )
        if len(evidence) >= limit:
            break
    return evidence


def signal_description(signal_type: str) -> str:
    return {
        "explicit_sarcasm": "explicit_sarcasm_label",
        "sarcasm_marker": "sarcasm_marker",
        "sarcasm_quotes": "dismissive_quotation_pattern",
        "playful_sarcasm": "playful_sarcasm_marker",
        "dismissive_sarcasm": "sarcasm_after_question_or_topic_shutdown",
        "threat": "explicit_threat_marker",
        "insult": "explicit_insult_marker",
        "aggressive_command": "urgent_repeated_command",
        "frustration": "explicit_frustration_marker",
        "assertive_boundary": "assertive_boundary_marker",
        "refusal": "explicit_refusal_marker",
        "transparent_persuasion": "reasoned_request_marker",
        "guilt_pressure": "guilt_or_obligation_pressure_marker",
        "urgency_pressure": "urgency_pressure_marker",
        "request_after_refusal": "request_repeated_after_refusal",
        "affectionate_language": "affectionate_language_marker",
        "personal_question": "personal_question_marker",
        "private_invitation": "private_invitation_marker",
        "reciprocal_initiation": "reciprocal_initiation_pattern",
        "refusal_or_reluctance": "refusal_or_reluctance_marker",
    }.get(signal_type, signal_type)


def signal_summaries(signals: Sequence[Signal], *, language: str) -> list[str]:
    labels = []
    for signal in signals:
        if signal.weight <= 0:
            continue
        labels.append(t(language, f"signal_{signal.signal_type}"))
    return dedupe(labels)[:6]


def dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def sarcasm_direction(signals: Sequence[Signal]) -> str:
    counts = Counter(signal.signal_type for signal in signals if signal.weight > 0)
    if counts["dismissive_sarcasm"] >= 1:
        return "dismissive"
    if counts["playful_sarcasm"] >= 1 and (counts["sarcasm_marker"] >= 1 or counts["explicit_sarcasm"] >= 1):
        return "playful"
    return "mixed" if len(counts) > 1 else "defensive"


def interpretation_level(status: str, count: int, *, direct: bool) -> str:
    if status not in {"available"}:
        return "unsupported_or_ambiguous"
    if direct:
        return "directly_observed"
    if count >= 2:
        return "strongly_supported_interpretation"
    return "unsupported_or_ambiguous"


def sarcasm_summary(status: str, direction: str | None, presence: str | None, *, semantic_source: str = "", semantic_depth: str = "", language: str) -> str:
    if status == "ambiguous":
        return t(language, "sarcasm_summary_ambiguous")
    if status != "available":
        return t(language, "sarcasm_summary_insufficient")
    if direction == "playful":
        return t(language, "sarcasm_summary_playful")
    if direction == "dismissive":
        if semantic_source == "local_pattern" and semantic_depth != "direct":
            return t(language, "sarcasm_summary_dismissive_local")
        return t(language, "sarcasm_summary_dismissive")
    if direction == "hostile":
        return t(language, "sarcasm_summary_hostile")
    return t(language, "sarcasm_summary_mixed", presence=presence or "")


def sarcasm_impact(status: str, direction: str | None, *, language: str) -> str:
    if status != "available":
        return t(language, "semantic_no_impact_available")
    return t(language, f"sarcasm_impact_{direction}") if direction else t(language, "sarcasm_impact_mixed")


def sarcasm_alternatives(status: str, direction: str | None, *, language: str) -> list[str]:
    if status == "available" and direction == "dismissive":
        return [t(language, "alternative_shared_humour")]
    if status == "ambiguous":
        return [t(language, "alternative_plain_joke"), t(language, "alternative_shared_humour")]
    return []


def aggression_summary(status: str, kind: str | None, frequency: str | None, *, language: str) -> str:
    if status != "available":
        return t(language, "aggression_summary_insufficient")
    return t(language, f"aggression_summary_{kind}", frequency=frequency or "")


def aggression_impact(status: str, kind: str | None, *, language: str) -> str:
    if status != "available":
        return t(language, "semantic_no_impact_available")
    if kind in {"verbal_aggression", "hostility"}:
        return t(language, "aggression_impact_direct")
    if kind == "assertiveness":
        return t(language, "aggression_impact_assertive")
    return t(language, "aggression_impact_frustration")


def aggression_alternatives(kind: str | None, *, language: str) -> list[str]:
    if kind in {"frustration", "assertiveness"}:
        return [t(language, "alternative_conflict_not_aggression")]
    return []


def influence_summary(status: str, category: str | None, strategy: str, *, language: str) -> str:
    if status == "ambiguous":
        return t(language, "influence_summary_ambiguous")
    if status != "available":
        return t(language, "influence_summary_insufficient")
    return t(language, f"influence_summary_{category}", strategy=t(language, f"influence_strategy_{strategy}") if strategy else "")


def influence_effect(status: str, category: str | None, *, language: str) -> str:
    if status != "available":
        return t(language, "semantic_no_impact_available")
    return t(language, f"influence_effect_{category}")


def influence_alternatives(status: str, category: str | None, *, language: str) -> list[str]:
    if status in {"ambiguous", "available"} and category in {None, "pressure", "possible_manipulation"}:
        return [t(language, "alternative_clumsy_request"), t(language, "alternative_stress")]
    return []


def interest_summary(status: str, strength: str | None, *, language: str) -> str:
    if status == "not_applicable":
        return t(language, "interest_summary_not_applicable")
    if status == "ambiguous":
        return t(language, "interest_summary_ambiguous")
    if status != "available":
        return t(language, "interest_summary_insufficient")
    return t(language, f"interest_summary_{strength}")


def interest_alternatives(status: str, *, language: str) -> list[str]:
    if status in {"available", "ambiguous"}:
        return [t(language, "alternative_friendliness"), t(language, "alternative_contextual_politeness")]
    return []


def finding_title(finding_type: str, result: dict[str, Any], *, language: str) -> str:
    if finding_type == "sarcasm":
        direction = result.get("direction") or "mixed"
        if direction == "dismissive" and result.get("semantic_source") == "local_pattern" and result.get("semantic_depth") != "direct":
            return t(language, "finding_title_sarcasm_dismissive_local")
        return t(language, f"finding_title_sarcasm_{direction}")
    if finding_type == "aggression":
        kind = result.get("type") or "mixed"
        return t(language, f"finding_title_aggression_{kind}")
    if finding_type == "influence":
        category = result.get("category") or "persuasion"
        return t(language, f"finding_title_influence_{category}")
    return t(language, "finding_title_possible_interest")


def finding_observation(finding_type: str, result: dict[str, Any], *, language: str) -> str:
    return t(language, "finding_observation_count", count=int(result.get("evidence_count") or 0), evidence_type=t(language, f"semantic_type_{finding_type}"))


def finding_severity(finding_type: str, result: dict[str, Any]) -> str:
    if finding_type == "possible_interest":
        return "neutral"
    if finding_type == "sarcasm":
        return "attention" if result.get("direction") in {"dismissive", "hostile", "defensive"} else "neutral"
    if finding_type == "aggression":
        return "problem" if result.get("type") in {"verbal_aggression", "hostility"} else "neutral"
    if finding_type == "influence":
        return "problem" if result.get("category") in {"possible_manipulation", "clear_manipulative_pattern"} else ("attention" if result.get("category") == "pressure" else "neutral")
    return "neutral"


def evidence_linked_advice(finding_type: str, result: dict[str, Any], *, language: str) -> dict[str, str]:
    if finding_type == "sarcasm" and result.get("direction") == "dismissive":
        return {"title": t(language, "advice_sarcasm_title"), "explanation": t(language, "advice_sarcasm_explanation")}
    if finding_type == "aggression" and result.get("type") in {"verbal_aggression", "hostility"}:
        return {"title": t(language, "advice_aggression_title"), "explanation": t(language, "advice_aggression_explanation")}
    if finding_type == "influence" and result.get("category") in {"pressure", "possible_manipulation", "clear_manipulative_pattern"}:
        return {"title": t(language, "advice_pressure_title"), "explanation": t(language, "advice_pressure_explanation")}
    if finding_type == "possible_interest":
        return {"title": t(language, "advice_interest_title"), "explanation": t(language, "advice_interest_explanation")}
    return {"title": t(language, "advice_clarity_title"), "explanation": t(language, "advice_clarity_explanation")}


def validate_semantic_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = dict(value)
    result["sarcasm"] = validate_sarcasm_result(result.get("sarcasm"))
    result["aggression"] = validate_aggression_result(result.get("aggression"))
    result["influence"] = validate_influence_result(result.get("influence"))
    result["possible_interest"] = validate_interest_result(result.get("possible_interest"))
    findings = result.get("findings") if isinstance(result.get("findings"), list) else []
    result["findings"] = [validate_evidence_finding(item) for item in findings[:8] if isinstance(item, dict)]
    result["model"] = str(result.get("model") or "three_level_interpretation_v1")
    result["levels"] = result.get("levels") if isinstance(result.get("levels"), list) else []
    return result


def validate_status(value: Any) -> str:
    text = str(value or "insufficient_data")
    return text if text in INTERPRETATION_STATUSES else "insufficient_data"


def validate_confidence(value: Any) -> str:
    text = str(value or "low")
    return text if text in CONFIDENCE_VALUES else "low"


def validate_sarcasm_result(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    status = validate_status(row.get("status"))
    presence = str(row.get("presence")) if row.get("presence") in {"none_visible", "isolated", "recurring", "frequent"} else None
    direction = str(row.get("direction")) if row.get("direction") in {"playful", "bonding", "defensive", "dismissive", "hostile", "mixed"} else None
    return {
        "status": status,
        "presence": presence if status == "available" else None,
        "direction": direction if status == "available" else None,
        "confidence": validate_confidence(row.get("confidence")),
        "source": validate_semantic_source(row.get("source") or row.get("semantic_source")),
        "semantic_source": validate_semantic_source(row.get("semantic_source") or row.get("source")),
        "semantic_depth": validate_semantic_depth(row.get("semantic_depth")),
        "evidence_count": safe_int(row.get("evidence_count")),
        "summary": str(row.get("summary") or ""),
        "impact": str(row.get("impact") or ""),
        "interpretation_level": validate_interpretation_level(row.get("interpretation_level")),
        "evidence": validate_evidence_list(row.get("evidence")),
        "alternative_interpretations": string_list(row.get("alternative_interpretations")),
        "limitations": string_list(row.get("limitations")),
        "period_scope": str(row.get("period_scope") or ""),
        "context_scope": str(row.get("context_scope") or ""),
    }


def validate_aggression_result(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    status = validate_status(row.get("status"))
    kind = str(row.get("type")) if row.get("type") in {"irritation", "frustration", "assertiveness", "conflict", "verbal_aggression", "hostility", "mixed"} else None
    return {
        "status": status,
        "type": kind if status == "available" else None,
        "frequency": str(row.get("frequency")) if row.get("frequency") in {"isolated", "recurring", "frequent"} and status == "available" else None,
        "confidence": validate_confidence(row.get("confidence")),
        "source": validate_semantic_source(row.get("source") or row.get("semantic_source")),
        "semantic_source": validate_semantic_source(row.get("semantic_source") or row.get("source")),
        "semantic_depth": validate_semantic_depth(row.get("semantic_depth")),
        "evidence_count": safe_int(row.get("evidence_count")),
        "summary": str(row.get("summary") or ""),
        "impact_on_dialogue": str(row.get("impact_on_dialogue") or ""),
        "interpretation_level": validate_interpretation_level(row.get("interpretation_level")),
        "evidence": validate_evidence_list(row.get("evidence")),
        "alternative_interpretations": string_list(row.get("alternative_interpretations")),
        "limitations": string_list(row.get("limitations")),
        "period_scope": str(row.get("period_scope") or ""),
        "context_scope": str(row.get("context_scope") or ""),
    }


def validate_influence_result(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    status = validate_status(row.get("status"))
    category = str(row.get("category")) if row.get("category") in {"persuasion", "pressure", "possible_manipulation", "clear_manipulative_pattern"} else None
    return {
        "status": status,
        "category": category if status == "available" else None,
        "strategy": str(row.get("strategy") or ""),
        "confidence": validate_confidence(row.get("confidence")),
        "source": validate_semantic_source(row.get("source") or row.get("semantic_source")),
        "semantic_source": validate_semantic_source(row.get("semantic_source") or row.get("source")),
        "semantic_depth": validate_semantic_depth(row.get("semantic_depth")),
        "evidence_count": safe_int(row.get("evidence_count")),
        "summary": str(row.get("summary") or ""),
        "effect": str(row.get("effect") or ""),
        "interpretation_level": validate_interpretation_level(row.get("interpretation_level")),
        "evidence": validate_evidence_list(row.get("evidence")),
        "alternative_interpretations": string_list(row.get("alternative_interpretations")),
        "limitations": string_list(row.get("limitations")),
        "period_scope": str(row.get("period_scope") or ""),
        "context_scope": str(row.get("context_scope") or ""),
    }


def validate_interest_result(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    status = validate_status(row.get("status"))
    strength = str(row.get("signal_strength")) if row.get("signal_strength") in {"weak", "moderate", "strong"} and status == "available" else None
    return {
        "status": status,
        "signal_strength": strength,
        "confidence": validate_confidence(row.get("confidence")),
        "source": validate_semantic_source(row.get("source") or row.get("semantic_source")),
        "semantic_source": validate_semantic_source(row.get("semantic_source") or row.get("source")),
        "semantic_depth": validate_semantic_depth(row.get("semantic_depth")),
        "supporting_signals": string_list(row.get("supporting_signals")),
        "contradicting_signals": string_list(row.get("contradicting_signals")),
        "summary": str(row.get("summary") or ""),
        "interpretation_level": validate_interpretation_level(row.get("interpretation_level")),
        "evidence_count": safe_int(row.get("evidence_count")),
        "evidence": validate_evidence_list(row.get("evidence")),
        "alternative_interpretations": string_list(row.get("alternative_interpretations")),
        "limitations": string_list(row.get("limitations")),
        "period_scope": str(row.get("period_scope") or ""),
        "context_scope": str(row.get("context_scope") or ""),
    }


def validate_evidence_finding(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    severity = str(row.get("severity") or "neutral")
    if severity not in {"positive", "neutral", "attention", "problem", "serious"}:
        severity = "neutral"
    status = validate_status(row.get("status") or "available")
    return {
        "finding_id": str(row.get("finding_id") or "finding"),
        "finding_type": str(row.get("finding_type") or "general"),
        "participant_scope": str(row.get("participant_scope") or "interaction"),
        "status": status,
        "title": str(row.get("title") or ""),
        "observation": str(row.get("observation") or ""),
        "interpretation": str(row.get("interpretation") or ""),
        "confidence": validate_confidence(row.get("confidence")),
        "severity": severity,
        "semantic_key": str(row.get("semantic_key") or ""),
        "semantic_source": validate_semantic_source(row.get("semantic_source") or row.get("source")),
        "semantic_depth": validate_semantic_depth(row.get("semantic_depth")),
        "evidence_count": safe_int(row.get("evidence_count")),
        "evidence_ids": string_list(row.get("evidence_ids")),
        "score_effect": safe_float(row.get("score_effect")),
        "advice_category": str(row.get("advice_category") or ""),
        "memory_eligible": bool(row.get("memory_eligible")),
        "evidence": validate_evidence_list(row.get("evidence")),
        "alternative_interpretations": string_list(row.get("alternative_interpretations")),
        "limitations": string_list(row.get("limitations")),
        "period_scope": str(row.get("period_scope") or ""),
        "context_scope": str(row.get("context_scope") or ""),
        "evidence_scope": str(row.get("evidence_scope") or row.get("scope") or ""),
        "advice": row.get("advice") if isinstance(row.get("advice"), dict) else {},
    }


def validate_evidence_list(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        evidence_type = str(row.get("evidence_type") or "semantic_pattern")
        if evidence_type not in EVIDENCE_TYPES:
            evidence_type = "semantic_pattern"
        result.append(
            {
                "evidence_id": str(row.get("evidence_id") or f"ev_{len(result) + 1}"),
                "evidence_type": evidence_type,
                "source": str(row.get("source") or "unknown"),
                "semantic_depth": validate_semantic_depth(row.get("semantic_depth")),
                "message_ref": str(row.get("message_ref") or ""),
                "sender": str(row.get("sender") or ""),
                "description": str(row.get("description") or ""),
            }
        )
    return result


def validate_interpretation_level(value: Any) -> str:
    text = str(value or "unsupported_or_ambiguous")
    return text if text in INTERPRETATION_LEVELS else "unsupported_or_ambiguous"


def validate_semantic_source(value: Any) -> str:
    text = str(value or "unknown")
    return text if text in SEMANTIC_SOURCES else "unknown"


def validate_semantic_depth(value: Any) -> str:
    text = str(value or "suggestive")
    return text if text in SEMANTIC_DEPTHS else "suggestive"


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def string_list(value: Any, *, limit: int = 8) -> list[str]:
    rows = value if isinstance(value, list) else []
    return [str(item) for item in rows[:limit] if str(item).strip()]
