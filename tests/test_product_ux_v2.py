from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relchat.bot.formatters import chunk_text, format_report_overview, format_report_section
from relchat.bot.keyboards import chat_list_keyboard
from relchat.bot.services import chat_browser
from relchat.bot.services.analysis_jobs import run_analysis_job
from relchat.bot.state import (
    RUNNABLE_MODULE_IDS,
    iso_date,
    normalize_module_selection,
    parse_user_date,
    period_start,
)
from relchat.config import Settings
from relchat.core.models import ConversationEvent, ConversationRef, Message
from relchat.database.repositories import (
    clear_reminders,
    clear_reports,
    create_analysis_job,
    create_reminder,
    create_report,
    dashboard_counts,
    delete_all_user_data,
    delete_imported_messages_for_chat,
    get_analysis_job,
    get_report,
    get_user_profile,
    get_user_settings,
    ensure_user_profile,
    list_messages,
    list_reminders,
    list_reports,
    list_user_chats,
    local_storage_summary,
    mark_stale_running_jobs_failed,
    save_user_chat,
    save_user_message,
    set_onboarding_completed,
    set_report_favorite,
    set_user_chat_favorite,
    update_reminder_status,
    update_reminder_time,
    update_user_setting,
)
from relchat.database.sqlite import connect, init_db


def settings_for(db_path: Path) -> Settings:
    return Settings(
        api_id=1,
        api_hash="hash",
        telegram_bot_token="token",
        allowed_user_ids=frozenset({100, 200}),
        data_dir=db_path.parent,
        db_path=db_path,
        session_path=db_path.parent / "telegram.session",
    )


def conversation(chat_id: str, title: str = "Alice", chat_type: str = "one_to_one") -> ConversationRef:
    return ConversationRef(
        source="telegram",
        conversation_id=chat_id,
        conversation_type=chat_type,
        title=title,
        username=title.lower(),
        last_message_at="2026-07-13T10:00:00+00:00",
    )


def message(message_id: int, text: str = "hello", sender: str = "a", minute: int | None = None) -> Message:
    minute = message_id if minute is None else minute
    return Message(
        source="telegram",
        source_message_id=message_id,
        conversation_id="chat-1",
        sender_id=sender,
        sender_name=f"Sender {sender}",
        timestamp=f"2026-07-13T10:{minute:02d}:00+00:00",
        text=text,
        message_type="text",
    )


class ProductDatabaseTest(unittest.TestCase):
    def test_clean_init_and_repeated_migrations_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            init_db(db_path)

            with connect(db_path) as conn:
                tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                indexes = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}

        self.assertIn("bot_user_profiles", tables)
        self.assertIn("user_settings", tables)
        self.assertIn("user_chats", tables)
        self.assertIn("analysis_jobs", tables)
        self.assertIn("reports", tables)
        self.assertIn("reminders", tables)
        self.assertIn("message_owners", tables)
        self.assertIn("idx_reports_user_chat", indexes)
        self.assertIn("idx_message_owners_user_chat", indexes)

    def test_migrates_legacy_schema_without_source_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.sqlite3"
            with connect(db_path) as conn:
                conn.execute("CREATE TABLE chats(chat_id TEXT PRIMARY KEY, chat_type TEXT NOT NULL, chat_title TEXT)")
                conn.execute(
                    """
                    CREATE TABLE messages(
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      message_id INTEGER NOT NULL,
                      chat_id TEXT NOT NULL,
                      sender_id TEXT,
                      sender_name TEXT,
                      timestamp TEXT NOT NULL,
                      text TEXT,
                      message_type TEXT NOT NULL,
                      is_outgoing INTEGER NOT NULL
                    )
                    """
                )

            init_db(db_path)

            with connect(db_path) as conn:
                chat_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chats)")}
                message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}

        self.assertIn("source", chat_columns)
        self.assertIn("source", message_columns)

    def test_profiles_settings_onboarding_and_language_persist_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                self.assertFalse(ensure_user_profile(conn, 100)["onboarding_completed"])
                set_onboarding_completed(conn, 100, True)
                update_user_setting(conn, 100, "language", "ru")
                update_user_setting(conn, 100, "default_period", "90d")

            with connect(db_path) as restarted:
                self.assertTrue(get_user_profile(restarted, 100)["onboarding_completed"])
                self.assertEqual(get_user_settings(restarted, 100)["language"], "ru")
                self.assertEqual(get_user_settings(restarted, 100)["default_period"], "90d")
                self.assertEqual(
                    restarted.execute("SELECT COUNT(*) AS count FROM bot_user_profiles WHERE bot_user_id = 100").fetchone()["count"],
                    1,
                )

    def test_repository_data_is_separated_by_bot_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                save_user_chat(conn, 100, conversation("chat-1"), saved=True)
                save_user_chat(conn, 200, conversation("chat-1"), saved=True)
                save_user_message(conn, 100, message(1, "private user 100"))
                save_user_message(conn, 200, message(1, "private user 100"))
                delete_imported_messages_for_chat(conn, "telegram", "chat-1", bot_user_id=100)

                self.assertEqual(len(list_user_chats(conn, 100, section="saved")), 1)
                self.assertEqual(len(list_user_chats(conn, 200, section="saved")), 1)
                self.assertEqual(len(list_messages(conn, "chat-1")), 1)

                delete_all_user_data(conn, 200)
                self.assertEqual(list_user_chats(conn, 200), [])
                self.assertEqual(list_messages(conn, "chat-1"), [])

    def test_reports_reminders_settings_and_storage_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                report = create_report(
                    conn,
                    bot_user_id=100,
                    job_id=None,
                    source="telegram",
                    chat_id="chat-1",
                    chat_title="Alice",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    imported_message_count=2,
                    modules=["balance"],
                    job_status="completed",
                    metrics_summary={"message_count": 2, "unanswered_questions": []},
                    event_summary={"total_events": 0, "by_type": {}},
                    data_quality={"completeness": "selected period imported", "confidence": "medium"},
                )
                set_report_favorite(conn, report["report_id"], True)
                reminder = create_reminder(conn, bot_user_id=100, title="Review meeting", status="suggested")
                update_reminder_status(conn, reminder["reminder_id"], 100, "confirmed")
                update_reminder_time(conn, reminder["reminder_id"], 100, "2026-07-13")
                update_user_setting(conn, 100, "progress_notifications", False)
                update_user_setting(conn, 100, "show_technical_details", True)
                update_user_setting(conn, 100, "data_retention_days", 30)

                self.assertEqual(len(list_reports(conn, 100, favorites=True)), 1)
                self.assertEqual(list_reminders(conn, 100, status="confirmed")[0]["reminder_time"], "2026-07-13")
                self.assertFalse(get_user_settings(conn, 100)["progress_notifications"])
                self.assertTrue(get_user_settings(conn, 100)["show_technical_details"])
                self.assertEqual(get_user_settings(conn, 100)["data_retention_days"], 30)
                self.assertEqual(local_storage_summary(conn, 100)["reports"], 1)
                self.assertEqual(clear_reminders(conn, 100), 1)
                self.assertEqual(clear_reports(conn, 100), 1)

    def test_stale_running_jobs_are_marked_failed_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                job = create_analysis_job(
                    conn,
                    bot_user_id=100,
                    source="telegram",
                    chat_id="chat-1",
                    chat_title="Alice",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    modules=["balance"],
                )
                self.assertEqual(mark_stale_running_jobs_failed(conn), 1)
                updated = get_analysis_job(conn, job["job_id"])

        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["error_message"], "stale_after_restart")


