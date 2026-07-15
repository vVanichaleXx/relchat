from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relchat.bot.formatters import format_timeline_page, format_timeline_story_page, format_timeline_summary
from relchat.bot.handlers.chat_home import CHAT_HOME_STATE, handle_chat_home_callback, send_timeline_chart
from relchat.bot.keyboards import timeline_page_keyboard, timeline_summary_keyboard
from relchat.bot.services.timeline_service import (
    build_relationship_timeline,
    contains_raw_text,
    filter_timeline_entries,
    filter_timeline_story_items,
    paginate_timeline_entries,
    paginate_timeline_story,
    render_timeline_chart,
)
from relchat.config import Settings
from relchat.core.models import Message
from relchat.database.repositories import create_reminder, create_report, ensure_user_profile, save_user_message, update_user_setting
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


def message(
    message_id: int,
    timestamp: str,
    *,
    sender_id: str = "a",
    sender_name: str = "Alice",
    text: str = "hello",
    chat_id: str = "telegram-chat-id-should-not-be-in-callbacks",
) -> Message:
    return Message(
        source="telegram",
        source_message_id=message_id,
        conversation_id=chat_id,
        sender_id=sender_id,
        sender_name=sender_name,
        timestamp=timestamp,
        text=text,
        message_type="text",
        is_outgoing=sender_id == "me",
    )


def sample_messages() -> list[Message]:
    return [
        message(1, "2026-06-01T10:00:00+00:00", sender_id="me", sender_name="Me", text="Are we meeting?"),
        message(2, "2026-06-01T10:10:00+00:00", sender_id="other", sender_name="Alice", text="yes"),
        message(3, "2026-06-09T10:00:00+00:00", sender_id="me", sender_name="Me", text="let's meet tomorrow"),
        message(4, "2026-06-18T10:00:00+00:00", sender_id="other", sender_name="Alice", text="I will send it"),
        message(5, "2026-07-06T10:00:00+00:00", sender_id="me", sender_name="Me", text="any update?"),
    ]


def report_dict(*, created_at: str = "2026-07-10T09:00:00+00:00") -> dict:
    return {
        "report_id": "rep_story",
        "chat_id": chat()["chat_id"],
        "chat_title": "Alice",
        "period_id": "30d",
        "period_label": "30 days",
        "created_at": created_at,
        "imported_message_count": 5,
        "modules": ["activity"],
        "job_status": "completed",
        "metrics_summary": {},
        "event_summary": {},
        "data_quality": {"confidence": "medium"},
    }


