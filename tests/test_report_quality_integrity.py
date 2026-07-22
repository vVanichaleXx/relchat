from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from relchat.bot.formatters import format_ai_result_overview, normalize_composed_text
from relchat.bot.services.advice_routing import route_advice
from relchat.bot.services.ai_analysis import communication_score_from_dimensions, local_fallback_analysis
from relchat.bot.services.participation import build_participation_interpretation
from relchat.bot.services.report_consistency import validate_report_consistency
from relchat.core.models import Message


BASE = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def msg(i: int, text: str, *, outgoing: bool = True, minutes: int | None = None) -> Message:
    return Message(
        source="telegram",
        source_message_id=i,
        conversation_id="quality-chat",
        sender_id="me" if outgoing else "other",
        sender_name="Me" if outgoing else "Other",
        timestamp=(BASE + timedelta(minutes=minutes if minutes is not None else i)).isoformat(),
        text=text,
        message_type="text",
        is_outgoing=outgoing,
    )


class ReportQualityIntegrityTests(unittest.TestCase):
    def test_no_contradictory_participation_claims_in_one_scope(self) -> None:
        messages = [msg(i + 1, "status update", outgoing=i < 60, minutes=i) for i in range(100)]
        result = local_fallback_analysis(
            messages=messages,
            events=[],
            period_label="30 days",
            chat_type="one_to_one",
            language="en",
            context_classification={"category": "friendship", "confidence": "high", "source": "user_confirmed"},
        )
        rendered = format_ai_result_overview({"chat_title": "Friend", "result": result}, language="en")
        participation = result["participation_interpretation"]
        self.assertEqual(participation["status"], "you_more")
        self.assertIn("you write more often", rendered.casefold())
        self.assertNotIn("activity is roughly balanced", rendered.casefold())
        self.assertNotIn("participation is balanced", rendered.casefold())

    def test_full_history_and_recent_participation_difference_is_scoped(self) -> None:
        messages = scoped_full_history_recent_fixture(total=8031, recent=70)
        result = local_fallback_analysis(
            messages=messages,
            events=[],
            period_label="Вся история",
            chat_type="one_to_one",
            language="ru",
            context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"},
        )
        rendered = format_ai_result_overview({"chat_title": "Семья", "result": result}, language="ru")
        self.assertTrue(result["participation_interpretation"]["has_scope_difference"])
        self.assertIn("По всей истории", rendered)
        self.assertIn("В недавнем окне", rendered)
        self.assertIn("Общий фон построен по 8031 сообщениям", rendered)
        self.assertIn("последним 70 сообщениям", rendered)

    def test_no_duplicated_prefixes_or_adjacent_duplicate_clauses(self) -> None:
        ru = normalize_composed_text("В этой переписке В этой переписке вы чаще возвращаете разговор. Паттерн паттерн повторяется.")
        en = normalize_composed_text("In this chat, In this chat, you return after pauses. Pattern pattern repeats.")
        self.assertNotIn("В этой переписке В этой переписке", ru)
        self.assertNotIn("Паттерн паттерн", ru)
        self.assertNotIn("In this chat, In this chat", en)
        self.assertNotIn("Pattern pattern", en)
        repeated = normalize_composed_text("Task discussion is regular. Task discussion is regular. Decisions remain unclear.")
        self.assertEqual(repeated.count("Task discussion is regular"), 1)

    def test_unsupported_manipulative_label_is_not_rendered(self) -> None:
        messages = []
        for index in range(4):
            messages.append(msg(index * 3 + 1, "No, I cannot do this.", outgoing=False, minutes=index * 20))
            messages.append(msg(index * 3 + 2, "If you cared, you would answer right now.", outgoing=True, minutes=index * 20 + 1))
            messages.append(msg(index * 3 + 3, "Please do it now.", outgoing=True, minutes=index * 20 + 2))
        result = local_fallback_analysis(
            messages=messages,
            events=[],
            period_label="30 days",
            chat_type="one_to_one",
            language="en",
            context_classification={"category": "friendship", "confidence": "high", "source": "user_confirmed"},
        )
        rendered = format_ai_result_overview({"chat_title": "Friend", "result": result}, language="en")
        self.assertIn("pressure", rendered.casefold())
        self.assertNotIn("manipulative", rendered.casefold())
        self.assertNotIn("toxic", rendered.casefold())
        self.assertNotIn("hidden intent", rendered.casefold())

    def test_indirect_local_sarcasm_is_phrased_as_uncertain(self) -> None:
        messages = [msg(1, "Ты можешь ответить на вопрос?", outgoing=True), msg(2, "ну конечно", outgoing=False)]
        messages.extend(msg(i + 3, "обычное сообщение", outgoing=i % 2 == 0, minutes=i + 3) for i in range(24))
        result = local_fallback_analysis(
            messages=messages,
            events=[],
            period_label="30 дней",
            chat_type="one_to_one",
            language="ru",
            context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"},
        )
        rendered = format_ai_result_overview({"chat_title": "Семья", "result": result}, language="ru")
        self.assertIn(result["semantic_analysis"]["sarcasm"]["status"], {"ambiguous", "insufficient_data"})
        self.assertIn("могут", rendered.casefold())
        self.assertNotIn("обесценивающий сарказм мешает", rendered.casefold())

    def test_advice_matches_leading_finding_and_changes_with_leader(self) -> None:
        sarcasm = canonical("sarcasm_1", "sarcasm", "attention", category="sarcasm", evidence_count=3)
        aggression = canonical("aggression_1", "aggression", "problem", category="aggression", evidence_count=4)
        first = route_advice([sarcasm], context_category="family", language="en")[0]
        second = route_advice([sarcasm, aggression], context_category="family", language="en")[0]
        self.assertEqual(first["finding_id"], "sarcasm_1")
        self.assertEqual(first["category"], "sarcasm")
        self.assertEqual(second["finding_id"], "aggression_1")
        self.assertEqual(second["category"], "aggression")

        repaired = validate_report_consistency(
            {
                "context": {"category": "family"},
                "canonical_findings": [sarcasm, aggression],
                "score_explanation": {},
                "advice": [{"priority": 1, "finding_id": "sarcasm_1", "finding_type": "sarcasm", "category": "sarcasm", "severity": "attention", "title": "Return", "explanation": "Return.", "example": ""}],
            },
            language="en",
        )
        self.assertEqual(repaired["leading_finding_id"], "aggression_1")
        self.assertEqual(repaired["advice_target_id"], "aggression_1")

    def test_score_is_null_when_independence_is_insufficient_and_single_risk_is_capped(self) -> None:
        low = communication_score_from_dimensions(
            {
                "reciprocity": dimension(8.0, 40),
                "reply_quality": dimension(6.5, 10),
                "hostility": dimension(9.0, 1, risk=True),
            },
            message_count=80,
        )
        self.assertIsNone(low["score"])

        supported = communication_score_from_dimensions(
            {
                "reciprocity": dimension(8.0, 80),
                "reply_quality": dimension(6.5, 40),
                "topic_continuation": dimension(6.5, 20),
                "hostility": dimension(9.0, 1, risk=True),
            },
            message_count=100,
        )
        self.assertIsNotNone(supported["score"])
        self.assertGreaterEqual(supported["score"], 4.0)

    def test_different_fixtures_have_different_opening_summaries(self) -> None:
        fixtures = [
            ("Friend", "friendship", balanced_friendship()),
            ("Romance", "romantic", one_sided_romance()),
            ("Work", "work", unclear_work()),
            ("Family", "family", supportive_family()),
        ]
        summaries = []
        for title, context, messages in fixtures:
            result = local_fallback_analysis(
                messages=messages,
                events=[],
                period_label="30 days",
                chat_type="one_to_one",
                language="en",
                context_classification={"category": context, "confidence": "high", "source": "user_confirmed"},
            )
            summaries.append(result["individualized_story"]["overall_picture"])
            rendered = format_ai_result_overview({"chat_title": title, "result": result}, language="en")
            self.assertNotIn("communication contains certain patterns", rendered.casefold())
        self.assertEqual(len(set(summaries)), len(summaries))

    def test_4494_and_8031_real_report_fixtures_are_concise_and_consistent(self) -> None:
        work = local_fallback_analysis(
            messages=large_regular_work_fixture(),
            events=[],
            period_label="Вся история",
            chat_type="one_to_one",
            language="ru",
            context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"},
        )
        family = local_fallback_analysis(
            messages=scoped_full_history_recent_fixture(total=8031, recent=70),
            events=[],
            period_label="Вся история",
            chat_type="one_to_one",
            language="ru",
            context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"},
        )
        for title, result in (("Работа", work), ("Семья", family)):
            rendered = format_ai_result_overview({"chat_title": title, "result": result}, language="ru")
            self.assertLessEqual(len([line for line in rendered.splitlines() if line.strip()]), 70)
            self.assertNotIn("В этой переписке В этой переписке", rendered)
            self.assertNotIn("манипулятив", rendered.casefold())
            self.assertNotIn("токсич", rendered.casefold())
            self.assertNotIn("кандидат", rendered.casefold())
            self.assertFalse("вы пишете чаще" in rendered.casefold() and "участие сбалансировано" in rendered.casefold() and "недавнем окне" not in rendered.casefold())