class ProductStateAndReportTest(unittest.TestCase):
    def test_chat_browser_filters_search_pagination_and_callback_privacy(self) -> None:
        conversations = [
            conversation("secret-chat-id", "Alice", "one_to_one"),
            conversation("group-1", "Project", "group"),
            conversation("channel-1", "News", "channel"),
        ]
        filtered = chat_browser.filter_conversations(
            conversations,
            "favorites",
            favorite_ids={"secret-chat-id"},
            recent_ids={"group-1"},
        )
        self.assertEqual([item.conversation_id for item in filtered], ["secret-chat-id"])
        self.assertEqual([item.conversation_id for item in chat_browser.search_conversations(conversations, "@alice")], ["secret-chat-id"])
        self.assertEqual(len(chat_browser.paginate_conversations(conversations * 4, 0).items), 10)

        keyboard = chat_list_keyboard(conversations, page=0, page_size=10, has_previous=False, has_next=False)
        callback_blob = "".join(button.callback_data or "" for row in keyboard.inline_keyboard for button in row)
        self.assertLess(max(len(button.callback_data or "") for row in keyboard.inline_keyboard for button in row), 64)
        self.assertNotIn("secret-chat-id", callback_blob)
        self.assertNotIn("private message", callback_blob)

    def test_period_date_and_module_selection(self) -> None:
        parsed_iso = parse_user_date("2026-07-01")
        parsed_ru = parse_user_date("01.07.2026")
        parsed_days = parse_user_date("7 days")

        self.assertEqual(iso_date(parsed_iso), "2026-07-01")
        self.assertEqual(iso_date(parsed_ru), "2026-07-01")
        self.assertIsNotNone(parsed_days)
        self.assertIsNone(parse_user_date("not a date"))
        self.assertIsNotNone(period_start("7d"))
        self.assertNotIn("topics", normalize_module_selection(["balance", "topics"]))
        self.assertEqual(set(normalize_module_selection([])), set(RUNNABLE_MODULE_IDS))

    def test_report_sections_do_not_render_raw_message_text_and_chunk_safely(self) -> None:
        report = {
            "report_id": "rep_1",
            "chat_title": "Alice",
            "period_label": "30 days",
            "imported_message_count": 2,
            "modules": RUNNABLE_MODULE_IDS,
            "metrics_summary": {
                "message_count": 2,
                "message_count_by_sender": {"Alice": 1, "Bob": 1},
                "initiation_balance": {"session_count": 1, "by_sender": {"Alice": 1}},
                "response_times": {"Bob": {"count": 1, "median_readable": "5m", "active_median_readable": "5m"}},
                "average_message_length": {"Alice": {"avg_chars": 4, "message_count": 1}},
                "unanswered_questions": [{"message_id": 1, "timestamp": "2026-07-13", "sender": "Alice"}],
            },
            "event_summary": {"total_events": 1, "by_type": {"follow_up_candidate": 1}},
            "data_quality": {"completeness": "selected period imported", "confidence": "medium"},
        }
        secret = "private appointment details"
        overview = format_report_overview(report)
        section = format_report_section(report, "questions")

        self.assertNotIn(secret, overview)
        self.assertNotIn(secret, section)
        self.assertTrue(all(len(chunk) <= 3800 for chunk in chunk_text(overview * 200)))


