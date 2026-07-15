from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from relchat.core.models import ConversationRef


PAGE_SIZE = 10
GUIDED_DIALOG_FETCH_LIMIT = None
STATE_CONVERSATIONS = "guided_conversations"
STATE_FILTERED_CONVERSATIONS = "guided_filtered_conversations"
STATE_FOLDERS = "guided_folders"
STATE_CATEGORY = "guided_category"
STATE_PAGE = "guided_page"
STATE_AWAITING_SEARCH = "guided_awaiting_search"
STATE_SEARCH_QUERY = "guided_search_query"
STATE_SELECTED_CHAT_ID = "guided_selected_chat_id"
STATE_SELECTED_CHAT_TITLE = "guided_selected_chat_title"
STATE_SELECTED_CHAT_TYPE = "guided_selected_chat_type"
STATE_SELECTED_PERIOD_ID = "guided_selected_period_id"
STATE_SELECTED_PERIOD_LABEL = "guided_selected_period_label"
STATE_SELECTED_PERIOD_WARNING = "guided_selected_period_warning"
STATE_RECENT_REPORTS = "guided_recent_reports"


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


@dataclass(frozen=True)
class PeriodOption:
    period_id: str
    label: str
    days: int | None
    full_history: bool = False
    custom_later: bool = False

    @property
    def warning(self) -> str | None:
        if self.full_history:
            return "Full history may take time for large chats."
        return None


@dataclass(frozen=True)
class CallbackRoute:
    action: str
    value: str | None = None


PERIOD_OPTIONS = {
    "30d": PeriodOption("30d", "Last 30 days", 30),
    "90d": PeriodOption("90d", "Last 90 days", 90),
    "365d": PeriodOption("365d", "Last year", 365),
    "full": PeriodOption("full", "Full history", None, full_history=True),
    "custom": PeriodOption("custom", "Custom later", None, custom_later=True),
}


def sort_conversations(conversations: list[ConversationRef]) -> list[ConversationRef]:
    return sorted(conversations, key=conversation_recency_sort_key, reverse=True)


def conversation_recency_sort_key(conversation: ConversationRef) -> tuple[int, str]:
    return (1 if conversation.last_message_at else 0, conversation.last_message_at or "")


def filter_conversations(conversations: list[ConversationRef], category: str) -> list[ConversationRef]:
    if category == "all":
        return sort_conversations(conversations)
    if category == "private":
        return filter_by_type(conversations, "one_to_one")
    if category == "groups":
        return filter_by_type(conversations, "group")
    if category == "channels":
        return filter_by_type(conversations, "channel")
    if category == "unread":
        return sort_conversations([conversation for conversation in conversations if conversation.unread_count > 0])
    if category.startswith("folder:"):
        folder_id = parse_int(category.removeprefix("folder:"))
        if folder_id is None:
            return []
        return sort_conversations([conversation for conversation in conversations if conversation.folder_id == folder_id])
    return []


def filter_by_type(conversations: list[ConversationRef], conversation_type: str) -> list[ConversationRef]:
    return sort_conversations(
        [conversation for conversation in conversations if conversation.conversation_type == conversation_type]
    )


def search_conversations(conversations: list[ConversationRef], query: str) -> list[ConversationRef]:
    normalized = normalize_search(query)
    if not normalized:
        return []
    return sort_conversations(
        [conversation for conversation in conversations if normalized in conversation_search_text(conversation)]
    )


def conversation_search_text(conversation: ConversationRef) -> str:
    values = [
        conversation.title or "",
        conversation.username or "",
        f"@{conversation.username}" if conversation.username else "",
    ]
    return normalize_search(" ".join(values))


def normalize_search(value: str) -> str:
    return " ".join(value.casefold().split())


def paginate_conversations(
    conversations: list[ConversationRef],
    page: int,
    *,
    page_size: int = PAGE_SIZE,
) -> Page:
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    total = len(conversations)
    max_page = max(0, (total - 1) // page_size)
    normalized_page = min(max(page, 0), max_page)
    start = normalized_page * page_size
    return Page(
        items=conversations[start : start + page_size],
        page=normalized_page,
        total=total,
        page_size=page_size,
    )


def parse_callback(data: str | None) -> CallbackRoute:
    if not data:
        return CallbackRoute("unknown")
    exact = {
        "rc:main:analyze": CallbackRoute("main", "analyze"),
        "rc:main:recent": CallbackRoute("main", "recent"),
        "rc:main:status": CallbackRoute("main", "status"),
        "rc:main:help": CallbackRoute("main", "help"),
        "rc:back:main": CallbackRoute("back", "main"),
        "rc:back:categories": CallbackRoute("back", "categories"),
        "rc:back:list": CallbackRoute("back", "list"),
        "rc:cancel": CallbackRoute("cancel"),
        "rc:search:start": CallbackRoute("search", "start"),
        "rc:confirm:import": CallbackRoute("confirm", "import"),
        "rc:page:previous": CallbackRoute("page", "previous"),
        "rc:page:next": CallbackRoute("page", "next"),
    }
    if data in exact:
        return exact[data]
    for prefix, action in [
        ("rc:cat:", "category"),
        ("rc:folder:", "folder"),
        ("rc:select:", "select"),
        ("rc:period:", "period"),
    ]:
        if data.startswith(prefix):
            value = data.removeprefix(prefix)
            return CallbackRoute(action, value or None)
    return CallbackRoute("unknown")


def period_option(period_id: str) -> PeriodOption | None:
    return PERIOD_OPTIONS.get(period_id)


def period_since(option: PeriodOption, *, now: datetime | None = None) -> datetime | None:
    if option.days is None:
        return None
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return anchor - timedelta(days=option.days)


def build_confirmation_state(conversation: ConversationRef, option: PeriodOption) -> dict[str, Any]:
    return {
        STATE_SELECTED_CHAT_ID: conversation.conversation_id,
        STATE_SELECTED_CHAT_TITLE: conversation.title,
        STATE_SELECTED_CHAT_TYPE: conversation.conversation_type,
        STATE_SELECTED_PERIOD_ID: option.period_id,
        STATE_SELECTED_PERIOD_LABEL: option.label,
        STATE_SELECTED_PERIOD_WARNING: option.warning,
    }


def parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def recent_report_entry(
    *,
    chat_title: str | None,
    period_label: str,
    message_count: int,
    event_count: int,
) -> dict[str, Any]:
    return {
        "chat_title": chat_title,
        "period_label": period_label,
        "message_count": message_count,
        "event_count": event_count,
    }
