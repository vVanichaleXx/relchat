from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from relchat.bot.formatters import format_ai_result_overview, format_ai_result_section
from relchat.bot.keyboards import ai_detail_keyboard
from relchat.bot.services.ai_analysis import (
    AIAnalysisError,
    build_ai_input_bundle,
    communication_score_from_dimensions,
    local_fallback_analysis,
    validate_ai_result,
)
from relchat.bot.services.analysis_frameworks import framework_payload_for_context, get_framework
from relchat.bot.services.analysis_memory import memory_candidates_from_analysis, merge_memory, persist_analysis_artifacts
from relchat.bot.services.communication_timeline import build_communication_timeline, timeline_events_from_result
from relchat.bot.services.evaluation_fixtures import OFFLINE_EVALUATION_FIXTURES
from relchat.bot.services.evidence_service import build_why_conclusion_panels
from relchat.bot.services.personal_profile import build_cross_chat_profile, build_personal_profile
from relchat.bot.services.semantic_interpretation import analyze_semantics, validate_semantic_result
from relchat.bot.services.story_builder import build_communication_story
from relchat.config import Settings
from relchat.core.models import ConversationRef, Message
from relchat.database.repositories import (
    create_ai_analysis,
    create_interpretation_finding,
    get_communication_memory,
    get_semantic_analysis_settings,
    list_communication_memories,
    list_communication_profile_snapshots,
    list_communication_timeline_events,
    list_interpretation_findings,
    remove_user_chat,
    save_user_chat,
    update_semantic_analysis_settings,
)
from relchat.database.sqlite import connect, init_db


BASE = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def settings_for(db_path: Path | None = None, **overrides: object) -> Settings:
    base = {
        "api_id": 1,
        "api_hash": "hash",
        "telegram_bot_token": "123456:token",
        "allowed_user_ids": frozenset({1, 2}),
        "data_dir": Path("data") if db_path is None else db_path.parent,
        "db_path": Path("data/relchat.sqlite3") if db_path is None else db_path,
        "session_path": Path("data/telegram.session") if db_path is None else db_path.parent / "telegram.session",
        "openai_api_key": "sk-test",
        "ai_enabled": True,
        "ai_model": "gpt-test",
        "ai_max_messages": 50,
        "ai_max_chars": 5000,
    }
    base.update(overrides)
    return Settings(**base)


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


def filler(start: int, count: int = 10) -> list[Message]:
    return [msg(start + index, "ordinary check-in", outgoing=index % 2 == 0) for index in range(count)]


