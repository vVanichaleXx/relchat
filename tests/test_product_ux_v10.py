from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from relchat.bot.keyboards import important_chat_list_keyboard, automation_suggestion_keyboard
from relchat.bot.localization import t
from relchat.bot.services.ai_analysis import (
    AIAnalysisError,
    build_deterministic_dimensions,
    local_fallback_analysis,
    validate_ai_result,
)
from relchat.bot.services.automation import evaluate_pause_candidate
from relchat.bot.services.period_comparison import (
    compare_current_vs_previous_session,
    compare_last_days,
    compare_report_to_previous,
    format_period_comparison_compact,
)
from relchat.config import Settings
from relchat.core.models import ConversationRef, Message
from relchat.database.repositories import (
    get_automation_state,
    get_important_chat_settings,
    get_user_settings,
    list_important_chats,
    save_user_chat,
    set_chat_important,
    update_important_chat_setting,
    update_user_setting,
    upsert_automation_state,
)
from relchat.database.sqlite import connect, init_db
from relchat.events.extractor import extract_events


def settings_for(db_path: Path) -> Settings:
    return Settings(
        api_id=1,
        api_hash="hash",
        telegram_bot_token="123456:token",
        allowed_user_ids=frozenset({100, 200}),
        data_dir=db_path.parent,
        db_path=db_path,
        session_path=db_path.parent / "telegram.session",
    )


def msg(message_id: int, day: int, sender: str, text: str, *, outgoing: bool) -> Message:
    return Message(
        source="telegram",
        source_message_id=message_id,
        conversation_id="chat-1",
        sender_id=sender,
        sender_name="You" if outgoing else "Other",
        timestamp=f"2026-07-{day:02d}T10:{message_id % 60:02d}:00+00:00",
        text=text,
        message_type="text",
        is_outgoing=outgoing,
    )


def alternating_messages(start_id: int, day: int, count: int, *, outgoing_first: bool = True) -> list[Message]:
    rows = []
    for index in range(count):
        outgoing = (index % 2 == 0) if outgoing_first else (index % 2 == 1)
        rows.append(msg(start_id + index, day, "100" if outgoing else "200", f"message {start_id + index}", outgoing=outgoing))
    return rows


def one_sided_messages(count: int = 18) -> list[Message]:
    rows = []
    for index in range(1, count + 1):
        outgoing = index > 3
        text = "Can you answer this?" if index in {count - 5, count - 3, count - 1} else f"visible {index}"
        rows.append(msg(index, 15, "100" if outgoing else "200", text, outgoing=outgoing))
    return rows


def model_result(**overrides) -> dict:
    result = {
        "summary": "The conversation was uneven. You carried most of the initiative.",
        "verdict": {
            "level": "weak",
            "headline": "The visible communication was weak.",
            "explanation": "One side carried most of the dialogue and several questions were not answered.",
        },
        "conversation_state": "active_uneven",
        "confidence": "medium",
        "direct_findings": [
            {"finding": "Several direct questions received no meaningful answer.", "severity": "high", "confidence": "medium", "evidence_type": "reply_pattern"}
        ],
        "participant_analysis": {
            "you": {"summary": "YOU asked direct questions.", "observable_patterns": ["carried initiative"], "strengths": [], "possible_improvements": ["reduce repeated follow-ups"]},
            "other": {"summary": "OTHER mostly reacted.", "observable_patterns": ["short replies"], "strengths": [], "possible_improvements": ["answer direct questions clearly"]},
        },
        "positive_patterns": [],
        "problem_patterns": [{"title": "Uneven initiative", "explanation": "One side started most sessions.", "severity": "medium", "evidence_type": "metric"}],
        "weak_reply_patterns": [{"category": "ignored_question", "explanation": "A direct question received no visible answer.", "severity": "medium", "anonymous_message_reference": "m2"}],
        "uncertainties": ["The reason cannot be determined from messages alone."],
        "recommended_action": {"action": "reduce_pressure", "explanation": "Do not send several new messages before reciprocal initiative appears."},
        "advice": [{"priority": 1, "title": "Wait for initiative", "explanation": "Do not add pressure.", "example": ""}],
        "limitations": ["Used only visible messages."],
    }
    result.update(overrides)
    return result


