from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relchat.bot.formatters import format_unified_analysis_result
from relchat.bot.handlers.analysis import handle_browse_callback, load_chat_browser
from relchat.bot.keyboards import analysis_result_keyboard
from relchat.bot.services.chat_browser import filter_folder_conversations, load_cached_browser_state
from relchat.config import Settings
from relchat.core.models import ConversationRef, DialogFolder
from relchat.database.repositories import save_dialog_cache
from relchat.database.sqlite import connect, init_db
from relchat.telegram.importer import dialog_folder_memberships


def settings_for(db_path: Path) -> Settings:
    return Settings(
        api_id=1,
        api_hash="hash",
        telegram_bot_token="token",
        allowed_user_ids=frozenset({100}),
        data_dir=db_path.parent,
        db_path=db_path,
        session_path=db_path.parent / "missing.session",
    )


def conversation(chat_id: str, title: str, chat_type: str = "one_to_one", *, folder_id: int | None = None) -> ConversationRef:
    return ConversationRef(
        source="telegram",
        conversation_id=chat_id,
        conversation_type=chat_type,
        title=title,
        username=title.lower(),
        folder_id=folder_id,
        last_message_at="2026-07-15T10:00:00+00:00",
        unread_count=1 if chat_id == "chat-1" else 0,
    )


def report() -> dict:
    return {
        "report_id": "rep_v8",
        "chat_title": "Anna",
        "period_label": "30 days",
        "imported_message_count": 42,
        "metrics_summary": {
            "message_count": 42,
            "message_count_by_sender": {"You": 20, "Other person": 22},
            "initiation_balance": {"session_count": 6, "by_sender": {"You": 3, "Other person": 3}},
            "response_times": {
                "You": {"count": 5, "median_seconds": 600, "active_median_seconds": 420},
                "Other person": {"count": 4, "median_seconds": 900, "active_median_seconds": 600},
            },
            "unanswered_questions": [{"message_id": 1, "text": "private secret text"}],
        },
        "event_summary": {"by_type": {"follow_up_candidate": 1}},
        "data_quality": {"confidence": "medium", "completeness": "selected period imported"},
    }


class ProductUxV8Test(unittest.IsolatedAsyncioTestCase):
    def test_dialog_cache_roundtrip_and_folder_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                save_dialog_cache(
                    conn,
                    100,
                    conversations=[conversation("chat-1", "Anna"), conversation("group-1", "Work", "group")],
                    folders=[DialogFolder(folder_id=20, title="Личные")],
                    folder_memberships={20: {"chat-1"}},
                )
            state = load_cached_browser_state(settings_for(db_path), 100)

        self.assertEqual([item.conversation_id for item in state["conversations"]], ["chat-1", "group-1"])
        self.assertEqual(state["folders"][0].title, "Личные")
        self.assertEqual(state["folder_memberships"][20], {"chat-1"})
        self.assertEqual([item.conversation_id for item in filter_folder_conversations(state["conversations"], 20, state["folder_memberships"])], ["chat-1"])

    async def test_chat_browser_uses_sqlite_cache_without_telegram_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                save_dialog_cache(
                    conn,
                    100,
                    conversations=[conversation("chat-1", "Anna"), conversation("group-1", "Work", "group")],
                    folders=[DialogFolder(folder_id=20, title="Личные")],
                    folder_memberships={20: {"chat-1"}},
                )
            context = fake_context(settings_for(db_path))
            update = fake_update("rc:nav:analyze")

            with patch("relchat.bot.handlers.analysis.refresh_dialog_cache", side_effect=AssertionError("network fetch should not run")):
                await load_chat_browser(update, context)

            self.assertIn("Choose", update.callback_query.edited_text)
            self.assertEqual(len(context.user_data["chat_browser"]["conversations"]), 2)

            await handle_browse_callback(update, context, ["rc", "browse", "folder", "20"])

        self.assertIn("Личные", update.callback_query.edited_text)
        self.assertIn("1-1", update.callback_query.edited_text)

    def test_dialog_filter_memberships_are_computed_without_iter_dialogs_folder(self) -> None:
        dialogs = [
            SimpleNamespace(id=1, is_user=True, is_group=False, is_channel=False, entity=SimpleNamespace(id=1, contact=True, bot=False)),
            SimpleNamespace(id=2, is_user=False, is_group=True, is_channel=False, entity=SimpleNamespace(id=2, megagroup=True)),
        ]
        folder = SimpleNamespace(id=7, contacts=True, non_contacts=False, groups=False, broadcasts=False, bots=False, include_peers=[], pinned_peers=[], exclude_peers=[])

        memberships = dialog_folder_memberships(dialogs, [folder])

        self.assertEqual(memberships[7], {"1"})

    def test_unified_result_is_complete_and_uses_three_buttons(self) -> None:
        rendered = format_unified_analysis_result(report(), language="en", chat_type="one_to_one")
        keyboard = analysis_result_keyboard("rep_v8", language="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        callbacks = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Analysis complete", rendered)
        self.assertIn("What stands out", rendered)
        self.assertIn("Needs attention", rendered)
        self.assertIn("Data quality", rendered)
        self.assertNotIn("private secret text", rendered)
        self.assertEqual(labels, ["Full analysis", "Advice", "Chat Home"])
        self.assertLessEqual(len(labels), 3)
        self.assertTrue(all(len(value) < 64 for value in callbacks))


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


if __name__ == "__main__":
    unittest.main()
