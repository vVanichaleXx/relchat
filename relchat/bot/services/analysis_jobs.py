from __future__ import annotations

import asyncio
import socket
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from relchat.bot.formatters import format_job_failure, format_job_progress, format_unified_analysis_result
from relchat.bot.keyboards import analysis_result_keyboard, job_progress_keyboard
from relchat.bot.services.ai_analysis import AIAnalysisError, CONSENT_VERSION, local_fallback_analysis, run_ai_communication_analysis
from relchat.bot.services.context import ANALYSIS_FRAMEWORK_VERSION, classify_context
from relchat.bot.services.period_comparison import compare_report_to_previous
from relchat.bot.services.ux_audit import record_ux_event
from relchat.bot.services.report_service import build_report
from relchat.bot.state import JOB_RUNNING_STATES
from relchat.config import Settings
from relchat.core.models import Message
from relchat.database.repositories import (
    create_ai_analysis,
    create_period_comparison,
    get_chat_context_classification,
    get_analysis_job,
    get_user_settings,
    list_reports,
    save_conversation,
    save_user_message,
    set_analysis_context_used,
    update_analysis_job,
)
from relchat.database.sqlite import connect, init_db
from relchat.events.extractor import extract_events
from relchat.telegram.importer import get_conversation, iter_messages


PROGRESS_THROTTLE_SECONDS = 5


def active_task_map(application: Any) -> dict[str, asyncio.Task]:
    tasks = application.bot_data.setdefault("relchat_analysis_tasks", {})
    return tasks if isinstance(tasks, dict) else {}


def cancel_set(application: Any) -> set[str]:
    values = application.bot_data.setdefault("relchat_cancelled_jobs", set())
    return values if isinstance(values, set) else set()


def start_background_job(application: Any, settings: Settings, job_id: str) -> None:
    task = application.create_task(run_analysis_job(application, settings, job_id))
    active_task_map(application)[job_id] = task


def request_cancel(application: Any, settings: Settings, job_id: str) -> dict[str, Any] | None:
    cancel_set(application).add(job_id)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        job = get_analysis_job(conn, job_id)
        if job and job["status"] in JOB_RUNNING_STATES:
            update_analysis_job(conn, job_id, status="cancelled", completed=True)
            job = get_analysis_job(conn, job_id)
    return job