class ProductUxV12SemanticTests(unittest.TestCase):
    def test_explicit_and_playful_sarcasm_becomes_available_without_aggression(self) -> None:
        messages = [
            msg(1, "Did the deploy work?", outgoing=True),
            msg(2, "Yeah right, brilliant success /s haha", outgoing=False),
            msg(3, "Ok, joking, we fix it now", outgoing=False),
            *filler(4, 10),
        ]
        result = analyze_semantics(messages=messages, context_category="friendship", period_label="today", language="en")
        self.assertEqual(result["sarcasm"]["status"], "available")
        self.assertEqual(result["sarcasm"]["direction"], "playful")
        self.assertNotEqual(result["aggression"]["type"], "hostility")
        local = local_fallback_analysis(messages=messages, events=[], period_label="today", chat_type="one_to_one", language="en", context_classification={"category": "friendship", "confidence": "high", "source": "user_confirmed"})
        self.assertEqual(local["dimensions"]["sarcasm_intensity"]["status"], "available")
        self.assertLess(local["dimensions"]["sarcasm_intensity"]["score"], 3.0)

    def test_dismissive_sarcasm_has_impact_and_evidence(self) -> None:
        messages = [
            msg(1, "Can you answer the actual question?", outgoing=True),
            msg(2, "Sure, great question, whatever", outgoing=False),
            msg(3, "I still need the answer", outgoing=True),
            msg(4, "Cool story. Anyway, forget it", outgoing=False),
            *filler(5, 10),
        ]
        result = analyze_semantics(messages=messages, context_category="mixed", period_label="today", language="en")
        self.assertEqual(result["sarcasm"]["status"], "available")
        self.assertEqual(result["sarcasm"]["direction"], "dismissive")
        self.assertGreaterEqual(result["sarcasm"]["evidence_count"], 2)
        self.assertIn("topic", result["sarcasm"]["impact"])
        panels = build_why_conclusion_panels({"evidence_findings": result["findings"]}, language="en")
        self.assertTrue(panels)
        self.assertTrue(panels[0]["supporting_evidence"])

    def test_ambiguous_sarcasm_is_not_false_zero_or_confident(self) -> None:
        result = analyze_semantics(messages=[msg(1, "ok 😂"), *filler(2, 10)], context_category="friendship", period_label="today", language="en")
        self.assertIn(result["sarcasm"]["status"], {"ambiguous", "insufficient_data"})
        local = local_fallback_analysis(messages=[msg(1, "ok 😂"), *filler(2, 10)], events=[], period_label="today", chat_type="one_to_one", language="en")
        self.assertIsNone(local["dimensions"]["sarcasm_intensity"]["score"])
        self.assertNotEqual(local["dimensions"]["sarcasm_intensity"]["status"], "available")

    def test_explicit_aggression_assertiveness_and_frustration_are_distinct(self) -> None:
        aggressive = analyze_semantics(messages=[msg(1, "Shut up, idiot"), msg(2, "Answer now"), *filler(3, 10)], context_category="mixed", period_label="today", language="en")
        self.assertEqual(aggressive["aggression"]["status"], "available")
        self.assertIn(aggressive["aggression"]["type"], {"verbal_aggression", "hostility"})
        self.assertEqual(aggressive["findings"][0]["severity"], "problem")

        boundary = analyze_semantics(messages=[msg(1, "I don't agree. Please stop asking."), *filler(2, 10)], context_category="mixed", period_label="today", language="en")
        self.assertEqual(boundary["aggression"]["type"], "assertiveness")
        self.assertIn("not hostility", boundary["aggression"]["summary"])

        frustration = analyze_semantics(messages=[msg(1, "I am frustrated, this is annoying."), *filler(2, 10)], context_category="mixed", period_label="today", language="en")
        self.assertEqual(frustration["aggression"]["type"], "frustration")
        self.assertNotEqual(frustration["aggression"]["type"], "hostility")

    def test_pressure_persuasion_and_manipulation_are_separate(self) -> None:
        pressure = analyze_semantics(
            messages=[
                msg(1, "No, I don't want this", outgoing=False),
                msg(2, "Please answer right now", outgoing=True),
                msg(3, "Can you do it now?", outgoing=True),
                *filler(4, 10),
            ],
            context_category="mixed",
            period_label="today",
            language="en",
        )
        self.assertEqual(pressure["influence"]["category"], "pressure")
        self.assertGreaterEqual(pressure["influence"]["evidence_count"], 2)

        persuasion = analyze_semantics(messages=[msg(1, "Can you consider this option because it saves time?"), *filler(2, 10)], context_category="work", period_label="today", language="en")
        self.assertEqual(persuasion["influence"]["category"], "persuasion")

        ambiguous = analyze_semantics(messages=[msg(1, "If you cared, you would help"), *filler(2, 10)], context_category="mixed", period_label="today", language="en")
        self.assertIn(ambiguous["influence"]["status"], {"ambiguous", "insufficient_data"})

        manipulation = analyze_semantics(
            messages=[
                msg(1, "No, I can't", outgoing=False),
                msg(2, "If you cared, you would answer now", outgoing=True),
                msg(3, "After all I did, you owe me this", outgoing=True),
                *filler(4, 10),
            ],
            context_category="mixed",
            period_label="today",
            language="en",
        )
        self.assertIn(manipulation["influence"]["category"], {"possible_manipulation", "clear_manipulative_pattern"})
        self.assertTrue(manipulation["influence"]["alternative_interpretations"])

    def test_possible_interest_is_probabilistic_and_not_gender_based(self) -> None:
        messages = [
            msg(1, "How was your day?", outgoing=True),
            msg(2, "I miss you and want dinner together just us", outgoing=False),
            msg(3, "Let's meet on Friday", outgoing=True),
            msg(4, "I like you, Friday works", outgoing=False),
            *filler(5, 12),
        ]
        result = analyze_semantics(messages=messages, context_category="romantic", period_label="today", language="en")
        self.assertEqual(result["possible_interest"]["status"], "available")
        self.assertIn("not prove", result["possible_interest"]["summary"])
        self.assertNotIn("definitely", json.dumps(result, ensure_ascii=False).casefold())

        work = analyze_semantics(messages=messages, context_category="work", period_label="today", language="en")
        self.assertEqual(work["possible_interest"]["status"], "not_applicable")

    def test_structured_finding_separates_observation_interpretation_and_advice(self) -> None:
        result = analyze_semantics(messages=[msg(1, "No", outgoing=False), msg(2, "Please answer right now", outgoing=True), *filler(3, 10)], context_category="mixed", period_label="today", language="en")
        finding = result["findings"][0]
        self.assertIn("observation", finding)
        self.assertIn("interpretation", finding)
        self.assertIn("advice", finding)
        self.assertGreaterEqual(len(finding["evidence"]), 1)
        self.assertIn(finding["confidence"], {"low", "medium", "high"})