class RelationshipTimelineV1Test(unittest.IsolatedAsyncioTestCase):
    def test_weekly_and_monthly_aggregation(self) -> None:
        weekly = build_relationship_timeline(messages=sample_messages(), chat_type="one_to_one", granularity="week")
        monthly = build_relationship_timeline(messages=sample_messages(), chat_type="one_to_one", granularity="month")

        self.assertEqual(weekly.buckets[0].label, "2026-06-01")
        self.assertGreaterEqual(len(weekly.buckets), 6)
        self.assertEqual(monthly.buckets[0].label, "2026-06")
        self.assertEqual(monthly.buckets[-1].label, "2026-07")
        self.assertEqual(monthly.buckets[0].total_messages, 4)

    def test_event_ordering_filters_pagination_and_long_silences(self) -> None:
        timeline = build_relationship_timeline(messages=sample_messages(), chat_type="one_to_one", granularity="week")
        timestamps = [entry.timestamp for entry in timeline.entries]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

        questions = filter_timeline_entries(timeline.entries, "questions")
        plans = filter_timeline_entries(timeline.entries, "plans")
        followups = filter_timeline_entries(timeline.entries, "followups")
        silences = filter_timeline_entries(timeline.entries, "silences")

        self.assertTrue(any(entry.entry_type == "question" for entry in questions))
        self.assertTrue(any(entry.entry_type == "plan_candidate" for entry in plans))
        self.assertTrue(any(entry.entry_type == "promise_candidate" for entry in followups))
        self.assertTrue(any(entry.entry_type == "long_silence" for entry in silences))

        page = paginate_timeline_entries(timeline.entries, page=0, page_size=3)
        next_page = paginate_timeline_entries(timeline.entries, page=1, page_size=3)
        self.assertEqual(len(page.entries), 3)
        self.assertTrue(page.has_older)
        self.assertTrue(next_page.has_newer)

    def test_empty_timeline_and_no_raw_message_text(self) -> None:
        secret = "private secret appointment details"
        timeline = build_relationship_timeline(
            messages=[message(1, "2026-06-01T10:00:00+00:00", text=f"remind me about {secret}?")],
            chat_type="one_to_one",
        )
        empty = build_relationship_timeline(messages=[], chat_type="one_to_one")
        rendered = format_timeline_page(paginate_timeline_entries(timeline.entries), chat=chat(), language="en")
        empty_rendered = format_timeline_summary(empty, chat=chat(), language="en")

        self.assertIn("No timeline story", empty_rendered)
        self.assertFalse(contains_raw_text(timeline.entries, secret))
        self.assertNotIn(secret, rendered)

    def test_completed_analyses_and_confirmed_reminders_are_timeline_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
                save_user_message(conn, 100, sample_messages()[0])
                report = create_report(
                    conn,
                    bot_user_id=100,
                    job_id=None,
                    source="telegram",
                    chat_id=chat()["chat_id"],
                    chat_title="Alice",
                    period_id="30d",
                    period_label="30 days",
                    period_start="2026-06-01T00:00:00+00:00",
                    period_end="2026-07-01T00:00:00+00:00",
                    imported_message_count=1,
                    modules=["activity"],
                    job_status="completed",
                    metrics_summary={},
                    event_summary={},
                    data_quality={"confidence": "medium"},
                )
                reminder = create_reminder(
                    conn,
                    bot_user_id=100,
                    chat_id=chat()["chat_id"],
                    chat_title="Alice",
                    report_id=report["report_id"],
                    event_type="follow_up_candidate",
                    title="Follow up",
                    reminder_time="2026-07-02T09:00:00+00:00",
                    status="confirmed",
                )

            timeline = build_relationship_timeline(
                messages=sample_messages()[:1],
                reports=[report],
                reminders=[reminder],
                chat_type="one_to_one",
            )

        types = {entry.entry_type for entry in timeline.entries}
        story_types = {entry.story_type for entry in timeline.story_items}
        self.assertIn("analysis_completed", types)
        self.assertIn("confirmed_reminder", types)
        self.assertIn("analysis_completed", story_types)
        self.assertIn("reminder_confirmed", story_types)

    def test_timeline_v2_story_items_and_filters(self) -> None:
        timeline = build_relationship_timeline(
            messages=sample_messages(),
            reports=[report_dict()],
            reminders=[
                {"status": "suggested", "updated_at": "2026-07-07T09:00:00+00:00", "event_type": "follow_up_candidate"},
                {"status": "confirmed", "reminder_time": "2026-07-08T09:00:00+00:00", "event_type": "follow_up_candidate"},
                {"status": "completed", "updated_at": "2026-07-09T09:00:00+00:00", "event_type": "follow_up_candidate"},
            ],
            chat_type="one_to_one",
        )
        story_types = {entry.story_type for entry in timeline.story_items}

        self.assertIn("activity_day", story_types)
        self.assertIn("quiet_started", story_types)
        self.assertIn("conversation_resumed", story_types)
        self.assertIn("plan_mentioned", story_types)
        self.assertIn("promise_mentioned", story_types)
        self.assertIn("followup_suggested", story_types)
        self.assertIn("reminder_suggested", story_types)
        self.assertIn("reminder_confirmed", story_types)
        self.assertIn("reminder_completed", story_types)
        self.assertIn("analysis_completed", story_types)

        followups = filter_timeline_story_items(timeline.story_items, "followups")
        silences = filter_timeline_story_items(timeline.story_items, "silences")
        self.assertTrue(all("followups" in item.filter_tags for item in followups))
        self.assertTrue(any(item.story_type == "quiet_started" for item in silences))

    def test_timeline_v2_story_rendering_is_grouped_and_safe(self) -> None:
        secret = "private timeline secret"
        local_messages = [
            message(1, "2026-07-13T18:00:00+00:00", text=secret, sender_id="me"),
            message(2, "2026-07-14T20:00:00+00:00", text="any update?", sender_id="other"),
        ]
        timeline = build_relationship_timeline(
            messages=local_messages,
            reports=[report_dict(created_at="2026-07-14T21:00:00+00:00")],
            reminders=[],
            chat_type="one_to_one",
        )
        page = paginate_timeline_story(timeline.story_items, page=0)
        rendered = format_timeline_story_page(
            page,
            chat=chat(),
            language="en",
            now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
        )

        self.assertIn("Timeline", rendered)
        self.assertIn("July 2026", rendered)
        self.assertIn("Today", rendered)
        self.assertIn("Yesterday", rendered)
        self.assertIn("● Conversation active", rendered)
        self.assertIn("Mostly in the evening", rendered)
        self.assertIn("30-day overview updated", rendered)
        self.assertNotIn("follow_up_candidate", rendered)
        self.assertNotIn("source_message_id", rendered)
        self.assertNotIn(secret, rendered)

    def test_timeline_v2_activity_change_and_pagination(self) -> None:
        local_messages = []
        for index in range(6):
            local_messages.append(message(index + 1, f"2026-06-0{index + 1}T10:00:00+00:00"))
        for index in range(12):
            local_messages.append(message(index + 20, f"2026-06-{10 + index:02d}T10:00:00+00:00"))
        timeline = build_relationship_timeline(messages=local_messages, chat_type="one_to_one", granularity="week")
        page = paginate_timeline_story(timeline.story_items, page=0, page_size=3)

        self.assertTrue(any(item.story_type == "activity_increased" for item in timeline.story_items))
        self.assertEqual(len(page.entries), 3)
        self.assertTrue(page.has_older)

    async def test_chart_generation_and_callback_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = render_timeline_chart(sample_messages(), chat_type="one_to_one", output_dir=Path(tmp))
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            path.unlink()

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            chart_path = Path(tmp) / "chart.png"
            chart_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
                for item in sample_messages():
                    save_user_message(conn, 100, item)
            context = fake_context(settings_for(db_path))
            context.user_data[CHAT_HOME_STATE] = chat()
            update = fake_update("rc:tl:chart")

            with patch("relchat.bot.handlers.chat_home.render_timeline_chart", return_value=chart_path):
                await send_timeline_chart(update, context)

            self.assertTrue(update.effective_message.photo_exists_during_send)
            self.assertFalse(chart_path.exists())

    async def test_chart_failure_falls_back_to_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
                update_user_setting(conn, 100, "language", "en")
            context = fake_context(settings_for(db_path))
            context.user_data[CHAT_HOME_STATE] = chat()
            update = fake_update("rc:tl:chart")

            with patch("relchat.bot.handlers.chat_home.render_timeline_chart", side_effect=RuntimeError("boom")):
                handled = await handle_chat_home_callback(update, context, ["rc", "tl", "chart"])

        self.assertTrue(handled)
        self.assertIn("Could not create the activity chart", update.callback_query.edited_text)
        self.assertNotIn("boom", update.callback_query.edited_text)

    async def test_timeline_handler_renders_summary_and_page_without_callback_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                ensure_user_profile(conn, 100)
                update_user_setting(conn, 100, "language", "en")
                for item in sample_messages():
                    save_user_message(conn, 100, item)
            context = fake_context(settings_for(db_path))
            context.user_data[CHAT_HOME_STATE] = chat()
            update = fake_update("rc:home:sec:timeline")

            handled = await handle_chat_home_callback(update, context, ["rc", "home", "sec", "timeline"])
            self.assertTrue(handled)
            self.assertIn("Timeline", update.callback_query.edited_text)
            self.assertIn("Conversation active", update.callback_query.edited_text)

            update_page = fake_update("rc:tl:filter:questions")
            handled = await handle_chat_home_callback(update_page, context, ["rc", "tl", "filter", "questions"])

        self.assertTrue(handled)
        self.assertIn("Questions", update_page.callback_query.edited_text)
        callbacks = callback_values(timeline_summary_keyboard(language="en")) + callback_values(
            timeline_page_keyboard(filter_id="questions", page=0, has_newer=True, has_older=True, language="en")
        )
        self.assertTrue(all(len(value) < 64 for value in callbacks))
        self.assertNotIn(chat()["chat_id"], "".join(callbacks))
        self.assertNotIn("Alice", "".join(callbacks))

    def test_private_group_channel_wording_and_localization(self) -> None:
        private = format_timeline_summary(
            build_relationship_timeline(messages=sample_messages(), chat_type="one_to_one"),
            chat=chat("one_to_one"),
            language="en",
        )
        group = format_timeline_summary(
            build_relationship_timeline(messages=sample_messages(), chat_type="group"),
            chat=chat("group"),
            language="en",
        )
        channel = format_timeline_summary(
            build_relationship_timeline(messages=sample_messages(), chat_type="channel"),
            chat=chat("channel"),
            language="en",
        )
        russian = format_timeline_summary(
            build_relationship_timeline(messages=sample_messages(), chat_type="one_to_one"),
            chat=chat("one_to_one"),
            language="ru",
        )

        self.assertIn("Conversation active", private)
        self.assertIn("Group active", group)
        self.assertIn("Channel active", channel)
        self.assertIn("Хронология", russian)
        self.assertNotIn("Timeline", russian)


def fake_context(settings: Settings):
    return SimpleNamespace(application=SimpleNamespace(bot_data={"settings": settings}), user_data={})


def fake_update(callback_data: str):
    query = FakeQuery(callback_data)
    message = FakeMessage()
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=100),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=message,
    )


def callback_values(markup) -> list[str]:
    return [button.callback_data or "" for row in markup.inline_keyboard for button in row]


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
    def __init__(self) -> None:
        self.photo_exists_during_send = False
        self.photo_caption = None

    async def reply_text(self, text: str, **kwargs) -> None:
        return None

    async def reply_photo(self, photo, caption: str | None = None) -> None:
        self.photo_exists_during_send = Path(photo.name).exists()
        self.photo_caption = caption


if __name__ == "__main__":
    unittest.main()
