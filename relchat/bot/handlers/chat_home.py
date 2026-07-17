from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import (
    format_ai_result_overview,
    format_ai_result_section,
    format_chat_overview,
    format_chat_overview_details,
    format_chat_home,
    format_chat_home_details_menu,
    format_chat_home_section,
    format_chat_home_loading,
    format_period_prompt,
    format_report_list,
    format_report_overview,
    format_timeline_chart_fallback,
    format_timeline_page,
    format_timeline_summary,
)
from relchat.bot.handlers.common import bot_user_id, edit_or_reply, get_context_settings
from relchat.bot.keyboards import (
    ai_detail_keyboard,
    ai_result_keyboard,
    chat_home_keyboard,
    chat_home_details_menu_keyboard,
    chat_home_reports_keyboard,
    chat_home_section_keyboard,
    chat_settings_keyboard,
    main_keyboard,
    period_keyboard,
    timeline_page_keyboard,
    timeline_summary_keyboard,
)
from relchat.bot.localization import t
from relchat.bot.services.chat_home_service import build_chat_home_view_model
from relchat.bot.services.timeline_service import (
    build_relationship_timeline,
    paginate_timeline_story,
    render_timeline_chart,
)
from relchat.bot.state import get_flow, JOB_RUNNING_STATES
from relchat.database.repositories import (
    get_important_chat_settings,
    get_user_settings,
    latest_ai_analysis_for_chat,
    list_analysis_jobs,
    list_messages,
    list_reminders,
    list_reports,
    set_chat_important,
    update_important_chat_setting,
    update_user_setting,
)
from relchat.database.sqlite import connect, init_db


CHAT_HOME_STATE = "chat_home_current"
CHAT_HOME_PARENT = "chat_home_parent"
CHAT_HOME_REPORTS = "chat_home_reports"
CHAT_HOME_TIMELINE = "chat_home_timeline"


async def show_chat_home(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat: dict[str, Any],
    *,
    parent: dict[str, Any] | None = None,
) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
    if getattr(update, "callback_query", None) is not None:
        await edit_or_reply(update, format_chat_home_loading(language=language))
    with connect(settings.db_path) as conn:
        reports = list_reports(conn, user_id, chat_id=chat["chat_id"], limit=2)
        latest_ai = latest_ai_analysis_for_chat(
            conn,
            user_id,
            source=chat.get("source") or "telegram",
            chat_id=chat["chat_id"],
        )
        messages = list_messages(conn, chat["chat_id"], source=chat.get("source") or "telegram")
        reminders = reminders_for_chat(conn, user_id, chat, limit=1000)
        running = is_analysis_running(conn, user_id, chat)
        important = get_important_chat_settings(conn, user_id, chat.get("source") or "telegram", chat["chat_id"])
        chat = {**chat, "is_important": important.get("is_important")}
    view_model = build_chat_home_view_model(
        chat=chat,
        reports=reports,
        messages=messages,
        reminders=reminders,
        running=running,
        language=language,
    )
    if latest_ai:
        view_model["analysis"]["latest_score"] = latest_ai.get("overall_score")
        confidence = latest_ai.get("confidence") or "low"
        view_model["analysis"]["score_confidence_label"] = t(language, f"confidence_{confidence}") if confidence in {"low", "medium", "high"} else confidence
        view_model["analysis"]["last_analysis_label"] = latest_ai.get("created_at") or view_model["analysis"].get("last_analysis_label")
        view_model["analysis"]["last_period_label"] = latest_ai.get("period_label") or view_model["analysis"].get("last_period_label")
    context.user_data[CHAT_HOME_STATE] = chat_home_state(chat)
    if parent is not None:
        context.user_data[CHAT_HOME_PARENT] = parent
    await edit_or_reply(
        update,
        format_chat_home(view_model, language=language),
        reply_markup=chat_home_keyboard(
            chat,
            has_report=bool(view_model["analysis"].get("has_report")),
            running=running,
            language=language,
        ),
    )


