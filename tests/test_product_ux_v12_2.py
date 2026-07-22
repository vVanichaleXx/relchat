from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from relchat.bot.formatters import format_ai_result_overview
from relchat.bot.services.advice_routing import route_advice, validate_advice_routes
from relchat.bot.services.ai_analysis import local_fallback_analysis, validate_ai_result
from relchat.bot.services.analysis_memory import memory_candidates_from_analysis
from relchat.bot.services.canonical_findings import build_canonical_findings
from relchat.bot.services.report_consistency import validate_report_consistency
from relchat.bot.services.score_explanation import build_score_explanation, validate_score_explanation_against_findings
from relchat.bot.services.semantic_interpretation import analyze_semantics
from relchat.bot.services.work_analysis import build_work_findings, work_effectiveness_score
from relchat.core.models import Message


BASE = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def msg(i: int, text: str, *, outgoing: bool | None = None, minutes: int | None = None) -> Message:
    if outgoing is None:
        outgoing = i % 2 == 1
    return Message(
        source="telegram",
        source_message_id=i,
        conversation_id="chat1",
        sender_id="me" if outgoing else "other",
        sender_name="Me" if outgoing else "Other",
        timestamp=(BASE + timedelta(minutes=minutes if minutes is not None else i)).isoformat(),
        text=text,
        message_type="text",
        reply_to_message_id=None,
        reactions=None,
        media_type=None,
        media_duration=None,
        forward_info=None,
        edit_date=None,
        is_outgoing=outgoing,
        raw_platform_payload_reference=None,
    )


def filler(start: int, count: int = 20, *, text: str = "status update") -> list[Message]:
    return [msg(start + index, text if index % 2 == 0 else "ok", outgoing=index % 2 == 0) for index in range(count)]


