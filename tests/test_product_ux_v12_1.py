from __future__ import annotations

import asyncio
import socket
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from relchat.bot.formatters import format_ai_result_overview, format_job_failure, format_job_progress
from relchat.bot.services.advice_routing import route_advice, validate_advice_routes
from relchat.bot.services.ai_analysis import local_fallback_analysis, validate_ai_result
from relchat.bot.services.analysis_memory import memory_candidates_from_analysis
from relchat.bot.services.history_segmentation import build_long_history_summary, segment_history
from relchat.bot.services.question_metrics import build_question_metrics
from relchat.bot.services.retry_policy import classify_failure, retry_decision, run_with_retries
from relchat.bot.services.score_explanation import build_score_explanation
from relchat.bot.services.semantic_interpretation import analyze_semantics
from relchat.bot.services.telethon_lifecycle import cancel_owned_tasks, owned_client, safe_disconnect, shutdown_analysis_tasks
from relchat.core.models import Message
from relchat.database.repositories import create_analysis_job, get_analysis_job, update_analysis_job
from relchat.database.sqlite import connect, init_db


BASE = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def msg(i: int, text: str, *, outgoing: bool | None = None, minutes: int | None = None, forward_info: str | None = None) -> Message:
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
        forward_info=forward_info,
        edit_date=None,
        is_outgoing=outgoing,
        raw_platform_payload_reference=None,
    )


def filler(start: int, count: int = 12) -> list[Message]:
    return [msg(start + index, "ordinary family note", outgoing=index % 2 == 0) for index in range(count)]