class ProductUxV12AnalysisFlowTests(unittest.TestCase):
    def test_equal_message_counts_do_not_create_empty_high_score(self) -> None:
        messages = [msg(i + 1, "ok", outgoing=i % 2 == 0) for i in range(1657)]
        result = local_fallback_analysis(messages=messages, events=[], period_label="1657 messages", chat_type="one_to_one", language="en", context_classification={"category": "unknown", "confidence": "low", "source": "automatic"})
        self.assertTrue(result["overall_score"] is None or result["overall_score"] < 8.0)
        self.assertNotEqual(result["verdict"]["level"], "strong")
        self.assertIsNone(result["dimensions"]["sarcasm_intensity"]["score"])
        self.assertIsNone(result["dimensions"]["hostility"]["score"])
        rendered = format_ai_result_overview({"chat_title": "Regression", "result": result}, language="en")
        self.assertIn("Local mode", "\n".join(result["limitations"]))
        self.assertNotIn("Sarcasm intensity: 0.0", rendered)
        self.assertNotIn("not available", rendered)

    def test_ai_prompt_payload_is_anonymized_and_contextual(self) -> None:
        settings = settings_for()
        bundle = build_ai_input_bundle(
            settings,
            chat={"source": "telegram", "chat_id": "raw_chat", "chat_type": "one_to_one", "title": "@secret_name +15555550123"},
            messages=[msg(1, "Hello @realuser +15555550123"), msg(2, "hi", outgoing=False)],
            events=[],
            period_label="today",
            language="en",
            context_classification={"category": "romantic", "confidence": "medium", "source": "automatic"},
        )
        payload_text = json.dumps(bundle.payload, ensure_ascii=False)
        self.assertIn("romantic", payload_text)
        self.assertIn("analysis_frameworks", bundle.payload)
        self.assertIn("semantic_capability_boundary", bundle.payload)
        self.assertNotIn("@realuser", payload_text)
        self.assertNotIn("+15555550123", payload_text)
        self.assertIn("YOU", payload_text)
        self.assertIn("OTHER", payload_text)

    def test_ai_validation_allows_careful_manipulation_and_rejects_proven_feelings(self) -> None:
        dimensions = {}
        ai_result = minimal_ai_result(
            semantic_analysis={
                "sarcasm": {"status": "insufficient_data"},
                "aggression": {"status": "insufficient_data"},
                "influence": {
                    "status": "available",
                    "category": "possible_manipulation",
                    "strategy": "guilt_induction_after_reluctance",
                    "confidence": "medium",
                    "evidence_count": 2,
                    "summary": "A possible manipulative pattern is visible, but intent is not proven.",
                    "effect": "It can restrict fair choice.",
                    "evidence": [{"evidence_id": "e1", "evidence_type": "explicit_wording", "source": "ai_interpretation", "message_ref": "m1", "sender": "YOU", "description": "guilt_or_obligation_pressure_marker"}],
                    "alternative_interpretations": ["It may be a clumsy request."],
                    "limitations": ["Selected period only."],
                    "period_scope": "today",
                    "context_scope": "mixed",
                },
                "possible_interest": {"status": "insufficient_data"},
                "findings": [],
            }
        )
        validated = validate_ai_result(ai_result, dimensions=dimensions, message_count=20, coverage={"sent_messages": 8, "available_messages": 20}, context_classification={"category": "mixed", "confidence": "medium", "source": "automatic"})
        self.assertEqual(validated["semantic_analysis"]["influence"]["category"], "possible_manipulation")
        bad = minimal_ai_result(summary="They definitely love you.")
        with self.assertRaises(AIAnalysisError):
            validate_ai_result(bad, dimensions=dimensions, message_count=20, coverage={"sent_messages": 8, "available_messages": 20}, context_classification={"category": "romantic", "confidence": "medium", "source": "automatic"})

    def test_local_ai_capability_boundary_and_russian_single_language(self) -> None:
        result = local_fallback_analysis(messages=[msg(i + 1, "ок", outgoing=i % 2 == 0) for i in range(249)], events=[], period_label="30 дней", chat_type="one_to_one", language="ru", context_classification={"category": "mixed", "confidence": "medium", "source": "automatic"})
        text = format_ai_result_overview({"chat_title": "Чат", "result": result}, language="ru")
        self.assertIn("Как вы общаетесь с этим человеком", text)
        self.assertIn("Локальный режим", "\n".join(result["limitations"]))
        for fragment in ["What is happening", "How you communicate", "not available", "Local semantic detection"]:
            self.assertNotIn(fragment, text)

    def test_story_profile_and_evidence_ux_are_human_readable(self) -> None:
        messages = [
            msg(1, "Can you answer the actual question?"),
            msg(2, "Sure, great question, whatever", outgoing=False),
            msg(3, "I still need the answer"),
            msg(4, "Cool story. Anyway, forget it", outgoing=False),
            *filler(5, 12),
        ]
        semantic = analyze_semantics(messages=messages, context_category="mixed", period_label="today", language="en")
        profile = build_personal_profile(messages=messages, semantic_analysis=semantic, context_category="mixed", period_label="today", language="en")
        story = build_communication_story(messages=messages, context_category="mixed", semantic_analysis=semantic, evidence_findings=semantic["findings"], personal_profile=profile, period_label="today", language="en")
        why = format_ai_result_section({"result": {"evidence_findings": semantic["findings"]}}, "why", language="en")
        self.assertTrue(story["what_is_happening"])
        self.assertIn("How you communicate", profile["title"])
        self.assertIn("Why this conclusion?", why)
        self.assertIn("What is directly visible", why)
        self.assertNotIn("Can you answer", why)

    def test_memory_promotion_contradiction_timeline_and_cross_chat_profile(self) -> None:
        messages = [msg(1, "Can you answer?"), msg(2, "Sarcasm: sure, great, whatever /s", outgoing=False), *filler(3, 12)]
        result = local_fallback_analysis(messages=messages, events=[], period_label="today", chat_type="one_to_one", language="en", context_classification={"category": "mixed", "confidence": "medium", "source": "automatic"})
        candidates = memory_candidates_from_analysis(result)
        self.assertTrue(candidates)
        first = merge_memory(None, candidates[0])
        repeated = merge_memory(first, candidates[0])
        self.assertTrue(repeated["active"])
        opposite = merge_memory(repeated, {"memory_key": "sarcasm:playful", "category": "sarcasm", "summary": "Playful sarcasm", "confidence": "medium", "evidence_count": 2})
        self.assertGreaterEqual(opposite["contradiction_count"], 1)
        events = timeline_events_from_result(result, language="en")
        self.assertTrue(any(event["event_type"].startswith("semantic_") for event in events))
        cross = build_cross_chat_profile([{"result": result}, {"result": result}, {"result": result}], language="en", min_coverage=2)
        self.assertEqual(cross["status"], "available")

    def test_framework_registry_and_offline_fixtures(self) -> None:
        core = get_framework("context_aware_core")
        self.assertIn("sarcasm", core.dimensions)
        self.assertTrue(framework_payload_for_context("romantic"))
        expected = {
            "balanced_healthy_friendship",
            "playful_sarcastic_friendship",
            "dismissive_sarcasm",
            "explicit_aggression",
            "ordinary_assertive_disagreement",
            "repeated_pressure_after_refusal",
            "legitimate_persuasion",
            "ambiguous_manipulation_candidate",
            "possible_mutual_romantic_interest",
            "one_sided_romantic_effort",
            "work_task_confusion",
            "supportive_family_conversation",
            "conflict_followed_by_repair",
            "active_but_superficial",
            "short_insufficient_data_chat",
            "group_chat",
            "channel",
        }
        self.assertTrue(expected <= set(OFFLINE_EVALUATION_FIXTURES))

    def test_callback_privacy_has_evidence_button_and_no_raw_ids(self) -> None:
        callbacks = [button.callback_data or "" for row in ai_detail_keyboard(language="en").inline_keyboard for button in row]
        self.assertIn("rc:home:ai:why", callbacks)
        self.assertTrue(all("chat1" not in callback and "123456789" not in callback for callback in callbacks))
        self.assertLessEqual(len(callbacks[0]), 64)


