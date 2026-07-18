from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from relchat.bot.formatters import format_ai_result_overview, format_ai_result_section
from relchat.bot.keyboards import ai_detail_keyboard, ai_result_keyboard, context_correction_keyboard
from relchat.bot.services.ai_analysis import (
    AIAnalysisError,
    build_ai_input_bundle,
    build_deterministic_dimensions,
    communication_score_from_dimensions,
    local_fallback_analysis,
    validate_ai_result,
)
from relchat.bot.services.context import classify_context
from relchat.config import Settings
from relchat.core.models import ConversationRef, Message
from relchat.database.repositories import (
    get_chat_context_classification,
    save_user_chat,
    set_chat_context_classification,
)
from relchat.database.sqlite import connect, init_db
from relchat.events.extractor import extract_events


def settings_for(db_path: Path | None = None, **overrides) -> Settings:
    base = {
        "api_id": 1,
        "api_hash": "hash",
        "telegram_bot_token": "123456:secret-bot-token",
        "allowed_user_ids": frozenset({100, 200}),
        "data_dir": Path("data") if db_path is None else db_path.parent,
        "db_path": Path("data/relchat.sqlite3") if db_path is None else db_path,
        "session_path": Path("data/telegram.session") if db_path is None else db_path.parent / "telegram.session",
        "ai_enabled": True,
        "openai_api_key": "sk-test-secret",
        "ai_model": "gpt-test",
        "ai_max_messages": 8,
        "ai_max_chars": 1200,
    }
    base.update(overrides)
    return Settings(**base)


def msg(message_id: int, text: str, *, outgoing: bool, chat_id: str = "chat-1") -> Message:
    return Message(
        source="telegram",
        source_message_id=message_id,
        conversation_id=chat_id,
        sender_id="100" if outgoing else "200",
        sender_name="Alice" if outgoing else "Bob",
        timestamp=f"2026-07-15T10:{message_id % 60:02d}:00+00:00",
        text=text,
        message_type="text",
        is_outgoing=outgoing,
    )


def equal_volume_regression_messages() -> list[Message]:
    rows: list[Message] = []
    for index in range(1, 1658):
        rows.append(msg(index, f"routine message {index}", outgoing=index <= 817))
    return rows


def ai_result(**overrides) -> dict:
    result = {
        "summary": "The work chat is active, but the task is not clearly resolved.",
        "context": {
            "category": "work",
            "confidence": "medium",
            "evidence_types": ["title", "message_topic_signal"],
            "source": "ai_interpreted",
            "explanation": "Work terms and task language are visible.",
        },
        "verdict": {"level": "mixed", "headline": "The communication was operationally mixed.", "explanation": "There is activity, but not enough clarity."},
        "conversation_state": "planning_focused",
        "confidence": "medium",
        "direct_findings": [
            {"finding": "The task was discussed repeatedly without a concrete next owner.", "severity": "medium", "confidence": "medium", "evidence_type": "reply_pattern"}
        ],
        "participant_analysis": {
            "you": {"summary": "YOU asked for clarity.", "observable_patterns": ["asks concrete work questions"], "strengths": [], "possible_improvements": []},
            "other": {"summary": "OTHER answered but stayed general.", "observable_patterns": ["replies without closing the task"], "strengths": [], "possible_improvements": []},
        },
        "positive_patterns": [{"title": "Regular replies", "explanation": "Replies are visible.", "evidence_type": "metric"}],
        "problem_patterns": [{"title": "Unclear ownership", "explanation": "No clear owner is assigned.", "severity": "medium", "evidence_type": "message_pattern"}],
        "weak_reply_patterns": [],
        "uncertainties": ["The reason cannot be determined from messages alone."],
        "recommended_action": {"action": "clarify", "explanation": "State the owner, result, and deadline in one message."},
        "advice": [{"priority": 1, "title": "Clarify ownership", "explanation": "Make the next step explicit.", "example": "Who owns this by Friday?"}],
        "limitations": ["Used only the selected period."],
    }
    result.update(overrides)
    return result