class ProductUxV121SemanticConfidenceTests(unittest.TestCase):
    def test_weak_local_sarcasm_stays_ambiguous_and_cautious(self) -> None:
        result = analyze_semantics(messages=[msg(1, "ну конечно"), *filler(2, 12)], context_category="family", period_label="today", language="ru", source="local_pattern")
        self.assertEqual(result["sarcasm"]["status"], "ambiguous")
        self.assertEqual(result["sarcasm"]["semantic_source"], "local_pattern")
        self.assertEqual(result["sarcasm"]["semantic_depth"], "suggestive")
        self.assertFalse(result["findings"])

        local = local_fallback_analysis(messages=[msg(1, "ну конечно"), *filler(2, 12)], events=[], period_label="сегодня", chat_type="one_to_one", language="ru", context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"})
        self.assertIsNone(local["dimensions"]["sarcasm_intensity"]["score"])
        self.assertFalse(memory_candidates_from_analysis(local))
        rendered = format_ai_result_overview({"chat_title": "Семья", "result": local}, language="ru")
        self.assertIn("Локальный режим", "\n".join(local["limitations"]))
        self.assertNotIn("Обесценивающий сарказм закрывает тему", rendered)

    def test_explicit_repeated_and_ai_confirmed_sarcasm_can_be_available(self) -> None:
        explicit = analyze_semantics(messages=[msg(1, "Sarcasm: sure, great /s haha"), *filler(2, 12)], context_category="friendship", period_label="today", language="en")
        self.assertEqual(explicit["sarcasm"]["status"], "available")
        self.assertEqual(explicit["sarcasm"]["semantic_source"], "explicit_rule")
        self.assertEqual(explicit["sarcasm"]["semantic_depth"], "direct")

        repeated = analyze_semantics(
            messages=[
                msg(1, "Can you answer?"),
                msg(2, "Sure, great question, whatever", outgoing=False),
                msg(3, "I still need the answer"),
                msg(4, "Cool story. Anyway, forget it", outgoing=False),
                *filler(5, 12),
            ],
            context_category="family",
            period_label="today",
            language="en",
            source="local_pattern",
        )
        self.assertEqual(repeated["sarcasm"]["status"], "available")
        self.assertEqual(repeated["sarcasm"]["direction"], "dismissive")
        self.assertEqual(repeated["sarcasm"]["semantic_source"], "local_pattern")

        ai_result = validate_ai_result(
            minimal_ai_result(
                semantic_analysis={
                    "sarcasm": {
                        "status": "available",
                        "presence": "recurring",
                        "direction": "dismissive",
                        "confidence": "medium",
                        "source": "ai_interpretation",
                        "semantic_source": "ai_interpretation",
                        "semantic_depth": "contextual",
                        "evidence_count": 2,
                        "summary": "Several contextual signs point to dismissive sarcasm, but intent is not proven.",
                        "impact": "It can prevent a direct answer.",
                        "interpretation_level": "strongly_supported_interpretation",
                        "evidence": [{"evidence_id": "e1", "evidence_type": "contextual_sequence", "source": "ai_interpretation", "message_ref": "m1", "sender": "OTHER", "description": "sarcasm_after_question_or_topic_shutdown"}],
                        "alternative_interpretations": ["It may be shared humour."],
                        "limitations": ["Selected period only."],
                        "period_scope": "today",
                        "context_scope": "family",
                    },
                    "aggression": {"status": "insufficient_data"},
                    "influence": {"status": "insufficient_data"},
                    "possible_interest": {"status": "not_applicable"},
                    "findings": [
                        {
                            "finding_id": "sarcasm_1",
                            "finding_type": "sarcasm",
                            "title": "Dismissive sarcasm interferes with a direct answer",
                            "observation": "Two contextual sequences support this.",
                            "interpretation": "Sarcasm may be closing the topic.",
                            "confidence": "medium",
                            "severity": "attention",
                            "semantic_source": "ai_interpretation",
                            "semantic_depth": "contextual",
                            "evidence": [{"evidence_id": "e1", "evidence_type": "contextual_sequence", "source": "ai_interpretation", "message_ref": "m1", "sender": "OTHER", "description": "sarcasm_after_question_or_topic_shutdown"}],
                            "alternative_interpretations": ["It may be shared humour."],
                            "limitations": ["Selected period only."],
                        }
                    ],
                }
            ),
            dimensions={},
            message_count=40,
            coverage={"sent_messages": 12, "available_messages": 40, "partial": True},
            context_classification={"category": "family", "confidence": "medium", "source": "automatic"},
        )
        self.assertEqual(ai_result["semantic_analysis"]["sarcasm"]["semantic_source"], "ai_interpretation")
        self.assertEqual(ai_result["dimensions"]["sarcasm_intensity"]["status"], "available")

    def test_assertiveness_and_frustration_are_not_hostility(self) -> None:
        boundary = analyze_semantics(messages=[msg(1, "I don't agree. Please stop asking."), *filler(2, 12)], context_category="family", period_label="today", language="en")
        self.assertEqual(boundary["aggression"]["type"], "assertiveness")
        self.assertLess(boundary["aggression"]["evidence_count"], 3)
        frustration = analyze_semantics(messages=[msg(1, "I am frustrated and this is annoying."), *filler(2, 12)], context_category="family", period_label="today", language="en")
        self.assertEqual(frustration["aggression"]["type"], "frustration")
        self.assertNotEqual(frustration["aggression"]["type"], "hostility")


class ProductUxV121AdviceAndRenderingTests(unittest.TestCase):
    def test_typed_advice_matches_finding_type_and_validates(self) -> None:
        findings = [
            finding("sarcasm_1", "sarcasm", "attention"),
            finding("aggression_1", "aggression", "problem"),
            finding("questions_1", "unanswered_questions", "attention"),
            finding("work_1", "work_task_ambiguity", "attention"),
        ]
        sarcasm_advice = route_advice([findings[0]], context_category="family", language="en")[0]
        self.assertEqual(sarcasm_advice["category"], "sarcasm")
        self.assertNotIn("insults", sarcasm_advice["explanation"].casefold())

        aggression_advice = route_advice([findings[1]], context_category="family", language="en")[0]
        self.assertEqual(aggression_advice["category"], "aggression")
        self.assertIn("boundary", aggression_advice["title"].casefold())

        question_advice = route_advice([findings[2]], context_category="family", language="en")[0]
        self.assertEqual(question_advice["category"], "question")

        work_advice = route_advice([findings[3]], context_category="work", language="en")[0]
        self.assertEqual(work_advice["category"], "task_clarity")

        invalid = [{"priority": 1, "finding_id": "sarcasm_1", "finding_type": "sarcasm", "category": "aggression", "severity": "problem", "title": "Bad", "explanation": "Bad", "example": ""}]
        self.assertFalse(validate_advice_routes(invalid, [findings[0]], language="en"))

    def test_participant_balance_dedup_and_strength_cleanup(self) -> None:
        messages = [msg(i + 1, "ok", outgoing=i % 2 == 0) for i in range(120)]
        result = local_fallback_analysis(messages=messages, events=[], period_label="30 days", chat_type="one_to_one", language="en", context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Family", "result": result}, language="en")
        self.assertIn("Participation balance", rendered)
        self.assertNotIn("Both sides participated", rendered)
        self.assertNotIn("How you communicate\n• Participates at a similar visible message volume", rendered)
        self.assertNotIn("How the other person communicates\n• Participates at a similar visible message volume", rendered)

    def test_question_metrics_filter_and_normalize_large_counts(self) -> None:
        messages = [
            msg(1, "https://example.test/?q=1"),
            msg(2, "???", outgoing=False),
            msg(3, "> Can you approve this?", outgoing=True),
            msg(4, "```python\nif x?: pass\n```", outgoing=False),
            msg(5, "Forwarded question?", forward_info="forwarded"),
            msg(6, "Who cares?", outgoing=False),
            msg(7, "Can you confirm the plan?", outgoing=True),
            msg(8, "Можешь подтвердить время?", outgoing=True),
            msg(9, "ordinary", outgoing=False),
        ]
        metrics = build_question_metrics(messages, language="en")
        self.assertEqual(metrics["raw_question_mark_candidates"], 8)
        self.assertEqual(metrics["direct_question_count"], 2)
        self.assertEqual(metrics["excluded_counts"]["url"], 1)
        self.assertEqual(metrics["excluded_counts"]["repeated_punctuation"], 1)
        self.assertEqual(metrics["excluded_counts"]["quote"], 1)
        self.assertEqual(metrics["excluded_counts"]["code"], 1)
        self.assertEqual(metrics["excluded_counts"]["forwarded"], 1)
        self.assertIn("2 direct questions", metrics["summary"])

    def test_long_history_segmentation_and_score_explanation_render(self) -> None:
        messages = [msg(i + 1, "family coordination", outgoing=i % 2 == 0, minutes=i * 360) for i in range(1800)]
        segments = build_long_history_summary(messages, period_label="Full history", session_count=120, context_category="family", language="en")
        self.assertTrue(segments["segmented"])
        self.assertLessEqual(segments["window_count"], 18)
        self.assertIn("family", segments["current_picture"].casefold())
        self.assertTrue(segment_history(messages))

        result = local_fallback_analysis(messages=messages, events=[], period_label="Full history", chat_type="one_to_one", language="en", context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Family", "result": result}, language="en")
        self.assertIn("Long history", rendered)
        self.assertIn("Why", rendered)
        self.assertNotIn("Overall score = weighted", rendered)
        explanation = build_score_explanation(dimensions=result["dimensions"], score_state=result["score_state"], language="en", semantic_mode="local")
        self.assertEqual(explanation["balance_note"], result["score_explanation"]["balance_note"])

    def test_real_family_full_history_regression(self) -> None:
        messages = large_family_fixture()
        result = local_fallback_analysis(messages=messages, events=[], period_label="Вся история", chat_type="one_to_one", language="ru", context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Семейный чат", "result": result}, language="ru")
        self.assertIn(result["semantic_analysis"]["sarcasm"]["status"], {"ambiguous", "insufficient_data"})
        self.assertNotEqual((result["semantic_analysis"]["aggression"] or {}).get("type"), "verbal_aggression")
        self.assertFalse(any(item.get("category") == "aggression" for item in result["advice"]))
        self.assertIn("Почему", rendered)
        self.assertIn("Длинная история", rendered)
        self.assertIn("семейн", rendered.casefold())
        self.assertNotIn("478", rendered)
        self.assertNotIn("Обе стороны участвовали", rendered)
        self.assertNotIn("Участвует с похожим видимым объемом", rendered)
        self.assertNotIn("Visible data", rendered)
        self.assertNotIn("local window", rendered.casefold())
        self.assertNotIn("Dismissive sarcasm", rendered)
        self.assertFalse(memory_candidates_from_analysis(result))


class ProductUxV121ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_policy_transient_and_permanent(self) -> None:
        self.assertEqual(classify_failure(socket.gaierror("DNS lookup failed")), "network_dns")
        decision = retry_decision(socket.gaierror("DNS lookup failed"), attempt=1, max_attempts=3, base_delay=0.0, jitter=0.0)
        self.assertTrue(decision.should_retry)

        class AuthExpired(Exception):
            pass

        permanent = retry_decision(AuthExpired("telegram auth expired"), attempt=1, max_attempts=3)
        self.assertFalse(permanent.should_retry)
        self.assertEqual(permanent.category, "telegram_auth")

    async def test_run_with_retries_is_idempotent_for_one_operation(self) -> None:
        attempts = 0
        retry_events = []

        async def operation():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise socket.gaierror("DNS lookup failed")
            return "completed"

        async def on_retry(decision):
            retry_events.append(decision.category)

        result = await run_with_retries(operation, max_attempts=3, sleep=no_sleep, on_retry=on_retry, base_delay=0.0, jitter=0.0)
        self.assertEqual(result, "completed")
        self.assertEqual(attempts, 2)
        self.assertEqual(retry_events, ["network_dns"])

    async def test_telethon_lifecycle_disconnects_and_cancels_owned_tasks(self) -> None:
        client = MockClient()
        await safe_disconnect(client)
        self.assertTrue(client.disconnected)

        made = MockClient()
        async with owned_client(lambda: made):
            self.assertTrue(made.started)
        self.assertTrue(made.disconnected)

        task = asyncio.create_task(asyncio.sleep(60))
        await cancel_owned_tasks([task])
        self.assertTrue(task.cancelled())

        class App:
            def __init__(self, task):
                self.bot_data = {"relchat_analysis_tasks": {"job": task}}

        task2 = asyncio.create_task(asyncio.sleep(60))
        app = App(task2)
        await shutdown_analysis_tasks(app)
        self.assertTrue(task2.cancelled())
        self.assertFalse(app.bot_data["relchat_analysis_tasks"])

    async def test_progress_and_failure_messages_are_localized_and_safe(self) -> None:
        progress = format_job_progress({"status": "retrying", "progress_percent": 40, "imported_message_count": 100, "chat_title": "Чат", "period_label": "30 дней"}, language="ru")
        self.assertIn("Повторная попытка", progress)
        self.assertNotIn("Traceback", progress)
        failure = format_job_failure({"error_message": "telegram_auth", "imported_message_count": 50, "chat_title": "Чат"}, language="ru")
        self.assertIn("повторный вход", failure)
        self.assertNotIn("RpcCallFailError", failure)


class ProductUxV121MigrationTests(unittest.TestCase):
    def test_retry_metadata_columns_initialize_idempotently_on_old_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "old.sqlite3"
            raw = sqlite3.connect(db_path)
            raw.execute(
                """
                CREATE TABLE analysis_jobs (
                  job_id TEXT PRIMARY KEY,
                  bot_user_id INTEGER NOT NULL,
                  source TEXT NOT NULL DEFAULT 'telegram',
                  chat_id TEXT NOT NULL,
                  chat_title TEXT,
                  period_id TEXT NOT NULL,
                  period_label TEXT NOT NULL,
                  period_start TEXT,
                  period_end TEXT,
                  modules TEXT NOT NULL,
                  status TEXT NOT NULL,
                  progress_percent INTEGER NOT NULL DEFAULT 0,
                  imported_message_count INTEGER NOT NULL DEFAULT 0,
                  error_reference TEXT,
                  error_message TEXT,
                  report_id TEXT,
                  progress_chat_id INTEGER,
                  progress_message_id INTEGER,
                  analysis_mode TEXT NOT NULL DEFAULT 'local',
                  ai_analysis_id TEXT,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  started_at TEXT,
                  completed_at TEXT,
                  elapsed_seconds INTEGER
                )
                """
            )
            raw.commit()
            raw.close()
            init_db(db_path)
            init_db(db_path)
            with connect(db_path) as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis_jobs)").fetchall()}
                self.assertIn("retry_attempt_count", columns)
                self.assertIn("failure_category", columns)
                self.assertIn("idempotency_key", columns)
                job = create_analysis_job(
                    conn,
                    bot_user_id=1,
                    source="telegram",
                    chat_id="chat1",
                    chat_title="Chat",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    modules=["activity"],
                )
                update_analysis_job(conn, job["job_id"], status="retrying", retry_attempt_count=1, failure_category="network_dns")
                conn.commit()
                stored = get_analysis_job(conn, job["job_id"])
                self.assertEqual(stored["retry_attempt_count"], 1)
                self.assertEqual(stored["failure_category"], "network_dns")
                self.assertTrue(stored["idempotency_key"])


def finding(finding_id: str, finding_type: str, severity: str) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "title": finding_type,
        "observation": "Observed.",
        "interpretation": "Interpreted.",
        "confidence": "medium",
        "severity": severity,
        "semantic_source": "explicit_rule",
        "semantic_depth": "direct",
        "evidence": [{"evidence_id": "e1", "evidence_type": "explicit_wording", "source": "explicit_rule", "message_ref": "m1", "sender": "YOU", "description": "explicit_refusal_marker"}],
        "alternative_interpretations": [],
        "limitations": ["Selected period only."],
    }


def large_family_fixture() -> list[Message]:
    messages: list[Message] = []
    raw_questionish = 0
    for index in range(8692):
        source_id = index + 1
        outgoing = index % 2 == 0
        text = "семейные бытовые сообщения"
        if raw_questionish < 478 and index % 18 == 0:
            text = "https://example.test/?family=1" if raw_questionish % 2 == 0 else "???"
            raw_questionish += 1
        if index % 430 == 5:
            text = "Можешь подтвердить время?"
        if index % 700 == 11:
            text = "ну конечно"
        messages.append(msg(source_id, text, outgoing=outgoing, minutes=index * 120))
    return messages


async def no_sleep(_: float) -> None:
    return None


class MockClient:
    def __init__(self) -> None:
        self.started = False
        self.disconnected = False

    async def start(self) -> None:
        self.started = True

    async def disconnect(self) -> None:
        self.disconnected = True


def minimal_ai_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "summary": "Evidence is limited.",
        "context": {"category": "family", "confidence": "medium", "evidence_types": ["title"], "source": "automatic", "explanation": "Estimated."},
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
        "advice": [{"priority": 1, "finding_id": "sarcasm_1", "finding_type": "sarcasm", "finding_severity": "attention", "evidence_source": "ai_interpretation", "context_category": "family", "category": "sarcasm", "severity": "attention", "title": "Return", "explanation": "Return to the question.", "example": "Can you answer?"}],
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
