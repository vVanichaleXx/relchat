from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relchat.bot.formatters import (
    format_ai_result_overview,
    format_ai_result_section,
    format_ai_unavailable,
)
from relchat.bot.handlers.analysis import choose_analysis_mode
from relchat.bot.keyboards import ai_result_keyboard, main_keyboard
from relchat.bot.services.ai_analysis import (
    AIAnalysisError,
    build_ai_input_bundle,
    build_deterministic_dimensions,
    communication_score_from_dimensions,
    derive_overall_score,
    local_fallback_analysis,
    run_ai_communication_analysis,
    validate_ai_result,
)
from relchat.bot.services.ux_audit import outgoing_payload
from relchat.config import Settings
from relchat.core.models import ConversationEvent, Message
from relchat.database.repositories import (
    accept_ai_consent,
    create_ai_analysis,
    get_ai_analysis,
    has_active_ai_consent,
    latest_ai_analysis_for_chat,
    revoke_ai_consent,
)
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
        "ai_max_messages": 4,
        "ai_max_chars": 1000,
        "ai_timeout_seconds": 5,
    }
    base.update(overrides)
    return Settings(**base)


def message(message_id: int, sender: str, text: str, *, outgoing: bool = False) -> Message:
    return Message(
        source="telegram",
        source_message_id=message_id,
        conversation_id="telegram-chat-12345",
        sender_id=sender,
        sender_name="Alice" if sender == "101" else "Bob",
        timestamp=f"2026-07-15T10:{message_id:02d}:00+00:00",
        text=text,
        message_type="text",
        is_outgoing=outgoing,
    )


def messages() -> list[Message]:
    return [
        message(1, "100", "Hi, can we confirm Friday? +1 415 555 0101", outgoing=True),
        message(2, "101", "Maybe @alice", outgoing=False),
        message(3, "100", "The bot token is 123456:abcdefghijklmnopqrstuvwxyz", outgoing=True),
        message(4, "101", "Let us keep it simple.", outgoing=False),
        message(5, "100", "Recent message should be kept.", outgoing=True),
    ]


def event() -> ConversationEvent:
    return ConversationEvent(
        source="telegram",
        conversation_id="telegram-chat-12345",
        event_type="follow_up_candidate",
        timestamp="2026-07-15T10:05:00+00:00",
        source_message_id=5,
        sender_id="100",
        sender_name="Alice",
    )


def ai_result(**overrides) -> dict:
    result = {
        "summary": "The conversation is active but uneven.",
        "conversation_state": "active_uneven",
        "confidence": "medium",
        "participant_analysis": {
            "you": {
                "summary": "YOU often asks direct questions and keeps plans clear.",
                "observable_patterns": ["often asks direct questions"],
                "strengths": ["keeps plans clear"],
                "possible_improvements": ["sometimes sends several messages in a row"],
            },
            "other": {
                "summary": "OTHER answers briefly and sometimes skips direct questions.",
                "observable_patterns": ["answers briefly"],
                "strengths": ["responds without hostility"],
                "possible_improvements": ["sometimes skips direct questions"],
            },
        },
        "positive_patterns": [
            {"title": "Shared planning", "explanation": "Both sides continue some plans.", "evidence_type": "metric"},
            {"title": "Regular replies", "explanation": "Replies are visible in the selected period.", "evidence_type": "metric"},
        ],
        "problem_patterns": [
            {"title": "Uneven initiative", "explanation": "One side starts more sessions.", "severity": "medium", "evidence_type": "metric"}
        ],
        "weak_reply_patterns": [
            {
                "category": "ignored_question",
                "explanation": "A direct question did not receive a clear answer.",
                "severity": "medium",
                "anonymous_message_reference": "m2",
            }
        ],
        "advice": [
            {
                "priority": 1,
                "title": "Ask one clear question",
                "explanation": "This makes the next reply easier.",
                "example": "Can you confirm Friday?",
            }
        ],
        "limitations": ["Used only the selected period."],
    }
    result.update(overrides)
    return result