class ProductUxV12PersistenceTests(unittest.TestCase):
    def test_v12_migrations_persistence_isolation_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            init_db(db_path)
            with connect(db_path) as conn:
                save_user_chat(conn, 1, ConversationRef(source="telegram", conversation_id="chat1", conversation_type="one_to_one", title="Chat One"))
                save_user_chat(conn, 2, ConversationRef(source="telegram", conversation_id="chat1", conversation_type="one_to_one", title="Chat One"))
                result = local_fallback_analysis(messages=[msg(1, "No", outgoing=False), msg(2, "Please answer right now", outgoing=True), *filler(3, 12)], events=[], period_label="today", chat_type="one_to_one", language="en")
                analysis = create_ai_analysis(
                    conn,
                    bot_user_id=1,
                    job_id=None,
                    report_id=None,
                    source="telegram",
                    chat_id="chat1",
                    chat_title="Chat One",
                    model_name=None,
                    analysis_mode="local",
                    status="completed",
                    period_id="today",
                    period_label="today",
                    period_start=None,
                    period_end=None,
                    result=result,
                    dimensions=result.get("dimensions"),
                    overall_score=result.get("overall_score"),
                    confidence=result.get("score_confidence"),
                )
                persist_analysis_artifacts(conn, analysis=analysis, result=result)
                create_interpretation_finding(conn, bot_user_id=2, source="telegram", chat_id="chat1", analysis_id=None, report_id=None, finding={"finding_id": "other", "finding_type": "sarcasm", "title": "Other", "confidence": "medium", "severity": "neutral", "evidence": []})
                conn.commit()

                self.assertTrue(list_communication_profile_snapshots(conn, 1, source="telegram", chat_id="chat1"))
                self.assertTrue(list_interpretation_findings(conn, 1, source="telegram", chat_id="chat1"))
                self.assertTrue(list_communication_timeline_events(conn, 1, source="telegram", chat_id="chat1"))
                self.assertTrue(list_communication_memories(conn, 1, source="telegram", chat_id="chat1"))
                self.assertEqual(len(list_interpretation_findings(conn, 2, source="telegram", chat_id="chat1")), 1)
                settings = get_semantic_analysis_settings(conn, 1)
                self.assertTrue(settings["enabled"])
                update_semantic_analysis_settings(conn, 1, ai_semantic_enabled=False)
                self.assertFalse(get_semantic_analysis_settings(conn, 1)["ai_semantic_enabled"])

                remove_user_chat(conn, 1, "telegram", "chat1")
                conn.commit()
                self.assertFalse(list_interpretation_findings(conn, 1, source="telegram", chat_id="chat1"))
                self.assertEqual(len(list_interpretation_findings(conn, 2, source="telegram", chat_id="chat1")), 1)

    def test_clean_older_database_initializes_v12_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "old.sqlite3"
            raw = sqlite3.connect(db_path)
            raw.execute("CREATE TABLE chats(source TEXT NOT NULL DEFAULT 'telegram', chat_id TEXT PRIMARY KEY, chat_type TEXT NOT NULL, chat_title TEXT)")
            raw.execute("CREATE TABLE messages(source TEXT NOT NULL DEFAULT 'telegram', message_id INTEGER PRIMARY KEY, chat_id TEXT, sender_id TEXT, timestamp TEXT, text TEXT, message_type TEXT, is_outgoing INTEGER)")
            raw.commit()
            raw.close()
            init_db(db_path)
            with connect(db_path) as conn:
                row = conn.execute("SELECT name FROM sqlite_master WHERE name = 'communication_memories'").fetchone()
                self.assertIsNotNone(row)


