from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from relchat.bot.guided import normalize_search, parse_int
from relchat.bot.services.ux_audit import record_ux_event
from relchat.config import Settings
from relchat.core.models import ConversationRef
from relchat.database.repositories import (
    cached_folder_memberships,
    list_cached_conversations,
    list_cached_dialog_folders,
    list_user_chats,
    save_dialog_cache,
)
from relchat.database.sqlite import connect, init_db
from relchat.telegram.importer import load_conversation_catalog


PAGE_SIZE = 10
LOGGER = logging.getLogger(__name__)
REFRESH_TASKS_KEY = "relchat_dialog_cache_refresh_tasks"


@dataclass(frozen=True)
class Page:
    items: list[ConversationRef]
    page: int
    total: int
    page_size: int = PAGE_SIZE

    @property
    def has_previous(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return (self.page + 1) * self.page_size < self.total

    @property
    def first_item_number(self) -> int:
        return self.page * self.page_size + 1 if self.total else 0

    @property
    def last_item_number(self) -> int:
        return min((self.page + 1) * self.page_size, self.total)


def sort_conversations(conversations: list[ConversationRef]) -> list[ConversationRef]:
    return sorted(conversations, key=lambda item: (1 if item.last_message_at else 0, item.last_message_at or ""), reverse=True)


def filter_conversations(
    conversations: list[ConversationRef],
    category: str,
    *,
    favorite_ids: set[str] | None = None,
    recent_ids: set[str] | None = None,
) -> list[ConversationRef]:
    favorite_ids = favorite_ids or set()
    recent_ids = recent_ids or set()
    if category == "all":
        return sort_conversations(conversations)
    if category == "private":
        return filter_by_type(conversations, "one_to_one")
    if category == "groups":
        return filter_by_type(conversations, "group")
    if category == "channels":
        return filter_by_type(conversations, "channel")
    if category == "unread":
        return sort_conversations([item for item in conversations if item.unread_count > 0])
    if category == "favorites":
        return sort_conversations([item for item in conversations if item.conversation_id in favorite_ids])
    if category == "recent":
        return sort_conversations([item for item in conversations if item.conversation_id in recent_ids])
    if category.startswith("folder:"):
        folder_id = parse_int(category.removeprefix("folder:"))
        if folder_id is None:
            return []
        return sort_conversations([item for item in conversations if item.folder_id == folder_id])
    return []


def filter_folder_conversations(
    conversations: list[ConversationRef],
    folder_id: int,
    memberships: dict[int, set[str]] | None = None,
) -> list[ConversationRef]:
    folder_ids = (memberships or {}).get(folder_id)
    if folder_ids:
        return sort_conversations([item for item in conversations if item.conversation_id in folder_ids])
    return sort_conversations([item for item in conversations if item.folder_id == folder_id])


def filter_by_type(conversations: list[ConversationRef], conversation_type: str) -> list[ConversationRef]:
    return sort_conversations([item for item in conversations if item.conversation_type == conversation_type])


def search_conversations(conversations: list[ConversationRef], query: str) -> list[ConversationRef]:
    normalized = normalize_search(query)
    if not normalized:
        return []
    return sort_conversations([item for item in conversations if normalized in conversation_search_text(item)])


def conversation_search_text(conversation: ConversationRef) -> str:
    values = [
        conversation.title or "",
        conversation.username or "",
        f"@{conversation.username}" if conversation.username else "",
    ]
    return normalize_search(" ".join(values))


def paginate_conversations(conversations: list[ConversationRef], page: int, *, page_size: int = PAGE_SIZE) -> Page:
    total = len(conversations)
    max_page = max(0, (total - 1) // page_size)
    normalized = min(max(page, 0), max_page)
    start = normalized * page_size
    return Page(
        items=conversations[start : start + page_size],
        page=normalized,
        total=total,
        page_size=page_size,
    )


def load_cached_browser_state(settings: Settings, bot_user_id: int) -> dict[str, Any]:
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        conversations = list_cached_conversations(conn, bot_user_id, limit=5000)
        folders = list_cached_dialog_folders(conn, bot_user_id)
        memberships = cached_folder_memberships(conn, bot_user_id)
        favorite_ids = {chat["chat_id"] for chat in list_user_chats(conn, bot_user_id, section="favorites", limit=1000)}
        recent_ids = {chat["chat_id"] for chat in list_user_chats(conn, bot_user_id, section="recent", limit=1000)}
    return {
        "conversations": conversations,
        "folders": folders,
        "folder_memberships": memberships,
        "favorite_ids": favorite_ids,
        "recent_ids": recent_ids,
    }


async def refresh_dialog_cache(settings: Settings, bot_user_id: int) -> dict[str, Any]:
    init_db(settings.db_path)
    catalog = await load_conversation_catalog(settings, limit=None)
    with connect(settings.db_path) as conn:
        save_dialog_cache(
            conn,
            bot_user_id,
            conversations=catalog.conversations,
            folders=catalog.folders,
            folder_memberships=catalog.folder_memberships,
        )
        conn.commit()
    return load_cached_browser_state(settings, bot_user_id)


def start_dialog_cache_refresh(application: Any, settings: Settings, bot_user_id: int) -> None:
    if not hasattr(application, "bot_data"):
        return
    tasks = refresh_task_map(application)
    key = str(bot_user_id)
    existing = tasks.get(key)
    if existing is not None and not existing.done():
        return
    if not hasattr(application, "create_task"):
        return
    tasks[key] = application.create_task(refresh_dialog_cache_safely(settings, bot_user_id))


async def refresh_dialog_cache_safely(settings: Settings, bot_user_id: int) -> None:
    record_ux_event(settings, "dialog_cache_refresh_started", payload={"bot_user_id": bot_user_id})
    try:
        state = await refresh_dialog_cache(settings, bot_user_id)
        record_ux_event(
            settings,
            "dialog_cache_refresh_completed",
            payload={
                "bot_user_id": bot_user_id,
                "conversation_count": len(state.get("conversations") or []),
                "folder_count": len(state.get("folders") or []),
            },
        )
    except Exception as exc:
        LOGGER.debug("Dialog cache refresh failed: %s", exc.__class__.__name__)
        record_ux_event(
            settings,
            "dialog_cache_refresh_failed",
            payload={"bot_user_id": bot_user_id, "error_type": exc.__class__.__name__},
        )


def refresh_task_map(application: Any) -> dict[str, asyncio.Task]:
    bot_data = getattr(application, "bot_data", None)
    if not isinstance(bot_data, dict):
        return {}
    tasks = bot_data.setdefault(REFRESH_TASKS_KEY, {})
    if not isinstance(tasks, dict):
        tasks = {}
        bot_data[REFRESH_TASKS_KEY] = tasks
    return tasks
