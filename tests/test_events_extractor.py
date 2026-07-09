from __future__ import annotations

import inspect
import unittest
from collections import Counter

from relchat.core.models import Message
from relchat.events import extractor
from relchat.events.extractor import extract_events


def message(message_id: int, sender: str, timestamp: str, text: str) -> Message:
    return Message(
        source="test",
        source_message_id=message_id,
        conversation_id="conversation-1",
        sender_id=sender,
        sender_name=sender.upper(),
        timestamp=timestamp,
        text=text,
        message_type="text",
    )


class EventExtractorTest(unittest.TestCase):
    def test_extracts_v0_event_types_from_normalized_messages(self) -> None:
        messages = [
            message(1, "a", "2026-01-01T10:00:00+00:00", "Are you free tomorrow?"),
            message(2, "b", "2026-01-01T10:05:00+00:00", "I will call the doctor and follow up."),
            message(3, "a", "2026-01-04T12:00:00+00:00", "Let's meet next week."),
            message(4, "a", "2026-01-04T12:02:00+00:00", "Can you send the file?"),
        ]

        events = extract_events(messages)
        counts = Counter(event.event_type for event in events)

        self.assertGreaterEqual(counts["question"], 2)
        self.assertEqual(counts["unanswered_question"], 1)
        self.assertEqual(counts["long_silence"], 1)
        self.assertEqual(counts["plan_candidate"], 1)
        self.assertEqual(counts["promise_candidate"], 1)
        self.assertEqual(counts["health_candidate"], 1)
        self.assertEqual(counts["follow_up_candidate"], 1)

    def test_events_do_not_store_message_text(self) -> None:
        secret_text = "private appointment details?"
        events = extract_events([message(1, "a", "2026-01-01T10:00:00+00:00", secret_text)])

        self.assertTrue(events)
        for event in events:
            self.assertFalse(hasattr(event, "text"))
            self.assertNotIn(secret_text, repr(event.metadata))

    def test_extractor_does_not_import_platform_or_storage_adapters(self) -> None:
        source = inspect.getsource(extractor)

        self.assertNotIn("relchat.telegram", source)
        self.assertNotIn("relchat.database", source)
        self.assertNotIn("sqlite", source)


if __name__ == "__main__":
    unittest.main()