async def handle_chat_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) >= 2 and parts[1] == "tl":
        await handle_timeline_callback(update, context, parts)
        return True
    if len(parts) < 2 or parts[1] != "home":
        return False
    action = parts[2] if len(parts) >= 3 else "open"
    if action == "open":
        chat = current_chat(context)
        if chat is None:
            await show_expired_navigation(update, context)
            return True
        await show_chat_home(update, context, chat)
        return True
    if action == "back":
        await handle_chat_home_back(update, context)
        return True
    if action == "run":
        await start_analysis_from_chat_home(update, context)
        return True
    if action == "sec" and len(parts) >= 4:
        await show_chat_home_section(update, context, parts[3])
        return True
    if action == "details":
        await show_chat_home_details(update, context)
        return True
    if action == "important" and len(parts) >= 4 and parts[3] == "toggle":
        await toggle_important_chat(update, context)
        return True
    if action == "set":
        await handle_chat_setting_callback(update, context, parts)
        return True
    if action == "ai" and len(parts) >= 4:
        await show_ai_analysis_section(update, context, parts[3])
        return True
    if action == "report" and len(parts) >= 4:
        await open_chat_home_report(update, context, parts[3])
        return True
    return False


async def show_chat_home_section(update: Update, context: ContextTypes.DEFAULT_TYPE, section: str) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        reports = list_reports(conn, user_id, chat_id=chat["chat_id"], limit=10)
        report = reports[0] if reports else None
        previous_report = reports[1] if len(reports) > 1 else None
        pending_followups = pending_followup_count(conn, user_id, chat)
        confirmed_reminders = confirmed_reminder_count(conn, user_id, chat)
        important = get_important_chat_settings(conn, user_id, chat.get("source") or "telegram", chat["chat_id"])
        chat = {**chat, "is_important": important.get("is_important")}
    if section == "reports":
        context.user_data[CHAT_HOME_REPORTS] = reports
        await edit_or_reply(
            update,
            format_report_list(t(language, "chat_reports_title"), reports, language=language),
            reply_markup=chat_home_reports_keyboard(reports, language=language),
        )
        return
    if section == "overview":
        await edit_or_reply(
            update,
            format_chat_overview(
                report,
                previous_report=previous_report,
                chat=chat,
                confirmed_reminders=confirmed_reminders,
                language=language,
            ),
            reply_markup=chat_home_section_keyboard(chat, language=language, section="overview"),
        )
        return
    if section == "timeline":
        await show_timeline_summary(update, context)
        return
    await edit_or_reply(
        update,
        format_chat_home_section(section, chat=chat, report=report, pending_followups=pending_followups, important_settings=important, language=language),
        reply_markup=chat_settings_keyboard(important, language=language) if section == "settings" else chat_home_section_keyboard(chat, language=language),
    )


async def toggle_important_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    source = chat.get("source") or "telegram"
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        current = get_important_chat_settings(conn, user_id, source, chat["chat_id"])
        updated = set_chat_important(conn, user_id, source, chat["chat_id"], not current.get("is_important"))
    chat = {**chat, "is_important": updated.get("is_important")}
    context.user_data[CHAT_HOME_STATE] = chat_home_state(chat)
    await edit_or_reply(
        update,
        format_chat_home(chat, language=language),
        reply_markup=chat_home_keyboard(chat, has_report=bool(chat.get("last_report_id")), language=language),
    )


