from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relchat.analytics.metrics import summarize
from relchat.bot.formatters import chunk_text, format_combined_report, format_metrics, sanitize_label
from relchat.bot.guided import (
    PAGE_SIZE,
    build_confirmation_state,
    filter_conversations,
    paginate_conversations,
    parse_callback,
    period_option,
    period_since,
    search_conversations,
)
from relchat.bot.handlers import register_handlers
from relchat.bot.keyboards import chat_list_keyboard
from relchat.bot.services.chat_browser import filter_conversations as filter_browser_conversations
from relchat.bot.security import BotSecurityError, validate_bot_startup
from relchat.bot.security import is_allowed_update
from relchat.config import Settings, parse_allowed_user_ids
from relchat.core.models import ConversationEvent, ConversationRef, Message
from relchat.telegram.importer import (
    dialog_matches_filter,
    filter_dialogs_by_dialog_filter,
    list_conversations,
    normalize_dialog_folders,
)


def settings(*, bot_token: str | None = "token", allowed_user_ids: frozenset[int] = frozenset({123})) -> Settings:
    return Settings(
        api_id=1,
        api_hash="hash",
        telegram_bot_token=bot_token,
        allowed_user_ids=allowed_user_ids,
        data_dir=Path("data"),
        db_path=Path("data/relchat.sqlite3"),
        session_path=Path("data/telegram.session"),
    )


def message(message_id: int, sender: str, text: str) -> Message:
    return Message(
        source="test",
        source_message_id=message_id,
        conversation_id="chat-1",
        sender_id=sender,
        sender_name=f"Sender {sender}",
        timestamp=f"2026-01-01T10:0{message_id}:00+00:00",
        text=text,
        message_type="text",
    )


def conversation(
    conversation_id: str,
    conversation_type: str,
    title: str,
    *,
    username: str | None = None,
    unread_count: int = 0,
    folder_id: int | None = None,
    last_message_at: str | None = None,
) -> ConversationRef:
    return ConversationRef(
        source="telegram",
        conversation_id=conversation_id,
        conversation_type=conversation_type,
        title=title,
        username=username,
        unread_count=unread_count,
        folder_id=folder_id,
        last_message_at=last_message_at,
    )


def fake_user_dialog(dialog_id: int, *, contact: bool = False, bot: bool = False, unread_count: int = 0):
    return SimpleNamespace(
        id=dialog_id,
        name=f"User {dialog_id}",
        message=SimpleNamespace(date=None),
        entity=SimpleNamespace(id=dialog_id, first_name=f"User {dialog_id}", contact=contact, bot=bot),
        is_user=True,
        is_group=False,
        is_channel=False,
        unread_count=unread_count,
        folder_id=None,
    )


def fake_group_dialog(dialog_id: int, *, archived: bool = False):
    return SimpleNamespace(
        id=dialog_id,
        name=f"Group {dialog_id}",
        message=SimpleNamespace(date=None),
        entity=SimpleNamespace(id=dialog_id, title=f"Group {dialog_id}", megagroup=True, participants_count=3),
        is_user=False,
        is_group=True,
        is_channel=False,
        unread_count=0,
        folder_id=1 if archived else None,
    )


def fake_channel_dialog(dialog_id: int):
    return SimpleNamespace(
        id=dialog_id,
        name=f"Channel {dialog_id}",
        message=SimpleNamespace(date=None),
        entity=SimpleNamespace(id=dialog_id, title=f"Channel {dialog_id}", broadcast=True),
        is_user=False,
        is_group=False,
        is_channel=True,
        unread_count=0,
        folder_id=None,
    )


