from __future__ import annotations

import unittest
from pathlib import Path

from relchat.analytics.metrics import summarize
from relchat.bot.formatters import chunk_text, format_metrics, sanitize_label
from relchat.bot.security import BotSecurityError, validate_bot_startup
from relchat.config import Settings, parse_allowed_user_ids
from relchat.core.models import Message


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


if __name__ == "__main__":
    unittest.main()
