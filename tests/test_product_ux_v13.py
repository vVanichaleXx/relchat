from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from relchat.bot.formatters import format_chat_home, format_chat_page, format_main_menu, format_unified_analysis_result
from relchat.bot.keyboards import analysis_result_keyboard, chat_home_keyboard, chat_list_keyboard, main_keyboard
from relchat.bot.services.chat_ranking import quick_access_chats, rank_chats
from relchat.bot.services.chat_search import search_chats
from relchat.bot.services.chat_types import chat_category, classify_chat_type, primary_analysis_button_key
from relchat.bot.services.native_navigation import (
    MAX_NAV_DEPTH,
    is_safe_callback_data,
    navigation_stack,
    pop_back,
    push_screen,
    register_nav_token,
    resolve_nav_token,
)
from relchat.core.models import ConversationRef
from relchat.database.repositories import (
    create_report,
    delete_all_user_data,
    ensure_report_callback_token,
    get_navigation_state,
    list_quick_access_chats,
    list_user_chats,
    list_user_chats_by_type,
    mark_user_chat_opened,
    save_dialog_cache,
    save_navigation_state,
    save_user_chat,
    search_user_chats,
    resolve_report_callback_token,
    set_user_chat_favorite,
    set_user_chat_pinned,
)
from relchat.database.sqlite import connect, init_db


def chat(
    chat_id: str,
    title: str,
    chat_type: str = "one_to_one",
    *,
    last: str | None = None,
    favorite: bool = False,
    pinned: bool = False,
    opened: str | None = None,
    analyzed: str | None = None,
) -> ConversationRef:
    return ConversationRef(
        source="telegram",
        conversation_id=chat_id,
        conversation_type=chat_type,
        title=title,
        last_message_at=last,
        is_favorite=favorite,
        is_pinned=pinned,
        recent_opened_at=opened,
        recent_analyzed_at=analyzed,
    )


