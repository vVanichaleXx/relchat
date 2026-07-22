from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from relchat.bot.formatters import format_chat_home, format_chat_home_section, format_chat_overview, format_chat_overview_details
from relchat.bot.handlers.chat_home import CHAT_HOME_STATE, handle_chat_home_callback
from relchat.bot.handlers.navigation import handle_navigation_callback
from relchat.bot.keyboards import chat_home_keyboard, main_keyboard
from relchat.bot.localization import t
from relchat.bot.state import ANALYSIS_FLOW, AWAITING_TEXT
from relchat.config import Settings
from relchat.database.repositories import create_report, ensure_user_profile, update_user_setting
from relchat.database.sqlite import connect, init_db


def settings_for(db_path: Path) -> Settings:
    return Settings(
        api_id=1,
        api_hash="hash",
        telegram_bot_token="token",
        allowed_user_ids=frozenset({100}),
        data_dir=db_path.parent,
        db_path=db_path,
        session_path=db_path.parent / "telegram.session",
    )


def chat(chat_type: str = "one_to_one") -> dict:
    return {
        "source": "telegram",
        "chat_id": "telegram-chat-id-should-not-be-in-callbacks",
        "chat_type": chat_type,
        "title": "Alice",
        "display_title": "Alice",
        "is_favorite": False,
    }


def report(modules: list[str] | None = None) -> dict:
    return {
        "report_id": "rep_test",
        "chat_title": "Alice",
        "period_label": "30 days",
        "created_at": "2026-07-14T10:00:00+00:00",
        "imported_message_count": 42,
        "modules": modules if modules is not None else ["balance", "activity", "response_times", "followups"],
        "metrics_summary": {
            "message_count": 42,
            "message_count_by_sender": {"Alice": 21, "Bob": 21},
            "unanswered_questions": [{"message_id": 1}],
        },
        "event_summary": {"total_events": 1, "by_type": {"follow_up_candidate": 1}},
        "data_quality": {"completeness": "selected period imported", "confidence": "medium"},
    }


