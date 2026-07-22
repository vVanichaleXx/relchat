from __future__ import annotations

from typing import Any

from relchat.bot.guided import normalize_search
from relchat.bot.services.chat_ranking import chat_rank_tuple, chat_title, chat_value
from relchat.bot.services.chat_types import chat_category, chat_type_icon


TYPE_SEARCH_ORDER = {
    "private": 0,
    "groups": 3,
    "channels": 4,
    "bots": 5,
    "other": 6,
}


def chat_search_text(chat: Any) -> str:
    username = str(chat_value(chat, "username") or "")
    values = [chat_title(chat), username, f"@{username}" if username else ""]
    return normalize_search(" ".join(value for value in values if value))


def search_chats(chats: list[Any], query: str, *, limit: int | None = None) -> list[Any]:
    normalized = normalize_search(query)
    if not normalized:
        return []
    matches = [chat for chat in chats if normalized in chat_search_text(chat)]
    ranked = sorted(matches, key=lambda chat: search_rank_tuple(chat, normalized))
    if limit is None:
        return ranked
    return ranked[: max(0, int(limit))]


def search_rank_tuple(chat: Any, normalized_query: str) -> tuple[Any, ...]:
    text = chat_search_text(chat)
    category = chat_category(chat)
    exact = text == normalized_query or normalize_search(chat_title(chat)) == normalized_query
    prefix = text.startswith(normalized_query) or normalize_search(chat_title(chat)).startswith(normalized_query)
    if exact and category == "private":
        match_rank = 0
    elif prefix and category == "private":
        match_rank = 1
    elif category == "private":
        match_rank = 2
    elif exact:
        match_rank = TYPE_SEARCH_ORDER.get(category, 6)
    elif prefix:
        match_rank = TYPE_SEARCH_ORDER.get(category, 6) + 1
    else:
        match_rank = TYPE_SEARCH_ORDER.get(category, 6) + 2
    return (match_rank, chat_rank_tuple(chat, category=category))


def chat_search_label(chat: Any, *, limit: int = 44) -> str:
    title = chat_title(chat)
    if len(title) > limit:
        title = f"{title[: limit - 3]}..."
    return f"{chat_type_icon(chat)} {title or 'Chat'}"
