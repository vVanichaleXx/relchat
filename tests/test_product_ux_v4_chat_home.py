from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from relchat.bot.formatters import format_chat_home, format_chat_home_loading
from relchat.bot.handlers.chat_home import CHAT_HOME_STATE, handle_chat_home_callback
from relchat.bot.keyboards import chat_home_details_menu_keyboard, chat_home_keyboard, primary_chat_home_actions, secondary_chat_home_actions, utility_chat_home_actions
from relchat.bot.services.chat_home_service import build_chat_home_view_model
from relchat.bot.ui_components import render_empty_state, render_field, render_status
from relchat.config import Settings
from relchat.core.models import Message
from relchat.database.repositories import create_reminder, create_report, ensure_user_profile, save_user_message, update_user_setting
from relchat.database.sqlite import connect, init_db


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
SECRET_TEXT = "secret appointment details"


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
        "title": "Anna",
        "display_title": "Anna",
        "username": "anna_secret_username",
        "is_favorite": False,
    }


def message(message_id: int, timestamp: str, *, text: str = "hello", sender_id: str = "me") -> Message:
    return Message(
        source="telegram",
        source_message_id=message_id,
        conversation_id=chat()["chat_id"],
        sender_id=sender_id,
        sender_name="Me" if sender_id == "me" else "Anna",
        timestamp=timestamp,
        text=text,
        message_type="text",
        is_outgoing=sender_id == "me",
    )


def messages() -> list[Message]:
    return [
        message(1, "2026-07-10T09:00:00+00:00", sender_id="me"),
        message(2, "2026-07-11T09:00:00+00:00", sender_id="other"),
        message(3, "2026-07-12T09:00:00+00:00", sender_id="me"),
        message(4, "2026-07-13T09:00:00+00:00", sender_id="other", text=SECRET_TEXT),
    ]