def overview_report(
    *,
    message_count: int = 80,
    initiation: dict | None = None,
    sender_counts: dict | None = None,
    unanswered: int = 0,
    by_type: dict | None = None,
    secret_text: str | None = None,
) -> dict:
    return {
        "report_id": "rep_overview",
        "chat_title": "Alice",
        "period_id": "30d",
        "period_label": "30 days",
        "created_at": "2026-07-14T10:00:00+00:00",
        "imported_message_count": message_count,
        "modules": ["balance", "activity", "response_times", "questions", "plans", "followups", "reminders"],
        "metrics_summary": {
            "message_count": message_count,
            "message_count_by_sender": sender_counts or {"Alice": message_count // 2, "Bob": message_count - message_count // 2},
            "initiation_balance": initiation or {
                "session_count": 10,
                "by_sender": {"Alice": 5, "Bob": 5},
                "share": {"Alice": 0.5, "Bob": 0.5},
            },
            "response_times": {
                "Alice": {
                    "count": 12,
                    "median_seconds": 900,
                    "median_readable": "15m",
                    "active_count": 10,
                    "active_median_seconds": 600,
                    "active_median_readable": "10m",
                },
                "Bob": {
                    "count": 12,
                    "median_seconds": 1200,
                    "median_readable": "20m",
                    "active_count": 10,
                    "active_median_seconds": 700,
                    "active_median_readable": "11.7m",
                },
            },
            "average_message_length": {
                "Alice": {"avg_chars": 24, "message_count": 40},
                "Bob": {"avg_chars": 22, "message_count": 40},
            },
            "unanswered_questions": [
                {"message_id": index, "timestamp": "2026-07-14T10:00:00+00:00", "text": secret_text or ""}
                for index in range(unanswered)
            ],
        },
        "event_summary": {
            "total_events": sum((by_type or {}).values()),
            "by_type": by_type or {},
        },
        "data_quality": {
            "range_start": "2026-06-14T10:00:00+00:00",
            "range_end": "2026-07-14T10:00:00+00:00",
            "completeness": "selected period imported",
            "confidence": "medium",
        },
    }


class ProductUxV3NavigationTest(unittest.IsolatedAsyncioTestCase):
    def test_main_menu_is_private_first_and_localized(self) -> None:
        english = main_keyboard("en")
        russian = main_keyboard("ru")

        english_labels = [button.text for row in english.inline_keyboard for button in row]
        russian_labels = [button.text for row in russian.inline_keyboard for button in row]

        self.assertIn("👤 Private chats", english_labels)
        self.assertIn("⭐ Favorites", english_labels)
        self.assertIn("🕘 Recent", english_labels)
        self.assertIn("🔍 Find chat", english_labels)
        self.assertIn("⚙️ Settings", english_labels)
        self.assertNotIn("Reports", english_labels)
        self.assertNotIn("Help", english_labels)
        self.assertIn("👤 Личные чаты", russian_labels)
        self.assertIn("⭐ Избранные", russian_labels)

    def test_private_group_channel_chat_home_variants(self) -> None:
        private_text = format_chat_home(chat("one_to_one"), report=report(), pending_followups=2, running=False, language="en")
        group_text = format_chat_home(chat("group"), report=report(), pending_followups=0, running=False, language="en")
        channel_text = format_chat_home(chat("channel"), report=report(), pending_followups=0, running=False, language="en")

        self.assertIn("Person", private_text)
        self.assertIn("Communication score", private_text)
        self.assertIn("2 follow-ups", private_text)
        self.assertIn("Group", group_text)
        self.assertIn("Activity score", group_text)
        self.assertIn("Channel", channel_text)
        self.assertIn("Activity score", channel_text)

        channel_buttons = [button.text for row in chat_home_keyboard(chat("channel"), has_report=True).inline_keyboard for button in row]
        self.assertNotIn("Response rhythm", channel_buttons)

    def test_chat_home_missing_report_and_unavailable_modules(self) -> None:
        missing = format_chat_home(chat(), report=None, pending_followups=0, running=False, language="en")
        not_included = format_chat_home_section("activity", chat=chat(), report=report(modules=["balance"]), language="en")
        coming_soon = format_chat_home_section("habits", chat=chat(), report=report(), language="en")

        self.assertIn("No analysis yet", missing)
        self.assertIn("Run your first analysis", missing)
        self.assertIn("Not included in this report", not_included)
        self.assertIn("Coming soon", coming_soon)

    def test_chat_home_russian_localization(self) -> None:
        rendered = format_chat_home(chat(), report=report(), pending_followups=1, running=False, language="ru")

        self.assertIn("Человек", rendered)
        self.assertIn("Есть несколько пунктов", rendered)
        self.assertIn("Оценка общения", rendered)
        self.assertNotIn("Communication score", rendered)

    def test_overview_balanced_conversation(self) -> None:
        rendered = format_chat_overview(overview_report(), chat=chat(), language="en")

        self.assertIn("Both people contributed", rendered)
        self.assertIn("Current snapshot", rendered)
        self.assertIn("Response rhythm", rendered)

    def test_overview_one_sided_initiation(self) -> None:
        rendered = format_chat_overview(
            overview_report(
                initiation={
                    "session_count": 10,
                    "by_sender": {"Alice": 8, "Bob": 2},
                    "share": {"Alice": 0.8, "Bob": 0.2},
                }
            ),
            chat=chat(),
            language="en",
        )

        self.assertIn("one participant starts most sessions", rendered)
        self.assertIn("Session starts", rendered)

    def test_overview_empty_and_limited_sample(self) -> None:
        empty = format_chat_overview(overview_report(message_count=0, sender_counts={}), chat=chat(), language="en")
        limited = format_chat_overview(overview_report(message_count=8, sender_counts={"Alice": 5, "Bob": 3}), chat=chat(), language="en")

        self.assertIn("no analyzed messages", empty)
        self.assertIn("sample is limited", limited)

    def test_overview_missing_comparison_period(self) -> None:
        rendered = format_chat_overview(overview_report(), previous_report=None, chat=chat(), language="en")

        self.assertIn("No comparable previous period", rendered)

    def test_overview_unanswered_followups_and_details(self) -> None:
        rendered = format_chat_overview(
            overview_report(unanswered=2, by_type={"plan_candidate": 1, "promise_candidate": 1, "follow_up_candidate": 2}),
            chat=chat(),
            confirmed_reminders=1,
            language="en",
        )
        details = format_chat_overview_details(
            overview_report(unanswered=2, by_type={"long_silence": 1}),
            chat=chat(),
            confirmed_reminders=1,
            language="en",
        )

        self.assertIn("Unanswered questions: 2", rendered)
        self.assertIn("Plans to review: 1", rendered)
        self.assertIn("Promises and follow-ups: 3", rendered)
        self.assertIn("Confirmed reminders: 1", rendered)
        self.assertIn("Average message length", details)
        self.assertIn("Quiet periods: 1", details)

    def test_overview_does_not_render_raw_message_text(self) -> None:
        secret = "private appointment details"
        rendered = format_chat_overview(overview_report(unanswered=1, secret_text=secret), chat=chat(), language="en")
        details = format_chat_overview_details(overview_report(unanswered=1, secret_text=secret), chat=chat(), language="en")

        self.assertNotIn(secret, rendered)
        self.assertNotIn(secret, details)

    def test_overview_english_russian_and_chat_type_wording(self) -> None:
        english_group = format_chat_overview(overview_report(), chat=chat("group"), language="en")
        english_channel = format_chat_overview(overview_report(), chat=chat("channel"), language="en")
        russian = format_chat_overview(overview_report(), chat=chat(), language="ru")

        self.assertIn("group was active", english_group)
        self.assertIn("channel overview focuses", english_channel)
        self.assertIn("Текущий обзор", russian)
        self.assertNotIn("Current snapshot", russian)

    def test_chat_home_callback_data_stays_short_and_private(self) -> None:
        keyboard = chat_home_keyboard(chat(), has_report=True, language="en")
        callback_data = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]

        self.assertTrue(all(len(value) < 64 for value in callback_data))
        self.assertNotIn("telegram-chat-id-should-not-be-in-callbacks", "".join(callback_data))
        self.assertNotIn("Alice", "".join(callback_data))

    async def test_cancel_clears_temporary_wizard_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
            context = fake_context(settings_for(db_path))
            context.user_data[ANALYSIS_FLOW] = {"chat_id": "secret"}
            context.user_data[AWAITING_TEXT] = "custom_start"

            await handle_navigation_callback(fake_update("rc:cancel"), context, ["rc", "cancel"])

        self.assertNotIn(ANALYSIS_FLOW, context.user_data)
        self.assertIsNone(context.user_data.get(AWAITING_TEXT))

    async def test_stale_chat_home_callback_fails_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
            update = fake_update("rc:home:sec:activity")
            context = fake_context(settings_for(db_path))

            handled = await handle_chat_home_callback(update, context, ["rc", "home", "sec", "activity"])

        self.assertTrue(handled)
        self.assertIn("out of date", update.callback_query.edited_text)
        self.assertIsNotNone(update.callback_query.edited_markup)

    async def test_back_navigation_returns_to_parent_saved_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
                update_user_setting(conn, 100, "language", "en")
            update = fake_update("rc:home:back")
            context = fake_context(settings_for(db_path))
            context.user_data[CHAT_HOME_STATE] = chat()
            context.user_data["chat_home_parent"] = {"kind": "my_chats", "section": "saved"}

            handled = await handle_chat_home_callback(update, context, ["rc", "home", "back"])

        self.assertTrue(handled)
        self.assertIn("Saved chats", update.callback_query.edited_text)


def fake_context(settings: Settings):
    return SimpleNamespace(application=SimpleNamespace(bot_data={"settings": settings}), user_data={})


def fake_update(callback_data: str):
    query = FakeQuery(callback_data)
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=100),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=FakeMessage(),
    )


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = SimpleNamespace(chat_id=1, message_id=2)
        self.edited_text = ""
        self.edited_markup = None

    async def answer(self) -> None:
        return None

    async def edit_message_text(self, text: str, reply_markup=None) -> None:
        self.edited_text = text
        self.edited_markup = reply_markup


class FakeMessage:
    async def reply_text(self, text: str, **kwargs) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
