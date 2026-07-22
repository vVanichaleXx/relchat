from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from relchat.bot.localization import t
from relchat.core.models import Message


BALANCED_MAX_MAJOR_SHARE = 0.58
MIN_MESSAGES_FOR_PARTICIPATION = 6


def build_participation_interpretation(
    messages: Sequence[Message],
    *,
    history_segments: dict[str, Any] | None = None,
    language: str = "en",
) -> dict[str, Any]:
    full = interpret_participation_counts(
        sum(1 for message in messages if message.is_outgoing),
        sum(1 for message in messages if not message.is_outgoing),
        scope="full_history" if is_full_history_scope(history_segments) else "selected_period",
        language=language,
    )
    recent = recent_window_interpretation(history_segments, language=language)
    if recent and full.get("status") != recent.get("status"):
        summary = t(language, "participation_scoped_difference", full=full["summary"], recent=recent["summary"])
        has_scope_difference = True
    else:
        summary = full["summary"]
        has_scope_difference = False
    return {
        "model": "participation_interpretation_v1",
        "neutral_major_share_max": BALANCED_MAX_MAJOR_SHARE,
        "status": full["status"],
        "scope": full["scope"],
        "summary": summary,
        "full_history": full,
        "recent_window": recent or {},
        "has_scope_difference": has_scope_difference,
    }


def interpret_participation_counts(
    outgoing_count: int,
    incoming_count: int,
    *,
    scope: str,
    language: str = "en",
) -> dict[str, Any]:
    outgoing = max(0, int(outgoing_count))
    incoming = max(0, int(incoming_count))
    total = outgoing + incoming
    if total < MIN_MESSAGES_FOR_PARTICIPATION:
        status = "insufficient_data"
    else:
        majority = max(outgoing, incoming) / max(1, total)
        if majority <= BALANCED_MAX_MAJOR_SHARE:
            status = "balanced"
        elif outgoing > incoming:
            status = "you_more"
        else:
            status = "other_more"
    user_share = outgoing / max(1, total)
    return {
        "scope": scope,
        "status": status,
        "outgoing_count": outgoing,
        "incoming_count": incoming,
        "message_count": total,
        "user_share": round(user_share, 3),
        "other_share": round(1.0 - user_share, 3) if total else 0.0,
        "summary": participation_summary(status, scope=scope, outgoing_count=outgoing, incoming_count=incoming, user_share=user_share, language=language),
    }


def recent_window_interpretation(history_segments: dict[str, Any] | None, *, language: str) -> dict[str, Any] | None:
    row = history_segments if isinstance(history_segments, dict) else {}
    windows = row.get("windows") if isinstance(row.get("windows"), list) else []
    if not row.get("segmented") or not windows:
        return None
    recent = windows[-1] if isinstance(windows[-1], dict) else {}
    if not recent:
        return None
    return interpret_participation_counts(
        int(recent.get("outgoing_count") or 0),
        int(recent.get("incoming_count") or 0),
        scope="recent_window",
        language=language,
    )


def participation_summary(
    status: str,
    *,
    scope: str,
    outgoing_count: int,
    incoming_count: int,
    user_share: float,
    language: str,
) -> str:
    scope_prefix = participation_scope_label(scope, language=language)
    if status == "balanced":
        return t(language, "participation_summary_balanced", scope=scope_prefix, you=outgoing_count, other=incoming_count)
    if status == "you_more":
        return t(language, "participation_summary_you_more", scope=scope_prefix, share=f"{user_share * 100:.0f}")
    if status == "other_more":
        return t(language, "participation_summary_other_more", scope=scope_prefix, share=f"{(1.0 - user_share) * 100:.0f}")
    return t(language, "participation_summary_insufficient", scope=scope_prefix)


def participation_scope_label(scope: str, *, language: str) -> str:
    key = {
        "full_history": "participation_scope_full_history",
        "recent_window": "participation_scope_recent_window",
        "selected_period": "participation_scope_selected_period",
        "recurring_across_periods": "participation_scope_recurring",
    }.get(scope, "participation_scope_selected_period")
    return t(language, key)


def is_full_history_scope(history_segments: dict[str, Any] | None) -> bool:
    row = history_segments if isinstance(history_segments, dict) else {}
    if row.get("segmented"):
        return True
    label = str(row.get("period_label") or "").casefold()
    return "full" in label or "вся" in label


def validate_participation_interpretation(value: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    row = value if isinstance(value, dict) else fallback or {}
    full = row.get("full_history") if isinstance(row.get("full_history"), dict) else {}
    recent = row.get("recent_window") if isinstance(row.get("recent_window"), dict) else {}
    return {
        "model": "participation_interpretation_v1",
        "neutral_major_share_max": BALANCED_MAX_MAJOR_SHARE,
        "status": normalize_status(row.get("status") or full.get("status")),
        "scope": normalize_scope(row.get("scope") or full.get("scope")),
        "summary": str(row.get("summary") or full.get("summary") or ""),
        "full_history": validate_scope_row(full),
        "recent_window": validate_scope_row(recent) if recent else {},
        "has_scope_difference": bool(row.get("has_scope_difference")),
    }


def validate_scope_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": normalize_scope(row.get("scope")),
        "status": normalize_status(row.get("status")),
        "outgoing_count": safe_int(row.get("outgoing_count")),
        "incoming_count": safe_int(row.get("incoming_count")),
        "message_count": safe_int(row.get("message_count")),
        "user_share": safe_float(row.get("user_share")),
        "other_share": safe_float(row.get("other_share")),
        "summary": str(row.get("summary") or ""),
    }


def normalize_status(value: Any) -> str:
    text = str(value or "insufficient_data")
    return text if text in {"balanced", "you_more", "other_more", "insufficient_data"} else "insufficient_data"


def normalize_scope(value: Any) -> str:
    text = str(value or "selected_period")
    return text if text in {"selected_period", "full_history", "recent_window", "recurring_across_periods"} else "selected_period"


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value or 0.0))), 3)
    except (TypeError, ValueError):
        return 0.0