def labels(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def callbacks(markup) -> list[str]:
    return [button.callback_data or "" for row in markup.inline_keyboard for button in row]


class ProductUxV13NavigationTest(unittest.TestCase):
    def test_main_menu_private_first_and_quick_access(self) -> None:
        quick = [{"chat_type": "one_to_one", "title": "Дарина"}, {"chat_type": "channel", "title": "News"}]
        text = format_main_menu(
            language="ru",
            telegram_connected=True,
            saved_chats=3,
            reports=2,
            running_jobs=0,
            quick_access=quick[:1],
        )
        keyboard = main_keyboard("ru", quick_access=[("👤 Дарина", "q1")])
        button_labels = labels(keyboard)

        self.assertIn("Быстрый доступ", text)
        self.assertIn("👤 Личные чаты", button_labels)
        self.assertLess(button_labels.index("👤 Личные чаты"), button_labels.index("👥 Группы"))
        self.assertIn("rc:quick:q1", callbacks(keyboard))
        self.assertNotIn("News", "".join(button_labels))

    def test_chat_type_classification_separates_bots_and_channels(self) -> None:
        self.assertEqual(classify_chat_type(chat("1", "Anna")), "private_human")
        self.assertEqual(classify_chat_type(chat("2", "Reminder", "bot")), "bot")
        self.assertEqual(classify_chat_type(chat("3", "Team", "supergroup")), "group")
        self.assertEqual(classify_chat_type(chat("4", "News", "channel")), "channel")
        self.assertEqual(chat_category(chat("2", "Reminder", "bot")), "bots")
        self.assertEqual(primary_analysis_button_key("channel"), "nav_analyze_channel")
        self.assertEqual(primary_analysis_button_key("group"), "nav_analyze_group")
        self.assertEqual(primary_analysis_button_key("one_to_one", "work"), "nav_analyze_effectiveness")

    def test_ranking_private_first_pinned_favorite_recent(self) -> None:
        rows = [
            chat("g", "Group", "group", last="2026-07-22T10:00:00"),
            chat("regular", "Regular", last="2026-07-22T09:00:00"),
            chat("fav", "Favorite", favorite=True, last="2026-07-20T09:00:00"),
            chat("pin", "Pinned", pinned=True, last="2026-07-19T09:00:00"),
            chat("recent", "Recent", opened="2026-07-22T11:00:00"),
        ]
        ranked = rank_chats(rows)
        quick = quick_access_chats(rows)

        self.assertEqual([item.conversation_id for item in ranked[:4]], ["pin", "fav", "recent", "regular"])
        self.assertEqual([item.conversation_id for item in quick], ["pin", "fav", "recent"])
        self.assertTrue(all(item.conversation_type == "one_to_one" for item in quick))

    def test_search_prioritizes_exact_private_unicode_then_groups_channels_bots(self) -> None:
        rows = [
            chat("g", "Ксения Team", "group"),
            chat("c", "Ксения News", "channel"),
            chat("b", "Ксения Bot", "bot"),
            chat("p2", "Ксения Иванова"),
            chat("p1", "Ксения"),
            chat("sub", "Моя Ксения"),
        ]
        found = search_chats(rows, "ксения")

        self.assertEqual([item.conversation_id for item in found[:6]], ["p1", "p2", "sub", "g", "c", "b"])

    def test_navigation_stack_back_tokens_and_stale_safety(self) -> None:
        user_data: dict = {}
        push_screen(user_data, "main_menu")
        push_screen(user_data, "chat_list:private", payload={"page": 1})
        push_screen(user_data, "chat_home", payload={"chat": {"chat_id": "secret-id"}})
        token = register_nav_token(user_data, bot_user_id=1, payload={"index": 3}, prefix="c")

        self.assertEqual(resolve_nav_token(user_data, bot_user_id=1, token=token), {"index": 3})
        self.assertIsNone(resolve_nav_token(user_data, bot_user_id=2, token=token))
        self.assertEqual(pop_back(user_data)["screen_id"], "chat_list:private")
        for index in range(MAX_NAV_DEPTH + 5):
            push_screen(user_data, f"s{index}")
        self.assertLessEqual(len(navigation_stack(user_data)), MAX_NAV_DEPTH)
        self.assertTrue(is_safe_callback_data(f"rc:browse:select:{token}"))
        self.assertFalse(is_safe_callback_data("rc:browse:select:telegram-chat-id-123"))

    def test_pagination_layout_and_callback_privacy(self) -> None:
        rows = [chat(str(index), f"Person {index}") for index in range(10)]
        keyboard = chat_list_keyboard(
            rows[:5],
            page=1,
            page_size=5,
            has_previous=True,
            has_next=True,
            language="ru",
            item_tokens=[f"c{index}" for index in range(5)],
            total=12,
            native=True,
        )
        flat_labels = labels(keyboard)
        flat_callbacks = callbacks(keyboard)

        self.assertIn("⬅️", flat_labels)
        self.assertIn("➡️", flat_labels)
        self.assertIn("Страница 2 из 3", flat_labels)
        self.assertIn("🏠 Меню", flat_labels)
        self.assertTrue(all("Person 0" not in value for value in flat_callbacks))
        self.assertTrue(all(len(value) < 64 for value in flat_callbacks))

    def test_chat_home_compact_actions_and_context_specific_primary(self) -> None:
        private_labels = labels(chat_home_keyboard({"chat_type": "one_to_one"}, has_report=True, language="ru"))
        work_labels = labels(chat_home_keyboard({"chat_type": "one_to_one", "confirmed_context_category": "work"}, has_report=True, language="ru"))
        group_labels = labels(chat_home_keyboard({"chat_type": "group"}, has_report=True, language="ru"))
        channel_labels = labels(chat_home_keyboard({"chat_type": "channel"}, has_report=True, language="ru"))

        self.assertEqual(private_labels[0], "🔍 Анализ общения")
        self.assertEqual(work_labels[0], "🔍 Анализ эффективности")
        self.assertEqual(group_labels[0], "🔍 Анализ группы")
        self.assertEqual(channel_labels[0], "📊 Анализ канала")
        self.assertIn("⋯ Ещё", private_labels)
        self.assertIn("🏠 Меню", private_labels)
        self.assertNotIn("Удалить локальные данные", private_labels)

    def test_report_keyboard_and_compact_local_report_hierarchy(self) -> None:
        keyboard = analysis_result_keyboard("internal_report_id", language="ru")
        flat_labels = labels(keyboard)
        rendered = format_unified_analysis_result(
            {
                "chat_title": "Работа",
                "period_label": "Последние 30 дней",
                "imported_message_count": 42,
                "metrics_summary": {"message_count": 42, "participants": {"outgoing": 20, "incoming": 22}},
                "data_quality": {"confidence": "medium", "completeness": "selected"},
                "modules": [],
            },
            language="ru",
            chat_type="one_to_one",
        )

        self.assertEqual(flat_labels, ["📄 Полный анализ", "💡 Почему такой вывод", "💬 К чату", "🏠 Меню"])
        self.assertIn("**Работа**", rendered)
        self.assertIn("_Локальный анализ", rendered)
        self.assertIn("**Анализ завершен**", rendered)
        self.assertEqual(rendered.count("Последние 30 дней"), 1)


class ProductUxV13PersistenceTest(unittest.TestCase):
    def test_repository_pins_recents_search_and_user_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                save_user_chat(conn, 1, chat("p", "Дарина"))
                save_user_chat(conn, 1, chat("g", "Дарина group", "group"))
                save_user_chat(conn, 1, chat("c", "Дарина channel", "channel"))
                save_user_chat(conn, 2, chat("p", "Дарина other user"))
                set_user_chat_pinned(conn, 1, "telegram", "p", True)
                set_user_chat_favorite(conn, 1, "telegram", "p", True)
                mark_user_chat_opened(conn, 1, "telegram", "p")
                save_navigation_state(conn, 1, token="n1", screen_id="chat_home", previous_screen_id="chat_list:private", state={"chat_id": "p"})

                private = list_user_chats_by_type(conn, 1, chat_types=["one_to_one"])
                quick = list_quick_access_chats(conn, 1)
                search = search_user_chats(conn, 1, "дарина")
                other_quick = list_quick_access_chats(conn, 2)
                nav_state = get_navigation_state(conn, 1, "n1")

        self.assertEqual([item["chat_id"] for item in private], ["p"])
        self.assertEqual([item["chat_id"] for item in quick], ["p"])
        self.assertEqual([item["chat_type"] for item in search[:3]], ["one_to_one", "group", "channel"])
        self.assertEqual(other_quick, [])
        self.assertEqual(nav_state["previous_screen_id"], "chat_list:private")

    def test_delete_all_user_data_removes_v13_navigation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                save_user_chat(conn, 1, chat("p", "Anna"))
                set_user_chat_pinned(conn, 1, "telegram", "p", True)
                save_navigation_state(conn, 1, token="n1", screen_id="chat_home", state={"chat_id": "p"})
                delete_all_user_data(conn, 1)
                self.assertEqual(list_user_chats(conn, 1), [])
                self.assertIsNone(get_navigation_state(conn, 1, "n1"))

    def test_report_callback_token_hides_internal_report_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relchat.sqlite3"
            init_db(db_path)
            with connect(db_path) as conn:
                report = create_report(
                    conn,
                    bot_user_id=1,
                    job_id=None,
                    source="telegram",
                    chat_id="secret-chat-id",
                    chat_title="Anna",
                    period_id="30d",
                    period_label="Last 30 days",
                    period_start=None,
                    period_end=None,
                    imported_message_count=20,
                    modules=[],
                    job_status="completed",
                    metrics_summary={},
                    event_summary={},
                    data_quality={},
                )
                token = ensure_report_callback_token(conn, 1, report["report_id"])
                resolved = resolve_report_callback_token(conn, 1, token)
            keyboard = analysis_result_keyboard(token, language="en")
            flat_callbacks = callbacks(keyboard)

        self.assertEqual(resolved, report["report_id"])
        self.assertTrue(token.startswith("r"))
        self.assertTrue(all(report["report_id"] not in value for value in flat_callbacks))
        self.assertTrue(all("secret-chat-id" not in value for value in flat_callbacks))


class ProductUxV13OfflineFlowFixtureTest(unittest.TestCase):
    def test_user_with_private_chats_and_many_channels_gets_private_first(self) -> None:
        rows = [chat(f"p{index}", f"Private {index}") for index in range(8)]
        rows.extend(chat(f"c{index}", f"Channel {index}", "channel", last=f"2026-07-22T{index % 24:02d}:00:00") for index in range(120))
        ranked_private = [item for item in rank_chats(rows) if chat_category(item) == "private"]
        quick = quick_access_chats([chat("p0", "Private 0", pinned=True), *rows])

        self.assertEqual(len(ranked_private), 8)
        self.assertTrue(all(item.conversation_type == "one_to_one" for item in ranked_private))
        self.assertEqual([item.conversation_id for item in quick], ["p0"])

    def test_user_with_400_private_chats_has_bounded_page_and_search(self) -> None:
        rows = [chat(f"p{index}", f"Person {index:03d}") for index in range(400)]
        page_text = format_chat_page(title="Private chats", first_item=1, last_item=10, total=len(rows), page=0, page_size=10, language="en")
        found = search_chats(rows, "Person 199")

        self.assertIn("1 / 40", page_text)
        self.assertEqual([item.conversation_id for item in found[:1]], ["p199"])

    def test_mostly_groups_empty_private_state_is_clear(self) -> None:
        page_text = format_chat_page(title="Личные чаты", first_item=0, last_item=0, total=0, page=0, page_size=10, language="ru")
        empty_keyboard = chat_list_keyboard([], page=0, page_size=10, has_previous=False, has_next=False, language="ru", total=0, native=True)

        self.assertIn("Личные чаты не найдены", page_text)
        self.assertIn("🏠 Меню", labels(empty_keyboard))