def strong_dimensions() -> dict:
    return {
        "reciprocity": {"score": 9.0, "confidence": "high", "evidence_count": 80, "explanation": "balanced", "available": True},
        "initiative_balance": {"score": 8.8, "confidence": "high", "evidence_count": 12, "explanation": "mutual", "available": True},
        "reply_quality": {"score": 8.6, "confidence": "high", "evidence_count": 40, "explanation": "answers", "available": True},
        "topic_continuation": {"score": 8.4, "confidence": "high", "evidence_count": 20, "explanation": "continues", "available": True},
        "respectfulness": {"score": 9.0, "confidence": "high", "evidence_count": 40, "explanation": "respectful", "available": True},
        "question_engagement": {"score": 8.5, "confidence": "high", "evidence_count": 20, "explanation": "answers", "available": True},
        "planning_cooperation": {"score": 8.0, "confidence": "medium", "evidence_count": 8, "explanation": "plans", "available": True},
        "pressure_risk": {"score": 0.2, "confidence": "medium", "evidence_count": 2, "explanation": "low", "available": True, "risk": True},
        "hostility": {"score": 0.0, "confidence": "high", "evidence_count": 20, "explanation": "low", "available": True, "risk": True},
        "dismissiveness": {"score": 0.0, "confidence": "high", "evidence_count": 20, "explanation": "low", "available": True, "risk": True},
        "unanswered_question_rate": {"score": 0.0, "confidence": "high", "evidence_count": 20, "explanation": "low", "available": True, "risk": True},
        "sarcasm_intensity": {"score": 0.0, "confidence": "high", "evidence_count": 20, "explanation": "low", "available": True, "risk": True},
    }


class ContextClassificationV11Test(unittest.TestCase):
    def test_supported_contexts_low_confidence_and_no_gender_inference(self) -> None:
        cases = [
            ("romantic", {"chat_type": "one_to_one", "title": "Friday date"}, [msg(1, "I miss you and loved the date", outgoing=True)]),
            ("friendship", {"chat_type": "one_to_one", "title": "Friends weekend"}, [msg(1, "Want to hang out with friends?", outgoing=True)]),
            ("family", {"chat_type": "one_to_one", "title": "Mom"}, [msg(1, "Family dinner with dad?", outgoing=True)]),
            ("work", {"chat_type": "one_to_one", "title": "Project deadline"}, [msg(1, "Can you own this task before the meeting?", outgoing=True)]),
            ("customer_or_service", {"chat_type": "one_to_one", "title": "Support order"}, [msg(1, "The delivery order needs a refund", outgoing=True)]),
            ("group_social", {"chat_type": "group", "title": "Team chat"}, []),
            ("channel_or_broadcast", {"chat_type": "channel", "title": "Updates"}, []),
            ("mixed", {"chat_type": "one_to_one", "title": "Project family"}, [msg(1, "deadline mom", outgoing=True)]),
        ]
        for expected, chat, messages in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_context(chat=chat, messages=messages).category, expected)

        unknown = classify_context(chat={"chat_type": "one_to_one", "title": "Ivan and Anna"}, messages=[msg(1, "hello", outgoing=True)])
        russian_name = classify_context(chat={"chat_type": "one_to_one", "title": "Мария"}, messages=[msg(1, "привет", outgoing=True)])
        self.assertEqual(unknown.category, "unknown")
        self.assertEqual(unknown.confidence, "low")
        self.assertEqual(russian_name.category, "unknown")

    def test_user_confirmed_context_persists_and_is_user_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            chat = ConversationRef("telegram", "chat-ctx", "one_to_one", "Project")
            with connect(db_path) as conn:
                save_user_chat(conn, 100, chat, saved=True)
                save_user_chat(conn, 200, chat, saved=True)
                set_chat_context_classification(
                    conn,
                    100,
                    "telegram",
                    "chat-ctx",
                    category="romantic",
                    classification_source="user_confirmed",
                    confidence="high",
                    evidence_types=["user_confirmed"],
                )
                own = get_chat_context_classification(conn, 100, "telegram", "chat-ctx")
                other = get_chat_context_classification(conn, 200, "telegram", "chat-ctx")

        classified = classify_context(chat={"chat_type": "one_to_one", "title": "Project deadline"}, messages=[msg(1, "work deadline", outgoing=True)], saved=own)
        self.assertEqual(classified.category, "romantic")
        self.assertTrue(classified.user_confirmed)
        self.assertIsNone(other)


