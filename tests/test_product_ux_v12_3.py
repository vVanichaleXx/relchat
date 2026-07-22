from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from relchat.bot.formatters import format_ai_result_overview
from relchat.bot.services.ai_analysis import build_ai_input_bundle, local_fallback_analysis, validate_ai_result
from relchat.bot.services.canonical_findings import build_canonical_findings
from relchat.bot.services.conversation_fingerprint import build_conversation_fingerprint
from relchat.bot.services.individualized_story import build_individualized_story
from relchat.bot.services.pattern_selector import select_distinctive_patterns
from relchat.bot.services.personal_profile import build_cross_chat_profile, build_personal_profile
from relchat.bot.services.personalized_feedback import build_personalized_feedback, feedback_to_advice
from relchat.bot.services.question_metrics import build_question_metrics
from relchat.bot.services.specificity_validator import improve_report_specificity, validate_report_specificity
from relchat.config import Settings
from relchat.core.models import Message


BASE = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)


def msg(i: int, text: str, *, outgoing: bool = True, minutes: int | None = None) -> Message:
    return Message(
        source="telegram",
        source_message_id=i,
        conversation_id="chat-v123",
        sender_id="me" if outgoing else "other",
        sender_name="Real Me" if outgoing else "Real Other",
        timestamp=(BASE + timedelta(minutes=minutes if minutes is not None else i)).isoformat(),
        text=text,
        message_type="text",
        is_outgoing=outgoing,
    )


def minimal_ai_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "summary": "Communication contains certain patterns.",
        "context": {"category": "work", "confidence": "high", "evidence_types": ["title"], "source": "automatic", "explanation": "Work chat."},
        "verdict": {"level": "mixed", "headline": "Communication was mixed.", "explanation": "Evidence is mixed."},
        "conversation_state": "casual",
        "confidence": "medium",
        "direct_findings": [],
        "participant_analysis": {
            "you": {"summary": "", "observable_patterns": [], "strengths": [], "possible_improvements": []},
            "other": {"summary": "", "observable_patterns": [], "strengths": [], "possible_improvements": []},
        },
        "positive_patterns": [{"title": "Both sides participated", "explanation": "", "evidence_type": "metric"}],
        "problem_patterns": [],
        "weak_reply_patterns": [],
        "uncertainties": ["The reason cannot be determined from messages alone."],
        "recommended_action": {"action": "clarify", "explanation": "Try to express your thoughts openly."},
        "advice": [{"priority": 1, "title": "Clear communication is important", "explanation": "Try to express your thoughts openly.", "example": ""}],
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