async def handle_chat_setting_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    source = chat.get("source") or "telegram"
    action = parts[3] if len(parts) >= 4 else ""
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        current = get_important_chat_settings(conn, user_id, source, chat["chat_id"])
        set_chat_important(conn, user_id, source, chat["chat_id"], True)
        if action == "auto":
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "automatic_analysis_enabled", not current.get("automatic_analysis_enabled"))
        elif action == "notify":
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "automatic_notification_enabled", not current.get("automatic_notification_enabled"))
        elif action == "inactive" and len(parts) >= 5:
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "inactivity_threshold_minutes", int(parts[4]))
        elif action == "min" and len(parts) >= 5:
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "minimum_new_messages", int(parts[4]))
        elif action == "cooldown" and len(parts) >= 5:
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "cooldown_hours", int(parts[4]))
        elif action == "mode" and len(parts) >= 5:
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "preferred_analysis_mode", parts[4])
        elif action == "delivery" and len(parts) >= 5:
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "automatic_delivery_mode", parts[4])
        elif action == "quiet":
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "quiet_hours_enabled", not current.get("quiet_hours_enabled"))
        elif action == "qstart":
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "quiet_hours_start", next_quiet_time(current.get("quiet_hours_start"), starts=True))
        elif action == "qend":
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "quiet_hours_end", next_quiet_time(current.get("quiet_hours_end"), starts=False))
        elif action == "pause24":
            paused_until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds")
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "automation_paused_until", paused_until)
        elif action == "disable":
            current = update_important_chat_setting(conn, user_id, source, chat["chat_id"], "automatic_analysis_enabled", False)
        elif action == "disable_all":
            update_user_setting(conn, user_id, "automatic_analysis_master_enabled", False)
        current = get_important_chat_settings(conn, user_id, source, chat["chat_id"])
    chat = {**chat, "is_important": current.get("is_important"), "important_settings": current}
    context.user_data[CHAT_HOME_STATE] = chat_home_state(chat)
    await edit_or_reply(
        update,
        format_chat_home_section("settings", chat=chat, report=None, important_settings=current, language=language),
        reply_markup=chat_settings_keyboard(current, language=language),
    )


def next_quiet_time(value: str | None, *, starts: bool) -> str:
    options = ["22:00", "23:00", "00:00"] if starts else ["07:00", "08:00", "09:00"]
    current = value if value in options else options[0]
    index = options.index(current)
    return options[(index + 1) % len(options)]


async def handle_timeline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    action = parts[2] if len(parts) >= 3 else "summary"
    if action == "page":
        page = 0
        if len(parts) >= 4:
            try:
                page = int(parts[3])
            except ValueError:
                page = 0
        await show_timeline_page(update, context, page=page)
        return
    if action == "filter" and len(parts) >= 4:
        await show_timeline_page(update, context, page=0, filter_id=parts[3])
        return
    if action == "chart":
        await send_timeline_chart(update, context)
        return
    await show_timeline_summary(update, context)


async def show_timeline_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    language, timeline = load_timeline(update, context, chat)
    page_data = paginate_timeline_story(timeline.story_items, filter_id="all", page=0)
    context.user_data[CHAT_HOME_TIMELINE] = {"filter": "all", "page": 0, "granularity": timeline.granularity}
    await edit_or_reply(
        update,
        format_timeline_summary(timeline, chat=chat, language=language),
        reply_markup=timeline_page_keyboard(
            filter_id=page_data.filter_id,
            page=page_data.page,
            has_newer=page_data.has_newer,
            has_older=page_data.has_older,
            language=language,
        ),
    )


async def show_timeline_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    page: int,
    filter_id: str | None = None,
) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    state = context.user_data.setdefault(CHAT_HOME_TIMELINE, {})
    if not isinstance(state, dict):
        state = {}
        context.user_data[CHAT_HOME_TIMELINE] = state
    selected_filter = filter_id or str(state.get("filter") or "all")
    language, timeline = load_timeline(update, context, chat, granularity=str(state.get("granularity") or "week"))
    page_data = paginate_timeline_story(
        timeline.story_items,
        filter_id=selected_filter,
        page=page,
    )
    state.update({"filter": page_data.filter_id, "page": page_data.page, "granularity": timeline.granularity})
    await edit_or_reply(
        update,
        format_timeline_page(page_data, chat=chat, language=language),
        reply_markup=timeline_page_keyboard(
            filter_id=page_data.filter_id,
            page=page_data.page,
            has_newer=page_data.has_newer,
            has_older=page_data.has_older,
            language=language,
        ),
    )