def strong_dimensions() -> dict:
    return {
        "reciprocity": {"score": 9, "confidence": "high", "evidence_count": 40, "explanation": "balanced", "available": True},
        "initiative_balance": {"score": 9, "confidence": "high", "evidence_count": 8, "explanation": "balanced", "available": True},
        "reply_quality": {"score": 8, "confidence": "high", "evidence_count": 20, "explanation": "answers", "available": True},
        "topic_continuation": {"score": 8, "confidence": "high", "evidence_count": 10, "explanation": "continues", "available": True},
        "respectfulness": {"score": 9, "confidence": "high", "evidence_count": 40, "explanation": "respectful", "available": True},
        "question_engagement": {"score": 8, "confidence": "high", "evidence_count": 8, "explanation": "answers", "available": True},
        "planning_cooperation": {"score": 8, "confidence": "medium", "evidence_count": 4, "explanation": "plans", "available": True},
        "pressure_risk": {"score": 0, "confidence": "high", "evidence_count": 0, "explanation": "low", "available": True, "risk": True},
        "hostility": {"score": 0, "confidence": "high", "evidence_count": 0, "explanation": "low", "available": True, "risk": True},
        "dismissiveness": {"score": 0, "confidence": "high", "evidence_count": 0, "explanation": "low", "available": True, "risk": True},
        "unanswered_question_rate": {"score": 0, "confidence": "high", "evidence_count": 0, "explanation": "low", "available": True, "risk": True},
        "sarcasm_intensity": {"score": 0, "confidence": "high", "evidence_count": 0, "explanation": "low", "available": True, "risk": True},
    }