class BackgroundJobTest(unittest.IsolatedAsyncioTestCase):
    async def test_background_job_completes_with_fake_importer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            settings = settings_for(db_path)
            init_db(db_path)
            with connect(db_path) as conn:
                save_user_chat(conn, 100, conversation("chat-1"), saved=True)
                job = create_analysis_job(
                    conn,
                    bot_user_id=100,
                    source="telegram",
                    chat_id="chat-1",
                    chat_title="Alice",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    modules=["balance", "reminders"],
                )

            async def fake_get_conversation(_settings, _chat_id):
                return conversation("chat-1")

            async def fake_iter_messages(_settings, _chat_id, *, limit, since):
                yield message(1, "remind me about the meeting?", "a", 1)
                yield message(2, "ok", "b", 2)

            app = SimpleNamespace(bot_data={"settings": settings}, bot=FakeBot())
            with patch("relchat.bot.services.analysis_jobs.get_conversation", fake_get_conversation), patch(
                "relchat.bot.services.analysis_jobs.iter_messages", fake_iter_messages
            ):
                await run_analysis_job(app, settings, job["job_id"])

            with connect(db_path) as conn:
                updated = get_analysis_job(conn, job["job_id"])
                reports = list_reports(conn, 100)
                reminders = list_reminders(conn, 100)
                stored = conn.execute("SELECT metrics_summary FROM reports").fetchone()["metrics_summary"]

        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["imported_message_count"], 2)
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(reminders), 1)
        self.assertNotIn("remind me about the meeting", stored)

    async def test_background_job_cancel_keeps_imported_messages_without_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            settings = settings_for(db_path)
            init_db(db_path)
            with connect(db_path) as conn:
                save_user_chat(conn, 100, conversation("chat-1"), saved=True)
                job = create_analysis_job(
                    conn,
                    bot_user_id=100,
                    source="telegram",
                    chat_id="chat-1",
                    chat_title="Alice",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    modules=["balance"],
                )

            app = SimpleNamespace(bot_data={"settings": settings}, bot=FakeBot())

            async def fake_get_conversation(_settings, _chat_id):
                return conversation("chat-1")

            async def fake_iter_messages(_settings, _chat_id, *, limit, since):
                yield message(1, "first", "a", 1)
                app.bot_data.setdefault("relchat_cancelled_jobs", set()).add(job["job_id"])
                yield message(2, "second", "b", 2)

            with patch("relchat.bot.services.analysis_jobs.get_conversation", fake_get_conversation), patch(
                "relchat.bot.services.analysis_jobs.iter_messages", fake_iter_messages
            ):
                await run_analysis_job(app, settings, job["job_id"])

            with connect(db_path) as conn:
                updated = get_analysis_job(conn, job["job_id"])
                reports = list_reports(conn, 100)
                messages = list_messages(conn, "chat-1")

        self.assertEqual(updated["status"], "cancelled")
        self.assertEqual(len(reports), 0)
        self.assertEqual(len(messages), 1)

    async def test_background_job_no_messages_fails_without_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            settings = settings_for(db_path)
            init_db(db_path)
            with connect(db_path) as conn:
                save_user_chat(conn, 100, conversation("chat-1"), saved=True)
                job = create_analysis_job(
                    conn,
                    bot_user_id=100,
                    source="telegram",
                    chat_id="chat-1",
                    chat_title="Alice",
                    period_id="30d",
                    period_label="30 days",
                    period_start=None,
                    period_end=None,
                    modules=["balance"],
                )

            async def fake_get_conversation(_settings, _chat_id):
                return conversation("chat-1")

            async def fake_iter_messages(_settings, _chat_id, *, limit, since):
                if False:
                    yield message(1)

            app = SimpleNamespace(bot_data={"settings": settings}, bot=FakeBot())
            with patch("relchat.bot.services.analysis_jobs.get_conversation", fake_get_conversation), patch(
                "relchat.bot.services.analysis_jobs.iter_messages", fake_iter_messages
            ):
                await run_analysis_job(app, settings, job["job_id"])

            with connect(db_path) as conn:
                updated = get_analysis_job(conn, job["job_id"])
                reports = list_reports(conn, 100)

        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["error_message"], "no_messages")
        self.assertEqual(len(reports), 0)


class FakeBot:
    def __init__(self) -> None:
        self.edits: list[dict] = []

    async def edit_message_text(self, **kwargs) -> None:
        self.edits.append(kwargs)


if __name__ == "__main__":
    unittest.main()
