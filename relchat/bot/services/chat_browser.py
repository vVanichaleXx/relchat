from __future__ import annotations

from dataclasses import dataclass

from relchat.bot.guided import normalize_search, parse_int
from relchat.core.models import ConversationRef


PAGE_SIZE = 10


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