def deterministic_dimensions() -> dict:
    return {
        "reciprocity": {"score": 6.0, "confidence": "medium", "evidence_count": 30, "explanation": "Both participants reply, but not evenly.", "available": True},
        "initiative_balance": {"score": 4.0, "confidence": "medium", "evidence_count": 6, "explanation": "One side starts more sessions.", "available": True},
        "reply_quality": {"score": 6.0, "confidence": "medium", "evidence_count": 8, "explanation": "Replies are present but sometimes brief.", "available": True},
        "respectfulness": {"score": 8.0, "confidence": "medium", "evidence_count": 30, "explanation": "No strong hostile wording in the sample.", "available": True},
        "topic_continuation": {"score": 5.0, "confidence": "medium", "evidence_count": 4, "explanation": "Some topics continue.", "available": True},
        "question_engagement": {"score": 6.0, "confidence": "low", "evidence_count": 2, "explanation": "Some questions continue.", "available": True},
        "planning_cooperation": {"score": 5.0, "confidence": "low", "evidence_count": 2, "explanation": "Some plans are visible.", "available": True},
        "pressure_risk": {"score": 2.0, "confidence": "low", "evidence_count": 1, "explanation": "No strong pressure pattern.", "available": True, "risk": True},
        "sarcasm_intensity": {"score": 1.0, "confidence": "low", "evidence_count": 1, "explanation": "Little harmful sarcasm.", "available": True, "risk": True},
    }


def validated_result(**overrides) -> dict:
    return validate_ai_result(
        ai_result(**overrides),
        dimensions=deterministic_dimensions(),
        message_count=42,
        coverage={"requested_period": "30 days", "available_messages": 42, "sent_messages": 4, "partial": True},
    )


class FakeResponses:
    def __init__(self, output: dict | str | None = None, *, error: Exception | None = None, delay: float = 0) -> None:
        self.output = output if output is not None else ai_result()
        self.error = error
        self.delay = delay
        self.payloads: list[dict] = []

    def create(self, **kwargs):
        self.payloads.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        output_text = self.output if isinstance(self.output, str) else json.dumps(self.output)
        return SimpleNamespace(output_text=output_text, status="completed", usage={"input_tokens": 100, "output_tokens": 80})


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def fake_context(settings: Settings):
    return SimpleNamespace(application=SimpleNamespace(bot_data={"settings": settings}), user_data={})


def fake_update(callback_data: str):
    query = FakeQuery(callback_data)
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=100),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=SimpleNamespace(text=""),
    )


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = SimpleNamespace(chat_id=1, message_id=2)
        self.edited_text = ""
        self.edited_markup = None

    async def edit_message_text(self, text: str, reply_markup=None) -> None:
        self.edited_text = text
        self.edited_markup = reply_markup