class ScoringAndRegressionV11Test(unittest.TestCase):
    def test_equal_message_counts_alone_cannot_produce_high_score_or_measured_risk_zeros(self) -> None:
        messages = equal_volume_regression_messages()
        dimensions = build_deterministic_dimensions(messages, [], chat_type="one_to_one")
        score = communication_score_from_dimensions(dimensions, message_count=len(messages))
        result = local_fallback_analysis(
            messages=messages,
            events=[],
            period_label="30 days",
            chat_type="one_to_one",
            language="ru",
            context_classification={"category": "unknown", "confidence": "low", "source": "automatic", "evidence_types": ["insufficient_signals"]},
        )
        overview = format_ai_result_overview({"chat_title": "Мария", "result": result}, language="ru")
        full = format_ai_result_section({"result": result}, "full", language="ru")

        self.assertLessEqual(float(score["score"]), 6.5)
        self.assertEqual(score["cap_reason"], "shallow_local_metrics")
        self.assertNotEqual(result["verdict"]["level"], "strong")
        self.assertIsNone(dimensions["sarcasm_intensity"]["score"])
        self.assertIsNone(dimensions["hostility"]["score"])
        self.assertFalse(dimensions["sarcasm_intensity"]["available"])
        self.assertIn("Локальный анализ видит структуру переписки", full)
        self.assertIn("Равный объем сообщений не доказывает", overview)
        self.assertNotIn("8.4 / 10", overview)
        self.assertNotIn("Выраженность сарказма: 0.0", full)
        self.assertNotIn("Враждебность: 0.0", full)
        for fragment in ["not available", "Communication score", "visible activity", "No AI text interpretation", "недоступно"]:
            self.assertNotIn(fragment, overview + "\n" + full)

    def test_score_caps_and_high_quality_evidence(self) -> None:
        shallow = {"reciprocity": {"score": 10.0, "confidence": "high", "evidence_count": 100, "explanation": "balanced", "available": True}}
        self.assertIsNone(communication_score_from_dimensions(shallow, message_count=100)["score"])

        deterministic = {
            "reciprocity": {"score": 10.0, "confidence": "high", "evidence_count": 100, "explanation": "balanced", "available": True},
            "reply_quality": {"score": 9.0, "confidence": "high", "evidence_count": 30, "explanation": "answers", "available": True},
            "question_engagement": {"score": 9.0, "confidence": "high", "evidence_count": 30, "explanation": "questions", "available": True},
            "topic_continuation": {"score": 9.0, "confidence": "high", "evidence_count": 20, "explanation": "topics", "available": True},
            "planning_cooperation": {"score": 9.0, "confidence": "high", "evidence_count": 12, "explanation": "plans", "available": True},
        }
        capped = communication_score_from_dimensions(deterministic, message_count=100)
        self.assertLessEqual(capped["score"], 7.2)
        self.assertEqual(capped["cap_reason"], "deterministic_without_text_interpretation")

        strong = communication_score_from_dimensions(strong_dimensions(), message_count=100, coverage={"sent_messages": 100, "partial": False}, context_confidence="high", ai_interpreted=True)
        self.assertGreater(strong["score"], 8.0)