def dimension(score: float, evidence_count: int, *, risk: bool = False) -> dict[str, object]:
    return {"score": score, "confidence": "medium", "evidence_count": evidence_count, "explanation": "supported", "available": True, "risk": risk}


def canonical(finding_id: str, finding_type: str, severity: str, *, category: str, evidence_count: int) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "participant_scope": "interaction",
        "status": "available",
        "severity": severity,
        "semantic_source": "explicit_rule",
        "semantic_depth": "direct",
        "confidence": "medium",
        "evidence_count": evidence_count,
        "evidence": [{"evidence_id": f"ev_{finding_id}", "description": "explicit_insult_marker" if finding_type == "aggression" else "explicit_sarcasm_label", "source": "explicit_rule"}],
        "score_effect": -0.8 if severity == "problem" else -0.35,
        "advice_category": category,
        "summary_key": f"{finding_type}:{finding_id}",
        "title": finding_type,
        "interpretation": finding_type,
    }


def scoped_full_history_recent_fixture(*, total: int, recent: int) -> list[Message]:
    messages: list[Message] = []
    early = total - recent
    for index in range(early):
        month = 1 + (index % 6)
        day = 1 + ((index // 6) % 24)
        timestamp = datetime(2026, month, day, 9, index % 60, tzinfo=timezone.utc)
        messages.append(
            Message(
                source="telegram",
                source_message_id=index + 1,
                conversation_id="quality-chat",
                sender_id="me" if index % 2 == 0 else "other",
                sender_name="Me" if index % 2 == 0 else "Other",
                timestamp=timestamp.isoformat(),
                text="семейное сообщение",
                message_type="text",
                is_outgoing=index % 2 == 0,
            )
        )
    for index in range(recent):
        timestamp = datetime(2026, 7, 1 + (index // 10), 10, index % 60, tzinfo=timezone.utc)
        messages.append(
            Message(
                source="telegram",
                source_message_id=early + index + 1,
                conversation_id="quality-chat",
                sender_id="me",
                sender_name="Me",
                timestamp=timestamp.isoformat(),
                text="возвращаюсь к вопросу",
                message_type="text",
                is_outgoing=True,
            )
        )
    return messages


def large_regular_work_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(4494):
        outgoing = index % 2 == 0
        text = "рабочее обновление по задаче" if outgoing else "принято"
        if index % 211 == 0:
            text = "можешь подтвердить срок?"
        if index == 300:
            text = "ну конечно"
        messages.append(msg(index + 1, text, outgoing=outgoing, minutes=index * 90))
    return messages


def balanced_friendship() -> list[Message]:
    return [msg(i + 1, "How was your day?" if i % 4 == 0 else "That makes sense", outgoing=i % 2 == 0, minutes=i * 20) for i in range(60)]


def one_sided_romance() -> list[Message]:
    return [msg(i + 1, "I miss you. Do you want to meet just us?" if i % 3 != 2 else "maybe", outgoing=i % 3 != 2, minutes=i * 40) for i in range(60)]


def unclear_work() -> list[Message]:
    texts = ["task review", "what exactly should I fix?", "which owner?", "can you clarify deadline?", "ticket issue", "what is expected?"]
    return [msg(i + 1, texts[i % len(texts)], outgoing=i % 2 == 0, minutes=i * 25) for i in range(72)]


def supportive_family() -> list[Message]:
    return [msg(i + 1, "Спасибо, помогу завтра" if i % 2 == 0 else "нужна помощь дома", outgoing=i % 2 == 0, minutes=i * 30) for i in range(72)]


if __name__ == "__main__":
    unittest.main()
