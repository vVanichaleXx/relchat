from __future__ import annotations

from dataclasses import dataclass, field


EventMetadataValue = str | int | float | bool | None


@dataclass(frozen=True)
class ConversationRef:
    """A source-agnostic conversation reference exposed by an importer."""

    source: str
    conversation_id: str
    conversation_type: str
    title: str | None = None
    last_message_at: str | None = None


@dataclass(frozen=True)
class Message:
    """A normalized message that analytics and future AI layers can consume."""

    source: str
    source_message_id: int
    conversation_id: str
    sender_id: str | None
    sender_name: str | None
    timestamp: str
    text: str
    message_type: str
    reply_to_message_id: int | None = None
    reactions: str | None = None
    media_type: str | None = None
    media_duration: float | None = None
    forward_info: str | None = None
    edit_date: str | None = None
    is_outgoing: bool = False
    raw_platform_payload_reference: str | None = None


@dataclass(frozen=True)
class ConversationEvent:
    """A source-agnostic event derived from normalized messages.

    Events intentionally do not carry message text. Interfaces can look up text
    from the original messages only when a user explicitly opts in.
    """

    source: str
    conversation_id: str
    event_type: str
    timestamp: str
    source_message_id: int | None = None
    sender_id: str | None = None
    sender_name: str | None = None
    related_message_id: int | None = None
    metadata: dict[str, EventMetadataValue] = field(default_factory=dict)
