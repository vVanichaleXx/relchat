from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from relchat.analytics.metrics import SESSION_GAP_HOURS, parse_ts, summarize
from relchat.bot.localization import t
from relchat.bot.services.ai_analysis import (
    ANALYSIS_VERSION,
    build_deterministic_dimensions,
    communication_score_from_dimensions,
)
from relchat.core.models import ConversationEvent, Message
from relchat.events.extractor import extract_events, summarize_events


MIN_COMPARABLE_MESSAGES = 10
MAX_DURATION_RATIO = 1.5
STABLE_RELATIVE_CHANGE = 0.12


@dataclass(frozen=True)
class PeriodBundle:
    source: str
    chat_id: str
    label: str
    metrics: dict[str, Any]
    event_summary: dict[str, Any]
    message_count: int
    start: datetime | None = None
    end: datetime | None = None
    analysis_version: str = ANALYSIS_VERSION
    report_id: str | None = None
    analysis_id: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.start is None or self.end is None:
            return None
        return max(0.0, (self.end - self.start).total_seconds())


METRIC_SPECS: dict[str, dict[str, Any]] = {
    "message_count": {"rule": "neutral", "importance": "low"},
    "sessions_started_by_you": {"rule": "neutral", "importance": "low"},
    "sessions_started_by_other": {"rule": "higher_better", "importance": "medium"},
    "initiative_balance": {"rule": "closer_to_balance", "importance": "high"},
    "response_time": {"rule": "lower_better_with_evidence", "importance": "medium"},
    "response_consistency": {"rule": "higher_better", "importance": "medium"},
    "average_reply_length": {"rule": "reply_length", "importance": "medium"},
    "question_engagement": {"rule": "higher_better", "importance": "high"},
    "unanswered_question_rate": {"rule": "lower_better", "importance": "high"},
    "topic_continuation": {"rule": "higher_better", "importance": "medium"},
    "planning_activity": {"rule": "higher_better", "importance": "low"},
    "follow_up_activity": {"rule": "lower_better", "importance": "medium"},
    "sarcasm_intensity": {"rule": "lower_better", "importance": "medium"},
    "dismissive_low_effort_patterns": {"rule": "lower_better", "importance": "high"},
    "pressure_risk": {"rule": "lower_better", "importance": "high"},
    "communication_score": {"rule": "higher_better", "importance": "high"},
}


def compare_current_vs_previous_session(messages: Sequence[Message], *, chat_type: str = "one_to_one") -> dict[str, Any]:
    sessions = split_sessions(messages)
    if len(sessions) < 2:
        return insufficient_result("current_vs_previous_session", "not_enough_periods")
    previous = bundle_from_messages(sessions[-2], label="previous conversation session", chat_type=chat_type)
    current = bundle_from_messages(sessions[-1], label="current conversation session", chat_type=chat_type)
    return compare_bundles(previous, current, comparison_type="current_vs_previous_session")


def compare_last_days(
    messages: Sequence[Message],
    *,
    days: int,
    now: datetime | None = None,
    chat_type: str = "one_to_one",
) -> dict[str, Any]:
    if days not in {7, 30}:
        raise ValueError("Only 7-day and 30-day comparisons are supported.")
    anchor = normalize_dt(now or datetime.now(timezone.utc))
    current_start = anchor - timedelta(days=days)
    previous_start = anchor - timedelta(days=days * 2)
    previous_messages = messages_in_range(messages, previous_start, current_start)
    current_messages = messages_in_range(messages, current_start, anchor)
    previous = bundle_from_messages(previous_messages, label=f"previous {days} days", chat_type=chat_type, start=previous_start, end=current_start)
    current = bundle_from_messages(current_messages, label=f"last {days} days", chat_type=chat_type, start=current_start, end=anchor)
    return compare_bundles(previous, current, comparison_type=f"{days}d")


