from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from relchat.config import Settings
from relchat.core.models import ConversationRef, Message
from relchat.telegram.client import make_client
from relchat.telegram.normalizer import entity_ref, normalize_dialog, normalize_entity, normalize_message


async def list_conversations(settings: Settings, limit: int) -> list[ConversationRef]:
    client = make_client(settings)
    await client.start()
    conversations: list[ConversationRef] = []
    try:
        async for dialog in client.iter_dialogs(limit=limit):
            conversations.append(normalize_dialog(dialog))
    finally:
        await client.disconnect()
    return conversations


async def get_conversation(settings: Settings, conversation_id: str) -> ConversationRef:
    client = make_client(settings)
    await client.start()
    try:
        entity = await client.get_entity(entity_ref(conversation_id))
        return normalize_entity(entity, conversation_id)
    finally:
        await client.disconnect()


async def iter_messages(
    settings: Settings,
    conversation_id: str,
    *,
    limit: int | None,
    since: datetime | None,
) -> AsyncIterator[Message]:
    client = make_client(settings)
    await client.start()
    entity = await client.get_entity(entity_ref(conversation_id))
    try:
        async for message in client.iter_messages(entity, limit=limit):
            if since and message.date and message.date < since:
                break
            sender = await message.get_sender() if getattr(message, "sender_id", None) else None
            yield normalize_message(message, conversation_id, sender)
    finally:
        await client.disconnect()
