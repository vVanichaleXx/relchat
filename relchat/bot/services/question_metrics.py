from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from relchat.bot.localization import t
from relchat.core.models import Message


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
QUESTION_WORD_RE = re.compile(
    r"\b("
    r"who|what|when|where|why|how|which|can|could|would|should|do|does|did|is|are|will|"
    r"кто|что|когда|где|почему|зачем|как|какой|какая|какие|можешь|можно|будешь|будет|"
    r"давай|надо|нужно"
    r")\b",
    re.IGNORECASE,
)
RHETORICAL_RE = re.compile(
    r"\b(who cares|right\?|isn't it\?|isnt it\?|you know\?|ну и что\?|разве нет\?|не так ли\?)\b",
    re.IGNORECASE,
)
CODE_HINT_RE = re.compile(r"```|^\s{4,}\S|;\s*$|\b(def|class|SELECT|INSERT|UPDATE|DELETE|function|const|let|var)\b", re.MULTILINE)


@dataclass(frozen=True)
class QuestionCandidate:
    message: Message
    participant: str
    raw_question_marks: int
    direct: bool
    rhetorical: bool
    excluded_reason: str | None


def build_question_metrics(messages: Sequence[Message], *, language: str = "en") -> dict[str, Any]:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    text_messages = [message for message in ordered if (message.text or "").strip()]
    candidates = [classify_question_candidate(message) for message in text_messages]
    by_participant = {
        "you": participant_question_metrics(candidates, text_messages, outgoing=True),
        "other": participant_question_metrics(candidates, text_messages, outgoing=False),
    }
    raw_count = sum(1 for item in candidates if item.raw_question_marks > 0)
    direct_count = sum(1 for item in candidates if item.direct)
    excluded_counts: dict[str, int] = {}
    for item in candidates:
        if item.excluded_reason:
            excluded_counts[item.excluded_reason] = excluded_counts.get(item.excluded_reason, 0) + 1
    return {
        "message_count": len(ordered),
        "text_message_count": len(text_messages),
        "raw_question_mark_candidates": raw_count,
        "direct_question_count": direct_count,
        "rhetorical_candidate_count": sum(1 for item in candidates if item.rhetorical),
        "excluded_counts": excluded_counts,
        "by_participant": by_participant,
        "summary": format_question_metric_summary(
            {
                "message_count": len(ordered),
                "text_message_count": len(text_messages),
                "raw_question_mark_candidates": raw_count,
                "direct_question_count": direct_count,
                "by_participant": by_participant,
            },
            language=language,
        ),
    }


def classify_question_candidate(message: Message) -> QuestionCandidate:
    text = message.text or ""
    participant = "you" if message.is_outgoing else "other"
    raw_marks = text.count("?")
    if not text.strip():
        return QuestionCandidate(message, participant, raw_marks, False, False, None)
    if getattr(message, "forward_info", None):
        return QuestionCandidate(message, participant, raw_marks, False, False, "forwarded")
    if CODE_HINT_RE.search(text):
        return QuestionCandidate(message, participant, raw_marks, False, False, "code")
    without_urls = URL_RE.sub("", text)
    if raw_marks and "?" not in without_urls and not QUESTION_WORD_RE.search(without_urls):
        return QuestionCandidate(message, participant, raw_marks, False, False, "url")
    visible = non_quoted_text(without_urls)
    if raw_marks and not visible.strip():
        return QuestionCandidate(message, participant, raw_marks, False, False, "quote")
    if raw_marks >= 2 and re.fullmatch(r"[\s?!.,…]+", visible or ""):
        return QuestionCandidate(message, participant, raw_marks, False, False, "repeated_punctuation")
    rhetorical = bool(RHETORICAL_RE.search(visible))
    direct = bool("?" in visible and QUESTION_WORD_RE.search(visible)) or direct_question_without_mark(visible)
    if rhetorical and not direct_question_without_mark(visible):
        direct = False
    return QuestionCandidate(message, participant, raw_marks, direct, rhetorical, None if direct or rhetorical or raw_marks == 0 else "weak_candidate")