async def send_timeline_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    state = context.user_data.get(CHAT_HOME_TIMELINE)
    granularity = str(state.get("granularity") if isinstance(state, dict) else "week") or "week"
    language, messages = load_timeline_messages(update, context, chat)
    chart_path = None
    try:
        chart_path = render_timeline_chart(messages, chat_type=chat.get("chat_type"), granularity=granularity)
        message = getattr(update, "effective_message", None)
        if message is None or not hasattr(message, "reply_photo"):
            raise RuntimeError("photo replies are not available")
        with chart_path.open("rb") as handle:
            await message.reply_photo(photo=handle, caption=t(language, "timeline_chart_caption"))
    except Exception:
        await edit_or_reply(
            update,
            format_timeline_chart_fallback(language=language),
            reply_markup=timeline_summary_keyboard(language=language),
        )
    finally:
        if chart_path is not None:
            chart_path.unlink(missing_ok=True)


def load_timeline(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: dict[str, Any], *, granularity: str = "week"):
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        messages = list_messages(conn, chat["chat_id"], source=chat.get("source") or "telegram")
        reports = list_reports(conn, user_id, chat_id=chat["chat_id"], limit=100)
        reminders = [
            item
            for item in list_reminders(conn, user_id, limit=1000)
            if item.get("chat_id") == chat["chat_id"] and (item.get("source") or "telegram") == (chat.get("source") or "telegram")
        ]
    return language, build_relationship_timeline(
        messages=messages,
        reports=reports,
        reminders=reminders,
        chat_type=chat.get("chat_type"),
        granularity=granularity,
    )


def load_timeline_messages(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: dict[str, Any]) -> tuple[str, list]:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        messages = list_messages(conn, chat["chat_id"], source=chat.get("source") or "telegram")
    return language, messages


async def show_chat_home_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
    await edit_or_reply(
        update,
        format_chat_home_details_menu(language=language),
        reply_markup=chat_home_details_menu_keyboard(language=language),
    )


async def show_ai_analysis_section(update: Update, context: ContextTypes.DEFAULT_TYPE, section: str) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        analysis = latest_ai_analysis_for_chat(
            conn,
            user_id,
            source=chat.get("source") or "telegram",
            chat_id=chat["chat_id"],
        )
        comparison = None
        if analysis:
            from relchat.database.repositories import latest_period_comparison_for_analysis

            comparison = latest_period_comparison_for_analysis(conn, user_id, analysis["analysis_id"])
    if not analysis:
        await edit_or_reply(update, t(language, "empty_no_report"), reply_markup=chat_home_section_keyboard(chat, language=language))
        return
    if comparison:
        analysis = {**analysis, "comparison": comparison.get("result") or {}}
    text = (
        format_ai_result_overview(analysis, chat_title=chat.get("title"), language=language)
        if section == "overview"
        else format_ai_result_section(analysis, section, language=language)
    )
    keyboard = ai_detail_keyboard(language=language) if section in {"full", "comparison"} else ai_result_keyboard(language=language)
    await edit_or_reply(update, text, reply_markup=keyboard)


async def open_chat_home_report(update: Update, context: ContextTypes.DEFAULT_TYPE, value: str) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    try:
        index = int(value)
    except ValueError:
        await show_expired_navigation(update, context)
        return
    reports = context.user_data.get(CHAT_HOME_REPORTS, [])
    if not isinstance(reports, list) or index < 0 or index >= len(reports):
        await show_expired_navigation(update, context)
        return
    settings = get_context_settings(context)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, bot_user_id(update)).get("language", "en")
    await edit_or_reply(
        update,
        format_report_overview(reports[index]),
        reply_markup=chat_home_section_keyboard(chat, language=language),
    )