def compare_report_to_previous(report: dict[str, Any], previous_reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    previous = select_previous_comparable_report(report, previous_reports)
    if previous is None:
        current = bundle_from_report(report)
        reason = first_incomparable_reason(current, [bundle_from_report(item) for item in previous_reports])
        return insufficient_result("selected_report_vs_previous", reason)
    return compare_bundles(
        bundle_from_report(previous),
        bundle_from_report(report),
        comparison_type="selected_report_vs_previous",
    )


def compare_latest_analysis_to_previous(analysis: dict[str, Any], previous_analyses: Sequence[dict[str, Any]]) -> dict[str, Any]:
    previous = select_previous_comparable_analysis(analysis, previous_analyses)
    if previous is None:
        current = bundle_from_analysis(analysis)
        reason = first_incomparable_reason(current, [bundle_from_analysis(item) for item in previous_analyses])
        return insufficient_result("latest_analysis_vs_previous", reason)
    return compare_bundles(
        bundle_from_analysis(previous),
        bundle_from_analysis(analysis),
        comparison_type="latest_analysis_vs_previous",
    )


def select_previous_comparable_report(report: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    current = bundle_from_report(report)
    for candidate in candidates:
        if candidate.get("report_id") == report.get("report_id"):
            continue
        previous = bundle_from_report(candidate)
        if comparable_periods(previous, current)[0]:
            return candidate
    return None


def select_previous_comparable_analysis(analysis: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    current = bundle_from_analysis(analysis)
    for candidate in candidates:
        if candidate.get("analysis_id") == analysis.get("analysis_id"):
            continue
        previous = bundle_from_analysis(candidate)
        if comparable_periods(previous, current)[0]:
            return candidate
    return None


def first_incomparable_reason(current: PeriodBundle, candidates: Sequence[PeriodBundle]) -> str:
    for previous in candidates:
        if previous.source != current.source or previous.chat_id != current.chat_id:
            continue
        comparable, reason = comparable_periods(previous, current)
        if not comparable:
            return reason
    return "not_enough_comparable_data"


def compare_bundles(previous: PeriodBundle, current: PeriodBundle, *, comparison_type: str) -> dict[str, Any]:
    comparable, reason = comparable_periods(previous, current)
    if not comparable:
        return insufficient_result(comparison_type, reason, previous=previous, current=current)
    previous_values = comparable_metric_values(previous)
    current_values = comparable_metric_values(current)
    rows = []
    for metric, spec in METRIC_SPECS.items():
        row = compare_metric(metric, previous_values.get(metric), current_values.get(metric), spec)
        rows.append(row)
    main_changes = meaningful_changes(rows)
    overall = overall_direction(rows)
    return {
        "status": "ok",
        "quality": "strong" if previous.message_count >= 30 and current.message_count >= 30 else "limited",
        "comparison_type": comparison_type,
        "analysis_version": ANALYSIS_VERSION,
        "previous": period_metadata(previous),
        "current": period_metadata(current),
        "metrics": rows,
        "main_changes": main_changes,
        "overall_direction": overall,
        "overall_explanation": overall_explanation(overall),
    }


def comparable_periods(previous: PeriodBundle, current: PeriodBundle) -> tuple[bool, str]:
    if previous.source != current.source or previous.chat_id != current.chat_id:
        return False, "different_chat"
    if previous.message_count < MIN_COMPARABLE_MESSAGES or current.message_count < MIN_COMPARABLE_MESSAGES:
        return False, "not_enough_messages"
    if previous.analysis_version != current.analysis_version:
        return False, "analysis_version_mismatch"
    previous_duration = previous.duration_seconds
    current_duration = current.duration_seconds
    if previous_duration is not None and current_duration is not None:
        shorter = max(1.0, min(previous_duration, current_duration))
        longer = max(previous_duration, current_duration)
        if longer / shorter > MAX_DURATION_RATIO:
            return False, "duration_mismatch"
    elif previous.report_id or current.report_id or previous.analysis_id or current.analysis_id:
        return False, "unknown_coverage"
    return True, "ok"


def comparable_metric_values(bundle: PeriodBundle) -> dict[str, Any]:
    metrics = bundle.metrics
    events = bundle.event_summary.get("by_type") if "by_type" in bundle.event_summary else bundle.event_summary
    dimensions = metrics.get("dimensions") if isinstance(metrics.get("dimensions"), dict) else {}
    initiation = metrics.get("initiation_balance") or {}
    by_sender = initiation.get("by_sender") or {}
    response = response_rollup(metrics)
    avg_length = average_reply_length_other(metrics)
    question_count = int(metrics.get("question_count") or 0)
    unanswered_count = int(metrics.get("unanswered_question_count") or len(metrics.get("unanswered_questions") or []))
    score = metrics.get("communication_score")
    if score is None and dimensions:
        score = communication_score_from_dimensions(dimensions, message_count=bundle.message_count).get("score")
    return {
        "message_count": bundle.message_count,
        "sessions_started_by_you": int(by_sender.get("YOU") or by_sender.get("You") or by_sender.get("Alice") or 0),
        "sessions_started_by_other": other_session_starts(by_sender),
        "initiative_balance": initiation_balance_value(by_sender),
        "response_time": response["median_seconds"],
        "response_consistency": dimension_score(dimensions, "reply_consistency"),
        "average_reply_length": avg_length,
        "question_engagement": dimension_score(dimensions, "question_engagement"),
        "unanswered_question_rate": unanswered_count / max(1, question_count or unanswered_count),
        "topic_continuation": dimension_score(dimensions, "topic_continuation"),
        "planning_activity": int(events.get("plan_candidate", 0) or 0),
        "follow_up_activity": int(events.get("follow_up_candidate", 0) or 0),
        "sarcasm_intensity": dimension_score(dimensions, "sarcasm_intensity"),
        "dismissive_low_effort_patterns": dimension_score(dimensions, "dismissiveness"),
        "pressure_risk": dimension_score(dimensions, "pressure_risk"),
        "communication_score": score,
        "_response_evidence": response["count"],
    }


def compare_metric(metric: str, previous: Any, current: Any, spec: dict[str, Any]) -> dict[str, Any]:
    if metric.startswith("_"):
        raise ValueError(metric)
    rule = spec["rule"]
    previous_value = scalar(previous)
    current_value = scalar(current)
    change = numeric_change(previous_value, current_value)
    arrow = change_arrow(change)
    direction = "unknown"
    if previous_value is not None and current_value is not None:
        direction = direction_for_rule(rule, previous_value, current_value, metric=metric)
    return {
        "metric": metric,
        "previous_value": previous_value,
        "current_value": current_value,
        "change": change,
        "direction": direction,
        "importance": importance_for(metric, previous_value, current_value, spec.get("importance", "low"), direction),
        "arrow": arrow,
        "explanation": metric_explanation(metric, direction, change, previous_value, current_value),
    }


def direction_for_rule(rule: str, previous: float, current: float, *, metric: str) -> str:
    if stable(previous, current):
        return "stable"
    if rule == "neutral":
        return "unknown"
    if rule == "higher_better":
        return "improved" if current > previous else "worsened"
    if rule == "lower_better":
        return "improved" if current < previous else "worsened"
    if rule == "closer_to_balance":
        previous_distance = abs(previous - 0.5)
        current_distance = abs(current - 0.5)
        if abs(previous_distance - current_distance) <= 0.05:
            return "stable"
        return "improved" if current_distance < previous_distance else "worsened"
    if rule == "lower_better_with_evidence":
        return "improved" if current < previous else "worsened"
    if rule == "reply_length":
        if current < previous * 0.8 and current < 60:
            return "worsened"
        if previous < 60 and current > previous * 1.25:
            return "improved"
        return "stable"
    return "unknown"


def meaningful_changes(rows: Sequence[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row.get("direction") in {"improved", "worsened"}
        and row.get("importance") in {"medium", "high"}
    ]
    candidates.sort(key=lambda row: ({"high": 0, "medium": 1, "low": 2}.get(row.get("importance"), 3), row.get("metric", "")))
    return candidates[:limit]


def overall_direction(rows: Sequence[dict[str, Any]]) -> str:
    score = 0
    for row in rows:
        weight = {"high": 2, "medium": 1, "low": 0}.get(str(row.get("importance")), 0)
        if row.get("direction") == "improved":
            score += weight
        elif row.get("direction") == "worsened":
            score -= weight
    if score >= 2:
        return "improved"
    if score <= -2:
        return "worsened"
    return "stable"


def overall_explanation(direction: str) -> str:
    return {
        "improved": "This conversation performed better than the previous comparable period.",
        "worsened": "This conversation performed worse than the previous comparable period.",
        "stable": "There were no substantial changes compared with the previous period.",
    }.get(direction, "Not enough comparable data.")


def insufficient_result(
    comparison_type: str,
    reason: str,
    *,
    previous: PeriodBundle | None = None,
    current: PeriodBundle | None = None,
) -> dict[str, Any]:
    return {
        "status": "insufficient_data",
        "quality": "weak",
        "comparison_type": comparison_type,
        "reason": reason,
        "previous": period_metadata(previous) if previous else {},
        "current": period_metadata(current) if current else {},
        "metrics": [],
        "main_changes": [],
        "overall_direction": "unknown",
        "overall_explanation": "Not enough comparable data.",
    }


def bundle_from_messages(
    messages: Sequence[Message],
    *,
    label: str,
    chat_type: str = "one_to_one",
    start: datetime | None = None,
    end: datetime | None = None,
) -> PeriodBundle:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    events = extract_events(ordered)
    metrics = summarize(ordered, ordered[0].conversation_id if ordered else "chat")
    metrics["question_count"] = sum(1 for message in ordered if "?" in (message.text or ""))
    dimensions = build_deterministic_dimensions(ordered, events, chat_type=chat_type)
    metrics["dimensions"] = dimensions
    metrics["communication_score"] = communication_score_from_dimensions(dimensions, message_count=len(ordered)).get("score")
    inferred_start = parse_message_dt(ordered[0]) if ordered else start
    inferred_end = parse_message_dt(ordered[-1]) if ordered else end
    return PeriodBundle(
        source=ordered[0].source if ordered else "telegram",
        chat_id=ordered[0].conversation_id if ordered else "unknown",
        label=label,
        metrics=metrics,
        event_summary=summarize_events(events),
        message_count=len(ordered),
        start=start or inferred_start,
        end=end or inferred_end,
    )


def bundle_from_report(report: dict[str, Any]) -> PeriodBundle:
    metrics = dict(report.get("metrics_summary") or {})
    metrics["question_count"] = int(metrics.get("question_count") or len(metrics.get("unanswered_questions") or []))
    quality = report.get("data_quality") or {}
    return PeriodBundle(
        source=report.get("source") or "telegram",
        chat_id=str(report.get("chat_id") or ""),
        label=str(report.get("period_label") or ""),
        metrics=metrics,
        event_summary=report.get("event_summary") or {},
        message_count=int(report.get("imported_message_count") or metrics.get("message_count") or 0),
        start=parse_dt(report.get("period_start") or quality.get("range_start")),
        end=parse_dt(report.get("period_end") or quality.get("range_end")),
        analysis_version=ANALYSIS_VERSION,
        report_id=report.get("report_id"),
    )


def bundle_from_analysis(analysis: dict[str, Any]) -> PeriodBundle:
    result = analysis.get("result") or {}
    coverage = result.get("coverage") or analysis.get("coverage") or {}
    metrics = {
        "dimensions": result.get("dimensions") or analysis.get("dimensions") or {},
        "communication_score": result.get("overall_score") or analysis.get("overall_score"),
        "message_count": int(coverage.get("available_messages") or 0),
        "unanswered_questions": [],
    }
    return PeriodBundle(
        source=analysis.get("source") or "telegram",
        chat_id=str(analysis.get("chat_id") or ""),
        label=str(analysis.get("period_label") or ""),
        metrics=metrics,
        event_summary={},
        message_count=int(coverage.get("available_messages") or 0),
        start=parse_dt(analysis.get("period_start")),
        end=parse_dt(analysis.get("period_end")),
        analysis_version=result.get("analysis_version") or ANALYSIS_VERSION,
        analysis_id=analysis.get("analysis_id"),
    )


def split_sessions(messages: Sequence[Message]) -> list[list[Message]]:
    ordered = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    sessions: list[list[Message]] = []
    current: list[Message] = []
    previous_time: datetime | None = None
    for message in ordered:
        ts = parse_ts(message.timestamp)
        if previous_time and ts - previous_time > timedelta(hours=SESSION_GAP_HOURS):
            sessions.append(current)
            current = []
        current.append(message)
        previous_time = ts
    if current:
        sessions.append(current)
    return sessions


def messages_in_range(messages: Sequence[Message], start: datetime, end: datetime) -> list[Message]:
    return [
        message
        for message in messages
        if start <= parse_message_dt(message) < end
    ]


def response_rollup(metrics: dict[str, Any]) -> dict[str, Any]:
    rows = list((metrics.get("response_times") or {}).values())
    values = [float(row.get("median_seconds")) for row in rows if isinstance(row, dict) and row.get("median_seconds") is not None and int(row.get("count") or 0) > 0]
    count = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))
    if not values:
        return {"median_seconds": None, "count": count}
    return {"median_seconds": sum(values) / len(values), "count": count}


def average_reply_length_other(metrics: dict[str, Any]) -> float | None:
    rows = metrics.get("average_message_length") or {}
    if not isinstance(rows, dict):
        return None
    candidates = []
    for key, row in rows.items():
        if not isinstance(row, dict) or row.get("avg_chars") is None:
            continue
        if str(key).casefold() in {"you", "alice"}:
            continue
        candidates.append(float(row.get("avg_chars") or 0))
    if not candidates and rows:
        candidates = [float(row.get("avg_chars") or 0) for row in rows.values() if isinstance(row, dict)]
    return sum(candidates) / len(candidates) if candidates else None


def other_session_starts(by_sender: dict[str, Any]) -> int:
    total = 0
    for key, value in by_sender.items():
        if str(key).casefold() in {"you", "alice"}:
            continue
        try:
            total += int(value or 0)
        except (TypeError, ValueError):
            continue
    return total


def initiation_balance_value(by_sender: dict[str, Any]) -> float | None:
    values = []
    for value in by_sender.values():
        try:
            values.append(int(value or 0))
        except (TypeError, ValueError):
            continue
    total = sum(values)
    if total <= 0 or len(values) < 2:
        return None
    return max(values) / total


def dimension_score(dimensions: dict[str, Any], key: str) -> float | None:
    row = dimensions.get(key) if isinstance(dimensions, dict) else None
    if not isinstance(row, dict) or row.get("score") is None or row.get("available") is False:
        return None
    try:
        return float(row.get("score"))
    except (TypeError, ValueError):
        return None


def stable(previous: float, current: float) -> bool:
    baseline = max(1.0, abs(previous))
    return abs(current - previous) / baseline <= STABLE_RELATIVE_CHANGE


def numeric_change(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None:
        return None
    return round(current - previous, 3)


def change_arrow(change: float | None) -> str:
    if change is None:
        return "?"
    if abs(change) <= 0.001:
        return "→"
    return "↑" if change > 0 else "↓"


def scalar(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def importance_for(metric: str, previous: float | None, current: float | None, default: str, direction: str) -> str:
    if previous is None or current is None or direction in {"stable", "unknown"}:
        return "low"
    if metric in {"communication_score", "unanswered_question_rate", "pressure_risk", "dismissive_low_effort_patterns", "initiative_balance"}:
        return "high"
    return default if default in {"low", "medium", "high"} else "low"


def metric_explanation(metric: str, direction: str, change: float | None, previous: float | None, current: float | None) -> str:
    if previous is None or current is None:
        return "This metric was not available in both periods."
    if direction == "unknown":
        return "The numeric change is observable, but this metric is not automatically positive or negative."
    if direction == "stable":
        return "The metric was almost unchanged."
    label = metric.replace("_", " ")
    return f"{label} {direction} compared with the previous period."


def period_metadata(bundle: PeriodBundle | None) -> dict[str, Any]:
    if bundle is None:
        return {}
    return {
        "source": bundle.source,
        "chat_id": bundle.chat_id,
        "label": bundle.label,
        "message_count": bundle.message_count,
        "start": bundle.start.isoformat() if bundle.start else None,
        "end": bundle.end.isoformat() if bundle.end else None,
        "analysis_version": bundle.analysis_version,
        "report_id": bundle.report_id,
        "analysis_id": bundle.analysis_id,
    }


def parse_message_dt(message: Message) -> datetime:
    return normalize_dt(parse_ts(message.timestamp))


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return normalize_dt(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def normalize_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_period_comparison_compact(comparison: dict[str, Any], *, language: str = "en") -> str:
    lines = [t(language, "comparison_title"), ""]
    if comparison.get("status") != "ok":
        return "\n".join([lines[0], "", t(language, "comparison_not_enough")])
    changes = comparison.get("main_changes") or []
    if not changes:
        lines.append(t(language, "comparison_no_substantial_changes"))
    for row in changes[:5]:
        lines.append(f"{row.get('arrow', '→')} {comparison_metric_sentence(row, language=language)}")
    lines.extend(["", t(language, "comparison_overall"), comparison_overall_sentence(comparison, language=language)])
    return "\n".join(lines).strip()


def format_period_comparison_full(comparison: dict[str, Any], *, language: str = "en") -> str:
    if comparison.get("status") != "ok":
        return "\n\n".join([t(language, "comparison_title"), t(language, "comparison_not_enough")])
    lines = [t(language, "comparison_title"), "", comparison_overall_sentence(comparison, language=language), ""]
    for row in comparison.get("metrics") or []:
        lines.append(
            f"{row.get('arrow', '→')} {comparison_metric_label(row.get('metric'), language=language)}: "
            f"{format_metric_value(row.get('previous_value'))} -> {format_metric_value(row.get('current_value'))}"
        )
        lines.append(str(row.get("explanation") or ""))
    return "\n".join(lines).strip()


def comparison_metric_sentence(row: dict[str, Any], *, language: str) -> str:
    key = f"comparison_change_{row.get('metric')}_{row.get('direction')}"
    translated = t(language, key)
    if translated != key:
        return translated
    return str(row.get("explanation") or row.get("metric") or "")


def comparison_overall_sentence(comparison: dict[str, Any], *, language: str) -> str:
    direction = comparison.get("overall_direction")
    key = {
        "improved": "comparison_overall_better",
        "worsened": "comparison_overall_worse",
        "stable": "comparison_no_substantial_changes",
    }.get(str(direction), "comparison_not_enough")
    return t(language, key)


def comparison_metric_label(metric: Any, *, language: str) -> str:
    key = f"comparison_metric_{metric}"
    translated = t(language, key)
    return translated if translated != key else str(metric or "")


def format_metric_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