def fake_filter(**overrides):
    values = {
        "id": 2,
        "title": "Личные",
        "contacts": False,
        "non_contacts": False,
        "groups": False,
        "broadcasts": False,
        "bots": False,
        "include_peers": [],
        "exclude_peers": [],
        "pinned_peers": [],
        "exclude_muted": False,
        "exclude_read": False,
        "exclude_archived": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeTelegramClient:
    def __init__(self, dialogs):
        self.dialogs = dialogs
        self.iter_calls = []
        self.started = False
        self.disconnected = False

    async def start(self):
        self.started = True

    async def disconnect(self):
        self.disconnected = True

    def iter_dialogs(self, **kwargs):
        self.iter_calls.append(kwargs)

        async def iterator():
            for dialog in self.dialogs:
                yield dialog

        return iterator()


class BotInterfaceTest(unittest.TestCase):
    def test_allowed_user_ids_are_required_for_startup(self) -> None:
        with self.assertRaises(BotSecurityError):
            validate_bot_startup(settings(allowed_user_ids=frozenset()))

    def test_bot_token_is_required_for_startup(self) -> None:
        with self.assertRaises(BotSecurityError):
            validate_bot_startup(settings(bot_token=None))

    def test_allowed_user_id_parser_accepts_commas_and_spaces(self) -> None:
        self.assertEqual(parse_allowed_user_ids("123, 456 789"), frozenset({123, 456, 789}))

    def test_allowed_user_id_parser_rejects_non_numeric_values(self) -> None:
        with self.assertRaises(SystemExit):
            parse_allowed_user_ids("123,abc")

    def test_formatter_redacts_phone_like_labels(self) -> None:
        self.assertEqual(sanitize_label("+1 415 555 0101"), "[redacted phone]")

    def test_metrics_formatter_does_not_render_message_text(self) -> None:
        secret_text = "private appointment details?"
        messages = [
            message(1, "a", secret_text),
            message(2, "b", "reply"),
        ]
        rendered = format_metrics(summarize(messages, "chat-1"))

        self.assertNotIn(secret_text, rendered)
        self.assertIn("Messages imported: 2", rendered)

    def test_long_messages_are_split_under_telegram_limit(self) -> None:
        chunks = chunk_text("a" * 5000, limit=1000)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))

    def test_guided_category_filtering(self) -> None:
        conversations = [
            conversation("1", "one_to_one", "Alice", unread_count=1),
            conversation("2", "group", "Project"),
            conversation("3", "channel", "Announcements", folder_id=7),
        ]

        self.assertEqual([item.conversation_id for item in filter_conversations(conversations, "private")], ["1"])
        self.assertEqual([item.conversation_id for item in filter_conversations(conversations, "groups")], ["2"])
        self.assertEqual([item.conversation_id for item in filter_conversations(conversations, "channels")], ["3"])
        self.assertEqual([item.conversation_id for item in filter_conversations(conversations, "unread")], ["1"])
        self.assertEqual([item.conversation_id for item in filter_conversations(conversations, "folder:7")], ["3"])

    def test_chat_browser_private_category_uses_complete_dialog_list(self) -> None:
        conversations = [
            conversation("1", "one_to_one", "Alice"),
            conversation("2", "group", "Project", folder_id=7),
            conversation("3", "one_to_one", "Bob", folder_id=99),
            conversation("4", "channel", "Announcements"),
        ]

        private_ids = [item.conversation_id for item in filter_browser_conversations(conversations, "private")]

        self.assertEqual(private_ids, ["1", "3"])

    def test_telegram_personal_folder_matches_dialog_filter_rules(self) -> None:
        dialogs = [
            fake_user_dialog(1, contact=True),
            fake_user_dialog(2, contact=False),
            fake_user_dialog(3, bot=True),
            fake_group_dialog(4),
            fake_channel_dialog(5),
        ]
        personal_filter = fake_filter(contacts=True, non_contacts=True)

        filtered = filter_dialogs_by_dialog_filter(dialogs, personal_filter)

        self.assertEqual([dialog.id for dialog in filtered], [1, 2])

    def test_telegram_custom_folder_includes_and_excludes_explicit_peers(self) -> None:
        dialogs = [
            fake_user_dialog(1, contact=True),
            fake_user_dialog(2, contact=False),
            fake_group_dialog(30),
            fake_group_dialog(40, archived=True),
        ]
        custom_filter = fake_filter(
            include_peers=[SimpleNamespace(user_id=2)],
            pinned_peers=[SimpleNamespace(chat_id=30), SimpleNamespace(chat_id=40)],
            exclude_peers=[SimpleNamespace(user_id=1)],
            exclude_archived=True,
        )

        filtered = filter_dialogs_by_dialog_filter(dialogs, custom_filter)

        self.assertEqual([dialog.id for dialog in filtered], [2, 30])

    def test_telegram_dialog_filter_flags_are_distinct_from_chat_type_categories(self) -> None:
        personal_filter = fake_filter(contacts=True, non_contacts=True, groups=False, broadcasts=False, bots=False)

        self.assertTrue(dialog_matches_filter(fake_user_dialog(1, contact=True), personal_filter))
        self.assertTrue(dialog_matches_filter(fake_user_dialog(2, contact=False), personal_filter))
        self.assertFalse(dialog_matches_filter(fake_user_dialog(3, bot=True), personal_filter))
        self.assertFalse(dialog_matches_filter(fake_group_dialog(4), personal_filter))
        self.assertFalse(dialog_matches_filter(fake_channel_dialog(5), personal_filter))

    def test_guided_chat_buttons_select_by_state_index_not_chat_id(self) -> None:
        conversations = [
            conversation("-100123456789", "one_to_one", "Alice"),
            conversation("-100987654321", "group", "Project"),
            conversation("42", "channel", "Announcements"),
        ]

        keyboard = chat_list_keyboard(
            conversations,
            page=0,
            page_size=PAGE_SIZE,
            has_previous=False,
            has_next=False,
        )
        callback_data = [row[0].callback_data for row in keyboard.inline_keyboard[:3]]

        self.assertEqual(callback_data, ["rc:browse:select:0", "rc:browse:select:1", "rc:browse:select:2"])
        self.assertNotIn("-100123456789", "".join(callback_data))
        self.assertIn("Person Alice", keyboard.inline_keyboard[0][0].text)
        self.assertIn("Group Project", keyboard.inline_keyboard[1][0].text)
        self.assertIn("Channel Announcements", keyboard.inline_keyboard[2][0].text)

    def test_guided_pagination_limits_to_ten_chats(self) -> None:
        conversations = [conversation(str(index), "group", f"Chat {index}") for index in range(11)]

        first_page = paginate_conversations(conversations, 0)
        second_page = paginate_conversations(conversations, 1)

        self.assertEqual(len(first_page.items), 10)
        self.assertTrue(first_page.has_next)
        self.assertFalse(first_page.has_previous)
        self.assertEqual(len(second_page.items), 1)
        self.assertTrue(second_page.has_previous)

    def test_guided_search_uses_dialog_metadata_only(self) -> None:
        conversations = [
            conversation("1", "one_to_one", "Alice Cooper", username="alice"),
            conversation("2", "group", "Project"),
        ]

        self.assertEqual([item.conversation_id for item in search_conversations(conversations, "ali")], ["1"])
        self.assertEqual([item.conversation_id for item in search_conversations(conversations, "@alice")], ["1"])
        self.assertEqual(search_conversations(conversations, "message contents"), [])

    def test_guided_telegram_folder_normalization(self) -> None:
        folders = normalize_dialog_folders(
            [
                SimpleNamespace(id=2, title=SimpleNamespace(text="Work")),
                SimpleNamespace(id=2, title="Duplicate"),
                SimpleNamespace(id=None, title="Default"),
            ]
        )

        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0].folder_id, 2)
        self.assertEqual(folders[0].title, "Work")

    def test_guided_callback_routing(self) -> None:
        self.assertEqual(parse_callback("rc:main:analyze").action, "main")
        self.assertEqual(parse_callback("rc:cat:groups").value, "groups")
        self.assertEqual(parse_callback("rc:select:4").action, "select")
        self.assertEqual(parse_callback("rc:period:90d").value, "90d")
        self.assertEqual(parse_callback("unknown").action, "unknown")

    def test_guided_period_selection_maps_to_safe_settings(self) -> None:
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        ninety_days = period_option("90d")
        full_history = period_option("full")

        self.assertIsNotNone(ninety_days)
        self.assertEqual(period_since(ninety_days, now=now), datetime(2026, 4, 14, tzinfo=timezone.utc))
        self.assertIsNotNone(full_history)
        self.assertIsNone(period_since(full_history, now=now))
        self.assertIn("may take time", full_history.warning)

    def test_guided_confirmation_state_keeps_selected_chat_in_state(self) -> None:
        selected = conversation("chat-123", "group", "Project")
        option = period_option("30d")

        state = build_confirmation_state(selected, option)

        self.assertEqual(state["guided_selected_chat_id"], "chat-123")
        self.assertEqual(state["guided_selected_period_label"], "Last 30 days")

    def test_allowed_user_security_rejects_unknown_user(self) -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(id=999))

        self.assertFalse(is_allowed_update(update, settings()))

    def test_combined_report_formatting_does_not_render_message_text(self) -> None:
        secret_text = "private appointment details?"
        messages = [message(1, "a", secret_text), message(2, "b", "reply")]
        metrics = summarize(messages, "chat-1")
        events = [
            ConversationEvent(
                source="test",
                conversation_id="chat-1",
                event_type="question",
                timestamp="2026-01-01T10:01:00+00:00",
                source_message_id=1,
            )
        ]

        rendered = format_combined_report(
            chat_id="chat-1",
            chat_title="Alice",
            period_label="Last 30 days",
            count=2,
            range_start=None,
            range_end=None,
            metrics_summary=metrics,
            messages=messages,
            events=events,
        )

        self.assertIn("RelChat analysis complete", rendered)
        self.assertIn("Metrics summary", rendered)
        self.assertIn("Event Engine v0 summary", rendered)
        self.assertNotIn(secret_text, rendered)

    def test_bot_handler_registration_includes_guided_flow_handlers(self) -> None:
        app = SimpleNamespace(handlers=[])
        app.add_handler = app.handlers.append

        register_handlers(app)
        handler_names = [handler.__class__.__name__ for handler in app.handlers]

        self.assertIn("CallbackQueryHandler", handler_names)
        self.assertIn("MessageHandler", handler_names)
        self.assertGreaterEqual(handler_names.count("CommandHandler"), 7)


class TelegramFolderLoadingTest(unittest.IsolatedAsyncioTestCase):
    async def test_custom_dialog_filter_does_not_use_iter_dialogs_folder_argument(self) -> None:
        client = FakeTelegramClient([fake_user_dialog(1, contact=True), fake_group_dialog(2)])

        async def fake_load_dialog_filter_items(_client):
            return [fake_filter(id=9, contacts=True)]

        with (
            patch("relchat.telegram.importer.make_client", return_value=client),
            patch("relchat.telegram.importer.load_dialog_filter_items", fake_load_dialog_filter_items),
        ):
            conversations = await list_conversations(settings(), limit=None, folder_id=9)

        self.assertEqual([item.conversation_id for item in conversations], ["1"])
        self.assertEqual(client.iter_calls, [{"limit": None}])
        self.assertTrue(client.started)
        self.assertTrue(client.disconnected)


if __name__ == "__main__":
    unittest.main()
