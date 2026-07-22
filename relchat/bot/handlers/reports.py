from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import (
    chunk_text,
    format_analysis_review,
    format_ai_result_section,
    format_destructive_confirmation,
    format_failed_jobs,
    format_report_list,
    format_report_overview,
    format_report_section,
    format_reports_home,
    format_unified_analysis_result,
)
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings
from relchat.bot.keyboards import (
    analysis_detail_keyboard,
    analysis_result_keyboard,
    delete_report_confirmation_keyboard,
    report_list_keyboard,
    report_sections_keyboard,
    reports_home_keyboard,
    review_keyboard,
)
from relchat.bot.localization import t
from relchat.bot.state import get_flow
from relchat.database.repositories import (
    clear_reports,
    delete_report,
    ensure_report_callback_token,
    get_report,
    get_user_settings,
    latest_ai_analysis_for_report,
    latest_period_comparison_for_report,
    list_analysis_jobs,
    list_reports,
    resolve_report_callback_token,
    set_report_favorite,
)
from relchat.database.sqlite import connect, init_db


async def show_reports_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        counts = {
            "reports": len(list_reports(conn, user_id, limit=1000)),
            "favorite_reports": len(list_reports(conn, user_id, favorites=True, limit=1000)),
            "failed_jobs": len(list_analysis_jobs(conn, user_id, statuses=["failed"], limit=1000)),
        }
        language = get_user_settings(conn, user_id).get("language", "en")
    await edit_or_reply(update, format_reports_home(counts), reply_markup=reports_home_keyboard(language))


async def handle_reports_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) >= 3 and parts[1] == "nav" and parts[2] == "reports":
        await show_reports_home(update, context)
        return True
    if len(parts) < 2 or parts[1] not in {"reports", "rep"}:
        return False
    if parts[1] == "reports":
        await handle_reports_home_action(update, context, parts)
        return True
    if parts[1] == "rep":
        await handle_report_action(update, context, parts)
        return True
    return False


async def handle_reports_home_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        if len(parts) >= 4 and parts[2] == "list":
            section = parts[3]
            if section == "failed":
                jobs = list_analysis_jobs(conn, user_id, statuses=["failed"], limit=10)
                await edit_or_reply(update, format_failed_jobs(jobs), reply_markup=reports_home_keyboard(language))
                return
            reports = list_reports(conn, user_id, favorites=section == "favorites", limit=20)
            reports = with_report_callback_refs(conn, user_id, reports)
            title = {
                "latest": "Latest reports",
                "by_chat": "Reports by chat",
                "favorites": "Favorite reports",
            }.get(section, "Reports")
            await edit_or_reply(update, format_report_list(title, reports, language=language), reply_markup=report_list_keyboard(reports, language=language))
            return
    if len(parts) >= 3 and parts[2] == "clear":
        await edit_or_reply(
            update,
            format_destructive_confirmation("clear report history"),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("Clear report history", callback_data="rc:reports:clear_confirm")],
                    [InlineKeyboardButton("Cancel", callback_data="rc:nav:reports")],
                ]
            ),
        )
        return
    if len(parts) >= 3 and parts[2] == "clear_confirm":
        with connect(settings.db_path) as conn:
            clear_reports(conn, user_id)
        await show_reports_home(update, context)


