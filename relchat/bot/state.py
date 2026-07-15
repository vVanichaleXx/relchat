from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


ANALYSIS_FLOW = "analysis_flow"
CHAT_BROWSER = "chat_browser"
AWAITING_TEXT = "awaiting_text"
RENAME_CHAT_TARGET = "rename_chat_target"
EDIT_REMINDER_TARGET = "edit_reminder_target"

JOB_RUNNING_STATES = {"queued", "loading", "importing", "analyzing"}
JOB_DONE_STATES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class PeriodOption:
    period_id: str
    label: str
    days: int | None
    full_history: bool = False
    custom: bool = False


@dataclass(frozen=True)
class AnalysisModule:
    module_id: str
    label: str
    coming_soon: bool = False


PERIOD_OPTIONS = [
    PeriodOption("7d", "7 days", 7),
    PeriodOption("30d", "30 days", 30),
    PeriodOption("90d", "90 days", 90),
    PeriodOption("365d", "1 year", 365),
    PeriodOption("full", "Full history", None, full_history=True),
    PeriodOption("custom", "Custom date range", None, custom=True),
]

PERIOD_BY_ID = {option.period_id: option for option in PERIOD_OPTIONS}

ANALYSIS_MODULES = [
    AnalysisModule("balance", "Conversation balance"),
    AnalysisModule("initiation", "Initiation"),
    AnalysisModule("response_times", "Response times"),
    AnalysisModule("activity", "Message activity"),
    AnalysisModule("questions", "Questions and unanswered questions"),
    AnalysisModule("plans", "Plans and promises"),
    AnalysisModule("followups", "Follow-up candidates"),
    AnalysisModule("reminders", "Important dates and reminders"),
    AnalysisModule("topics", "Topic analysis", coming_soon=True),
]

MODULE_BY_ID = {module.module_id: module for module in ANALYSIS_MODULES}
RUNNABLE_MODULE_IDS = [module.module_id for module in ANALYSIS_MODULES if not module.coming_soon]
DEFAULT_MODULE_IDS = RUNNABLE_MODULE_IDS.copy()


def period_label(period_id: str, *, custom_start: str | None = None, custom_end: str | None = None) -> str:
    if period_id == "custom":
        if custom_start and custom_end:
            return f"{custom_start} to {custom_end}"
        if custom_start:
            return f"From {custom_start}"
        return "Custom date range"
    option = PERIOD_BY_ID.get(period_id)
    return option.label if option else period_id


def period_start(period_id: str, *, now: datetime | None = None) -> datetime | None:
    option = PERIOD_BY_ID.get(period_id)
    if option is None or option.days is None:
        return None
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return anchor - timedelta(days=option.days)


def normalize_module_selection(values: list[str] | None) -> list[str]:
    selected = []
    for value in values or DEFAULT_MODULE_IDS:
        module = MODULE_BY_ID.get(value)
        if module is not None and not module.coming_soon and value not in selected:
            selected.append(value)
    return selected or DEFAULT_MODULE_IDS.copy()


def module_label(module_id: str) -> str:
    module = MODULE_BY_ID.get(module_id)
    return module.label if module else module_id


def module_labels(module_ids: list[str]) -> list[str]:
    return [module_label(module_id) for module_id in module_ids]


def parse_user_date(value: str, *, now: datetime | None = None) -> datetime | None:
    text = " ".join(value.strip().lower().split())
    if not text:
        return None
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    if text.endswith(" days") or text.endswith(" day"):
        number = text.split()[0]
        if number.isdigit():
            return anchor - timedelta(days=int(number))
    if text.endswith("d") and text[:-1].isdigit():
        return anchor - timedelta(days=int(text[:-1]))
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def iso_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.date().isoformat()


def callback_parts(data: str | None) -> list[str]:
    if not data or not data.startswith("rc:"):
        return []
    return data.split(":")


def set_flow_value(user_data: dict[str, Any], key: str, value: Any) -> None:
    flow = user_data.setdefault(ANALYSIS_FLOW, {})
    if isinstance(flow, dict):
        flow[key] = value


def get_flow(user_data: dict[str, Any]) -> dict[str, Any]:
    flow = user_data.setdefault(ANALYSIS_FLOW, {})
    if not isinstance(flow, dict):
        flow = {}
        user_data[ANALYSIS_FLOW] = flow
    return flow


def clear_flow(user_data: dict[str, Any]) -> None:
    user_data.pop(ANALYSIS_FLOW, None)
    user_data.pop(AWAITING_TEXT, None)
    user_data.pop(RENAME_CHAT_TARGET, None)
    user_data.pop(EDIT_REMINDER_TARGET, None)
