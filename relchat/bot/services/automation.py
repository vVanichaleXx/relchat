from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

from relchat.bot.formatters import format_automatic_analysis_result, format_automation_suggestion
from relchat.bot.keyboards import automatic_analysis_result_keyboard, automation_suggestion_keyboard
from relchat.bot.services.analysis_memory import persist_analysis_artifacts
from relchat.bot.services.ai_analysis import AIAnalysisError, CONSENT_VERSION, run_ai_communication_analysis
from relchat.bot.services.analysis_jobs import create_local_communication_analysis, safe_error_code
from relchat.bot.services.context import classify_context
from relchat.bot.services.period_comparison import compare_report_to_previous
from relchat.bot.services.report_service import build_report
from relchat.bot.services.ux_audit import record_ux_event
from relchat.bot.state import DEFAULT_MODULE_IDS
from relchat.config import Settings
from relchat.core.models import Message
from relchat.database.repositories import (
    create_ai_analysis,
    create_analysis_job,
    create_pending_automatic_notification,
    create_period_comparison,
    ensure_report_callback_token,
    get_automation_state,
    get_important_chat_settings,
    get_pending_automatic_notification,
    get_user_settings,
    has_active_ai_consent,
    list_automation_enabled_chats,
    list_due_automatic_notifications,
    list_reports,
    list_user_messages,
    record_automatic_range,
    save_user_message,
    update_analysis_job,
    update_automatic_notification_status,
    update_important_chat_setting,
    update_user_setting,
    upsert_automation_state,
    automatic_range_exists,
    count_automatic_notifications_since,
)
from relchat.database.sqlite import connect, init_db
from relchat.events.extractor import extract_events
from relchat.telegram.client import make_client
from relchat.telegram.importer import entity_ref
from relchat.telegram.normalizer import normalize_message


MessageLoader = Callable[[Settings, Sequence[dict[str, Any]]], Awaitable[dict[tuple[int, str, str], list[Message]]]]


@dataclass(frozen=True)
class PauseDecision:
    action: str
    reason: str
    start_message_id: int | None = None
    end_message_id: int | None = None
    message_count: int = 0
    deliver_after: datetime | None = None