class ProductUxV123FingerprintAndSelectionTests(unittest.TestCase):
    def test_conversation_fingerprint_is_deterministic_and_specific(self) -> None:
        messages = detailed_user_concise_other()
        canonical = build_canonical_findings(
            work_findings=[
                {
                    "finding_id": "work_response_rhythm_1",
                    "finding_type": "work_response_consistency",
                    "title": "Replies are regular",
                    "status": "available",
                    "severity": "positive",
                    "confidence": "medium",
                    "semantic_source": "local_pattern",
                    "semantic_depth": "direct",
                    "evidence_count": 24,
                    "score_effect": 0.25,
                    "summary_key": "work_response_consistency:test",
                    "evidence": [{"evidence_id": "ev1", "description": "work_response_consistency", "source": "local_pattern"}],
                }
            ],
            context_category="work",
            period_label="30 days",
            language="en",
        )
        first = build_conversation_fingerprint(messages=messages, canonical_findings=canonical, context_category="work", period_scope="30 days", language="en")
        second = build_conversation_fingerprint(messages=messages, canonical_findings=canonical, context_category="work", period_scope="30 days", language="en")
        self.assertEqual(first, second)
        self.assertTrue(first["distinctive_features"])
        self.assertTrue(any("detail" in item["semantic_key"] for item in first["asymmetries"]))
        self.assertIn(first["participant_mapping_confidence"], {"medium", "high"})

    def test_pattern_selector_ranks_useful_findings_above_generic_activity(self) -> None:
        fingerprint = {
            "distinctive_features": [
                {"feature_id": "generic", "role": "asymmetry", "text": "Both sides participated regularly.", "semantic_key": "both_participated", "evidence_count": 100, "confidence": "high"},
                {"feature_id": "detail", "role": "asymmetry", "text": "You send more detailed task context than the other participant.", "semantic_key": "detail:you_more", "participant_scope": "you", "evidence_count": 40, "confidence": "high", "comparison_type": "participant", "practical_consequence": "The requested action can be harder to find."},
                {"feature_id": "repeat", "role": "asymmetry", "text": "You send more detailed task context than the other participant.", "semantic_key": "detail:you_more", "participant_scope": "you", "evidence_count": 40, "confidence": "high", "comparison_type": "participant", "practical_consequence": "The requested action can be harder to find."},
            ],
            "evidence_coverage": {"structural": 1.0, "semantic": 0.0, "historical": 0.0},
        }
        selected = select_distinctive_patterns(fingerprint=fingerprint, canonical_findings=[], context_category="work", language="en")
        self.assertEqual(selected[0]["semantic_key"], "detail:you_more")
        self.assertEqual(sum(1 for item in selected if item["semantic_key"] == "detail:you_more"), 1)
        self.assertFalse(any(item["semantic_key"] == "both_participated" for item in selected))

    def test_story_arc_uses_distinctive_dynamic_without_duplicate_content(self) -> None:
        fingerprint = {
            "period_scope": "30 days",
            "evidence_coverage": {"structural": 1.0, "semantic": 0.0, "historical": 0.4},
            "uncertainties": ["Local mode cannot confirm every decision."],
        }
        patterns = [
            {"pattern_id": "detail", "observation": "You often send the task context in longer messages.", "consequence": "The requested action can be harder to find.", "semantic_key": "detail:you_more", "participant_scope": "you", "finding_type": "", "severity": "neutral", "confidence": "medium", "evidence_count": 20, "specificity_score": 0.8, "comparison_type": "participant"},
            {"pattern_id": "work", "observation": "Task language appears repeatedly in this period.", "consequence": "Task clarity matters more than message volume.", "semantic_key": "topic:work_tasks", "participant_scope": "interaction", "finding_type": "work_task_ambiguity", "severity": "attention", "confidence": "medium", "evidence_count": 8, "specificity_score": 0.7, "comparison_type": "topic", "topic": "work_tasks"},
        ]
        story = build_individualized_story(fingerprint=fingerprint, selected_patterns=patterns, context_category="work", score_state={"score": 5.8}, language="en")
        self.assertIn("task", story["headline"].casefold())
        self.assertIn("longer messages", story["user_role"].casefold())
        self.assertIn("Task language", story["distinctive_dynamic"])
        self.assertNotEqual(story["overall_picture"], story["distinctive_dynamic"])


