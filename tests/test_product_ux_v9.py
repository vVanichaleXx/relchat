from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from relchat.bot.formatters import chunk_text, format_ai_result_overview, format_ai_result_section
from relchat.bot.handlers.reports import edit_or_reply_chunked
from relchat.bot.keyboards import analysis_result_keyboard
from relchat.bot.services.ai_analysis import (
    AIAnalysisError,
    build_ai_input_bundle,
    build_deterministic_dimensions,
    communication_score_from_dimensions,
    extract_response_text,
    local_fallback_analysis,
    validate_ai_result,
)
from relchat.config import Settings
from relchat.core.models import ConversationEvent, Message
from relchat.database.repositories import create_ai_analysis, latest_ai_analysis_for_report
from relchat.database.sqlite import connect, init_db


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
        "ai_max_messages": 6,
        "ai_max_chars": 900,
        "ai_timeout_seconds": 5,
    }
    base.update(overrides)
    return Settings(**base)


def message(message_id: int, sender: str, text: str, *, outgoing: bool = False, hour: int = 10) -> Message:
    return Message(
        source="telegram",
        source_message_id=message_id,
        conversation_id="telegram-chat-secret",
        sender_id=sender,
        sender_name="Alice" if outgoing else "Bob",
        timestamp=f"2026-07-15T{hour:02d}:{message_id % 60:02d}:00+00:00",
        text=text,
        message_type="text",
        is_outgoing=outgoing,
    )