class AutomaticAnalysisService:
    def __init__(
        self,
        application: Any,
        settings: Settings,
        *,
        message_loader: MessageLoader | None = None,
    ) -> None:
        self.application = application
        self.settings = settings
        self.message_loader = message_loader or load_new_messages_for_important_chats
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._semaphore = asyncio.Semaphore(max(1, int(settings.automation_max_concurrency or 1)))

    async def start(self) -> None:
        if not self.settings.automation_enabled:
            return
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self.run(), name="relchat-automation")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.poll_once()
            except Exception as exc:
                record_ux_event(self.settings, "automatic_check_failed", payload={"error_code": safe_error_code(exc)})
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=max(30, int(self.settings.automation_poll_seconds)))
            except TimeoutError:
                continue

    async def poll_once(self, *, now: datetime | None = None) -> None:
        if not self.settings.automation_enabled:
            return
        current = normalize_dt(now or datetime.now(timezone.utc))
        init_db(self.settings.db_path)
        with connect(self.settings.db_path) as conn:
            due = list_due_automatic_notifications(conn, now=current.isoformat(), limit=20)
            chats = list_automation_enabled_chats(conn, limit=100)
        for notification in due:
            await self.deliver_pending_notification(notification, now=current)
        if not chats:
            return
        record_ux_event(
            self.settings,
            "automatic_check_started",
            payload={"chat_count": len(chats)},
        )
        loaded = await self.message_loader(self.settings, chats)
        tasks = [self.process_chat(row, loaded.get(chat_key(row), []), now=current) for row in chats]
        if tasks:
            await asyncio.gather(*tasks)

    async def process_chat(self, row: dict[str, Any], new_messages: Sequence[Message], *, now: datetime) -> None:
        async with self._semaphore:
            started = time.monotonic()
            bot_user_id = int(row["bot_user_id"])
            source = row.get("source") or "telegram"
            chat_id = row["chat_id"]
            with connect(self.settings.db_path) as conn:
                for message in new_messages:
                    save_user_message(conn, bot_user_id, message)
                all_messages = list_user_messages(conn, bot_user_id, chat_id, source=source)
                settings = get_important_chat_settings(conn, bot_user_id, source, chat_id)
                user_settings = get_user_settings(conn, bot_user_id)
                state = get_automation_state(conn, bot_user_id, source, chat_id)
                if state.get("observed_message_cursor") is None and not state.get("last_automatic_message_id") and not settings.get("last_automatic_message_id"):
                    state = {**state, "observed_message_cursor": latest_message_id(all_messages)}
                decision = evaluate_pause_candidate(
                    chat_settings=settings,
                    user_settings=user_settings,
                    state=state,
                    messages=all_messages,
                    now=now,
                    max_daily_notifications=self.settings.automation_max_notifications_per_day,
                    notifications_today=count_automatic_notifications_since(conn, bot_user_id, start_of_day(now).isoformat()),
                )
                upsert_automation_state(
                    conn,
                    bot_user_id,
                    source,
                    chat_id,
                    observed_message_cursor=latest_message_id(all_messages),
                    last_observed_message_at=latest_message_at(all_messages),
                )
                if (
                    decision.action in {"suggest", "analyze", "delay"}
                    and decision.start_message_id is not None
                    and decision.end_message_id is not None
                    and automatic_range_exists(conn, bot_user_id, source, chat_id, decision.start_message_id, decision.end_message_id)
                ):
                    decision = PauseDecision(
                        "none",
                        "duplicate_range",
                        start_message_id=decision.start_message_id,
                        end_message_id=decision.end_message_id,
                        message_count=decision.message_count,
                    )
                conn.commit()
            record_ux_event(
                self.settings,
                "conversation_pause_candidate_detected" if decision.action in {"suggest", "analyze", "delay"} else "notification_suppressed",
                payload={
                    "bot_user_id": bot_user_id,
                    "source": source,
                    "chat_id_hash": safe_chat_hash(chat_id),
                    "action": decision.action,
                    "reason": decision.reason,
                    "message_count": decision.message_count,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            if decision.action == "suggest":
                await self.offer_analysis(row, decision, now=now)
            elif decision.action == "analyze":
                await self.run_automatic_analysis(row, decision, now=now)
            elif decision.action == "delay":
                await self.delay_notification(row, decision)

    async def offer_analysis(self, row: dict[str, Any], decision: PauseDecision, *, now: datetime) -> None:
        with connect(self.settings.db_path) as conn:
            notification = create_pending_automatic_notification(
                conn,
                bot_user_id=row["bot_user_id"],
                source=row.get("source") or "telegram",
                chat_id=row["chat_id"],
                chat_title=row.get("title") or row.get("display_title"),
                range_start_message_id=decision.start_message_id or 0,
                range_end_message_id=decision.end_message_id or 0,
                notification_type="suggestion",
                deliver_after=None,
                payload={"message_count": decision.message_count},
            )
            record_automatic_range(
                conn,
                bot_user_id=row["bot_user_id"],
                source=row.get("source") or "telegram",
                chat_id=row["chat_id"],
                start_message_id=decision.start_message_id or 0,
                end_message_id=decision.end_message_id or 0,
                message_count=decision.message_count,
                action="offered",
            )
            upsert_automation_state(
                conn,
                row["bot_user_id"],
                row.get("source") or "telegram",
                row["chat_id"],
                last_notification_at=now.isoformat(),
                pending_new_message_count=decision.message_count,
                pending_range_start_message_id=decision.start_message_id,
                pending_range_end_message_id=decision.end_message_id,
            )
            language = get_user_settings(conn, row["bot_user_id"]).get("language", "en")
            conn.commit()
        await self.application.bot.send_message(
            chat_id=row["bot_user_id"],
            text=format_automation_suggestion(row, message_count=decision.message_count, language=language),
            reply_markup=automation_suggestion_keyboard(notification["notification_id"], language=language),
        )
        with connect(self.settings.db_path) as conn:
            update_automatic_notification_status(conn, row["bot_user_id"], notification["notification_id"], "delivered")
        record_ux_event(self.settings, "automatic_analysis_offered", payload={"mode": "suggest", "message_count": decision.message_count})

    async def delay_notification(self, row: dict[str, Any], decision: PauseDecision) -> None:
        with connect(self.settings.db_path) as conn:
            create_pending_automatic_notification(
                conn,
                bot_user_id=row["bot_user_id"],
                source=row.get("source") or "telegram",
                chat_id=row["chat_id"],
                chat_title=row.get("title") or row.get("display_title"),
                range_start_message_id=decision.start_message_id or 0,
                range_end_message_id=decision.end_message_id or 0,
                notification_type=row.get("automatic_delivery_mode") or "suggestion",
                deliver_after=decision.deliver_after.isoformat() if decision.deliver_after else None,
                payload={"message_count": decision.message_count},
            )
            upsert_automation_state(
                conn,
                row["bot_user_id"],
                row.get("source") or "telegram",
                row["chat_id"],
                pending_new_message_count=decision.message_count,
                pending_range_start_message_id=decision.start_message_id,
                pending_range_end_message_id=decision.end_message_id,
                pending_deliver_after=decision.deliver_after.isoformat() if decision.deliver_after else None,
                suppressed_reason="quiet_hours",
            )
        record_ux_event(self.settings, "notification_suppressed", payload={"reason": "quiet_hours", "message_count": decision.message_count})

    async def deliver_pending_notification(self, notification: dict[str, Any], *, now: datetime) -> None:
        with connect(self.settings.db_path) as conn:
            settings = get_important_chat_settings(conn, notification["bot_user_id"], notification["source"], notification["chat_id"])
            user_settings = get_user_settings(conn, notification["bot_user_id"])
            if not user_settings.get("automatic_analysis_master_enabled") or not settings.get("automatic_analysis_enabled"):
                update_automatic_notification_status(conn, notification["bot_user_id"], notification["notification_id"], "suppressed")
                return
            row = {**settings, "title": notification.get("chat_title")}
        decision = PauseDecision(
            action="analyze" if notification.get("notification_type") == "auto" else "suggest",
            reason="delayed",
            start_message_id=notification["range_start_message_id"],
            end_message_id=notification["range_end_message_id"],
            message_count=int((notification.get("payload") or {}).get("message_count") or 0),
        )
        if decision.action == "analyze":
            await self.run_automatic_analysis(row, decision, now=now, notification_id=notification["notification_id"])
        else:
            await self.offer_analysis(row, decision, now=now)
            with connect(self.settings.db_path) as conn:
                update_automatic_notification_status(conn, notification["bot_user_id"], notification["notification_id"], "delivered")

    async def run_automatic_analysis(
        self,
        row: dict[str, Any],
        decision: PauseDecision,
        *,
        now: datetime,
        notification_id: str | None = None,
    ) -> None:
        bot_user_id = int(row["bot_user_id"])
        source = row.get("source") or "telegram"
        chat_id = row["chat_id"]
        with connect(self.settings.db_path) as conn:
            settings = get_important_chat_settings(conn, bot_user_id, source, chat_id)
            user_settings = get_user_settings(conn, bot_user_id)
            language = user_settings.get("language", "en")
            messages = [
                message
                for message in list_user_messages(conn, bot_user_id, chat_id, source=source)
                if (decision.start_message_id or 0) <= message.source_message_id <= (decision.end_message_id or 0)
            ]
            if not messages:
                return
            context_classification = classify_context(chat=row, messages=messages).to_dict()
            analysis_mode = settings.get("preferred_analysis_mode") or "local"
            if analysis_mode == "ai" and not has_active_ai_consent(conn, bot_user_id):
                await self.application.bot.send_message(
                    chat_id=bot_user_id,
                    text=format_automation_suggestion(row, message_count=len(messages), language=language, ai_consent_missing=True),
                    reply_markup=automation_suggestion_keyboard(notification_id or "missing_consent", language=language),
                )
                return
            job = create_analysis_job(
                conn,
                bot_user_id=bot_user_id,
                source=source,
                chat_id=chat_id,
                chat_title=row.get("title") or row.get("display_title"),
                period_id="automatic_pause",
                period_label="Automatic paused conversation",
                period_start=messages[0].timestamp,
                period_end=messages[-1].timestamp,
                modules=user_settings.get("default_modules") or DEFAULT_MODULE_IDS,
                analysis_mode=analysis_mode,
            )
            update_analysis_job(conn, job["job_id"], status="analyzing", progress_percent=85, imported_message_count=len(messages), started=True)
            events = extract_events(messages)
            report = build_report(
                conn,
                bot_user_id=bot_user_id,
                job=job,
                messages=messages,
                events=events,
                modules=job["modules"],
                range_start=messages[0].timestamp,
                range_end=messages[-1].timestamp,
            )
            conn.commit()
        analysis = None
        ai_failed = False
        if analysis_mode == "ai":
            analysis, ai_failed = await self.run_ai_or_local_fallback(row, job, report, messages, events, language=language, context_classification=context_classification)
        else:
            analysis = create_local_communication_analysis(
                settings=self.settings,
                job=job,
                report=report,
                messages=messages,
                events=events,
                chat_type=row.get("chat_type") or "one_to_one",
                language=language,
                context_classification=context_classification,
                started=time.monotonic(),
            )
        with connect(self.settings.db_path) as conn:
            reports = list_reports(conn, bot_user_id, chat_id=chat_id, limit=10)
            previous = [item for item in reports if item.get("report_id") != report.get("report_id")]
            comparison = compare_report_to_previous(report, previous)
            stored_comparison = create_period_comparison(
                conn,
                bot_user_id=bot_user_id,
                source=source,
                chat_id=chat_id,
                comparison_type=comparison.get("comparison_type") or "selected_report_vs_previous",
                status=comparison.get("status") or "insufficient_data",
                quality=comparison.get("quality") or "weak",
                result=comparison,
                current_report_id=report.get("report_id"),
                previous_report_id=(comparison.get("previous") or {}).get("report_id"),
                current_analysis_id=analysis.get("analysis_id") if analysis else None,
            )
            update_analysis_job(conn, job["job_id"], status="completed", progress_percent=100, report_id=report["report_id"], ai_analysis_id=analysis.get("analysis_id") if analysis else None, completed=True)
            record_automatic_range(
                conn,
                bot_user_id=bot_user_id,
                source=source,
                chat_id=chat_id,
                start_message_id=decision.start_message_id or messages[0].source_message_id,
                end_message_id=decision.end_message_id or messages[-1].source_message_id,
                message_count=len(messages),
                action="analyzed",
                analysis_id=analysis.get("analysis_id") if analysis else None,
                report_id=report.get("report_id"),
            )
            update_important_chat_setting(conn, bot_user_id, source, chat_id, "last_automatic_analysis_at", now.isoformat())
            update_important_chat_setting(conn, bot_user_id, source, chat_id, "last_automatic_message_id", messages[-1].source_message_id)
            upsert_automation_state(
                conn,
                bot_user_id,
                source,
                chat_id,
                last_automatic_analysis_at=now.isoformat(),
                last_automatic_message_id=messages[-1].source_message_id,
                last_notification_at=now.isoformat(),
                pending_new_message_count=0,
            )
            callback_ref = ensure_report_callback_token(conn, bot_user_id, report["report_id"])
            if notification_id:
                update_automatic_notification_status(conn, bot_user_id, notification_id, "completed")
            conn.commit()
        if analysis:
            analysis = {**analysis, "comparison": stored_comparison.get("result") or comparison}
        await self.application.bot.send_message(
            chat_id=bot_user_id,
            text=format_automatic_analysis_result(row, analysis=analysis, ai_failed=ai_failed, language=language),
            reply_markup=automatic_analysis_result_keyboard(callback_ref, source_notification_id=notification_id, language=language),
        )
        result = (analysis.get("result") if isinstance(analysis, dict) else {}) or {}
        record_ux_event(
            self.settings,
            "automatic_analysis_completed",
            payload={
                "mode": analysis_mode,
                "message_count": len(messages),
                "ai_failed": ai_failed,
                "context_category": (result.get("context") or {}).get("category") if isinstance(result, dict) else None,
                "analysis_framework_version": result.get("analysis_framework_version") if isinstance(result, dict) else None,
                "semantic_finding_count": len(result.get("evidence_findings") or []) if isinstance(result, dict) else 0,
            },
        )

    async def run_ai_or_local_fallback(
        self,
        row: dict[str, Any],
        job: dict[str, Any],
        report: dict[str, Any],
        messages: list[Message],
        events: Sequence[Any],
        *,
        language: str,
        context_classification: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, bool]:
        try:
            outcome = await run_ai_communication_analysis(
                self.settings,
                chat={"source": row.get("source"), "chat_id": row.get("chat_id"), "chat_type": row.get("chat_type"), "title": row.get("title")},
                messages=messages,
                events=events,
                period_label=job.get("period_label") or "",
                language=language,
                context_classification=context_classification,
            )
            with connect(self.settings.db_path) as conn:
                analysis = create_ai_analysis(
                    conn,
                    bot_user_id=job["bot_user_id"],
                    job_id=job.get("job_id"),
                    report_id=report.get("report_id"),
                    source=job.get("source") or "telegram",
                    chat_id=job["chat_id"],
                    chat_title=job.get("chat_title"),
                    model_name=outcome.model_name,
                    status="completed",
                    period_id=job.get("period_id"),
                    period_label=job.get("period_label"),
                    period_start=job.get("period_start"),
                    period_end=job.get("period_end"),
                    message_count_sent=outcome.message_count_sent,
                    char_count_sent=outcome.char_count_sent,
                    coverage=outcome.coverage,
                    result=outcome.result,
                    dimensions=outcome.result.get("dimensions"),
                    overall_score=outcome.result.get("overall_score"),
                    confidence=outcome.result.get("score_confidence"),
                    consent_version=CONSENT_VERSION,
                    token_usage=outcome.token_usage,
                )
                persist_analysis_artifacts(conn, analysis=analysis, result=outcome.result)
                conn.commit()
            return analysis, False
        except Exception as exc:
            error_code = exc.code if isinstance(exc, AIAnalysisError) else safe_error_code(exc)
            record_ux_event(self.settings, "automatic_analysis_failed", payload={"mode": "ai", "error_code": error_code})
            analysis = create_local_communication_analysis(
                settings=self.settings,
                job=job,
                report=report,
                messages=messages,
                events=events,
                chat_type=row.get("chat_type") or "one_to_one",
                language=language,
                context_classification=context_classification,
                started=time.monotonic(),
            )
            return analysis, True


def evaluate_pause_candidate(
    *,
    chat_settings: dict[str, Any],
    user_settings: dict[str, Any],
    state: dict[str, Any],
    messages: Sequence[Message],
    now: datetime,
    max_daily_notifications: int,
    notifications_today: int,
) -> PauseDecision:
    if not chat_settings.get("is_important"):
        return PauseDecision("none", "not_important")
    if not user_settings.get("automatic_analysis_master_enabled"):
        return PauseDecision("none", "master_disabled")
    if not chat_settings.get("automatic_analysis_enabled"):
        return PauseDecision("none", "chat_disabled")
    if not chat_settings.get("automatic_notification_enabled"):
        return PauseDecision("none", "notifications_disabled")
    paused_until = parse_dt(chat_settings.get("automation_paused_until"))
    if paused_until and now < paused_until:
        return PauseDecision("none", "paused")
    if notifications_today >= max_daily_notifications:
        return PauseDecision("none", "daily_cap")
    if not messages:
        return PauseDecision("none", "no_messages")
    last_covered = int(chat_settings.get("last_automatic_message_id") or state.get("last_automatic_message_id") or state.get("observed_message_cursor") or 0)
    new_messages = [message for message in messages if message.source_message_id > last_covered]
    if not new_messages:
        return PauseDecision("none", "no_new_messages")
    minimum = int(chat_settings.get("minimum_new_messages") or 10)
    if len(new_messages) < minimum:
        return PauseDecision("none", "below_threshold", message_count=len(new_messages))
    latest = new_messages[-1]
    latest_at = parse_dt(latest.timestamp)
    if latest_at is None:
        return PauseDecision("none", "missing_timestamp", message_count=len(new_messages))
    inactivity = timedelta(minutes=int(chat_settings.get("inactivity_threshold_minutes") or 45))
    if now - latest_at < inactivity:
        return PauseDecision("none", "inactivity_not_reached", message_count=len(new_messages))
    start_id = new_messages[0].source_message_id
    end_id = new_messages[-1].source_message_id
    if state.get("pending_range_start_message_id") == start_id and state.get("pending_range_end_message_id") == end_id:
        return PauseDecision("none", "duplicate_pending", start_message_id=start_id, end_message_id=end_id, message_count=len(new_messages))
    last_analysis = parse_dt(chat_settings.get("last_automatic_analysis_at") or state.get("last_automatic_analysis_at"))
    cooldown = timedelta(hours=int(chat_settings.get("cooldown_hours") or 12))
    if last_analysis and now - last_analysis < cooldown:
        return PauseDecision("none", "cooldown", start_message_id=start_id, end_message_id=end_id, message_count=len(new_messages))
    if quiet_hours_active(chat_settings, now):
        return PauseDecision("delay", "quiet_hours", start_message_id=start_id, end_message_id=end_id, message_count=len(new_messages), deliver_after=next_quiet_hours_end(chat_settings, now))
    mode = chat_settings.get("automatic_delivery_mode") or "suggest"
    return PauseDecision("analyze" if mode == "auto" else "suggest", "pause_detected", start_message_id=start_id, end_message_id=end_id, message_count=len(new_messages))


async def load_new_messages_for_important_chats(settings: Settings, chats: Sequence[dict[str, Any]]) -> dict[tuple[int, str, str], list[Message]]:
    if not chats:
        return {}
    client = make_client(settings)
    await client.start()
    result: dict[tuple[int, str, str], list[Message]] = {}
    try:
        for row in chats:
            key = chat_key(row)
            cursor = int(row.get("last_automatic_message_id") or 0)
            entity = await client.get_entity(entity_ref(row["chat_id"]))
            messages: list[Message] = []
            async for message in client.iter_messages(entity, limit=200):
                if getattr(message, "id", 0) <= cursor:
                    break
                sender = await message.get_sender() if getattr(message, "sender_id", None) else None
                messages.append(normalize_message(message, row["chat_id"], sender))
            result[key] = sorted(messages, key=lambda item: (item.timestamp, item.source_message_id))
    finally:
        await client.disconnect()
    return result


def chat_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (int(row["bot_user_id"]), row.get("source") or "telegram", str(row["chat_id"]))


def latest_message_id(messages: Sequence[Message]) -> int | None:
    if not messages:
        return None
    return max(message.source_message_id for message in messages)


def latest_message_at(messages: Sequence[Message]) -> str | None:
    if not messages:
        return None
    return max(message.timestamp for message in messages)


def quiet_hours_active(settings: dict[str, Any], now: datetime) -> bool:
    if not settings.get("quiet_hours_enabled"):
        return False
    start = parse_hhmm(settings.get("quiet_hours_start") or "23:00")
    end = parse_hhmm(settings.get("quiet_hours_end") or "08:00")
    current = now.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def next_quiet_hours_end(settings: dict[str, Any], now: datetime) -> datetime:
    end = parse_hhmm(settings.get("quiet_hours_end") or "08:00")
    candidate = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def parse_hhmm(value: str) -> dt_time:
    try:
        hour, minute = str(value).split(":", 1)
        return dt_time(hour=max(0, min(23, int(hour))), minute=max(0, min(59, int(minute))))
    except Exception:
        return dt_time(hour=0, minute=0)


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


def start_of_day(value: datetime) -> datetime:
    value = normalize_dt(value)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def safe_chat_hash(chat_id: str) -> str:
    return f"chat_{abs(hash(str(chat_id))) % 1000000}"


def start_automation_service(application: Any, settings: Settings) -> AutomaticAnalysisService:
    service = AutomaticAnalysisService(application, settings)
    application.bot_data["relchat_automation_service"] = service
    return service


async def stop_automation_service(application: Any) -> None:
    service = application.bot_data.get("relchat_automation_service")
    if isinstance(service, AutomaticAnalysisService):
        await service.stop()