def report(report_id: str, start: str, end: str, count: int, *, unanswered: int = 0, score: float = 6.0, other_starts: int = 3, avg_other: float = 80) -> dict:
    return {
        "report_id": report_id,
        "bot_user_id": 100,
        "source": "telegram",
        "chat_id": "chat-1",
        "chat_title": "Anna",
        "period_id": "7d",
        "period_label": "7 days",
        "period_start": start,
        "period_end": end,
        "imported_message_count": count,
        "modules": ["balance"],
        "metrics_summary": {
            "message_count": count,
            "message_count_by_sender": {"You": count // 2, "Other": count - count // 2},
            "initiation_balance": {"session_count": 6, "by_sender": {"You": 6 - other_starts, "Other": other_starts}},
            "response_times": {"Other": {"count": 5, "median_seconds": 600}, "You": {"count": 5, "median_seconds": 600}},
            "average_message_length": {"You": {"avg_chars": 90}, "Other": {"avg_chars": avg_other}},
            "unanswered_questions": [{"message_id": i} for i in range(unanswered)],
            "question_count": max(unanswered, 6),
            "dimensions": {
                **strong_dimensions(),
                "communication_score": {"score": score},
            },
            "communication_score": score,
        },
        "event_summary": {"by_type": {"follow_up_candidate": unanswered}},
        "data_quality": {"range_start": start, "range_end": end, "confidence": "medium", "completeness": "selected period imported"},
    }


class HonestAnalysisV10Test(unittest.TestCase):
    def test_honest_schema_direct_language_and_forbidden_softening(self) -> None:
        result = validate_ai_result(model_result(), dimensions=strong_dimensions(), message_count=40)
        blob = json.dumps(result).casefold()

        self.assertEqual(result["verdict"]["level"], "weak")
        self.assertIn("Several direct questions", result["direct_findings"][0]["finding"])
        self.assertNotIn("do not worry", blob)
        self.assertNotIn("may just be busy", blob)

        for unsafe in [
            "They may just be busy.",
            "Do not worry.",
            "They hate you.",
            "This person is a narcissist.",
            "Garbage reply from a loser.",
        ]:
            with self.assertRaises(AIAnalysisError):
                validate_ai_result(model_result(summary=unsafe), dimensions=strong_dimensions(), message_count=40)

    def test_local_fallback_is_direct_for_weak_strong_and_insufficient_data(self) -> None:
        weak = local_fallback_analysis(messages=one_sided_messages(), events=extract_events(one_sided_messages()), period_label="7 days", chat_type="one_to_one")
        strong = validate_ai_result(model_result(verdict={"level": "strong", "headline": "The visible communication was strong.", "explanation": "The data supports a positive communication conclusion."}), dimensions=strong_dimensions(), message_count=40)
        insufficient = local_fallback_analysis(messages=one_sided_messages(4), events=[], period_label="7 days", chat_type="one_to_one")

        self.assertIn(weak["verdict"]["level"], {"weak", "very_weak"})
        self.assertIn("received no visible response", json.dumps(weak))
        self.assertEqual(strong["verdict"]["level"], "strong")
        self.assertEqual(insufficient["verdict"]["level"], "insufficient_data")
        self.assertNotIn("wonderful in its own way", json.dumps(weak).casefold())


class PeriodComparisonV10Test(unittest.TestCase):
    def test_sessions_7_day_30_day_report_and_rendering(self) -> None:
        previous = alternating_messages(1, 1, 14)
        current = alternating_messages(30, 2, 14, outgoing_first=False)
        shifted = []
        for item in current:
            shifted.append(
                Message(**{**item.__dict__, "timestamp": item.timestamp.replace("T10", "T23")})
            )
        comparison = compare_current_vs_previous_session(previous + shifted)

        self.assertEqual(comparison["status"], "ok")
        self.assertLessEqual(len(comparison["main_changes"]), 5)

        timeline = alternating_messages(100, 1, 12) + alternating_messages(200, 10, 12) + alternating_messages(300, 20, 12)
        self.assertIn(compare_last_days(timeline, days=7, now=datetime(2026, 7, 22, tzinfo=timezone.utc))["status"], {"ok", "insufficient_data"})
        self.assertIn(compare_last_days(timeline, days=30, now=datetime(2026, 7, 31, tzinfo=timezone.utc))["status"], {"ok", "insufficient_data"})

        current_report = report("rep_current", "2026-07-08T00:00:00+00:00", "2026-07-15T00:00:00+00:00", 40, unanswered=4, score=4.2, other_starts=1, avg_other=35)
        previous_report = report("rep_previous", "2026-07-01T00:00:00+00:00", "2026-07-08T00:00:00+00:00", 35, unanswered=1, score=6.8, other_starts=3, avg_other=90)
        report_comparison = compare_report_to_previous(current_report, [previous_report])
        rendered_en = format_period_comparison_compact(report_comparison, language="en")
        rendered_ru = format_period_comparison_compact(report_comparison, language="ru")

        self.assertEqual(report_comparison["status"], "ok")
        self.assertEqual(report_comparison["overall_direction"], "worsened")
        self.assertTrue(any(row["metric"] == "message_count" and row["direction"] == "unknown" for row in report_comparison["metrics"]))
        self.assertIn("Compared with the previous period", rendered_en)
        self.assertIn("По сравнению с предыдущим периодом", rendered_ru)
        self.assertIn("Больше вопросов осталось без ответа", rendered_ru)

    def test_comparable_period_rules_reject_weak_data_and_duration_mismatch(self) -> None:
        too_small = compare_report_to_previous(
            report("current", "2026-07-08T00:00:00+00:00", "2026-07-15T00:00:00+00:00", 9),
            [report("previous", "2026-07-01T00:00:00+00:00", "2026-07-08T00:00:00+00:00", 30)],
        )
        mismatch = compare_report_to_previous(
            report("current", "2026-07-14T00:00:00+00:00", "2026-07-15T00:00:00+00:00", 30),
            [report("previous", "2026-06-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00", 30)],
        )

        self.assertEqual(too_small["status"], "insufficient_data")
        self.assertEqual(mismatch["reason"], "duration_mismatch")
        self.assertIn("Недостаточно сопоставимых данных", format_period_comparison_compact(too_small, language="ru"))


class ImportantChatsV10Test(unittest.TestCase):
    def test_important_chat_settings_defaults_isolation_persistence_and_callbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            chat = ConversationRef("telegram", "raw-chat-id-123", "one_to_one", "Anna")
            with connect(db_path) as conn:
                save_user_chat(conn, 100, chat, saved=True)
                save_user_chat(conn, 200, chat, saved=True)
                defaults = get_important_chat_settings(conn, 100, "telegram", "raw-chat-id-123")
                self.assertFalse(defaults["is_important"])
                self.assertFalse(defaults["automatic_analysis_enabled"])

                set_chat_important(conn, 100, "telegram", "raw-chat-id-123", True)
                update_important_chat_setting(conn, 100, "telegram", "raw-chat-id-123", "automatic_analysis_enabled", True)
                update_important_chat_setting(conn, 100, "telegram", "raw-chat-id-123", "minimum_new_messages", 20)
                update_user_setting(conn, 100, "automatic_analysis_master_enabled", True)

            with connect(db_path) as conn:
                own = get_important_chat_settings(conn, 100, "telegram", "raw-chat-id-123")
                other = get_important_chat_settings(conn, 200, "telegram", "raw-chat-id-123")
                listed = list_important_chats(conn, 100)
                master = get_user_settings(conn, 100)["automatic_analysis_master_enabled"]

            keyboard = important_chat_list_keyboard(listed, language="en")
            callbacks = "".join(button.callback_data or "" for row in keyboard.inline_keyboard for button in row)
            suggestion_callbacks = "".join(button.callback_data or "" for row in automation_suggestion_keyboard("not_123", language="en").inline_keyboard for button in row)

        self.assertTrue(own["is_important"])
        self.assertTrue(own["automatic_analysis_enabled"])
        self.assertEqual(own["minimum_new_messages"], 20)
        self.assertFalse(other["is_important"])
        self.assertTrue(master)
        self.assertNotIn("raw-chat-id-123", callbacks)
        self.assertNotIn("raw-chat-id-123", suggestion_callbacks)


class AutomaticAnalysisV10Test(unittest.TestCase):
    def base_settings(self, **overrides) -> tuple[dict, dict, dict]:
        chat_settings = {
            "is_important": True,
            "automatic_analysis_enabled": True,
            "automatic_notification_enabled": True,
            "minimum_new_messages": 10,
            "inactivity_threshold_minutes": 45,
            "cooldown_hours": 12,
            "quiet_hours_enabled": False,
            "quiet_hours_start": "23:00",
            "quiet_hours_end": "08:00",
            "automatic_delivery_mode": "suggest",
        }
        chat_settings.update(overrides)
        user_settings = {"automatic_analysis_master_enabled": True}
        state = {"observed_message_cursor": 0, "last_automatic_message_id": 0}
        return chat_settings, user_settings, state

    def test_pause_heuristic_thresholds_cooldown_quiet_hours_and_switches(self) -> None:
        now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
        messages = [msg(i, 16, "100" if i % 2 else "200", f"m{i}", outgoing=bool(i % 2)) for i in range(1, 13)]
        messages = [Message(**{**item.__dict__, "timestamp": "2026-07-16T10:00:00+00:00"}) for item in messages]
        chat_settings, user_settings, state = self.base_settings()

        detected = evaluate_pause_candidate(chat_settings=chat_settings, user_settings=user_settings, state=state, messages=messages, now=now, max_daily_notifications=5, notifications_today=0)
        self.assertEqual(detected.action, "suggest")
        self.assertEqual(detected.reason, "pause_detected")

        below = evaluate_pause_candidate(chat_settings={**chat_settings, "minimum_new_messages": 20}, user_settings=user_settings, state=state, messages=messages, now=now, max_daily_notifications=5, notifications_today=0)
        active = evaluate_pause_candidate(chat_settings=chat_settings, user_settings=user_settings, state=state, messages=[Message(**{**item.__dict__, "timestamp": "2026-07-16T11:45:00+00:00"}) for item in messages], now=now, max_daily_notifications=5, notifications_today=0)
        master_off = evaluate_pause_candidate(chat_settings=chat_settings, user_settings={"automatic_analysis_master_enabled": False}, state=state, messages=messages, now=now, max_daily_notifications=5, notifications_today=0)
        chat_off = evaluate_pause_candidate(chat_settings={**chat_settings, "automatic_analysis_enabled": False}, user_settings=user_settings, state=state, messages=messages, now=now, max_daily_notifications=5, notifications_today=0)
        daily_cap = evaluate_pause_candidate(chat_settings=chat_settings, user_settings=user_settings, state=state, messages=messages, now=now, max_daily_notifications=5, notifications_today=5)
        quiet = evaluate_pause_candidate(chat_settings={**chat_settings, "quiet_hours_enabled": True, "quiet_hours_start": "11:00", "quiet_hours_end": "13:00"}, user_settings=user_settings, state=state, messages=messages, now=now, max_daily_notifications=5, notifications_today=0)
        paused = evaluate_pause_candidate(chat_settings={**chat_settings, "automation_paused_until": "2026-07-17T12:00:00+00:00"}, user_settings=user_settings, state=state, messages=messages, now=now, max_daily_notifications=5, notifications_today=0)

        self.assertEqual(below.reason, "below_threshold")
        self.assertEqual(active.reason, "inactivity_not_reached")
        self.assertEqual(master_off.reason, "master_disabled")
        self.assertEqual(chat_off.reason, "chat_disabled")
        self.assertEqual(daily_cap.reason, "daily_cap")
        self.assertEqual(quiet.action, "delay")
        self.assertEqual(paused.reason, "paused")

    def test_restart_state_restores_cursor_without_duplicate_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                upsert_automation_state(conn, 100, "telegram", "chat-1", observed_message_cursor=42, last_automatic_message_id=40)
            with connect(db_path) as conn:
                state = get_automation_state(conn, 100, "telegram", "chat-1")

        self.assertEqual(state["observed_message_cursor"], 42)
        self.assertEqual(state["last_automatic_message_id"], 40)


if __name__ == "__main__":
    unittest.main()