class ContextSpecificRenderingV11Test(unittest.TestCase):
    def test_work_and_romantic_contexts_use_different_language_without_manipulation(self) -> None:
        work = local_fallback_analysis(
            messages=[msg(i, "Can we confirm the task owner and deadline?", outgoing=i % 2 == 1) for i in range(1, 24)],
            events=[],
            period_label="7 days",
            chat_type="one_to_one",
            language="ru",
            context_classification={"category": "work", "confidence": "high", "source": "user_confirmed", "evidence_types": ["user_confirmed"]},
        )
        romantic = local_fallback_analysis(
            messages=[msg(i, "Как тебе четверг вечером?", outgoing=i % 2 == 1) for i in range(1, 24)],
            events=[],
            period_label="7 days",
            chat_type="one_to_one",
            language="ru",
            context_classification={"category": "romantic", "confidence": "high", "source": "user_confirmed", "evidence_types": ["user_confirmed"]},
        )
        work_text = format_ai_result_overview({"chat_title": "Проект", "result": work}, language="ru")
        romantic_text = format_ai_result_overview({"chat_title": "Анна", "result": romantic}, language="ru")

        self.assertIn("Рабочее общение", work_text)
        self.assertIn("Оценка эффективности", work_text)
        self.assertNotIn("романтический интерес", work_text.casefold())
        self.assertIn("Романтическое общение", romantic_text)
        self.assertNotIn("застав", romantic_text.casefold())
        self.assertNotIn("ревност", romantic_text.casefold())
        self.assertNotIn("игнор", romantic_text.casefold())

    def test_group_channel_avoid_two_person_relationship_score(self) -> None:
        group = local_fallback_analysis(messages=[msg(i, "team update", outgoing=i % 3 == 0) for i in range(1, 35)], events=[], period_label="7 days", chat_type="group", language="en")
        channel = local_fallback_analysis(messages=[msg(i, "post update", outgoing=True) for i in range(1, 35)], events=[], period_label="7 days", chat_type="channel", language="en")
        group_text = format_ai_result_overview({"result": group}, language="en")
        channel_text = format_ai_result_overview({"result": channel}, language="en")
        self.assertIn("Group activity", group_text)
        self.assertIn("Activity score", group_text)
        self.assertIn("Channel or broadcast activity", channel_text)
        self.assertNotIn("the other person communicates", group_text.casefold())

    def test_rendering_single_language_empty_sections_and_buttons(self) -> None:
        result = validate_ai_result(
            ai_result(),
            dimensions=strong_dimensions(),
            message_count=80,
            coverage={"requested_period": "7 days", "available_messages": 80, "sent_messages": 80, "partial": False},
            context_classification={"category": "work", "confidence": "high", "source": "user_confirmed", "evidence_types": ["user_confirmed"]},
        )
        ru_text = format_ai_result_overview({"chat_title": "Работа", "result": result}, language="ru")
        en_text = format_ai_result_overview({"chat_title": "Work", "result": result}, language="en")
        primary_labels = [button.text for row in ai_result_keyboard(language="ru").inline_keyboard for button in row]
        detail_callbacks = [button.callback_data or "" for row in ai_detail_keyboard(language="ru").inline_keyboard for button in row]
        correction_callbacks = [button.callback_data or "" for row in context_correction_keyboard(language="ru").inline_keyboard for button in row]

        self.assertLessEqual(len(primary_labels), 3)
        self.assertIn("rc:home:context", detail_callbacks)
        self.assertTrue(all("chat-1" not in value for value in correction_callbacks))
        self.assertNotIn("not available", ru_text.casefold())
        self.assertNotIn("недоступно", ru_text.casefold())
        self.assertNotIn("Оценка", en_text)
        self.assertNotIn("Краткий", en_text)


class AIV11BehaviorTest(unittest.TestCase):
    def test_ai_payload_includes_context_language_and_no_identity_fields(self) -> None:
        bundle = build_ai_input_bundle(
            settings_for(ai_max_messages=4),
            chat={"chat_type": "one_to_one", "chat_id": "raw-chat-id", "title": "Project Anna"},
            messages=[msg(i, "Can you confirm the project deadline?", outgoing=i % 2 == 1) for i in range(1, 20)],
            events=[],
            period_label="7 days",
            language="ru",
            context_classification={"category": "work", "confidence": "high", "source": "user_confirmed", "evidence_types": ["user_confirmed"]},
        )
        payload = bundle.payload
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["context_classification"]["category"], "work")
        self.assertEqual(payload["output_language"], "Russian")
        self.assertIn("context_framework", payload)
        self.assertNotIn("raw-chat-id", blob)
        self.assertNotIn("Alice", blob)
        self.assertNotIn("Bob", blob)

    def test_validation_blocks_diagnosis_hidden_feelings_and_pickup_tactics(self) -> None:
        for unsafe in [
            {"summary": "They definitely do not care."},
            {"summary": "This person is a narcissist."},
            {"advice": [{"priority": 1, "title": "Make them chase", "explanation": "Use jealousy tactics.", "example": ""}]},
            {"advice": [{"priority": 1, "title": "Push-pull", "explanation": "Pretend to be unavailable.", "example": ""}]},
        ]:
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(AIAnalysisError):
                    validate_ai_result(ai_result(**unsafe), dimensions=strong_dimensions(), message_count=80)


if __name__ == "__main__":
    unittest.main()