def sample_messages(count: int = 24) -> list[Message]:
    rows = []
    for index in range(1, count + 1):
        outgoing = index % 2 == 1
        text = "Can we confirm Friday?" if index in {3, 19} else f"Visible message {index}"
        rows.append(message(index, "100" if outgoing else "200", text, outgoing=outgoing, hour=8 + (index // 4)))
    return rows


def event(message_id: int = 19, event_type: str = "follow_up_candidate") -> ConversationEvent:
    return ConversationEvent(
        source="telegram",
        conversation_id="telegram-chat-secret",
        event_type=event_type,
        timestamp="2026-07-15T14:00:00+00:00",
        source_message_id=message_id,
        sender_id="100",
        sender_name="Alice",
    )


def model_result(**overrides) -> dict:
    result = {
        "summary": "The visible conversation is active but uneven.",
        "conversation_state": "active_uneven",
        "confidence": "medium",
        "participant_analysis": {
            "you": {
                "summary": "YOU usually starts practical topics.",
                "observable_patterns": ["often initiates", "asks direct questions"],
                "strengths": ["keeps plans explicit"],
                "possible_improvements": ["send one question at a time"],
            },
            "other": {
                "summary": "OTHER replies regularly but restarts less often.",
                "observable_patterns": ["answers consistently", "rarely restarts after pauses"],
                "strengths": ["responds without hostile wording"],
                "possible_improvements": ["answer direct questions more clearly"],
            },
        },
        "positive_patterns": [
            {"title": "Regular replies", "explanation": "Replies are visible in the selected period.", "evidence_type": "metric"}
        ],
        "problem_patterns": [
            {"title": "Uneven initiative", "explanation": "YOU starts more visible sessions.", "severity": "medium", "evidence_type": "metric"}
        ],
        "weak_reply_patterns": [
            {"category": "ignored_question", "explanation": "A direct question was not clearly answered.", "severity": "medium", "anonymous_message_reference": "m3"},
            {"category": "abrupt_reply", "explanation": "A short reply ended a substantial topic.", "severity": "low", "anonymous_message_reference": "m4"},
            {"category": "dismissive", "explanation": "A reply reduced the clarity of a serious topic.", "severity": "low", "anonymous_message_reference": "m5"},
        ],
        "advice": [
            {"priority": 1, "title": "Ask one clear question", "explanation": "This makes the next reply easier.", "example": "Does Friday still work?"},
            {"priority": 2, "title": "Leave space after the question", "explanation": "Avoid adding pressure before the other person can answer.", "example": "Wait for a reply before adding another topic."},
            {"priority": 3, "title": "Clarify plans directly", "explanation": "Direct checks are clearer than repeated hints.", "example": "Should I book it or wait?"},
        ],
        "limitations": ["Used only the selected period."],
    }
    result.update(overrides)
    return result


def dimensions() -> dict:
    return build_deterministic_dimensions(sample_messages(), [event()], chat_type="one_to_one")


def validated(**overrides) -> dict:
    return validate_ai_result(
        model_result(**overrides),
        dimensions=dimensions(),
        message_count=24,
        coverage={"requested_period": "30 days", "available_messages": 24, "sent_messages": 6, "partial": True},
    )


class ProductUxV9AnalysisTest(unittest.TestCase):
    def test_structured_result_rejects_scores_invalid_enums_and_diagnosis_language(self) -> None:
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(model_result(overall_score=8.8), dimensions=dimensions(), message_count=24)
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(model_result(conversation_state="attachment_analysis"), dimensions=dimensions(), message_count=24)
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(
                model_result(positive_patterns=[{"title": "Bad", "explanation": "", "evidence_type": "telepathy"}]),
                dimensions=dimensions(),
                message_count=24,
            )
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(
                model_result(weak_reply_patterns=[{"category": "mind_reading", "explanation": "", "severity": "low", "anonymous_message_reference": "m1"}]),
                dimensions=dimensions(),
                message_count=24,
            )
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(model_result(summary="They definitely love you."), dimensions=dimensions(), message_count=24)
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(
                model_result(advice=[{"priority": 1, "title": "Make them chase", "explanation": "Use pressure.", "example": ""}]),
                dimensions=dimensions(),
                message_count=24,
            )

    def test_oversized_lists_and_text_are_limited(self) -> None:
        result = validated(
            positive_patterns=[{"title": f"Pattern {index}", "explanation": "x" * 1000, "evidence_type": "metric"} for index in range(20)],
            advice=[{"priority": index, "title": f"Advice {index}", "explanation": "x" * 1000, "example": "y" * 500} for index in range(1, 8)],
        )

        self.assertLessEqual(len(result["positive_patterns"]), 6)
        self.assertLessEqual(len(result["advice"]), 3)
        self.assertLessEqual(len(result["advice"][0]["explanation"]), 600)

    def test_score_formula_normalizes_weights_and_does_not_penalize_positive_sarcasm(self) -> None:
        dims = dimensions()
        dims.pop("planning_cooperation", None)
        dims["sarcasm_intensity"]["score"] = 0

        score = communication_score_from_dimensions(dims, message_count=24)

        self.assertIsNotNone(score["score"])
        self.assertGreater(score["score"], 0)
        self.assertLessEqual(score["score"], 10)

    def test_local_fallback_private_group_and_channel_wording(self) -> None:
        private = local_fallback_analysis(messages=sample_messages(), events=[event()], period_label="30 days", chat_type="one_to_one")
        group = local_fallback_analysis(messages=sample_messages(), events=[event()], period_label="30 days", chat_type="group")
        channel = local_fallback_analysis(messages=sample_messages(), events=[event()], period_label="30 days", chat_type="channel")

        self.assertIn("visible activity", private["summary"])
        self.assertIn("Group activity", group["summary"])
        self.assertIn("Channel activity", channel["summary"])

    def test_anonymized_payload_balances_participants_and_limits_input(self) -> None:
        bundle = build_ai_input_bundle(
            settings_for(ai_max_messages=6, ai_max_chars=900),
            chat={"chat_type": "one_to_one", "chat_id": "telegram-chat-secret", "title": "Alice"},
            messages=sample_messages(30),
            events=[event(19)],
            period_label="30 days",
        )
        blob = json.dumps(bundle.payload, ensure_ascii=False)
        senders = {row["sender"] for row in bundle.payload["messages"]}

        self.assertLessEqual(bundle.message_count_sent, 6)
        self.assertIn("YOU", senders)
        self.assertIn("OTHER", senders)
        self.assertNotIn("telegram-chat-secret", blob)
        self.assertNotIn("Alice", blob)
        self.assertNotIn("Bob", blob)
        self.assertTrue(bundle.coverage["partial"])

    def test_provider_refusal_is_safe(self) -> None:
        refusal = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="refusal", text="no")],
                )
            ],
            status="completed",
        )
        with self.assertRaises(AIAnalysisError) as error:
            extract_response_text(refusal)
        self.assertEqual(error.exception.code, "content_refused")

    def test_main_and_full_rendering_have_no_raw_source_text_and_are_localized(self) -> None:
        result = validated()
        analysis = {"chat_title": "Anna", "result": result, "coverage": result["coverage"]}
        overview = format_ai_result_overview(analysis, language="en")
        full = format_ai_result_section(analysis, "full", language="en")
        advice = format_ai_result_section(analysis, "advice", language="ru")

        self.assertIn("Communication analysis", overview)
        self.assertIn("How you communicate", overview)
        self.assertIn("What weakens it", overview)
        self.assertIn("A sample of 6 messages", overview)
        self.assertIn("Replies that weakened the conversation", full)
        self.assertIn("Советы", advice)
        self.assertNotIn("Can we confirm Friday?", overview)
        self.assertNotIn("Visible message", full)

    def test_result_keyboard_is_compact_and_navigation_safe(self) -> None:
        keyboard = analysis_result_keyboard("rep_123", language="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        callbacks = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]

        self.assertEqual(labels, ["📄 Full analysis", "💡 Why this conclusion", "💬 Chat", "🏠 Menu"])
        self.assertLessEqual(len(labels), 4)
        self.assertTrue(all(len(value) < 64 for value in callbacks))
        self.assertNotIn("telegram-chat", "".join(callbacks))

    def test_per_user_report_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            result = validated()
            with connect(db_path) as conn:
                create_ai_analysis(
                    conn,
                    bot_user_id=100,
                    job_id="job_1",
                    report_id="rep_shared",
                    source="telegram",
                    chat_id="chat-1",
                    chat_title="Anna",
                    model_name="gpt-test",
                    status="completed",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    result=result,
                    dimensions=result["dimensions"],
                    overall_score=result["overall_score"],
                    confidence=result["score_confidence"],
                )
                create_ai_analysis(
                    conn,
                    bot_user_id=200,
                    job_id="job_2",
                    report_id="rep_shared",
                    source="telegram",
                    chat_id="chat-1",
                    chat_title="Anna",
                    model_name="gpt-test",
                    status="completed",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    result=result,
                    dimensions=result["dimensions"],
                    overall_score=result["overall_score"],
                    confidence=result["score_confidence"],
                )

                self.assertEqual(latest_ai_analysis_for_report(conn, 100, "rep_shared")["bot_user_id"], 100)
                self.assertEqual(latest_ai_analysis_for_report(conn, 200, "rep_shared")["bot_user_id"], 200)


class ProductUxV9ChunkingTest(unittest.IsolatedAsyncioTestCase):
    async def test_full_analysis_chunking_places_keyboard_only_on_final_chunk(self) -> None:
        keyboard = object()
        text = "\n".join(["Line " + str(index) + " " + ("x" * 120) for index in range(140)])
        query = FakeQuery()
        update = SimpleNamespace(callback_query=query, effective_message=query.message)

        await edit_or_reply_chunked(update, text, reply_markup=keyboard)

        self.assertGreater(len(chunk_text(text)), 1)
        self.assertIsNone(query.edited_markup)
        self.assertTrue(query.message.replies)
        self.assertIs(query.message.replies[-1][1], keyboard)
        self.assertTrue(all(markup is None for _, markup in query.message.replies[:-1]))


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, object | None]] = []

    async def reply_text(self, text: str, reply_markup=None) -> None:
        self.replies.append((text, reply_markup))


class FakeQuery:
    def __init__(self) -> None:
        self.data = "rc:rep:full:rep_1"
        self.message = FakeMessage()
        self.edited_text = ""
        self.edited_markup = None

    async def edit_message_text(self, text: str, reply_markup=None) -> None:
        self.edited_text = text
        self.edited_markup = reply_markup


if __name__ == "__main__":
    unittest.main()
