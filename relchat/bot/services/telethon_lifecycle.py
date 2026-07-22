from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Iterable
from contextlib import asynccontextmanager
from typing import Any, Callable


async def safe_disconnect(client: Any) -> None:
    if client is None:
        return
    disconnect = getattr(client, "disconnect", None)
    if disconnect is None:
        return
    result = disconnect()
    if inspect.isawaitable(result):
        await result


async def cancel_owned_tasks(tasks: Iterable[asyncio.Task]) -> list[Any]:
    owned = [task for task in tasks if task is not None and not task.done()]
    for task in owned:
        task.cancel()
    if not owned:
        return []
    return await asyncio.gather(*owned, return_exceptions=True)


@asynccontextmanager
async def owned_client(factory: Callable[[], Any]):
    client = factory()
    try:
        start = getattr(client, "start", None)
        if start is not None:
            result = start()
            if inspect.isawaitable(result):
                await result
        yield client
    finally:
        await safe_disconnect(client)


async def shutdown_analysis_tasks(application: Any) -> None:
    tasks = []
    bot_data = getattr(application, "bot_data", {}) or {}
    mapping = bot_data.get("relchat_analysis_tasks")
    if isinstance(mapping, dict):
        tasks.extend(task for task in mapping.values() if isinstance(task, asyncio.Task))
        mapping.clear()
    await cancel_owned_tasks(tasks)