async def start_analysis_from_chat_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = current_chat(context)
    if chat is None:
        await show_expired_navigation(update, context)
        return
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, user_id).get("language", "en")
        if is_analysis_running(conn, user_id, chat):
            await edit_or_reply(update, t(language, "analysis_already_running"), reply_markup=chat_home_section_keyboard(chat, language=language))
            return
        modules = get_user_settings(conn, user_id).get("default_modules", [])
    flow = get_flow(context.user_data)
    flow.clear()
    flow.update(
        {
            "source": chat.get("source") or "telegram",
            "chat_id": chat["chat_id"],
            "chat_title": chat.get("title"),
            "chat_type": chat.get("chat_type"),
            "modules": modules,
        }
    )
    await edit_or_reply(
        update,
        format_period_prompt(chat_title=chat.get("title"), chat_type=chat.get("chat_type")),
        reply_markup=period_keyboard(language),
    )


async def handle_chat_home_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parent = context.user_data.get(CHAT_HOME_PARENT)
    if isinstance(parent, dict):
        if parent.get("kind") == "my_chats":
            from relchat.bot.handlers.chats import show_chat_section

            await show_chat_section(update, context, str(parent.get("section") or "saved"))
            return
        if parent.get("kind") == "browse":
            from relchat.bot.handlers.analysis import render_chat_page

            await render_chat_page(update, context)
            return
        if parent.get("kind") == "reports":
            from relchat.bot.handlers.reports import show_reports_home

            await show_reports_home(update, context)
            return
    await show_expired_navigation(update, context)


async def show_expired_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    with connect(settings.db_path) as conn:
        language = get_user_settings(conn, bot_user_id(update)).get("language", "en")
    await edit_or_reply(update, t(language, "expired_navigation"), reply_markup=main_keyboard(language))


def chat_home_state(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": chat.get("source") or "telegram",
        "chat_id": chat.get("chat_id"),
        "chat_type": chat.get("chat_type"),
        "title": chat.get("title") or chat.get("local_title") or chat.get("display_title"),
        "display_title": chat.get("display_title"),
        "local_title": chat.get("local_title"),
        "username": chat.get("username"),
        "is_favorite": bool(chat.get("is_favorite")),
        "is_important": bool(chat.get("is_important")),
        "last_report_id": chat.get("last_report_id"),
    }


def current_chat(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    chat = context.user_data.get(CHAT_HOME_STATE)
    if not isinstance(chat, dict):
        return None
    if not chat.get("chat_id"):
        return None
    return chat


def latest_report_for_chat(conn, user_id: int, chat: dict[str, Any]) -> dict[str, Any] | None:
    reports = list_reports(conn, user_id, chat_id=chat["chat_id"], limit=1)
    return reports[0] if reports else None


def pending_followup_count(conn, user_id: int, chat: dict[str, Any]) -> int:
    count = 0
    for status in ["suggested", "confirmed"]:
        count += sum(1 for item in list_reminders(conn, user_id, status=status, limit=1000) if item.get("chat_id") == chat["chat_id"])
    return count


def confirmed_reminder_count(conn, user_id: int, chat: dict[str, Any]) -> int:
    return sum(1 for item in list_reminders(conn, user_id, status="confirmed", limit=1000) if item.get("chat_id") == chat["chat_id"])


def reminders_for_chat(conn, user_id: int, chat: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    source = chat.get("source") or "telegram"
    return [
        item
        for item in list_reminders(conn, user_id, limit=limit)
        if item.get("chat_id") == chat["chat_id"] and (item.get("source") or "telegram") == source
    ]


def is_analysis_running(conn, user_id: int, chat: dict[str, Any]) -> bool:
    jobs = list_analysis_jobs(conn, user_id, statuses=JOB_RUNNING_STATES, limit=1000)
    return any(job.get("chat_id") == chat["chat_id"] for job in jobs)
