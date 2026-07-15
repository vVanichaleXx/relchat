from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relchat.bot.handlers.common import reply_chunks
from relchat.bot.services.ux_audit import (
    clear_current_audit_settings,
    error_payload,
    format_ux_audit_report,
    incoming_text_payload,
    keyboard_payload,
    load_ux_audit_events,
    outgoing_payload,
    record_ux_event,
    set_current_audit_settings,
)
from relchat.config import Settings, get_settings


def audit_settings(path: Path, *, include_user_text: bool = False, max_events: int = 1000) -> Settings:
    return Settings(
        api_id=1,
        api_hash="hash",
        telegram_bot_token="token",
        allowed_user_ids=frozenset({100}),
        data_dir=path.parent,
        db_path=path.parent / "relchat.sqlite3",
        session_path=path.parent / "telegram.session",
        ux_audit_enabled=True,
        ux_audit_max_events=max_events,
        ux_audit_include_user_text=include_user_text,
        ux_audit_path=path,
    )


def fake_update() -> SimpleNamespace:
    message = FakeMessage()
    return SimpleNamespace(
        update_id=10,
        effective_user=SimpleNamespace(id=100),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=message,
        callback_query=None,
    )


class FakeMessage:
    message_id = 55

    def __init__(self) -> None:
        self.replies: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append((text, kwargs))


class UxAuditTest(unittest.IsolatedAsyncioTestCase):
    def test_config_reads_ux_audit_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            env = {
                "RELCHAT_DATA_DIR": tmp,
                "RELCHAT_UX_AUDIT_ENABLED": "true",
                "RELCHAT_UX_AUDIT_MAX_EVENTS": "42",
                "RELCHAT_UX_AUDIT_INCLUDE_USER_TEXT": "true",
                "RELCHAT_UX_AUDIT_PATH": str(audit_path),
            }
            with patch.dict(os.environ, env, clear=True), patch("relchat.config.load_dotenv", lambda path=None: None):
                settings = get_settings()

        self.assertTrue(settings.ux_audit_enabled)
        self.assertEqual(settings.ux_audit_max_events, 42)
        self.assertTrue(settings.ux_audit_include_user_text)
        self.assertEqual(settings.ux_audit_path, audit_path)

    def test_record_event_redacts_sensitive_values_and_trims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path, max_events=2)
            record_ux_event(settings, "first", update=fake_update(), payload={"text": "old"})
            record_ux_event(
                settings,
                "second",
                update=fake_update(),
                payload={
                    "phone": "+1 415 555 0101",
                    "token": "123456789:abcdefghijklmnopqrstuvwxyzABCDE",
                    "api_hash": "a" * 32,
                    "session": "/tmp/telegram.session",
                },
            )
            record_ux_event(settings, "third", update=fake_update(), payload={"text": "new"})

            lines = path.read_text(encoding="utf-8").splitlines()
            rendered = "\n".join(lines)

        self.assertEqual(len(lines), 2)
        self.assertNotIn("first", rendered)
        self.assertIn("[redacted phone]", rendered)
        self.assertIn("[redacted bot token]", rendered)
        self.assertIn("[redacted api hash]", rendered)
        self.assertIn("[redacted session path]", rendered)

    def test_user_text_is_omitted_unless_explicitly_enabled(self) -> None:
        omitted = incoming_text_payload("secret search text", mode="chat_search", include_text=False)
        included = incoming_text_payload("call +1 415 555 0101", mode="chat_search", include_text=True)

        self.assertNotIn("secret search text", json.dumps(omitted))
        self.assertEqual(omitted["text_length"], 18)
        self.assertIn("[redacted phone]", included["text"])

    def test_keyboard_payload_keeps_callback_data_short_and_redacted(self) -> None:
        markup = SimpleNamespace(
            inline_keyboard=[
                [
                    SimpleNamespace(text="Open", callback_data="rc:nav:main"),
                    SimpleNamespace(text="Token", callback_data="123456789:abcdefghijklmnopqrstuvwxyzABCDE"),
                ]
            ]
        )

        payload = keyboard_payload(markup)

        self.assertEqual(payload[0][0]["callback_data"], "rc:nav:main")
        self.assertEqual(payload[0][0]["callback_length"], 11)
        self.assertIn("[redacted bot token]", payload[0][1]["callback_data"])

    def test_export_report_is_readable_and_does_not_include_exception_messages(self) -> None:
        events = [
            {
                "timestamp": "2026-07-14T10:00:00+00:00",
                "event_type": "handler_error",
                "update": {"user_id": 100, "chat_type": "private"},
                "payload": error_payload(RuntimeError("private stack detail")),
            },
            {
                "timestamp": "2026-07-14T10:00:01+00:00",
                "event_type": "bot_edit",
                "update": {"user_id": 100, "chat_type": "private"},
                "payload": outgoing_payload("Main menu", action="edit"),
            },
        ]

        rendered = format_ux_audit_report(events)

        self.assertIn("RelChat UX Audit", rendered)
        self.assertIn("handler_error", rendered)
        self.assertIn("RuntimeError", rendered)
        self.assertNotIn("private stack detail", rendered)
        self.assertIn("Main menu", rendered)

    async def test_reply_chunks_records_bot_reply_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            update = fake_update()
            set_current_audit_settings(settings)

            try:
                await reply_chunks(update, "Choose an action")
                events = load_ux_audit_events(path)
            finally:
                clear_current_audit_settings()

        self.assertEqual(update.effective_message.replies[0][0], "Choose an action")
        self.assertEqual(events[0]["event_type"], "bot_reply")
        self.assertEqual(events[0]["payload"]["action"], "reply")
        self.assertIn("Choose an action", events[0]["payload"]["text_preview"])


if __name__ == "__main__":
    unittest.main()
