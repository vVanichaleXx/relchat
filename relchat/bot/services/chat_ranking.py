from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from relchat.bot.guided import normalize_search
from relchat.bot.services.chat_types import chat_category, classify_chat_type


CATEGORY_ORDER = {
    "private": 0,
    "groups": 1,
    "channels": 2,
    "bots": 3,
    "other": 4,
}


@dataclass(frozen=True)
class RankedChat:
    chat: Any
    category: str
    rank_tuple: tuple[Any, ...]


def chat_value(chat: Any, key: str, default: Any = None) -> Any:
    if isinstance(chat, dict):
        return chat.get(key, default)
    if key == "chat_id":
        return getattr(chat, "conversation_id", default)
    if key == "chat_type":
        return getattr(chat, "conversation_type", default)
    if key == "title":
        return getattr(chat, "title", default)
    return getattr(chat, key, default)


def chat_title(chat: Any) -> str:
    return str(chat_value(chat, "title") or chat_value(chat, "display_title") or "")


def chat_recent_time(chat: Any) -> str:
    values = [
        chat_value(chat, "recent_analyzed_at"),
        chat_value(chat, "recent_opened_at"),
        chat_value(chat, "last_message_at"),
        chat_value(chat, "updated_at"),
    ]
    for value in values:
        if value:
            return str(value)
    return ""


def chat_rank_tuple(chat: Any, *, category: str | None = None) -> tuple[Any, ...]:
    selected_category = category or chat_category(chat)
    return (
        -int(bool(chat_value(chat, "is_pinned", False))),
        -int(bool(chat_value(chat, "is_favorite", False))),
        -int(bool(chat_value(chat, "recent_analyzed_at"))),
        -int(bool(chat_value(chat, "recent_opened_at"))),
        -int(bool(chat_value(chat, "last_message_at"))),
        CATEGORY_ORDER.get(selected_category, 9),
        _reverse_time_key(chat_recent_time(chat)),
        normalize_search(chat_title(chat)),
        str(chat_value(chat, "chat_id") or chat_value(chat, "conversation_id") or ""),
    )


def _reverse_time_key(value: str) -> str:
    # ISO timestamps sort lexicographically. Invert ASCII chars for ascending sort.
    return "".join(chr(255 - ord(char)) for char in value)


def rank_chats(chats: list[Any], *, category: str | None = None) -> list[Any]:
    return [item.chat for item in sorted((RankedChat(chat, chat_category(chat), chat_rank_tuple(chat, category=category)) for chat in chats), key=lambda item: item.rank_tuple)]


def quick_access_chats(chats: list[Any], *, limit: int = 5) -> list[Any]:
    candidates = [
        chat
        for chat in chats
        if classify_chat_type(chat) in {"private_human", "self"}
        and (
            bool(chat_value(chat, "is_pinned", False))
            or bool(chat_value(chat, "is_favorite", False))
            or bool(chat_value(chat, "recent_analyzed_at"))
            or bool(chat_value(chat, "recent_opened_at"))
        )
    ]
    return rank_chats(candidates, category="private")[: max(0, int(limit))]


def bounded_chats(chats: list[Any], *, limit: int) -> list[Any]:
    return rank_chats(chats)[: max(0, int(limit))]
