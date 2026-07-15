from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relchat.bot.handlers import register_handlers
from relchat.bot.handlers.common import reply_chunks
from relchat.bot.handlers.debug import debug_clear_command, debug_export_command, debug_status_command, handle_debug_callback
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
    user_ux_audit_events,
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


def fake_command_update(text: str = "/debug_status", *, user_id: int = 100) -> SimpleNamespace:
    message = FakeMessage(text=text)
    return SimpleNamespace(
        update_id=10,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=message,
        callback_query=None,
    )


class FakeMessage:
    message_id = 55

    def __init__(self, *, text: str = "") -> None:
        self.text = text
        self.replies: list[tuple[str, dict]] = []
        self.documents: list[dict] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append((text, kwargs))

    async def reply_document(self, document, **kwargs) -> None:
        content = document.read()
        self.documents.append(
            {
                "content": content.decode("utf-8") if isinstance(content, bytes) else str(content),
                "kwargs": kwargs,
            }
        )


class FailingDocumentMessage(FakeMessage):
    async def reply_document(self, document, **kwargs) -> None:
        raise RuntimeError("send failed")


def fake_context(settings: Settings, *, args: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(application=SimpleNamespace(bot_data={"settings": settings}), args=args or [], user_data={})


def write_raw_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def raw_event(user_id: int, event_type: str, payload: dict, *, timestamp: str = "2026-07-15T10:00:00+00:00") -> dict:
    return {
        "timestamp": timestamp,
        "event_type": event_type,
        "update": {"user_id": user_id, "chat_type": "private"},
        "payload": payload,
    }


class UxAuditTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        clear_current_audit_settings()

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


class UxAuditDebugCommandTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        clear_current_audit_settings()

    def test_debug_handlers_are_registered_with_aliases(self) -> None:
        app = SimpleNamespace(handlers=[])
        app.add_handler = app.handlers.append

        register_handlers(app)
        command_sets = [getattr(handler, "commands", frozenset()) for handler in app.handlers]
        commands = set().union(*command_sets)

        self.assertIn("debug_status", commands)
        self.assertIn("debug_export", commands)
        self.assertIn("debug_clear", commands)
        self.assertIn("debug_log", commands)
        self.assertIn("debug_report", commands)

    async def test_debug_status_output_is_compact_and_user_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path, max_events=50)
            record_ux_event(settings, "bot_reply", update=fake_command_update(user_id=100), payload=outgoing_payload("Main", action="reply"))
            record_ux_event(settings, "bot_reply", update=fake_command_update(user_id=200), payload=outgoing_payload("Other", action="reply"))
            update = fake_command_update("/debug_status", user_id=100)

            await debug_status_command(update, fake_context(settings))

        rendered = update.effective_message.replies[-1][0]
        self.assertIn("UX audit enabled: yes", rendered)
        self.assertIn("Event count: 2", rendered)
        self.assertIn("Maximum configured events: 50", rendered)
        self.assertIn("User text included: no", rendered)
        self.assertIn("Log file exists: yes", rendered)
        self.assertNotIn(str(path), rendered)

    async def test_debug_export_creates_readable_txt_for_requesting_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            write_raw_event(
                path,
                raw_event(
                    100,
                    "bot_reply",
                    {
                        "action": "reply",
                        "text_preview": "Main menu\nChoose an action.",
                        "keyboard": [[{"text": "Main", "callback_data": "rc:nav:main"}]],
                    },
                    timestamp="2026-07-15T10:00:00+00:00",
                ),
            )
            write_raw_event(path, raw_event(100, "incoming_callback", {"callback_data": "rc:nav:main", "parts": ["rc", "nav", "main"]}))
            write_raw_event(path, raw_event(100, "incoming_command", {"command": "/start"}))
            write_raw_event(path, raw_event(100, "handler_error", {"error_type": "RuntimeError", "reference": "err_test"}))
            write_raw_event(path, raw_event(200, "bot_reply", {"action": "reply", "text_preview": "other-user-secret"}))
            update = fake_command_update("/debug_export 100", user_id=100)

            await debug_export_command(update, fake_context(settings, args=["100"]))

        document = update.effective_message.documents[-1]
        exported = document["content"]
        self.assertTrue(document["kwargs"]["filename"].endswith(".txt"))
        self.assertIn("RelChat UX Debug Export", exported)
        self.assertIn("BOT  bot_reply", exported)
        self.assertIn("USER  incoming_callback", exported)
        self.assertIn("command: /start", exported)
        self.assertIn("callback route: rc > nav > main", exported)
        self.assertIn("callback/button label: Main", exported)
        self.assertIn("screen: Main menu", exported)
        self.assertIn("visible bot text: Main menu", exported)
        self.assertIn("visible buttons: Main", exported)
        self.assertIn("safe error: err_test", exported)
        self.assertNotIn("other-user-secret", exported)

    async def test_debug_export_supports_time_window_and_skips_malformed_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{bad json\n", encoding="utf-8")
            write_raw_event(path, raw_event(100, "bot_reply", {"action": "reply", "text_preview": "Recent"}))
            update = fake_command_update("/debug_export 30m", user_id=100)

            await debug_export_command(update, fake_context(settings, args=["30m"]))

        exported = update.effective_message.documents[-1]["content"]
        self.assertIn("Scope: last 30 minutes", exported)
        self.assertIn("Recent", exported)
        self.assertNotIn("{bad json", exported)

    async def test_debug_export_aliases_use_same_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            write_raw_event(path, raw_event(100, "incoming_command", {"command": "/debug_log"}))

            log_update = fake_command_update("/debug_log", user_id=100)
            report_update = fake_command_update("/debug_report", user_id=100)
            await debug_export_command(log_update, fake_context(settings))
            await debug_export_command(report_update, fake_context(settings))

        self.assertEqual(len(log_update.effective_message.documents), 1)
        self.assertEqual(len(report_update.effective_message.documents), 1)

    async def test_debug_export_failure_keeps_local_file_and_replies_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            write_raw_event(path, raw_event(100, "bot_reply", {"action": "reply", "text_preview": "Main"}))
            message = FailingDocumentMessage(text="/debug_export")
            update = SimpleNamespace(
                update_id=10,
                effective_user=SimpleNamespace(id=100),
                effective_chat=SimpleNamespace(type="private"),
                effective_message=message,
                callback_query=None,
            )

            await debug_export_command(update, fake_context(settings))
            exports = list((path.parent / "exports").glob("*.txt"))

        self.assertEqual(len(exports), 1)
        self.assertIn("Could not send debug export", update.effective_message.replies[-1][0])
        self.assertNotIn(str(exports[0].parent), update.effective_message.replies[-1][0])

    async def test_debug_clear_confirmation_and_clear_only_requesting_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            write_raw_event(path, raw_event(100, "bot_reply", {"action": "reply", "text_preview": "Mine"}))
            write_raw_event(path, raw_event(200, "bot_reply", {"action": "reply", "text_preview": "Other"}))
            update = fake_command_update("/debug_clear", user_id=100)

            await debug_clear_command(update, fake_context(settings))
            confirmation_markup = update.effective_message.replies[-1][1]["reply_markup"]
            await handle_debug_callback(update, fake_context(settings), ["rc", "debug", "clear", "confirm"])
            user_events = user_ux_audit_events(path, 100)
            other_events = user_ux_audit_events(path, 200)

        self.assertEqual(confirmation_markup.inline_keyboard[0][0].callback_data, "rc:debug:clear:confirm")
        self.assertEqual(user_events, [])
        self.assertEqual(len(other_events), 1)
        self.assertIn("Other", other_events[0]["payload"]["text_preview"])

    async def test_unauthorized_user_cannot_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            write_raw_event(path, raw_event(100, "bot_reply", {"action": "reply", "text_preview": "Main"}))
            update = fake_command_update("/debug_export", user_id=999)

            await debug_export_command(update, fake_context(settings))

        self.assertEqual(update.effective_message.documents, [])
        self.assertEqual(update.effective_message.replies, [])

    async def test_debug_export_redacts_secrets_and_omits_raw_message_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ux-audit.jsonl"
            settings = audit_settings(path)
            secret_text = "imported private message body should not appear"
            write_raw_event(
                path,
                raw_event(
                    100,
                    "bot_reply",
                    {
                        "action": "reply",
                        "text_preview": "Token 123456789:abcdefghijklmnopqrstuvwxyzABCDE phone +1 415 555 0101 hash " + ("a" * 32),
                        "raw_message_text": secret_text,
                        "message_text": secret_text,
                        "session": "/tmp/telegram.session",
                    },
                ),
            )
            update = fake_command_update("/debug_export", user_id=100)

            await debug_export_command(update, fake_context(settings))

        exported = update.effective_message.documents[-1]["content"]
        self.assertIn("[redacted bot token]", exported)
        self.assertIn("[redacted phone]", exported)
        self.assertIn("[redacted api hash]", exported)
        self.assertNotIn("123456789:abcdefghijklmnopqrstuvwxyzABCDE", exported)
        self.assertNotIn("+1 415 555 0101", exported)
        self.assertNotIn("a" * 32, exported)
        self.assertNotIn("telegram.session", exported)
        self.assertNotIn(secret_text, exported)


if __name__ == "__main__":
    unittest.main()