def report(*, count: int = 40, by_type: dict | None = None, unanswered: int = 0) -> dict:
    return {
        "report_id": "rep_current",
        "chat_title": "Anna",
        "period_id": "30d",
        "period_label": "30 days",
        "created_at": "2026-07-14T10:00:00+00:00",
        "imported_message_count": count,
        "modules": ["balance", "activity", "response_times", "followups"],
        "metrics_summary": {
            "message_count": count,
            "message_count_by_sender": {"Me": count // 2, "Anna": count - count // 2},
            "initiation_balance": {
                "session_count": 8,
                "by_sender": {"Me": 4, "Anna": 4},
                "share": {"Me": 0.5, "Anna": 0.5},
            },
            "response_times": {
                "Me": {"count": 4, "median_seconds": 900, "active_median_seconds": 600},
                "Anna": {"count": 4, "median_seconds": 1200, "active_median_seconds": 700},
            },
            "unanswered_questions": [{"message_id": index, "text": SECRET_TEXT} for index in range(unanswered)],
        },
        "event_summary": {"total_events": sum((by_type or {}).values()), "by_type": by_type or {}},
        "data_quality": {"completeness": "selected period imported", "confidence": "medium"},
    }


class ProductUxV4ChatHomeTest(unittest.IsolatedAsyncioTestCase):
    def test_private_chat_home_stable_dashboard(self) -> None:
        view = build_chat_home_view_model(
            chat=chat(),
            reports=[report(count=40), report(count=42)],
            messages=messages(),
            reminders=[],
            language="en",
            now=NOW,
        )
        rendered = format_chat_home(view, language="en")

        self.assertEqual(view["state"]["label"], "stable")
        self.assertIn("Anna", rendered)
        self.assertIn("Everything looks stable.", rendered)
        self.assertIn("Communication score", rendered)
        self.assertIn("Last analysis\nToday", rendered)
        self.assertIn("Follow-up\nNo follow-ups suggested yet.", rendered)
        self.assertNotIn(SECRET_TEXT, rendered)
        self.assertNotIn(chat()["chat_id"], rendered)
        self.assertNotIn("anna_secret_username", rendered)

    def test_attention_and_next_reminder_are_prominent(self) -> None:
        reminder = {
            "chat_id": chat()["chat_id"],
            "source": "telegram",
            "status": "confirmed",
            "event_type": "follow_up_candidate",
            "title": SECRET_TEXT,
            "reminder_time": "2026-07-15T09:00:00+00:00",
        }
        view = build_chat_home_view_model(
            chat=chat(),
            reports=[report(by_type={"follow_up_candidate": 1}, unanswered=1), report(count=40)],
            messages=messages(),
            reminders=[reminder],
            language="en",
            now=NOW,
        )
        rendered = format_chat_home(view, language="en")

        self.assertEqual(view["state"]["tone"], "attention")
        self.assertIn("A few items may need your attention.", rendered)
        self.assertIn("Follow-up\n3 follow-ups", rendered)
        self.assertNotIn(SECRET_TEXT, rendered)

    def test_group_and_channel_wording(self) -> None:
        group = format_chat_home(
            build_chat_home_view_model(
                chat=chat("group"),
                reports=[report(count=50), report(count=50)],
                messages=messages(),
                language="en",
                now=NOW,
            ),
            language="en",
        )
        channel = format_chat_home(
            build_chat_home_view_model(
                chat=chat("channel"),
                reports=[report(count=50), report(count=50)],
                messages=messages(),
                language="en",
                now=NOW,
            ),
            language="en",
        )

        self.assertIn("Activity score", group)
        self.assertNotIn("relationship", group.lower())
        self.assertIn("Activity score", channel)
        self.assertNotIn("Communication rhythm", channel)

    def test_no_report_state_and_keyboard(self) -> None:
        rendered = format_chat_home(
            build_chat_home_view_model(chat=chat(), reports=[], messages=[], reminders=[], language="en", now=NOW),
            language="en",
        )
        labels = [button.text for row in chat_home_keyboard(chat(), has_report=False, language="en").inline_keyboard for button in row]

        self.assertIn("No analysis yet.", rendered)
        self.assertIn("Run your first analysis", rendered)
        self.assertEqual(labels[0], "▶ Run analysis")
        self.assertIn("Details", labels)
        self.assertNotIn("Timeline", labels)
        self.assertNotIn("Chat settings", labels)

    def test_keyboard_callback_privacy_and_shape(self) -> None:
        keyboard = chat_home_keyboard(chat(), has_report=True, language="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        callbacks = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]

        self.assertEqual(labels[0], "▶ Update analysis")
        self.assertIn("Details", labels)
        self.assertNotIn("Reports", labels)
        self.assertNotIn("Response rhythm", labels)
        self.assertTrue(all(len(value) < 64 for value in callbacks))
        self.assertNotIn(chat()["chat_id"], "".join(callbacks))
        self.assertNotIn("Anna", "".join(callbacks))
        self.assertIn("rc:home:details", callbacks)

        details_labels = [button.text for row in chat_home_details_menu_keyboard(language="en").inline_keyboard for button in row]
        self.assertIn("Timeline", details_labels)
        self.assertIn("Activity", details_labels)
        self.assertIn("Reports", details_labels)
        self.assertIn("Chat settings", details_labels)

    def test_reusable_render_components(self) -> None:
        status = render_status(icon="🟠", title="Needs attention", explanation="No communication for 9 days.")
        field = render_field("Communication rhythm", "Very active", "Usually responds within hours.")
        empty = render_empty_state("No analysis yet.", "Run your first analysis to see communication insights.")

        self.assertIn("🟠 Needs attention", status)
        self.assertIn("No communication for 9 days.", status)
        self.assertIn("Communication rhythm\nVery active", field)
        self.assertIn("Usually responds within hours.", field)
        self.assertIn("No analysis yet.", empty)

    def test_loading_state(self) -> None:
        english = format_chat_home_loading(language="en")
        russian = format_chat_home_loading(language="ru")

        self.assertIn("Loading chat...", english)
        self.assertIn("Loading latest report", english)
        self.assertIn("Loading reminders", english)
        self.assertIn("Загружаю чат...", russian)
        self.assertNotIn("Loading chat...", russian)

    def test_action_group_helpers(self) -> None:
        primary = primary_chat_home_actions(has_report=True, running=False, language="en")
        secondary = secondary_chat_home_actions(language="en")
        utility = utility_chat_home_actions(language="en")

        self.assertEqual(primary[0][0].text, "▶ Update analysis")
        self.assertEqual([button.text for button in secondary[0]], ["Timeline", "Activity"])
        self.assertEqual([button.text for button in secondary[1]], ["Insights", "Follow-ups"])
        self.assertIn("Delete Local Data", [button.text for row in utility for button in row])

    def test_russian_localization(self) -> None:
        rendered = format_chat_home(
            build_chat_home_view_model(
                chat=chat(),
                reports=[report(count=40), report(count=40)],
                messages=messages(),
                language="ru",
                now=NOW,
            ),
            language="ru",
        )

        self.assertIn("Все выглядит стабильно.", rendered)
        self.assertIn("Общая оценка", rendered)
        self.assertIn("Сегодня", rendered)
        self.assertNotIn("Everything looks stable", rendered)

    async def test_handler_renders_v4_chat_home_from_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
                update_user_setting(conn, 100, "language", "en")
                for item in messages():
                    save_user_message(conn, 100, item)
                create_report(
                    conn,
                    bot_user_id=100,
                    job_id=None,
                    source="telegram",
                    chat_id=chat()["chat_id"],
                    chat_title="Anna",
                    period_id="30d",
                    period_label="30 days",
                    period_start="2026-06-14T00:00:00+00:00",
                    period_end="2026-07-14T00:00:00+00:00",
                    imported_message_count=40,
                    modules=["activity"],
                    job_status="completed",
                    metrics_summary=report()["metrics_summary"],
                    event_summary={},
                    data_quality={"confidence": "medium"},
                )
                create_reminder(
                    conn,
                    bot_user_id=100,
                    chat_id=chat()["chat_id"],
                    chat_title="Anna",
                    event_type="follow_up_candidate",
                    title=SECRET_TEXT,
                    reminder_time="2026-07-15T09:00:00+00:00",
                    status="confirmed",
                )
            context = fake_context(settings_for(db_path))
            context.user_data[CHAT_HOME_STATE] = chat()
            update = fake_update("rc:home:open")

            handled = await handle_chat_home_callback(update, context, ["rc", "home", "open"])

        self.assertTrue(handled)
        self.assertIn("Anna", update.callback_query.edited_text)
        self.assertIn("Communication score", update.callback_query.edited_text)
        self.assertIn("1 follow-ups", update.callback_query.edited_text)
        self.assertNotIn(SECRET_TEXT, update.callback_query.edited_text)


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