class ProductUxV122IntegrityTests(unittest.TestCase):
    def test_canonical_findings_are_single_source_for_score_and_advice(self) -> None:
        findings = build_canonical_findings(
            evidence_findings=[
                {
                    "finding_id": "sarcasm_1",
                    "finding_type": "sarcasm",
                    "title": "Possible sarcasm",
                    "status": "ambiguous",
                    "severity": "problem",
                    "confidence": "medium",
                    "semantic_source": "local_pattern",
                    "semantic_depth": "suggestive",
                    "evidence_count": 1,
                    "evidence": [{"evidence_id": "e1", "description": "sarcasm_marker", "source": "local_pattern"}],
                    "score_effect": -1.2,
                }
            ],
            context_category="work",
            period_label="today",
            language="en",
        )
        self.assertEqual(findings[0]["status"], "ambiguous")
        self.assertLessEqual(abs(findings[0]["score_effect"]), 0.2)
        self.assertNotEqual(findings[0]["severity"], "problem")

        explanation = validate_score_explanation_against_findings(
            {"negative_contributors": [{"text": "hostility", "finding_id": "missing", "severity": "problem"}]},
            findings,
            language="en",
        )
        self.assertFalse(explanation["negative_contributors"])

        advice = route_advice(findings, context_category="work", language="en")[0]
        self.assertEqual(advice["category"], "ambiguous_sarcasm")
        self.assertNotIn("insult", advice["explanation"].casefold())
        self.assertNotIn("threat", advice["explanation"].casefold())

    def test_local_sarcasm_does_not_create_hostility_or_aggression_advice(self) -> None:
        messages = [
            msg(1, "Can you clarify the deadline?", outgoing=True),
            msg(2, "ну конечно", outgoing=False),
            *filler(3, 30),
        ]
        result = local_fallback_analysis(messages=messages, events=[], period_label="today", chat_type="one_to_one", language="en", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        self.assertEqual(result["semantic_analysis"]["sarcasm"]["status"], "ambiguous")
        self.assertIsNone(result["dimensions"]["hostility"]["score"])
        self.assertFalse(any(row.get("category") == "aggression" for row in result["advice"]))
        self.assertFalse(any("hostil" in str(row).casefold() for row in result["score_explanation"]["negative_contributors"]))

    def test_supported_aggression_gets_aggression_advice_but_threat_requires_threat_evidence(self) -> None:
        aggression = build_canonical_findings(
            evidence_findings=[
                {
                    "finding_id": "aggression_1",
                    "finding_type": "aggression",
                    "title": "Direct insult",
                    "status": "available",
                    "severity": "problem",
                    "confidence": "high",
                    "semantic_source": "explicit_rule",
                    "semantic_depth": "direct",
                    "evidence_count": 1,
                    "evidence": [{"evidence_id": "e1", "description": "explicit_insult_marker", "source": "explicit_rule"}],
                }
            ],
            context_category="work",
            period_label="today",
            language="en",
        )
        advice = route_advice(aggression, context_category="work", language="en")[0]
        self.assertEqual(advice["category"], "aggression")
        self.assertNotIn("threat", advice["explanation"].casefold())

        threat_advice = [{"priority": 1, "finding_id": "aggression_1", "finding_type": "aggression", "category": "threat", "severity": "problem", "title": "Threat", "explanation": "threat", "example": ""}]
        self.assertFalse(validate_advice_routes(threat_advice, aggression, language="en"))

    def test_work_findings_drive_effectiveness_score(self) -> None:
        clear = [
            msg(1, "Task: send final file. Owner: me. Deadline today.", outgoing=True),
            msg(2, "Confirmed, approved.", outgoing=False),
            msg(3, "Done.", outgoing=True),
            *filler(4, 12, text="status update done"),
        ]
        unclear = [
            msg(1, "task deploy review", outgoing=True),
            msg(2, "what exactly should I fix?", outgoing=False),
            msg(3, "can you clarify deadline?", outgoing=True),
            msg(4, "which one?", outgoing=False),
            msg(5, "task ticket issue", outgoing=True),
            msg(6, "кто делает и какой срок?", outgoing=False),
            *filler(7, 30, text="task update"),
        ]
        clear_result = local_fallback_analysis(messages=clear, events=[], period_label="today", chat_type="one_to_one", language="en", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        unclear_result = local_fallback_analysis(messages=unclear, events=[], period_label="today", chat_type="one_to_one", language="en", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        self.assertGreater(clear_result["overall_score"], unclear_result["overall_score"])
        self.assertLessEqual(unclear_result["overall_score"], 6.4)
        self.assertTrue(any(row["finding_type"].startswith("work_") for row in unclear_result["canonical_findings"]))

    def test_report_consistency_removes_unsupported_contradictions(self) -> None:
        result = {
            "context": {"category": "work"},
            "canonical_findings": [],
            "score_explanation": {"negative_contributors": [{"text": "supported hostility", "finding_id": "hostility_1", "severity": "problem"}]},
            "advice": [{"priority": 1, "finding_id": "sarcasm_1", "finding_type": "sarcasm", "category": "aggression", "severity": "problem", "title": "Set boundary", "explanation": "direct insults or threats", "example": ""}],
            "recommended_action": {"action": "reduce_pressure", "explanation": "bad"},
            "adaptive_tone": "serious",
            "problem_patterns": [{"title": "hostile form", "explanation": "devaluation", "severity": "high", "evidence_type": "message_pattern"}],
            "direct_findings": [{"finding": "supported signs of hostile form", "severity": "high", "confidence": "medium", "evidence_type": "reply_pattern"}],
            "positive_patterns": [{"title": "Both sides participated", "explanation": "Activity exists", "evidence_type": "metric"}],
        }
        cleaned = validate_report_consistency(result, language="en")
        self.assertEqual(cleaned["adaptive_tone"], "neutral_limited")
        self.assertFalse(cleaned["score_explanation"]["negative_contributors"])
        self.assertFalse(cleaned["problem_patterns"])
        self.assertFalse(cleaned["direct_findings"])
        self.assertFalse(cleaned["positive_patterns"])
        self.assertNotEqual(cleaned["advice"][0]["category"], "aggression")

    def test_real_work_full_history_regression(self) -> None:
        messages = large_work_fixture()
        result = local_fallback_analysis(messages=messages, events=[], period_label="Вся история", chat_type="one_to_one", language="ru", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Рабочий чат", "result": result}, language="ru")
        self.assertEqual(result["semantic_analysis"]["sarcasm"]["status"], "ambiguous")
        self.assertGreater(result["overall_score"], 3.3)
        self.assertFalse(any("вражд" in str(row).casefold() or "агресс" in str(row).casefold() for row in result["score_explanation"]["negative_contributors"]))
        self.assertFalse(any("обесцен" in str(row).casefold() for row in result["score_explanation"]["negative_contributors"]))
        self.assertFalse(any(row.get("category") == "aggression" for row in result["advice"]))
        self.assertNotIn("оскорб", rendered.casefold())
        self.assertNotIn("угроз", rendered.casefold())
        self.assertNotIn("кандидат", rendered.casefold())
        self.assertNotIn("medium", rendered.casefold())
        self.assertEqual(rendered.count("Существенных изменений нет"), 1)
        self.assertIn("Рабочее общение", rendered)
        self.assertIn("Оценка эффективности", rendered)
        self.assertIn("Почему", rendered)
        self.assertFalse(memory_candidates_from_analysis(result))

    def test_partial_ai_failure_rebuilds_local_without_ai_semantic_claims(self) -> None:
        messages = [msg(1, "Can you clarify deadline?", outgoing=True), msg(2, "ну конечно", outgoing=False), *filler(3, 20)]
        local = local_fallback_analysis(messages=messages, events=[], period_label="today", chat_type="one_to_one", language="en", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        self.assertEqual(local["semantic_analysis"]["sarcasm"]["semantic_source"], "local_pattern")
        self.assertFalse(any(row.get("semantic_source") == "ai_interpretation" for row in local["canonical_findings"]))

    def test_validated_ai_result_rejects_unsupported_score_contributor_and_advice(self) -> None:
        result = minimal_ai_result(
            context={"category": "work", "confidence": "high", "evidence_types": ["title"], "source": "automatic", "explanation": "Work chat."},
            problem_patterns=[{"title": "hostile form", "explanation": "devaluation", "severity": "high", "evidence_type": "message_pattern"}],
            advice=[{"priority": 1, "finding_id": "sarcasm_1", "finding_type": "sarcasm", "category": "aggression", "severity": "problem", "title": "Boundary", "explanation": "Stop insults and threats.", "example": ""}],
            semantic_analysis={
                "sarcasm": {
                    "status": "ambiguous",
                    "presence": None,
                    "direction": None,
                    "confidence": "low",
                    "semantic_source": "local_pattern",
                    "semantic_depth": "suggestive",
                    "evidence_count": 1,
                    "summary": "Possible sarcasm.",
                    "impact": "",
                    "evidence": [{"evidence_id": "e1", "description": "sarcasm_marker", "source": "local_pattern"}],
                },
                "aggression": {"status": "insufficient_data"},
                "influence": {"status": "insufficient_data"},
                "possible_interest": {"status": "not_applicable"},
                "findings": [],
            },
            evidence_findings=[],
            score_explanation={"negative_contributors": [{"text": "hostile form", "finding_id": "hostility_1", "severity": "problem"}]},
            adaptive_tone="serious",
        )
        validated = validate_ai_result(result, dimensions={}, message_count=80, coverage={"sent_messages": 20, "available_messages": 80, "partial": True}, context_classification={"category": "work", "confidence": "high", "source": "automatic"})
        self.assertNotEqual(validated["adaptive_tone"], "serious")
        self.assertFalse(any("hostil" in str(row).casefold() for row in validated["score_explanation"]["negative_contributors"]))
        self.assertFalse(any(row.get("category") == "aggression" for row in validated["advice"]))


def large_work_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(4494):
        source_id = index + 1
        outgoing = index % 2 == 0
        if index >= 4425:
            text = "статус обновлен" if outgoing else "ок"
        elif index % 37 == 0:
            text = "Можешь уточнить срок по задаче?"
        elif index % 41 == 0:
            text = "Что именно нужно исправить по тикету?"
        elif index % 53 == 0:
            text = "task deploy review"
        elif index % 211 == 0:
            text = "ну конечно"
        elif outgoing:
            text = "статус по задаче"
        else:
            text = "ок принято"
        messages.append(msg(source_id, text, outgoing=outgoing, minutes=index * 90))
    return messages


def minimal_ai_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "summary": "Evidence is limited.",
        "context": {"category": "work", "confidence": "medium", "evidence_types": ["title"], "source": "automatic", "explanation": "Estimated."},
        "verdict": {"level": "mixed", "headline": "Mixed.", "explanation": "Evidence is mixed."},
        "conversation_state": "casual",
        "confidence": "medium",
        "direct_findings": [],
        "participant_analysis": {
            "you": {"summary": "", "observable_patterns": [], "strengths": [], "possible_improvements": []},
            "other": {"summary": "", "observable_patterns": [], "strengths": [], "possible_improvements": []},
        },
        "positive_patterns": [],
        "problem_patterns": [],
        "weak_reply_patterns": [],
        "uncertainties": ["The reason cannot be determined from messages alone."],
        "recommended_action": {"action": "clarify", "explanation": "Ask directly."},
        "advice": [{"priority": 1, "finding_id": "general", "finding_type": "general", "finding_severity": "neutral", "evidence_source": "local_pattern", "context_category": "work", "category": "clarity", "severity": "neutral", "title": "Clarify", "explanation": "Ask directly.", "example": ""}],
        "semantic_analysis": {},
        "evidence_findings": [],
        "personal_profile": {},
        "communication_story": {},
        "adaptive_tone": "calm",
        "communication_timeline_events": [],
        "memory_candidates": [],
        "limitations": ["Selected period only."],
    }
    result.update(overrides)
    return result