class ProductUxV123ProfileAndAdviceTests(unittest.TestCase):
    def test_personal_profile_uses_user_specific_observation_without_personality_label(self) -> None:
        profile = build_personal_profile(messages=detailed_user_concise_other(), semantic_analysis={}, context_category="work", period_label="30 days", language="en")
        text = " ".join([profile["summary"], *[row["observation"] for row in profile["dimensions"]]])
        self.assertIn("your messages", text.casefold())
        self.assertNotIn("overly verbose person", text.casefold())
        self.assertNotIn("visible communication style can be described", text.casefold())

    def test_other_participant_section_requires_asymmetry(self) -> None:
        symmetric = [msg(i + 1, "ok", outgoing=i % 2 == 0) for i in range(80)]
        result = local_fallback_analysis(messages=symmetric, events=[], period_label="30 days", chat_type="one_to_one", language="en", context_classification={"category": "family", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Family", "result": result}, language="en")
        self.assertIn("Participation balance", rendered)
        self.assertNotIn("How the other participant responds\nThe other participant visibly participates", rendered)

    def test_advice_is_tailored_or_omitted_when_no_actionable_problem_exists(self) -> None:
        clear_work = [
            msg(1, "Task: send the final file. Owner: me. Deadline today.", outgoing=True),
            msg(2, "Confirmed. Approved.", outgoing=False),
            msg(3, "Done.", outgoing=True),
            msg(4, "Thanks, that closes it.", outgoing=False),
        ] + [msg(5 + i, "status done" if i % 2 == 0 else "ok", outgoing=i % 2 == 0) for i in range(20)]
        result = local_fallback_analysis(messages=clear_work, events=[], period_label="7 days", chat_type="one_to_one", language="en", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        self.assertTrue(result["personalized_feedback"])
        if result["advice"]:
            self.assertNotIn("try to express your thoughts openly", result["advice"][0]["explanation"].casefold())
        else:
            self.assertFalse(result["personalized_feedback"]["action_needed"])

    def test_work_task_advice_fits_detailed_user_pattern(self) -> None:
        findings = build_canonical_findings(
            work_findings=[
                {
                    "finding_id": "work_task_clarity_1",
                    "finding_type": "work_task_ambiguity",
                    "title": "Tasks are not fully specified",
                    "status": "available",
                    "severity": "attention",
                    "confidence": "medium",
                    "semantic_source": "local_pattern",
                    "semantic_depth": "direct",
                    "evidence_count": 10,
                    "score_effect": -0.6,
                    "summary_key": "work_task_ambiguity:test",
                    "evidence": [{"evidence_id": "ev1", "description": "work_task_without_clear_owner_or_deadline", "source": "local_pattern"}],
                }
            ],
            context_category="work",
            period_label="today",
            language="en",
        )
        patterns = [{"finding_id": "work_task_clarity_1", "finding_type": "work_task_ambiguity", "participant_scope": "interaction", "observation": "Tasks are not fully specified.", "semantic_key": "work_task_ambiguity:test", "severity": "attention", "confidence": "medium", "evidence_count": 10, "specificity_score": 0.8}]
        profile = {"dimensions": [{"dimension": "message_detail", "observation": "Your messages are usually more detailed than the other participant's.", "confidence": "medium"}]}
        feedback = build_personalized_feedback(selected_patterns=patterns, canonical_findings=findings, personal_profile=profile, context_category="work", language="en")
        advice = feedback_to_advice(feedback, findings, context_category="work", language="en")[0]
        self.assertIn("first", advice["title"].casefold())
        self.assertEqual(advice["finding_id"], "work_task_clarity_1")

    def test_user_rarely_initiates_but_responds_deeply_is_not_called_disengaged(self) -> None:
        messages = rarely_initiates_but_deep_fixture()
        fingerprint = build_conversation_fingerprint(messages=messages, canonical_findings=[], context_category="friendship", period_scope="30 days", language="en")
        keys = {item["semantic_key"] for item in fingerprint["distinctive_features"]}
        self.assertIn("initiative:other_starts", keys)
        self.assertIn("detail:you_more", keys)
        result = local_fallback_analysis(messages=messages, events=[], period_label="30 days", chat_type="one_to_one", language="en", context_classification={"category": "friendship", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Friend", "result": result}, language="en")
        self.assertIn("did not restart", rendered)
        self.assertIn("more detailed", rendered)
        self.assertNotIn("disengaged", rendered.casefold())
        self.assertNotIn("How you communicate\n\n", rendered)

    def test_frequent_questions_with_good_answers_are_not_treated_as_problem(self) -> None:
        messages = answered_questions_fixture()
        metrics = build_question_metrics(messages, language="en")
        self.assertGreater(metrics["direct_question_count"], 8)
        result = local_fallback_analysis(messages=messages, events=[], period_label="30 days", chat_type="one_to_one", language="en", context_classification={"category": "friendship", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Friend", "result": result}, language="en")
        self.assertFalse(any(item.get("finding_type") == "unanswered_questions" for item in result["canonical_findings"]))
        self.assertFalse(result["advice"])
        self.assertIn("questions receive answers", rendered)
        self.assertNotIn("remain unfinished", rendered.casefold())

    def test_few_questions_in_efficient_work_chat_are_not_negative(self) -> None:
        result = local_fallback_analysis(messages=efficient_low_question_work_fixture(), events=[], period_label="14 days", chat_type="one_to_one", language="en", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        finding_types = {item.get("finding_type") for item in result["canonical_findings"]}
        self.assertIn("work_decision_completion", finding_types)
        self.assertNotIn("work_unanswered_questions", finding_types)
        self.assertGreaterEqual(result["overall_score"], 6.0)
        self.assertFalse(result["advice"])
        rendered = format_ai_result_overview({"chat_title": "Work", "result": result}, language="en")
        self.assertIn("decisions", rendered.casefold())
        self.assertNotIn("few direct-question", rendered.casefold())

    def test_balanced_superficial_chat_explains_balance_is_not_depth(self) -> None:
        result = local_fallback_analysis(messages=balanced_superficial_fixture(), events=[], period_label="30 days", chat_type="one_to_one", language="en", context_classification={"category": "friendship", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Friend", "result": result}, language="en")
        self.assertTrue(result["overall_score"] is None or result["overall_score"] < 8.0)
        self.assertIn("does not prove equal attention", rendered)
        self.assertNotIn("strong communication", rendered.casefold())

    def test_warm_one_sided_romantic_separates_warmth_from_reciprocity(self) -> None:
        result = local_fallback_analysis(messages=warm_one_sided_romantic_fixture(), events=[], period_label="30 days", chat_type="one_to_one", language="en", context_classification={"category": "romantic", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Romance", "result": result}, language="en")
        self.assertTrue(any(item.get("finding_type") == "possible_interest" for item in result["canonical_findings"]))
        self.assertIn("possible interest", rendered.casefold())
        self.assertIn("you write more often", rendered.casefold())
        for fragment in ("proves attraction", "definitely love", "secretly"):
            self.assertNotIn(fragment, rendered.casefold())

    def test_cross_chat_personalization_uses_aggregates_only(self) -> None:
        analyses = []
        for index in range(3):
            profile = build_personal_profile(messages=detailed_user_concise_other(), semantic_analysis={}, context_category="work", period_label=f"chat {index}", language="en")
            analyses.append({"context": {"category": "work"}, "personal_profile": profile})
        aggregate = build_cross_chat_profile(analyses, language="en", min_coverage=3)
        fingerprint = build_conversation_fingerprint(messages=detailed_user_concise_other(), canonical_findings=[], context_category="work", period_scope="30 days", cross_chat_profile=aggregate, language="en")
        self.assertEqual(aggregate["status"], "available")
        self.assertTrue(fingerprint["cross_chat_features"])
        serialized = str(fingerprint)
        self.assertIn("aggregates only", serialized)
        self.assertNotIn("chat 0", serialized)
        self.assertNotIn("Real Other", serialized)


class ProductUxV123SpecificityAndRegressionTests(unittest.TestCase):
    def test_specificity_validator_catches_generic_filler_and_improves_report(self) -> None:
        result = minimal_ai_result(
            evidence_findings=[
                {
                    "finding_id": "work_task_clarity_1",
                    "finding_type": "work_task_ambiguity",
                    "title": "Tasks are not fully specified",
                    "observation": "There are task mentions but few owner or deadline signals.",
                    "interpretation": "Task clarity is the supported work issue.",
                    "confidence": "medium",
                    "severity": "attention",
                    "semantic_source": "local_pattern",
                    "semantic_depth": "direct",
                    "evidence": [{"evidence_id": "ev1", "description": "work_task_without_clear_owner_or_deadline", "source": "local_pattern"}],
                    "period_scope": "30 days",
                    "context_scope": "work",
                }
            ],
            advice=[{"priority": 1, "title": "Clear communication is important", "explanation": "Try to express your thoughts openly.", "example": ""}],
        )
        validated = validate_ai_result(result, dimensions={}, message_count=80, coverage={"available_messages": 80, "sent_messages": 20, "partial": True}, context_classification={"category": "work", "confidence": "high", "source": "automatic"})
        rendered = format_ai_result_overview({"chat_title": "Work", "result": validated}, language="en")
        self.assertNotIn("Communication contains certain patterns", rendered)
        self.assertNotIn("Try to express your thoughts openly", rendered)
        self.assertIn("task", rendered.casefold())
        self.assertGreaterEqual(validated["specificity"]["distinctive_finding_count"], 1)

    def test_ai_input_contains_fingerprint_without_participant_identities(self) -> None:
        settings = Settings(
            api_id=None,
            api_hash=None,
            telegram_bot_token=None,
            allowed_user_ids=frozenset(),
            data_dir=Path("/tmp"),
            db_path=Path("/tmp/relchat-test.sqlite3"),
            session_path=Path("/tmp/relchat-test.session"),
            openai_api_key="test",
            ai_enabled=True,
            ai_model="test-model",
            ai_max_messages=20,
            ai_max_chars=4000,
        )
        bundle = build_ai_input_bundle(settings, chat={"chat_type": "one_to_one", "title": "Alice Bob"}, messages=detailed_user_concise_other(), events=[], period_label="30 days", language="en", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        self.assertIn("conversation_fingerprint", bundle.payload)
        serialized = str(bundle.payload)
        self.assertNotIn("Real Me", serialized)
        self.assertNotIn("Real Other", serialized)
        self.assertNotIn("user:", serialized)

    def test_real_work_report_regression_is_specific_and_concise(self) -> None:
        result = local_fallback_analysis(messages=large_regular_work_fixture(), events=[], period_label="Вся история", chat_type="one_to_one", language="ru", context_classification={"category": "work", "confidence": "high", "source": "user_confirmed"})
        rendered = format_ai_result_overview({"chat_title": "Рабочий чат", "result": result}, language="ru")
        self.assertGreater(result["overall_score"], 3.3)
        self.assertFalse(result["personalized_feedback"]["action_needed"])
        self.assertFalse(result["advice"])
        self.assertIn("Рабочее общение", rendered)
        self.assertIn("регуляр", rendered.casefold())
        self.assertIn("локальный", rendered.casefold())
        self.assertIn("Что отличает эту переписку", rendered)
        self.assertNotIn("очень слаб", rendered.casefold())
        self.assertNotIn("обе стороны участв", rendered.casefold())
        self.assertNotIn("кандидат", rendered.casefold())
        self.assertNotIn("агресс", rendered.casefold())
        self.assertNotIn("оскорб", rendered.casefold())
        self.assertLessEqual(rendered.count("Существенных изменений нет"), 1)
        for fragment in ("What is happening", "visible style", "medium"):
            self.assertNotIn(fragment, rendered)

    def test_template_similarity_fixtures_do_not_collapse_to_same_structure(self) -> None:
        fixtures = [
            ("Friend", "friendship", balanced_friendship_fixture()),
            ("Romance", "romantic", one_sided_romantic_fixture()),
            ("Work", "work", unclear_work_fixture()),
            ("Family", "family", supportive_family_fixture()),
            ("Playful", "friendship", playful_sarcasm_fixture()),
            ("Questions", "friendship", unanswered_questions_fixture()),
            ("Repair", "family", conflict_repair_fixture()),
            ("Superficial", "friendship", balanced_superficial_fixture()),
            ("Resumed", "friendship", long_silence_resumed_fixture()),
            ("ClearWork", "work", efficient_low_question_work_fixture()),
        ]
        structures = []
        rendered = []
        for title, context, messages in fixtures:
            result = local_fallback_analysis(messages=messages, events=[], period_label="30 days", chat_type="one_to_one", language="en", context_classification={"category": context, "confidence": "high", "source": "user_confirmed"})
            structures.append((result["individualized_story"]["headline"], tuple(item.get("semantic_key") for item in result.get("selected_patterns") or []), tuple(item.get("category") for item in result.get("advice") or [])))
            rendered.append(format_ai_result_overview({"chat_title": title, "result": result}, language="en"))
        self.assertGreaterEqual(len(set(structures)), 8)
        self.assertGreaterEqual(sum("work" in text.casefold() for text in rendered), 1)
        self.assertLess(shared_sentence_ratio(rendered), 0.35)

    def test_specificity_validator_allows_short_honest_low_evidence_report(self) -> None:
        result = local_fallback_analysis(messages=[msg(1, "ok"), msg(2, "ok", outgoing=False)], events=[], period_label="today", chat_type="one_to_one", language="en", context_classification={"category": "unknown", "confidence": "low", "source": "automatic"})
        specificity = validate_report_specificity(result, language="en")
        improved = improve_report_specificity(result, specificity=specificity, language="en")
        self.assertEqual(improved["specificity"]["evidence_depth"], "low")
        self.assertFalse(improved["advice"])
        self.assertIn("not enough", format_ai_result_overview({"chat_title": "Short", "result": improved}, language="en").casefold())


def detailed_user_concise_other() -> list[Message]:
    messages: list[Message] = []
    for index in range(30):
        messages.append(msg(index * 2 + 1, "I reviewed the task context, the release note, and the dependency. Can you confirm the owner and deadline?", outgoing=True, minutes=index * 20))
        messages.append(msg(index * 2 + 2, "ok", outgoing=False, minutes=index * 20 + 4))
    return messages


def rarely_initiates_but_deep_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(8):
        base = index * 24 * 60
        messages.append(msg(index * 3 + 1, "How are you doing this week?", outgoing=False, minutes=base))
        messages.append(
            msg(
                index * 3 + 2,
                "I am doing alright. Work was heavy, but I wanted to answer properly and ask how your trip went.",
                outgoing=True,
                minutes=base + 8,
            )
        )
        messages.append(msg(index * 3 + 3, "Glad to hear that.", outgoing=False, minutes=base + 15))
    return messages


def answered_questions_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(16):
        base = index * 50
        messages.append(msg(index * 2 + 1, "Can you tell me how your day went?", outgoing=True, minutes=base))
        messages.append(msg(index * 2 + 2, "Yes, it was busy but good. Thanks for asking.", outgoing=False, minutes=base + 6))
    return messages


def efficient_low_question_work_fixture() -> list[Message]:
    texts = [
        ("Task: send final file. Owner: me. Deadline today.", True),
        ("Confirmed and approved.", False),
        ("Done. Release note is ready.", True),
        ("That closes the task.", False),
        ("Next ticket: review invoice by Friday.", True),
        ("Approved. I will file it today.", False),
    ]
    messages = [msg(index + 1, text, outgoing=outgoing, minutes=index * 18) for index, (text, outgoing) in enumerate(texts * 5)]
    return messages


def balanced_superficial_fixture() -> list[Message]:
    return [msg(i + 1, "ok" if i % 2 == 0 else "yo", outgoing=i % 2 == 0, minutes=i * 10) for i in range(90)]


def warm_one_sided_romantic_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(12):
        base = index * 16 * 60
        messages.append(msg(index * 4 + 1, "I miss you. Do you want to meet just the two of us this week?", outgoing=True, minutes=base))
        messages.append(msg(index * 4 + 2, "That is sweet, maybe.", outgoing=False, minutes=base + 12))
        messages.append(msg(index * 4 + 3, "I liked talking yesterday and would enjoy dinner together.", outgoing=True, minutes=base + 20))
    return messages


def large_regular_work_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(4494):
        outgoing = index % 2 == 0
        if index >= 4425:
            text = "статус обновлен" if outgoing else "ок"
        elif index == 300:
            text = "ну конечно"
        elif index % 89 == 0:
            text = "можешь подтвердить?"
        elif outgoing:
            text = "рабочее обновление"
        else:
            text = "принято"
        messages.append(msg(index + 1, text, outgoing=outgoing, minutes=index * 90))
    return messages


def balanced_friendship_fixture() -> list[Message]:
    return [msg(i + 1, "How was your day?" if i % 5 == 0 else "That sounds fun", outgoing=i % 2 == 0, minutes=i * 30) for i in range(80)]


def one_sided_romantic_fixture() -> list[Message]:
    messages = []
    for i in range(60):
        outgoing = i % 3 != 2
        text = "Do you want to meet this week?" if outgoing else "maybe"
        messages.append(msg(i + 1, text, outgoing=outgoing, minutes=i * 60))
    return messages


def unclear_work_fixture() -> list[Message]:
    texts = [
        "task deploy review",
        "what exactly should I fix?",
        "can you clarify deadline?",
        "which owner?",
        "task ticket issue",
        "what is the expected result?",
    ]
    return [msg(i + 1, texts[i % len(texts)], outgoing=i % 2 == 0, minutes=i * 25) for i in range(90)]


def supportive_family_fixture() -> list[Message]:
    return [msg(i + 1, "Спасибо, помогу завтра" if i % 2 == 0 else "нужна помощь дома", outgoing=i % 2 == 0, minutes=i * 45) for i in range(70)]


def conflict_repair_fixture() -> list[Message]:
    texts = ["I am frustrated", "I hear you", "Let's fix this tomorrow", "Thanks for coming back to it"]
    return [msg(i + 1, texts[i % len(texts)], outgoing=i % 2 == 0, minutes=i * 40) for i in range(72)]


def playful_sarcasm_fixture() -> list[Message]:
    texts = [
        "Sure, great job /s haha",
        "lol yes, totally saved the day",
        "Just kidding, thanks for fixing it",
        "haha, all good",
    ]
    return [msg(i + 1, texts[i % len(texts)], outgoing=i % 2 == 0, minutes=i * 30) for i in range(64)]


def unanswered_questions_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(14):
        base = index * 72 * 60
        messages.append(msg(index * 2 + 1, "Can you answer this plan question?", outgoing=True, minutes=base))
        messages.append(msg(index * 2 + 2, "Let's talk later.", outgoing=True, minutes=base + 20))
    return messages


def long_silence_resumed_fixture() -> list[Message]:
    messages: list[Message] = []
    for index in range(9):
        base = index * 3 * 24 * 60
        messages.append(msg(index * 2 + 1, "I wanted to return to our plan after the pause.", outgoing=True, minutes=base))
        messages.append(msg(index * 2 + 2, "ok, let's continue", outgoing=False, minutes=base + 12))
    return messages


def shared_sentence_ratio(texts: list[str]) -> float:
    sentence_sets = []
    for text in texts:
        sentences = {" ".join(line.casefold().split()) for line in text.splitlines() if len(line.split()) >= 4}
        sentence_sets.append(sentences)
    shared = set.intersection(*sentence_sets) if sentence_sets else set()
    total = set.union(*sentence_sets) if sentence_sets else set()
    return len(shared) / max(1, len(total))


if __name__ == "__main__":
    unittest.main()
