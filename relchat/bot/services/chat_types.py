from __future__ import annotations

from typing import Any

from relchat.bot.localization import t


PRIVATE_HUMAN_TYPES = {"one_to_one", "private", "private_human", "person"}
BOT_TYPES = {"bot", "private_bot"}
GROUP_TYPES = {"group", "basic_group", "supergroup", "group_social"}
CHANNEL_TYPES = {"channel", "broadcast", "channel_or_broadcast"}
SELF_TYPES = {"self", "saved_messages"}
UNAVAILABLE_TYPES = {"deleted", "unavailable", "inaccessible"}


def raw_chat_type(value: Any) -> str:
    if hasattr(value, "conversation_type"):
        return str(getattr(value, "conversation_type") or "unknown")
    if isinstance(value, dict):
        return str(value.get("chat_type") or value.get("conversation_type") or "unknown")
    return str(value or "unknown")


def classify_chat_type(value: Any) -> str:
    raw = raw_chat_type(value)
    if raw in PRIVATE_HUMAN_TYPES:
        return "private_human"
    if raw in BOT_TYPES:
        return "bot"
    if raw in GROUP_TYPES:
        return "group"
    if raw in CHANNEL_TYPES:
        return "channel"
    if raw in SELF_TYPES:
        return "self"
    if raw in UNAVAILABLE_TYPES:
        return "unavailable"
    return "unknown"


def chat_category(value: Any) -> str:
    kind = classify_chat_type(value)
    if kind in {"private_human", "self"}:
        return "private"
    if kind == "group":
        return "groups"
    if kind == "channel":
        return "channels"
    if kind == "bot":
        return "bots"
    return "other"


def is_private_human(value: Any) -> bool:
    return classify_chat_type(value) == "private_human"


def is_private_supported(value: Any) -> bool:
    return classify_chat_type(value) in {"private_human", "self"}


def chat_type_icon(value: Any) -> str:
    return {
        "private_human": "👤",
        "self": "👤",
        "group": "👥",
        "channel": "📢",
        "bot": "🤖",
        "unavailable": "✕",
    }.get(classify_chat_type(value), "💬")


def chat_type_label(value: Any, *, language: str = "en") -> str:
    return t(language, f"nav_chat_type_{classify_chat_type(value)}")


def category_title(category: str, *, language: str = "en") -> str:
    key = {
        "private": "nav_private_chats",
        "groups": "nav_groups",
        "channels": "nav_channels",
        "bots": "nav_bots",
        "favorites": "nav_favorites",
        "recent": "nav_recent",
        "search": "nav_search",
        "all": "nav_all_chats",
    }.get(category, "nav_chats")
    return t(language, key)


def primary_analysis_button_key(chat_type: str | None, context_category: str | None = None) -> str:
    kind = classify_chat_type(chat_type)
    if kind == "channel":
        return "nav_analyze_channel"
    if kind == "group":
        return "nav_analyze_group"
    if context_category == "work":
        return "nav_analyze_effectiveness"
    return "nav_analyze_communication"