async def handle_report_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    if len(parts) < 4:
        return
    action = parts[2]
    report_ref = parts[3]
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        report_id = resolve_report_callback_token(conn, user_id, report_ref)
        report = get_report(conn, report_id)
        language = get_user_settings(conn, user_id).get("language", "en")
        analysis = latest_ai_analysis_for_report(conn, user_id, report_id) if report else None
        comparison = latest_period_comparison_for_report(conn, user_id, report_id) if report else None
        callback_ref = ensure_report_callback_token(conn, user_id, report_id) if report_id and report else report_ref
    if not report or report["bot_user_id"] != user_id:
        await edit_or_reply(update, "This local report is no longer available.")
        return
    report = {**report, "callback_ref": callback_ref}
    if analysis and comparison:
        analysis = {**analysis, "comparison": comparison.get("result") or {}}
    if action in {"open", "full"}:
        text = (
            format_ai_result_section(analysis, "full", language=language)
            if analysis and analysis.get("status") == "completed"
            else format_unified_analysis_result(report, language=language)
        )
        keyboard = analysis_detail_keyboard(callback_ref, language=language) if action == "full" else analysis_result_keyboard(callback_ref, language=language)
        await edit_or_reply_chunked(update, text, reply_markup=keyboard)
        return
    if action == "compare":
        text = (
            format_ai_result_section(analysis or {"comparison": comparison.get("result") if comparison else None}, "comparison", language=language)
            if comparison
            else format_ai_result_section({"comparison": {"status": "insufficient_data"}}, "comparison", language=language)
        )
        await edit_or_reply(update, text, reply_markup=analysis_detail_keyboard(callback_ref, language=language))
        return
    if action in {"prev", "next"}:
        target = adjacent_report_for_chat(settings, user_id, report, previous=action == "prev")
        if target is None:
            await edit_or_reply(update, t(language, "comparison_not_enough"), reply_markup=analysis_detail_keyboard(callback_ref, language=language))
            return
        with connect(settings.db_path) as conn:
            target = {**target, "callback_ref": ensure_report_callback_token(conn, user_id, target["report_id"])}
        await edit_or_reply(update, format_report_overview(target), reply_markup=report_sections_keyboard(target, language=language))
        return
    if action == "advice":
        text = (
            format_ai_result_section(analysis, "advice", language=language)
            if analysis and analysis.get("status") == "completed"
            else format_unified_analysis_result(report, language=language)
        )
        await edit_or_reply(update, text, reply_markup=analysis_result_keyboard(callback_ref, language=language))
        return
    if action == "why":
        text = (
            format_ai_result_section(analysis, "why", language=language)
            if analysis and analysis.get("status") == "completed"
            else format_unified_analysis_result(report, language=language)
        )
        await edit_or_reply(update, text, reply_markup=analysis_detail_keyboard(callback_ref, language=language))
        return
    if action == "sec":
        section = parts[4] if len(parts) >= 5 else "overview"
        await edit_or_reply(update, format_report_section(report, section), reply_markup=report_sections_keyboard(report, language=language))
        return
    if action == "fav":
        with connect(settings.db_path) as conn:
            set_report_favorite(conn, report_id, not report.get("is_favorite"))
            report = get_report(conn, report_id) or report
        report = {**report, "callback_ref": callback_ref}
        await edit_or_reply(update, format_report_overview(report), reply_markup=report_sections_keyboard(report, language=language))
        return
    if action == "delete":
        await edit_or_reply(
            update,
            format_destructive_confirmation("delete this local report"),
            reply_markup=delete_report_confirmation_keyboard(callback_ref, language=language),
        )
        return
    if action == "delete_confirm":
        with connect(settings.db_path) as conn:
            delete_report(conn, report_id, user_id)
        await show_reports_home(update, context)
        return
    if action == "again":
        flow = get_flow(context.user_data)
        flow.clear()
        flow.update(
            {
                "source": report["source"],
                "chat_id": report["chat_id"],
                "chat_title": report["chat_title"],
                "period_id": report["period_id"],
                "period_label": report["period_label"],
                "period_start": report["period_start"],
                "period_end": report["period_end"],
                "modules": report["modules"],
            }
        )
        await edit_or_reply(update, format_analysis_review(flow), reply_markup=review_keyboard(language))


async def edit_or_reply_chunked(update: Update, text: str, *, reply_markup=None) -> None:
    chunks = chunk_text(text)
    if len(chunks) <= 1:
        await edit_or_reply(update, text, reply_markup=reply_markup)
        return
    await edit_or_reply(update, chunks[0])
    query = update.callback_query
    message = query.message if query else update.effective_message
    if message is None or not hasattr(message, "reply_text"):
        return
    for index, chunk in enumerate(chunks[1:], start=1):
        await message.reply_text(chunk, reply_markup=reply_markup if index == len(chunks) - 1 else None)


def adjacent_report_for_chat(settings, user_id: int, report: dict, *, previous: bool) -> dict | None:
    with connect(settings.db_path) as conn:
        reports = list_reports(conn, user_id, chat_id=report["chat_id"], limit=100)
    ids = [item.get("report_id") for item in reports]
    try:
        index = ids.index(report.get("report_id"))
    except ValueError:
        return None
    target_index = index + 1 if previous else index - 1
    if target_index < 0 or target_index >= len(reports):
        return None
    return reports[target_index]


def with_report_callback_refs(conn, user_id: int, reports: list[dict]) -> list[dict]:
    return [{**report, "callback_ref": ensure_report_callback_token(conn, user_id, report["report_id"])} for report in reports]