class ProductUxV7AiTest(unittest.IsolatedAsyncioTestCase):
    def test_simplified_three_button_main_menu(self) -> None:
        labels = [button.text for row in main_keyboard("en").inline_keyboard for button in row]

        self.assertEqual(labels, ["Analyze a chat", "My chats", "Settings"])
        self.assertNotIn("Reports", labels)
        self.assertNotIn("Help", labels)

    def test_ai_disabled_and_missing_key_errors_are_safe(self) -> None:
        self.assertIn("disabled", format_ai_unavailable("ai_disabled", language="en"))
        self.assertIn("API key", format_ai_unavailable("missing_api_key", language="en"))
        self.assertIn("отключен", format_ai_unavailable("ai_disabled", language="ru"))

        with self.assertRaises(AIAnalysisError) as disabled:
            asyncio.run(
                run_ai_communication_analysis(
                    settings_for(ai_enabled=False),
                    chat={"chat_type": "one_to_one"},
                    messages=messages(),
                    events=[],
                    period_label="30 days",
                    client_factory=lambda _settings: FakeClient(FakeResponses()),
                )
            )
        self.assertEqual(disabled.exception.code, "ai_disabled")

    async def test_ai_request_uses_anonymized_minimized_payload(self) -> None:
        responses = FakeResponses()
        outcome = await run_ai_communication_analysis(
            settings_for(ai_max_messages=3, ai_max_chars=600),
            chat={"chat_type": "one_to_one", "chat_id": "telegram-chat-12345", "title": "Alice"},
            messages=messages(),
            events=[event()],
            period_label="30 days",
            client_factory=lambda _settings: FakeClient(responses),
        )

        payload = json.loads(responses.payloads[0]["input"][1]["content"])
        payload_blob = json.dumps(payload, ensure_ascii=False)
        self.assertLessEqual(outcome.message_count_sent, 3)
        self.assertNotIn("telegram-chat-12345", payload_blob)
        self.assertNotIn("101", payload_blob)
        self.assertNotIn("Alice", payload_blob)
        self.assertNotIn("123456:abcdefghijklmnopqrstuvwxyz", payload_blob)
        self.assertNotIn("+1 415 555 0101", payload_blob)
        self.assertIn("YOU", payload_blob)
        self.assertIn("OTHER", payload_blob)
        self.assertIn("Recent message should be kept.", payload_blob)
        self.assertIn("local_dimensions", payload)
        self.assertIsNone(outcome.result.get("overall_score"))
        self.assertTrue(outcome.result["score_state"]["insufficient_data"])

    async def test_ai_timeout_rate_limit_and_malformed_output_are_safe(self) -> None:
        with self.assertRaises(AIAnalysisError) as timeout:
            await run_ai_communication_analysis(
                settings_for(ai_timeout_seconds=0.001),
                chat={"chat_type": "one_to_one"},
                messages=messages(),
                events=[],
                period_label="30 days",
                client_factory=lambda _settings: FakeClient(FakeResponses(delay=0.05)),
            )
        self.assertEqual(timeout.exception.code, "timeout")

        with self.assertRaises(AIAnalysisError) as rate:
            await run_ai_communication_analysis(
                settings_for(),
                chat={"chat_type": "one_to_one"},
                messages=messages(),
                events=[],
                period_label="30 days",
                client_factory=lambda _settings: FakeClient(FakeResponses(error=RuntimeError("rate limit"))),
            )
        self.assertEqual(rate.exception.code, "rate_limited")

        with self.assertRaises(AIAnalysisError):
            validate_ai_result("{not json")

    def test_strict_schema_score_formula_and_forbidden_claims(self) -> None:
        validated = validated_result()

        self.assertEqual(validated["overall_score"], derive_overall_score(validated["dimensions"]))
        self.assertGreaterEqual(validated["overall_score"], 0)
        self.assertLessEqual(validated["overall_score"], 10)

        with self.assertRaises(AIAnalysisError):
            validate_ai_result(ai_result(overall_score=10), dimensions=deterministic_dimensions(), message_count=42)
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(ai_result(conversation_state="secret_feelings"), dimensions=deterministic_dimensions(), message_count=42)
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(ai_result(summary="They like you and lost interest."), dimensions=deterministic_dimensions(), message_count=42)

    def test_score_boundaries_missing_dimensions_and_insufficient_data(self) -> None:
        low_sample = communication_score_from_dimensions(deterministic_dimensions(), message_count=4)
        self.assertIsNone(low_sample["score"])
        self.assertTrue(low_sample["insufficient_data"])

        partial = {"reciprocity": deterministic_dimensions()["reciprocity"]}
        self.assertIsNone(communication_score_from_dimensions(partial, message_count=30)["score"])

        extreme = deterministic_dimensions()
        extreme["reciprocity"]["score"] = 99
        extreme["pressure_risk"]["score"] = 99
        score = communication_score_from_dimensions(extreme, message_count=100)["score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 10)

    def test_ai_rendering_has_no_raw_text_and_is_localized(self) -> None:
        analysis = {"chat_title": "Anna", "result": validated_result(summary="Call +1 415 555 0101 and @alice.")}
        overview = format_ai_result_overview(analysis, language="en")
        weak = format_ai_result_section(analysis, "weak", language="en")
        russian = format_ai_result_overview(analysis, language="ru")

        self.assertIn("Communication score", overview)
        self.assertIn("Advice", format_ai_result_section(analysis, "advice", language="en"))
        self.assertIn("How you communicate", overview)
        self.assertIn("How the other person communicates", overview)
        self.assertIn("Replies that weakened the conversation", weak)
        self.assertIn("Raw message text is hidden", weak)
        self.assertNotIn("Can you confirm Friday?", overview)
        self.assertNotIn("+1 415 555 0101", overview)
        self.assertNotIn("@alice", overview)
        self.assertIn("Анализ общения", russian)
        self.assertIn("Оценка общения", russian)

        audit_payload = outgoing_payload(overview, action="edit")
        self.assertEqual(audit_payload["text_preview"], "[omitted private analysis]")
        self.assertNotIn("The conversation is active", json.dumps(audit_payload))

    def test_ai_result_callbacks_are_private_and_short(self) -> None:
        keyboard = ai_result_keyboard(language="en")
        callbacks = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertEqual(labels, ["Full analysis", "Advice", "Chat Home"])
        self.assertTrue(all(len(value) < 64 for value in callbacks))
        self.assertNotIn("Anna", "".join(callbacks))
        self.assertNotIn("telegram-chat", "".join(callbacks))

    def test_consent_and_per_user_persistence_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                self.assertFalse(has_active_ai_consent(conn, 100))
                accept_ai_consent(conn, 100)
                self.assertTrue(has_active_ai_consent(conn, 100))
                revoke_ai_consent(conn, 100)
                self.assertFalse(has_active_ai_consent(conn, 100))

                result = validated_result()
                own = create_ai_analysis(
                    conn,
                    bot_user_id=100,
                    job_id="job_1",
                    report_id="rep_1",
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
                    report_id="rep_2",
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

                self.assertIsNotNone(get_ai_analysis(conn, own["analysis_id"], bot_user_id=100))
                self.assertIsNone(get_ai_analysis(conn, own["analysis_id"], bot_user_id=200))
                self.assertEqual(latest_ai_analysis_for_chat(conn, 100, source="telegram", chat_id="chat-1")["bot_user_id"], 100)

    async def test_consent_required_before_ai_job_and_revoked_consent_asks_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            context = fake_context(settings_for(db_path))
            context.user_data["analysis_flow"] = {
                "source": "telegram",
                "chat_id": "chat-1",
                "chat_title": "Anna",
                "period_id": "30d",
                "period_label": "30 days",
                "modules": ["balance"],
            }
            update = fake_update("rc:analysis:mode:ai")

            with patch("relchat.bot.handlers.analysis.find_spec", return_value=object()):
                await choose_analysis_mode(update, context, "ai")

            self.assertIn("AI-enhanced analysis sends", update.callback_query.edited_text)
            self.assertNotEqual(context.user_data["analysis_flow"].get("analysis_mode"), "ai")

            with connect(db_path) as conn:
                accept_ai_consent(conn, 100)
                revoke_ai_consent(conn, 100)
            update = fake_update("rc:analysis:mode:ai")
            with patch("relchat.bot.handlers.analysis.find_spec", return_value=object()):
                await choose_analysis_mode(update, context, "ai")

            self.assertIn("AI-enhanced analysis sends", update.callback_query.edited_text)


class ProductUxV7BundleTest(unittest.TestCase):
    def test_group_and_channel_payload_wording(self) -> None:
        group = build_ai_input_bundle(settings_for(), chat={"chat_type": "group"}, messages=messages(), events=[], period_label="7 days")
        channel = build_ai_input_bundle(settings_for(), chat={"chat_type": "channel"}, messages=messages(), events=[], period_label="7 days")

        self.assertEqual(group.payload["chat_type"], "group")
        self.assertEqual(channel.payload["chat_type"], "channel")

    def test_local_fallback_and_participant_mapping(self) -> None:
        result = local_fallback_analysis(messages=messages(), events=[event()], period_label="30 days", chat_type="one_to_one")
        self.assertIn("participant_analysis", result)
        self.assertIn("advice", result)
        bundle = build_ai_input_bundle(settings_for(ai_max_messages=4), chat={"chat_type": "one_to_one"}, messages=messages(), events=[event()], period_label="30 days")
        senders = {item["sender"] for item in bundle.payload["messages"]}
        self.assertIn("YOU", senders)
        self.assertIn("OTHER", senders)


if __name__ == "__main__":
    unittest.main()
