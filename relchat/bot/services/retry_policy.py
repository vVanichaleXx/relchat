from __future__ import annotations

import asyncio
import random
import socket
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


FAILURE_CATEGORIES = {
    "telegram_temporary",
    "telegram_auth",
    "telegram_rate_limit",
    "telegram_internal",
    "network_dns",
    "provider_timeout",
    "provider_rate_limit",
    "provider_invalid_response",
    "database_locked",
    "validation_error",
    "cancelled",
    "unknown",
}
TRANSIENT_FAILURES = {
    "telegram_temporary",
    "telegram_rate_limit",
    "telegram_internal",
    "network_dns",
    "provider_timeout",
    "provider_rate_limit",
    "database_locked",
}


@dataclass(frozen=True)
class RetryDecision:
    category: str
    transient: bool
    should_retry: bool
    attempt: int
    max_attempts: int
    delay_seconds: float


def classify_failure(exc: BaseException) -> str:
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    name = exc.__class__.__name__.casefold()
    text = str(exc).casefold()
    code = str(getattr(exc, "code", "") or "").casefold()
    combined = f"{name} {text} {code}"
    if any(term in combined for term in ("auth", "unauthorized", "sessionpassword", "phonecod", "revoked")):
        return "telegram_auth" if "telegram" in combined or "session" in combined else "validation_error"
    if any(term in combined for term in ("floodwait", "flood_wait", "rate limit", "ratelimit", "too many requests")):
        return "telegram_rate_limit" if "telegram" in combined or "flood" in combined else "provider_rate_limit"
    if any(term in combined for term in ("rpccallfail", "server error", "internal", "temporarily unavailable", "temporary")):
        return "telegram_internal" if "telegram" in combined or "rpc" in combined else "telegram_temporary"
    if isinstance(exc, (socket.gaierror, ConnectionError, TimeoutError, OSError)) and any(term in combined for term in ("dns", "gaierror", "name resolution", "connecterror", "network", "connection")):
        return "network_dns"
    if "database is locked" in combined or "sqlite_busy" in combined:
        return "database_locked"
    if any(term in combined for term in ("timeout", "timed out")):
        return "provider_timeout"
    if any(term in combined for term in ("invalid response", "malformed_output", "schema", "validation")):
        return "provider_invalid_response" if "provider" in combined or "openai" in combined else "validation_error"
    if any(term in combined for term in ("forbidden", "notfound", "deleted", "private")):
        return "validation_error"
    return "unknown"


def is_transient_failure(category: str) -> bool:
    return category in TRANSIENT_FAILURES


def retry_decision(exc: BaseException, *, attempt: int, max_attempts: int, base_delay: float = 0.5, jitter: float = 0.25) -> RetryDecision:
    category = classify_failure(exc)
    transient = is_transient_failure(category)
    should_retry = transient and attempt < max_attempts
    delay = retry_delay_seconds(attempt, base_delay=base_delay, jitter=jitter) if should_retry else 0.0
    return RetryDecision(
        category=category,
        transient=transient,
        should_retry=should_retry,
        attempt=attempt,
        max_attempts=max_attempts,
        delay_seconds=delay,
    )


def retry_delay_seconds(attempt: int, *, base_delay: float = 0.5, jitter: float = 0.25) -> float:
    exponent = max(0, int(attempt) - 1)
    return round(base_delay * (2**exponent) + random.uniform(0.0, max(0.0, jitter)), 3)


async def run_with_retries(
    operation: Callable[[], Awaitable[Any]],
    *,
    max_attempts: int = 3,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    on_retry: Callable[[RetryDecision], Awaitable[Any] | None] | None = None,
    base_delay: float = 0.5,
    jitter: float = 0.25,
) -> Any:
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return await operation()
        except BaseException as exc:
            decision = retry_decision(exc, attempt=attempt, max_attempts=max_attempts, base_delay=base_delay, jitter=jitter)
            if not decision.should_retry:
                raise
            if on_retry is not None:
                maybe = on_retry(decision)
                if maybe is not None:
                    await maybe
            await sleep(decision.delay_seconds)
    raise RuntimeError("retry_exhausted")

