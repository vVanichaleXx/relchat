from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from relchat.config import Settings
from relchat.core.models import ConversationRef, DialogFolder, Message
from relchat.telegram.client import make_client
from relchat.telegram.normalizer import entity_ref, normalize_dialog, normalize_entity, normalize_message


@dataclass(frozen=True)
class ConversationCatalog:
    conversations: list[ConversationRef]
    folders: list[DialogFolder]
    folder_memberships: dict[int, set[str]]


async def list_conversations(
    settings: Settings,
    limit: int | None,
    *,
    folder_id: int | None = None,
) -> list[ConversationRef]:
    client = make_client(settings)
    await client.start()
    try:
        dialogs = await collect_dialogs(client, limit=limit)
        if folder_id is not None:
            dialog_filter = find_dialog_filter(await load_dialog_filter_items(client), folder_id)
            if dialog_filter is not None:
                dialogs = filter_dialogs_by_dialog_filter(dialogs, dialog_filter)
            else:
                dialogs = await collect_dialogs(client, limit=limit, folder=folder_id)
        return [normalize_dialog(dialog) for dialog in dialogs]
    finally:
        await client.disconnect()


async def load_conversation_catalog(settings: Settings, limit: int | None) -> ConversationCatalog:
    client = make_client(settings)
    await client.start()
    try:
        dialogs = await collect_dialogs(client, limit=limit)
        filters = await load_dialog_filter_items(client)
        conversations = [normalize_dialog(dialog) for dialog in dialogs]
        folders = normalize_dialog_folders(filters)
        memberships = dialog_folder_memberships(dialogs, filters)
        return ConversationCatalog(
            conversations=conversations,
            folders=folders,
            folder_memberships=memberships,
        )
    finally:
        await client.disconnect()


async def list_dialog_folders(settings: Settings) -> list[DialogFolder]:
    client = make_client(settings)
    await client.start()
    try:
        return normalize_dialog_folders(await load_dialog_filter_items(client))
    finally:
        await client.disconnect()


async def collect_dialogs(client: Any, *, limit: int | None, folder: int | None = None) -> list[Any]:
    dialogs: list[Any] = []
    kwargs: dict[str, Any] = {"limit": limit}
    if folder is not None:
        kwargs["folder"] = folder
    async for dialog in client.iter_dialogs(**kwargs):
        dialogs.append(dialog)
    return dialogs


async def load_dialog_filter_items(client: Any) -> list[Any]:
    try:
        from telethon import functions
    except ModuleNotFoundError:
        return []
    try:
        filters = await client(functions.messages.GetDialogFiltersRequest())
    except Exception:
        return []
    return dialog_filter_items(filters)


def dialog_filter_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    filters = getattr(value, "filters", None)
    if isinstance(filters, list):
        return filters
    try:
        return list(value)
    except TypeError:
        return []


def normalize_dialog_folders(filters: list[Any]) -> list[DialogFolder]:
    folders: list[DialogFolder] = []
    seen: set[int] = set()
    for item in filters:
        folder_id = getattr(item, "id", None)
        if folder_id is None:
            continue
        try:
            normalized_id = int(folder_id)
        except (TypeError, ValueError):
            continue
        if normalized_id in seen:
            continue
        title = dialog_folder_title(getattr(item, "title", None))
        if not title:
            continue
        seen.add(normalized_id)
        folders.append(DialogFolder(folder_id=normalized_id, title=title))
    return folders


def dialog_folder_title(value: Any) -> str | None:
    if value is None:
        return None
    text = getattr(value, "text", None)
    if text:
        return str(text)
    if isinstance(value, str):
        return value
    return str(value)


def find_dialog_filter(filters: list[Any], folder_id: int) -> Any | None:
    for item in filters:
        try:
            item_id = int(getattr(item, "id"))
        except (AttributeError, TypeError, ValueError):
            continue
        if item_id == folder_id:
            return item
    return None


def filter_dialogs_by_dialog_filter(dialogs: list[Any], dialog_filter: Any) -> list[Any]:
    return [dialog for dialog in dialogs if dialog_matches_filter(dialog, dialog_filter)]