def non_quoted_text(text: str) -> str:
    lines = []
    for line in text.splitlines() or [text]:
        stripped = line.lstrip()
        if stripped.startswith(">") or stripped.startswith("»"):
            continue
        lines.append(line)
    return "\n".join(lines)


def direct_question_without_mark(text: str) -> bool:
    normalized = f" {text.casefold().strip()} "
    starters = (
        " can you ",
        " could you ",
        " would you ",
        " tell me ",
        " please confirm ",
        " можешь ",
        " скажи ",
        " скажите ",
        " подтвердите ",
        " давай уточним ",
    )
    return any(starter in normalized for starter in starters)


def participant_question_metrics(candidates: Sequence[QuestionCandidate], messages: Sequence[Message], *, outgoing: bool) -> dict[str, Any]:
    side = "you" if outgoing else "other"
    text_count = sum(1 for message in messages if message.is_outgoing is outgoing)
    raw_count = sum(1 for item in candidates if item.participant == side and item.raw_question_marks > 0)
    direct_count = sum(1 for item in candidates if item.participant == side and item.direct)
    rhetorical_count = sum(1 for item in candidates if item.participant == side and item.rhetorical)
    rate = direct_count / text_count if text_count else 0.0
    return {
        "text_messages": text_count,
        "raw_question_mark_candidates": raw_count,
        "direct_question_count": direct_count,
        "rhetorical_candidate_count": rhetorical_count,
        "question_rate": round(rate, 4),
        "per_100_messages": round(rate * 100.0, 1),
    }


def format_question_metric_summary(metrics: dict[str, Any], *, language: str = "en") -> str:
    by_participant = metrics.get("by_participant") if isinstance(metrics.get("by_participant"), dict) else {}
    you = by_participant.get("you") if isinstance(by_participant.get("you"), dict) else {}
    other = by_participant.get("other") if isinstance(by_participant.get("other"), dict) else {}
    user_count = int(you.get("direct_question_count") or 0)
    user_denominator = int(you.get("text_messages") or 0)
    user_rate = float(you.get("per_100_messages") or 0.0)
    other_rate = float(other.get("per_100_messages") or 0.0)
    return t(
        language,
        "question_metric_normalized",
        count=user_count,
        denominator=user_denominator,
        rate=f"{user_rate:.1f}",
        other_rate=f"{other_rate:.1f}",
    )


def question_evidence_finding(metrics: dict[str, Any], *, unanswered_count: int, period_label: str, context_category: str, language: str) -> dict[str, Any] | None:
    if unanswered_count <= 0:
        return None
    by_participant = metrics.get("by_participant") if isinstance(metrics.get("by_participant"), dict) else {}
    you = by_participant.get("you") if isinstance(by_participant.get("you"), dict) else {}
    direct_count = int(you.get("direct_question_count") or 0)
    denominator = int(you.get("text_messages") or 0)
    if denominator <= 0:
        return None
    rate = float(you.get("per_100_messages") or 0.0)
    severity = "problem" if unanswered_count >= 8 and rate >= 8.0 else ("attention" if unanswered_count >= 2 else "neutral")
    return {
        "finding_id": "questions_1",
        "finding_type": "unanswered_questions",
        "semantic_key": "question_engagement:unanswered_normalized",
        "title": t(language, "finding_title_unanswered_questions"),
        "observation": t(language, "question_metric_unanswered_observation", unanswered=unanswered_count, count=direct_count, denominator=denominator, rate=f"{rate:.1f}"),
        "interpretation": t(language, "question_metric_unanswered_interpretation"),
        "confidence": "medium" if denominator >= 20 else "low",
        "severity": severity,
        "semantic_source": "local_pattern",
        "semantic_depth": "direct",
        "evidence": [
            {
                "evidence_id": "ev_questions_rate",
                "evidence_type": "event_pattern",
                "source": "local_pattern",
                "message_ref": "",
                "sender": "YOU",
                "description": "normalized_question_rate",
            }
        ],
        "alternative_interpretations": [t(language, "question_metric_alternative")],
        "limitations": [t(language, "question_metric_limitation")],
        "period_scope": period_label,
        "context_scope": context_category,
    }