def minimal_ai_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "summary": "Visible evidence is limited.",
        "context": {"category": "mixed", "confidence": "medium", "evidence_types": ["title"], "source": "automatic", "explanation": "Estimated."},
        "verdict": {"level": "mixed", "headline": "Mixed visible communication.", "explanation": "Evidence is mixed."},
        "conversation_state": "casual",
        "confidence": "medium",
        "direct_findings": [],
        "participant_analysis": {
            "you": {"summary": "You participate.", "observable_patterns": [], "strengths": [], "possible_improvements": []},
            "other": {"summary": "The other participant participates.", "observable_patterns": [], "strengths": [], "possible_improvements": []},
        },
        "positive_patterns": [],
        "problem_patterns": [],
        "weak_reply_patterns": [],
        "uncertainties": ["The reason cannot be determined from messages alone."],
        "recommended_action": {"action": "no_action", "explanation": "Evidence is limited."},
        "advice": [{"priority": 1, "title": "Clarify", "explanation": "Ask directly.", "example": "Can you clarify?"}],
        "semantic_analysis": {},
        "evidence_findings": [],
        "personal_profile": {},
        "communication_story": {},
        "adaptive_tone": "neutral_limited",
        "communication_timeline_events": [],
        "memory_candidates": [],
        "limitations": ["Selected period only."],
    }
    result.update(overrides)
    return result