async def run_analysis_job(application: Any, settings: Settings, job_id: str) -> None:
    init_db(settings.db_path)
    started = time.monotonic()
    last_progress_edit = 0.0
    try:
        with connect(settings.db_path) as conn:
            job = get_analysis_job(conn, job_id)
            if job is None:
                return
            update_analysis_job(conn, job_id, status="loading", progress_percent=5, started=True)
            job = get_analysis_job(conn, job_id)
            user_settings = get_user_settings(conn, job["bot_user_id"])
            language = user_settings.get("language", "en")
            progress_enabled = bool(user_settings.get("progress_notifications", True))
        if progress_enabled:
            await edit_job_message(application, job, language=language)

        conversation = await get_conversation(settings, job["chat_id"])
        with connect(settings.db_path) as conn:
            save_conversation(conn, conversation, selected=True)
            update_analysis_job(conn, job_id, status="importing", progress_percent=10)
            job = get_analysis_job(conn, job_id)
            user_settings = get_user_settings(conn, job["bot_user_id"])
            language = user_settings.get("language", "en")
            progress_enabled = bool(user_settings.get("progress_notifications", True))
        if progress_enabled:
            await edit_job_message(application, job, language=language)

        since = parse_job_datetime(job.get("period_start"))
        until = parse_job_datetime(job.get("period_end"))
        imported: list[Message] = []
        count = 0
        last_message_id = None
        range_start = None
        range_end = None

        with connect(settings.db_path) as conn:
            async for message in iter_messages(settings, job["chat_id"], limit=None, since=since):
                if is_cancelled(application, settings, job_id):
                    update_analysis_job(
                        conn,
                        job_id,
                        status="cancelled",
                        imported_message_count=count,
                        completed=True,
                        elapsed_seconds=int(time.monotonic() - started),
                    )
                    await edit_cancelled_message(application, get_analysis_job(conn, job_id), language=language)
                    return
                if until is not None and parse_message_datetime(message) > until:
                    continue
                save_user_message(conn, job["bot_user_id"], message)
                imported.append(message)
                count += 1
                last_message_id = message.source_message_id
                range_start = message.timestamp if range_start is None else min(range_start, message.timestamp)
                range_end = message.timestamp if range_end is None else max(range_end, message.timestamp)
                if count % 250 == 0:
                    conn.commit()
                now = time.monotonic()
                if count == 1 or now - last_progress_edit >= PROGRESS_THROTTLE_SECONDS:
                    percent = min(80, 10 + min(60, count // 100))
                    update_analysis_job(
                        conn,
                        job_id,
                        progress_percent=percent,
                        imported_message_count=count,
                        elapsed_seconds=int(now - started),
                    )
                    conn.commit()
                    if progress_enabled:
                        await edit_job_message(application, get_analysis_job(conn, job_id), language=language)
                    last_progress_edit = now

            if not imported:
                reference = error_reference()
                update_analysis_job(
                    conn,
                    job_id,
                    status="failed",
                    progress_percent=100,
                    imported_message_count=0,
                    error_reference=reference,
                    error_message="no_messages",
                    completed=True,
                    elapsed_seconds=int(time.monotonic() - started),
                )
                await edit_failure_message(application, get_analysis_job(conn, job_id), language=language)
                return

            update_analysis_job(
                conn,
                job_id,
                status="analyzing",
                progress_percent=85,
                imported_message_count=count,
                elapsed_seconds=int(time.monotonic() - started),
            )
            conn.commit()
            job = get_analysis_job(conn, job_id)
        if progress_enabled:
            await edit_job_message(application, job, language=language)

        events = extract_events(imported)
        with connect(settings.db_path) as conn:
            saved_context = get_chat_context_classification(conn, job["bot_user_id"], job.get("source") or "telegram", job["chat_id"])
        context_classification = classify_context(
            chat={
                "source": job.get("source"),
                "chat_id": job.get("chat_id"),
                "chat_type": conversation.conversation_type,
                "title": job.get("chat_title") or conversation.title,
            },
            messages=imported,
            saved=saved_context,
        ).to_dict()
        record_ux_event(
            settings,
            "context_confirmed_or_classified",
            payload={
                "job_id": job.get("job_id"),
                "category": context_classification.get("category"),
                "confidence": context_classification.get("confidence"),
                "source": context_classification.get("source"),
                "user_confirmed": bool(context_classification.get("user_confirmed")),
            },
        )
        with connect(settings.db_path) as conn:
            job = get_analysis_job(conn, job_id)
            if job is None:
                return
            if is_cancelled(application, settings, job_id):
                update_analysis_job(
                    conn,
                    job_id,
                    status="cancelled",
                    imported_message_count=count,
                    completed=True,
                    elapsed_seconds=int(time.monotonic() - started),
                )
                await edit_cancelled_message(application, get_analysis_job(conn, job_id), language=language)
                return
            report = build_report(
                conn,
                bot_user_id=job["bot_user_id"],
                job=job,
                messages=imported,
                events=events,
                modules=job["modules"],
                range_start=range_start,
                range_end=range_end,
            )
            conn.commit()
        ai_analysis = None
        ai_failed = False
        if job.get("analysis_mode") == "ai":
            ai_analysis, ai_failed = await run_optional_ai_analysis(
                settings=settings,
                job=job,
                report=report,
                messages=imported,
                events=events,
                chat_type=conversation.conversation_type,
                language=language,
                context_classification=context_classification,
                started=started,
            )
        else:
            ai_analysis = create_local_communication_analysis(
                settings=settings,
                job=job,
                report=report,
                messages=imported,
                events=events,
                chat_type=conversation.conversation_type,
                language=language,
                context_classification=context_classification,
                started=started,
            )
        with connect(settings.db_path) as conn:
            set_analysis_context_used(
                conn,
                job["bot_user_id"],
                job.get("source") or "telegram",
                job["chat_id"],
                category=str(context_classification.get("category") or "unknown"),
                framework_version=ANALYSIS_FRAMEWORK_VERSION,
            )
            conn.commit()
        comparison = persist_report_comparison(settings, job=job, report=report, ai_analysis=ai_analysis)
        if ai_analysis is not None and comparison is not None:
            ai_analysis = {**ai_analysis, "comparison": comparison.get("result") or comparison}
        with connect(settings.db_path) as conn:
            update_analysis_job(
                conn,
                job_id,
                status="completed",
                progress_percent=100,
                imported_message_count=count,
                report_id=report["report_id"],
                ai_analysis_id=ai_analysis.get("analysis_id") if ai_analysis else None,
                completed=True,
                elapsed_seconds=int(time.monotonic() - started),
            )
            conn.commit()
        await edit_completed_message(
            application,
            report,
            language=language,
            ai_analysis=ai_analysis,
            ai_failed=ai_failed,
            chat_type=conversation.conversation_type,
        )
    except Exception as exc:
        await fail_job(application, settings, job_id, exc, elapsed_seconds=int(time.monotonic() - started))
    finally:
        active_task_map(application).pop(job_id, None)
        cancel_set(application).discard(job_id)


def is_cancelled(application: Any, settings: Settings, job_id: str) -> bool:
    if job_id in cancel_set(application):
        return True
    with connect(settings.db_path) as conn:
        job = get_analysis_job(conn, job_id)
        return bool(job and job["status"] == "cancelled")


async def fail_job(application: Any, settings: Settings, job_id: str, exc: Exception, *, elapsed_seconds: int) -> None:
    init_db(settings.db_path)
    reference = error_reference()
    with connect(settings.db_path) as conn:
        job = get_analysis_job(conn, job_id)
        if job is None:
            return
        language = get_user_settings(conn, job["bot_user_id"]).get("language", "en")
        if job["status"] == "cancelled":
            await edit_cancelled_message(application, job, language=language)
            return
        update_analysis_job(
            conn,
            job_id,
            status="failed",
            progress_percent=100,
            error_reference=reference,
            error_message=safe_error_code(exc),
            completed=True,
            elapsed_seconds=elapsed_seconds,
        )
        job = get_analysis_job(conn, job_id)
    await edit_failure_message(application, job, language=language)


async def edit_job_message(application: Any, job: dict[str, Any] | None, *, language: str) -> None:
    if not job:
        return
    await safe_edit(
        application,
        job,
        format_job_progress(job),
        reply_markup=job_progress_keyboard(job["job_id"], can_cancel=True, language=language),
    )


async def run_optional_ai_analysis(
    *,
    settings: Settings,
    job: dict[str, Any],
    report: dict[str, Any],
    messages: list[Message],
    events: Sequence[Any],
    chat_type: str | None,
    language: str,
    context_classification: dict[str, Any],
    started: float,
) -> tuple[dict[str, Any] | None, bool]:
    record_ux_event(
        settings,
        "ai_analysis_started",
        payload={
            "mode": "ai",
            "job_id": job.get("job_id"),
            "message_count": len(messages),
        },
    )
    try:
        outcome = await run_ai_communication_analysis(
            settings,
            chat={
                "source": job.get("source"),
                "chat_id": job.get("chat_id"),
                "chat_type": chat_type,
                "title": job.get("chat_title"),
            },
            messages=messages,
            events=events,
            period_label=job.get("period_label") or "",
            language=language,
            context_classification=context_classification,
        )
        with connect(settings.db_path) as conn:
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
            conn.commit()
        record_ux_event(
            settings,
            "ai_analysis_completed",
            payload={
                "mode": "ai",
                "job_id": job.get("job_id"),
                "duration_seconds": int(time.monotonic() - started),
                "message_count_sent": outcome.message_count_sent,
                "char_count_sent": outcome.char_count_sent,
                "token_usage": outcome.token_usage,
                "score_produced": outcome.result.get("overall_score") is not None,
            },
        )
        return analysis, False
    except Exception as exc:
        error_code = exc.code if isinstance(exc, AIAnalysisError) else safe_error_code(exc)
        with connect(settings.db_path) as conn:
            analysis = create_ai_analysis(
                conn,
                bot_user_id=job["bot_user_id"],
                job_id=job.get("job_id"),
                report_id=report.get("report_id"),
                source=job.get("source") or "telegram",
                chat_id=job["chat_id"],
                chat_title=job.get("chat_title"),
                model_name=settings.ai_model,
                status="failed",
                period_id=job.get("period_id"),
                period_label=job.get("period_label"),
                period_start=job.get("period_start"),
                period_end=job.get("period_end"),
                consent_version=CONSENT_VERSION,
                error_code=error_code,
            )
            conn.commit()
        record_ux_event(
            settings,
            "ai_analysis_failed",
            payload={
                "mode": "ai",
                "job_id": job.get("job_id"),
                "duration_seconds": int(time.monotonic() - started),
                "error_code": error_code,
            },
        )
        local_analysis = create_local_communication_analysis(
            settings=settings,
            job=job,
            report=report,
            messages=messages,
            events=events,
            chat_type=chat_type,
            language=language,
            context_classification=context_classification,
            started=started,
        )
        return local_analysis or analysis, True


def create_local_communication_analysis(
    *,
    settings: Settings,
    job: dict[str, Any],
    report: dict[str, Any],
    messages: Sequence[Message],
    events: Sequence[Any],
    chat_type: str | None,
    language: str,
    context_classification: dict[str, Any],
    started: float,
) -> dict[str, Any] | None:
    record_ux_event(
        settings,
        "communication_analysis_started",
        payload={
            "mode": "local",
            "job_id": job.get("job_id"),
            "message_count": len(messages),
        },
    )
    result = local_fallback_analysis(
        messages=messages,
        events=events,
        period_label=job.get("period_label") or "",
        chat_type=chat_type or "one_to_one",
        language=language,
        context_classification=context_classification,
    )
    with connect(settings.db_path) as conn:
        analysis = create_ai_analysis(
            conn,
            bot_user_id=job["bot_user_id"],
            job_id=job.get("job_id"),
            report_id=report.get("report_id"),
            source=job.get("source") or "telegram",
            chat_id=job["chat_id"],
            chat_title=job.get("chat_title"),
            model_name=None,
            analysis_mode="local",
            status="completed",
            period_id=job.get("period_id"),
            period_label=job.get("period_label"),
            period_start=job.get("period_start"),
            period_end=job.get("period_end"),
            message_count_sent=0,
            char_count_sent=0,
            coverage=result.get("coverage"),
            result=result,
            dimensions=result.get("dimensions"),
            overall_score=result.get("overall_score"),
            confidence=result.get("score_confidence"),
            consent_version=None,
            token_usage={},
        )
        conn.commit()
    record_ux_event(
        settings,
        "communication_analysis_completed",
        payload={
            "mode": "local",
            "job_id": job.get("job_id"),
            "duration_seconds": int(time.monotonic() - started),
            "message_count": len(messages),
            "score_produced": result.get("overall_score") is not None,
        },
    )
    return analysis


def persist_report_comparison(
    settings: Settings,
    *,
    job: dict[str, Any],
    report: dict[str, Any],
    ai_analysis: dict[str, Any] | None,
) -> dict[str, Any] | None:
    with connect(settings.db_path) as conn:
        reports = list_reports(conn, job["bot_user_id"], chat_id=job["chat_id"], limit=10)
        previous_reports = [item for item in reports if item.get("report_id") != report.get("report_id")]
        comparison = compare_report_to_previous(report, previous_reports)
        stored = create_period_comparison(
            conn,
            bot_user_id=job["bot_user_id"],
            source=job.get("source") or "telegram",
            chat_id=job["chat_id"],
            comparison_type=comparison.get("comparison_type") or "selected_report_vs_previous",
            status=comparison.get("status") or "insufficient_data",
            quality=comparison.get("quality") or "weak",
            result=comparison,
            current_report_id=report.get("report_id"),
            previous_report_id=(comparison.get("previous") or {}).get("report_id"),
            current_analysis_id=ai_analysis.get("analysis_id") if ai_analysis else None,
        )
        conn.commit()
    record_ux_event(
        settings,
        "comparison_generated",
        payload={
            "job_id": job.get("job_id"),
            "status": comparison.get("status"),
            "quality": comparison.get("quality"),
            "message_count_current": (comparison.get("current") or {}).get("message_count"),
            "message_count_previous": (comparison.get("previous") or {}).get("message_count"),
        },
    )
    return stored


async def edit_completed_message(
    application: Any,
    report: dict[str, Any],
    *,
    language: str,
    ai_analysis: dict[str, Any] | None = None,
    ai_failed: bool = False,
    chat_type: str | None = None,
) -> None:
    job_like = {
        "progress_chat_id": report.get("progress_chat_id"),
        "progress_message_id": report.get("progress_message_id"),
    }
    with connect_from_report(application, report) as conn:
        job = get_analysis_job(conn, report.get("job_id")) if report.get("job_id") else None
    if job:
        job_like = job
    text = format_unified_analysis_result(
        report,
        ai_analysis=ai_analysis,
        ai_failed=ai_failed,
        chat_type=chat_type,
        language=language,
    )
    await safe_edit(
        application,
        job_like,
        text,
        reply_markup=analysis_result_keyboard(report["report_id"], language=language),
    )


async def edit_failure_message(application: Any, job: dict[str, Any] | None, *, language: str) -> None:
    if not job:
        return
    await safe_edit(
        application,
        job,
        format_job_failure(job),
        reply_markup=job_progress_keyboard(job["job_id"], can_cancel=False, failed=True, language=language),
    )


async def edit_cancelled_message(application: Any, job: dict[str, Any] | None, *, language: str) -> None:
    if not job:
        return
    text = (
        "Analysis cancelled\n\n"
        f"Imported messages kept locally: {int(job.get('imported_message_count') or 0)}\n"
        "No completed report was created."
    )
    await safe_edit(
        application,
        job,
        text,
        reply_markup=job_progress_keyboard(job["job_id"], can_cancel=False, language=language),
    )


async def safe_edit(application: Any, job: dict[str, Any], text: str, *, reply_markup: Any | None = None) -> None:
    chat_id = job.get("progress_chat_id")
    message_id = job.get("progress_message_id")
    if chat_id is None or message_id is None:
        return
    try:
        await application.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
    except Exception:
        return


def parse_job_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed


def parse_message_datetime(message: Message) -> datetime:
    return datetime.fromisoformat(message.timestamp.replace("Z", "+00:00"))


def safe_error_code(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    if "floodwait" in name or "flood_wait" in name:
        return "flood_wait"
    if "unauthorized" in name or "auth" in name or "session" in name:
        return "auth_expired"
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout, OSError)):
        return "network_unavailable"
    if "notfound" in name or "forbidden" in name or "private" in name:
        return "chat_inaccessible"
    return "unexpected"


def error_reference() -> str:
    return f"err_{uuid.uuid4().hex[:8]}"


def connect_from_report(application: Any, report: dict[str, Any]):
    settings = application.bot_data["settings"]
    return connect(settings.db_path)
