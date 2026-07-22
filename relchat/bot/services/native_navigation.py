from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NAV_STACK_KEY = "native_navigation_stack"
NAV_TOKENS_KEY = "native_navigation_tokens"
NAV_TOKEN_COUNTER_KEY = "native_navigation_token_counter"
MAX_NAV_DEPTH = 12
MAX_TOKEN_COUNT = 80


@dataclass(frozen=True)
class NavigationEntry:
    screen_id: str
    payload: dict[str, Any]


def navigation_stack(user_data: dict[str, Any]) -> list[dict[str, Any]]:
    stack = user_data.setdefault(NAV_STACK_KEY, [])
    if not isinstance(stack, list):
        stack = []
        user_data[NAV_STACK_KEY] = stack
    return stack


def current_screen(user_data: dict[str, Any]) -> dict[str, Any] | None:
    stack = navigation_stack(user_data)
    return stack[-1] if stack else None


def push_screen(
    user_data: dict[str, Any],
    screen_id: str,
    *,
    payload: dict[str, Any] | None = None,
    replace: bool = False,
) -> None:
    stack = navigation_stack(user_data)
    entry = {"screen_id": screen_id, "payload": dict(payload or {})}
    if replace and stack:
        stack[-1] = entry
    elif stack and stack[-1].get("screen_id") == screen_id and stack[-1].get("payload") == entry["payload"]:
        return
    else:
        stack.append(entry)
    if len(stack) > MAX_NAV_DEPTH:
        del stack[: len(stack) - MAX_NAV_DEPTH]


def pop_back(user_data: dict[str, Any]) -> dict[str, Any] | None:
    stack = navigation_stack(user_data)
    if stack:
        stack.pop()
    return stack[-1] if stack else None


def reset_navigation(user_data: dict[str, Any]) -> None:
    user_data[NAV_STACK_KEY] = []
    clear_navigation_tokens(user_data)


def token_store(user_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    store = user_data.setdefault(NAV_TOKENS_KEY, {})
    if not isinstance(store, dict):
        store = {}
        user_data[NAV_TOKENS_KEY] = store
    return store


def register_nav_token(
    user_data: dict[str, Any],
    *,
    bot_user_id: int,
    payload: dict[str, Any],
    prefix: str = "s",
) -> str:
    store = token_store(user_data)
    counter = int(user_data.get(NAV_TOKEN_COUNTER_KEY) or 0) + 1
    user_data[NAV_TOKEN_COUNTER_KEY] = counter
    token = f"{prefix}{counter:x}"
    store[token] = {"bot_user_id": int(bot_user_id), "payload": dict(payload)}
    if len(store) > MAX_TOKEN_COUNT:
        for key in list(store.keys())[: len(store) - MAX_TOKEN_COUNT]:
            store.pop(key, None)
    return token


def resolve_nav_token(user_data: dict[str, Any], *, bot_user_id: int, token: str) -> dict[str, Any] | None:
    row = token_store(user_data).get(str(token))
    if not isinstance(row, dict):
        return None
    if int(row.get("bot_user_id") or 0) != int(bot_user_id):
        return None
    payload = row.get("payload")
    return dict(payload) if isinstance(payload, dict) else None


def clear_navigation_tokens(user_data: dict[str, Any]) -> None:
    user_data[NAV_TOKENS_KEY] = {}


def is_safe_callback_data(value: str) -> bool:
    if len(value) > 64:
        return False
    lowered = value.casefold()
    blocked = ["telegram", "chat_id=", "bot_user", "phone", "username"]
    if any(item in lowered for item in blocked):
        return False
    return True