def dialog_folder_memberships(dialogs: list[Any], filters: list[Any]) -> dict[int, set[str]]:
    memberships: dict[int, set[str]] = {}
    for dialog in dialogs:
        folder_id = getattr(dialog, "folder_id", None)
        try:
            normalized_folder_id = int(folder_id) if folder_id is not None else None
        except (TypeError, ValueError):
            normalized_folder_id = None
        if normalized_folder_id is not None:
            memberships.setdefault(normalized_folder_id, set()).add(str(dialog.id))
    for dialog_filter in filters:
        try:
            folder_id = int(getattr(dialog_filter, "id"))
        except (AttributeError, TypeError, ValueError):
            continue
        matched = {str(dialog.id) for dialog in filter_dialogs_by_dialog_filter(dialogs, dialog_filter)}
        if matched:
            memberships.setdefault(folder_id, set()).update(matched)
    return memberships


def dialog_matches_filter(dialog: Any, dialog_filter: Any) -> bool:
    peer_key = telegram_peer_key(getattr(dialog, "entity", None)) or telegram_peer_key(dialog)
    if peer_key and peer_key in dialog_filter_peer_keys(dialog_filter, "exclude_peers"):
        return False
    if getattr(dialog_filter, "exclude_archived", False) and dialog_is_archived(dialog):
        return False
    if getattr(dialog_filter, "exclude_muted", False) and dialog_is_muted(dialog):
        return False
    if getattr(dialog_filter, "exclude_read", False) and safe_int(getattr(dialog, "unread_count", 0)) <= 0:
        return False

    included_peers = dialog_filter_peer_keys(dialog_filter, "include_peers") | dialog_filter_peer_keys(dialog_filter, "pinned_peers")
    if peer_key and peer_key in included_peers:
        return True

    entity = getattr(dialog, "entity", None)
    if dialog_is_user(dialog):
        if getattr(entity, "bot", False):
            return bool(getattr(dialog_filter, "bots", False))
        if getattr(entity, "contact", False):
            return bool(getattr(dialog_filter, "contacts", False))
        return bool(getattr(dialog_filter, "non_contacts", False))
    if dialog_is_group(dialog):
        return bool(getattr(dialog_filter, "groups", False))
    if dialog_is_broadcast(dialog):
        return bool(getattr(dialog_filter, "broadcasts", False))
    return False


def dialog_filter_peer_keys(dialog_filter: Any, attr: str) -> set[str]:
    return {key for key in (telegram_peer_key(peer) for peer in getattr(dialog_filter, attr, []) or []) if key}


def telegram_peer_key(value: Any) -> str | None:
    if value is None:
        return None
    try:
        from telethon import utils

        return str(utils.get_peer_id(value))
    except Exception:
        pass
    for attr in ("user_id", "chat_id", "channel_id", "id"):
        raw = getattr(value, attr, None)
        if raw is not None:
            try:
                return str(int(raw))
            except (TypeError, ValueError):
                return str(raw)
    return None


def dialog_is_user(dialog: Any) -> bool:
    if getattr(dialog, "is_user", False):
        return True
    entity = getattr(dialog, "entity", None)
    return hasattr(entity, "first_name") or hasattr(entity, "last_name")


def dialog_is_group(dialog: Any) -> bool:
    if getattr(dialog, "is_group", False):
        return True
    entity = getattr(dialog, "entity", None)
    if getattr(entity, "broadcast", False):
        return False
    return bool(getattr(entity, "megagroup", False) or hasattr(entity, "participants_count"))


def dialog_is_broadcast(dialog: Any) -> bool:
    entity = getattr(dialog, "entity", None)
    if getattr(entity, "broadcast", False):
        return True
    return bool(getattr(dialog, "is_channel", False) and not dialog_is_group(dialog))


def dialog_is_archived(dialog: Any) -> bool:
    if getattr(dialog, "archived", False):
        return True
    try:
        return int(getattr(dialog, "folder_id", 0) or 0) == 1
    except (TypeError, ValueError):
        return False


def dialog_is_muted(dialog: Any) -> bool:
    value = getattr(dialog, "is_muted", None)
    if value is not None:
        return bool(value)
    settings = getattr(dialog, "notify_settings", None)
    mute_until = getattr(settings, "mute_until", None)
    if mute_until is None:
        return False
    if isinstance(mute_until, datetime):
        return mute_until > datetime.now(mute_until.tzinfo or None)
    try:
        return int(mute_until) > int(datetime.now().timestamp())
    except (TypeError, ValueError):
        return bool(mute_until)


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
