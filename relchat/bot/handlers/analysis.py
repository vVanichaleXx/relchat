from __future__ import annotations

from datetime import datetime, timezone
from importlib.util import find_spec
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from relchat.bot.formatters import (
    format_analysis_review,
    format_analysis_mode_prompt,
    format_ai_consent_prompt,
    format_ai_unavailable,
    format_category_prompt,
    format_chat_page,
    format_custom_end_prompt,
    format_custom_start_prompt,
    format_invalid_date_message,
    format_job_progress,
    format_module_selection,
)
from relchat.bot.handlers.chat_home import show_chat_home
from relchat.bot.handlers.common import (
    bot_user_id,
    edit_or_reply,
    ensure_mtproto_ready,
    get_context_settings,
)
from relchat.bot.keyboards import (
    ai_consent_keyboard,
    analysis_mode_keyboard,
    category_keyboard,
    chat_list_keyboard,
    custom_end_keyboard,
    job_progress_keyboard,
    module_keyboard,
    review_keyboard,
    search_prompt_keyboard,
)
from relchat.bot.services.analysis_jobs import request_cancel, start_background_job
from relchat.bot.services.chat_browser import PAGE_SIZE, filter_conversations, paginate_conversations, search_conversations
from relchat.bot.state import (
    ANALYSIS_FLOW,
    AWAITING_TEXT,
    CHAT_BROWSER,
    DEFAULT_MODULE_IDS,
    PERIOD_BY_ID,
    RUNNABLE_MODULE_IDS,
    clear_flow,
    get_flow,
    iso_date,
    normalize_module_selection,
    parse_user_date,
    period_label,
    period_start,
)
from relchat.core.models import ConversationRef, DialogFolder
from relchat.database.repositories import (
    accept_ai_consent,
    create_analysis_job,
    get_analysis_job,
    get_user_settings,
    has_active_ai_consent,
    list_user_chats,
    save_user_chat,
)
from relchat.database.sqlite import connect, init_db
from relchat.telegram.importer import list_conversations, list_dialog_folders


GUIDED_DIALOG_FETCH_LIMIT = None


async def handle_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> bool:
    if len(parts) < 2:
        return False
    if parts[1] == "nav" and len(parts) >= 3 and parts[2] == "analyze":
        await load_chat_browser(update, context)
        return True
    if parts[1] == "browse":
        await handle_browse_callback(update, context, parts)
        return True
    if parts[1] == "analysis":
        await handle_analysis_step_callback(update, context, parts)
        return True
    if parts[1] == "job":
        await handle_job_callback(update, context, parts)
        return True
    return False


async def load_chat_browser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        settings = get_context_settings(context)
        ensure_mtproto_ready(settings)
        language = get_language(update, context)
        await edit_or_reply(update, "Loading chats...")
        init_db(settings.db_path)
        conversations = await list_conversations(settings, limit=GUIDED_DIALOG_FETCH_LIMIT)
        folders = await safe_list_dialog_folders(settings)
        user_id = bot_user_id(update)
        with connect(settings.db_path) as conn:
            favorite_ids = {chat["chat_id"] for chat in list_user_chats(conn, user_id, section="favorites", limit=1000)}
            recent_ids = {chat["chat_id"] for chat in list_user_chats(conn, user_id, section="recent", limit=1000)}
            for conversation in conversations:
                save_user_chat(conn, user_id, conversation)
        context.user_data[CHAT_BROWSER] = {
            "conversations": conversations,
            "filtered": conversations,
            "folders": folders,
            "category": "All chats",
            "page": 0,
            "search_query": None,
            "favorite_ids": favorite_ids,
            "recent_ids": recent_ids,
        }
        await edit_or_reply(
            update,
            format_category_prompt(folder_count=len(folders)),
            reply_markup=category_keyboard(folders, language=language),
        )
    except Exception as exc:
        await edit_or_reply(
            update,
            "Could not load chats. Check the local Telegram connection and try again.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("Retry", callback_data="rc:nav:analyze")],
                    [InlineKeyboardButton("Cancel", callback_data="rc:cancel")],
                ]
            ),
        )


async def safe_list_dialog_folders(settings) -> list[DialogFolder]:
    try:
        return await list_dialog_folders(settings)
    except Exception:
        return []


async def handle_browse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    language = get_language(update, context)
    browser = get_browser(context)
    if len(parts) >= 4 and parts[2] == "cat":
        category = parts[3]
        filtered = filter_conversations(
            browser["conversations"],
            category,
            favorite_ids=set(browser.get("favorite_ids") or set()),
            recent_ids=set(browser.get("recent_ids") or set()),
        )
        browser.update(
            {
                "filtered": filtered,
                "category": category_title(category),
                "page": 0,
                "search_query": None,
            }
        )
        await render_chat_page(update, context)
        return
    if len(parts) >= 4 and parts[2] == "folder":
        folder_id = parse_folder_id(parts[3])
        if folder_id is None:
            await edit_or_reply(update, "This folder is no longer available. Return to the chat list and try again.")
            return
        await edit_or_reply(update, "Loading chats...")
        filtered = await load_folder_conversations(update, context, folder_id)
        browser.update({"filtered": filtered, "category": folder_title(browser, str(folder_id)), "page": 0, "search_query": None})
        await render_chat_page(update, context)
        return
    if len(parts) >= 4 and parts[2] == "page":
        page = int(browser.get("page") or 0)
        if parts[3] == "next":
            page += 1
        elif parts[3] == "previous":
            page -= 1
        browser["page"] = page
        await render_chat_page(update, context)
        return
    if len(parts) >= 4 and parts[2] == "back":
        if parts[3] == "categories":
            await edit_or_reply(
                update,
                format_category_prompt(folder_count=len(browser.get("folders") or [])),
                reply_markup=category_keyboard(browser.get("folders") or [], language=language),
            )
        else:
            context.user_data[AWAITING_TEXT] = None
            await render_chat_page(update, context)
        return
    if len(parts) >= 3 and parts[2] == "search":
        context.user_data[AWAITING_TEXT] = "chat_search"
        await edit_or_reply(
            update,
            "Search chat\n\nSend a display name, title, or username. Message contents are not searched.",
            reply_markup=search_prompt_keyboard(language),
        )
        return
    if len(parts) >= 4 and parts[2] == "select":
        await select_chat(update, context, parts[3])
        return


async def render_chat_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = get_language(update, context)
    browser = get_browser(context)
    page = paginate_conversations(browser["filtered"], int(browser.get("page") or 0), page_size=PAGE_SIZE)
    browser["page"] = page.page
    flow = get_flow(context.user_data)
    await edit_or_reply(
        update,
        format_chat_page(
            title=str(browser.get("category") or "Chats"),
            first_item=page.first_item_number,
            last_item=page.last_item_number,
            total=page.total,
            search_query=browser.get("search_query"),
        ),
        reply_markup=chat_list_keyboard(
            page.items,
            page=page.page,
            page_size=PAGE_SIZE,
            has_previous=page.has_previous,
            has_next=page.has_next,
            selected_chat_id=flow.get("chat_id"),
            language=language,
        ),
    )


async def select_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, value: str) -> None:
    try:
        index = int(value)
    except ValueError:
        await edit_or_reply(update, "Selected chat is no longer available.")
        return
    browser = get_browser(context)
    conversations: list[ConversationRef] = browser.get("filtered") or []
    if index < 0 or index >= len(conversations):
        await edit_or_reply(update, "Selected chat is no longer available. Choose it again.")
        return
    conversation = conversations[index]
    settings = get_context_settings(context)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        save_user_chat(conn, user_id, conversation, saved=True)
    await show_chat_home(
        update,
        context,
        {
            "source": conversation.source,
            "chat_id": conversation.conversation_id,
            "chat_type": conversation.conversation_type,
            "title": conversation.title,
            "display_title": conversation.title,
            "username": conversation.username,
            "folder_id": conversation.folder_id,
            "unread_count": conversation.unread_count,
        },
        parent={"kind": "browse"},
    )


async def handle_analysis_step_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    if len(parts) >= 4 and parts[2] == "period":
        await set_period(update, context, parts[3])
        return
    if len(parts) >= 4 and parts[2] == "custom_end" and parts[3] == "none":
        flow = get_flow(context.user_data)
        flow["period_end"] = None
        flow["period_label"] = period_label("custom", custom_start=flow.get("period_start_date"))
        await show_analysis_mode(update, context)
        return
    if len(parts) >= 4 and parts[2] == "mode":
        await choose_analysis_mode(update, context, parts[3])
        return
    if len(parts) >= 4 and parts[2] == "ai_consent":
        await handle_ai_consent(update, context, parts[3])
        return
    if len(parts) >= 4 and parts[2] == "module":
        toggle_module(context, parts[3])
        await show_module_selection(update, context)
        return
    if len(parts) >= 4 and parts[2] == "modules":
        if parts[3] == "all":
            get_flow(context.user_data)["modules"] = RUNNABLE_MODULE_IDS.copy()
            await show_module_selection(update, context)
            return
        if parts[3] == "clear":
            get_flow(context.user_data)["modules"] = []
            await show_module_selection(update, context)
            return
        if parts[3] == "continue":
            flow = get_flow(context.user_data)
            if not flow.get("modules"):
                flow["modules"] = DEFAULT_MODULE_IDS.copy()
            await edit_or_reply(update, format_analysis_review(flow), reply_markup=review_keyboard(get_language(update, context)))
            return
    if len(parts) >= 4 and parts[2] == "back" and parts[3] == "modules":
        await show_module_selection(update, context)
        return
    if len(parts) >= 3 and parts[2] == "start":
        await create_and_start_job(update, context)
        return


async def set_period(update: Update, context: ContextTypes.DEFAULT_TYPE, period_id: str) -> None:
    flow = get_flow(context.user_data)
    option = PERIOD_BY_ID.get(period_id)
    if option is None:
        await edit_or_reply(update, "Unknown period. Choose another option.")
        return
    if option.custom:
        flow["period_id"] = "custom"
        context.user_data[AWAITING_TEXT] = "custom_start"
        await edit_or_reply(update, format_custom_start_prompt(flow.get("chat_title")))
        return
    start = period_start(period_id)
    flow.update(
        {
            "period_id": period_id,
            "period_label": option.label,
            "period_start": start.isoformat() if start else None,
            "period_start_date": iso_date(start),
            "period_end": None,
        }
    )
    await show_analysis_mode(update, context)


async def show_module_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = get_language(update, context)
    flow = get_flow(context.user_data)
    selected = list(flow.get("modules") or [])
    await edit_or_reply(update, format_module_selection(selected), reply_markup=module_keyboard(selected, language=language))


async def show_analysis_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    language = get_language(update, context)
    flow = get_flow(context.user_data)
    ensure_default_modules(update, context, flow)
    await edit_or_reply(
        update,
        format_analysis_mode_prompt(chat_title=flow.get("chat_title"), language=language),
        reply_markup=analysis_mode_keyboard(ai_available=bool(settings.ai_enabled), language=language),
    )


async def choose_analysis_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    flow = get_flow(context.user_data)
    if mode == "local":
        flow["analysis_mode"] = "local"
        await create_and_start_job(update, context)
        return
    if mode != "ai":
        await show_analysis_mode(update, context)
        return
    settings = get_context_settings(context)
    language = get_language(update, context)
    unavailable = ai_unavailable_reason(settings)
    if unavailable:
        await edit_or_reply(
            update,
            format_ai_unavailable(unavailable, language=language),
            reply_markup=analysis_mode_keyboard(ai_available=False, language=language),
        )
        return
    with connect(settings.db_path) as conn:
        consent = has_active_ai_consent(conn, bot_user_id(update))
    if not consent:
        await edit_or_reply(update, format_ai_consent_prompt(language=language), reply_markup=ai_consent_keyboard(language))
        return
    flow["analysis_mode"] = "ai"
    await create_and_start_job(update, context)


async def handle_ai_consent(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    flow = get_flow(context.user_data)
    if action == "local":
        flow["analysis_mode"] = "local"
        await create_and_start_job(update, context)
        return
    if action != "accept":
        await show_analysis_mode(update, context)
        return
    settings = get_context_settings(context)
    with connect(settings.db_path) as conn:
        accept_ai_consent(conn, bot_user_id(update))
    flow["analysis_mode"] = "ai"
    await create_and_start_job(update, context)


def toggle_module(context: ContextTypes.DEFAULT_TYPE, module_id: str) -> None:
    if module_id not in RUNNABLE_MODULE_IDS:
        return
    flow = get_flow(context.user_data)
    selected = list(flow.get("modules") or [])
    if module_id in selected:
        selected.remove(module_id)
    else:
        selected.append(module_id)
    flow["modules"] = selected


async def create_and_start_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_context_settings(context)
    init_db(settings.db_path)
    flow = get_flow(context.user_data)
    if not flow.get("chat_id") or not flow.get("period_id"):
        await edit_or_reply(update, "Choose a chat and time period first.")
        return
    modules = normalize_module_selection(list(flow.get("modules") or []))
    analysis_mode = "ai" if flow.get("analysis_mode") == "ai" else "local"
    query = update.callback_query
    progress_chat_id = query.message.chat_id if query and query.message else None
    progress_message_id = query.message.message_id if query and query.message else None
    with connect(settings.db_path) as conn:
        job = create_analysis_job(
            conn,
            bot_user_id=bot_user_id(update),
            source=flow.get("source") or "telegram",
            chat_id=flow["chat_id"],
            chat_title=flow.get("chat_title"),
            period_id=flow["period_id"],
            period_label=flow["period_label"],
            period_start=flow.get("period_start"),
            period_end=flow.get("period_end"),
            modules=modules,
            progress_chat_id=progress_chat_id,
            progress_message_id=progress_message_id,
            analysis_mode=analysis_mode,
        )
    clear_flow(context.user_data)
    await edit_or_reply(update, format_job_progress(job), reply_markup=job_progress_keyboard(job["job_id"], language=get_language(update, context)))
    start_background_job(context.application, settings, job["job_id"])


async def handle_job_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    if len(parts) < 4:
        return
    settings = get_context_settings(context)
    job_id = parts[3]
    if parts[2] == "cancel":
        job = request_cancel(context.application, settings, job_id)
        if job:
            await edit_or_reply(
                update,
                "Analysis cancellation requested.\n\nRelChat will stop at the next safe point.",
                reply_markup=job_progress_keyboard(job_id, can_cancel=False, language=get_language(update, context)),
            )
        return
    if parts[2] == "retry":
        with connect(settings.db_path) as conn:
            job = get_analysis_job(conn, job_id)
        if not job:
            await edit_or_reply(update, "This job is no longer available.")
            return
        flow = get_flow(context.user_data)
        flow.clear()
        flow.update(
            {
                "source": job["source"],
                "chat_id": job["chat_id"],
                "chat_title": job["chat_title"],
                "period_id": job["period_id"],
                "period_label": job["period_label"],
                "period_start": job["period_start"],
                "period_end": job["period_end"],
                "modules": job["modules"],
            }
        )
        await edit_or_reply(update, format_analysis_review(flow), reply_markup=review_keyboard(get_language(update, context)))


async def handle_analysis_text(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, text: str) -> bool:
    if mode == "chat_search":
        browser = get_browser(context)
        results = search_conversations(browser.get("conversations") or [], text)
        browser.update({"filtered": results, "category": "Search results", "search_query": text, "page": 0})
        context.user_data[AWAITING_TEXT] = None
        await render_chat_page(update, context)
        return True
    if mode == "custom_start":
        parsed = parse_user_date(text)
        if parsed is None:
            await edit_or_reply(update, format_invalid_date_message())
            return True
        flow = get_flow(context.user_data)
        flow["period_id"] = "custom"
        flow["period_start"] = parsed.isoformat()
        flow["period_start_date"] = iso_date(parsed)
        context.user_data[AWAITING_TEXT] = "custom_end"
        await edit_or_reply(
            update,
            format_custom_end_prompt(flow["period_start_date"]),
            reply_markup=custom_end_keyboard(get_language(update, context)),
        )
        return True
    if mode == "custom_end":
        parsed = parse_user_date(text)
        if parsed is None:
            await edit_or_reply(update, format_invalid_date_message(), reply_markup=custom_end_keyboard(get_language(update, context)))
            return True
        flow = get_flow(context.user_data)
        start = datetime.fromisoformat(flow["period_start"])
        if parsed < start:
            await edit_or_reply(update, "End date must be after the start date.", reply_markup=custom_end_keyboard(get_language(update, context)))
            return True
        flow["period_end"] = parsed.replace(tzinfo=timezone.utc).isoformat()
        flow["period_end_date"] = iso_date(parsed)
        flow["period_label"] = period_label("custom", custom_start=flow.get("period_start_date"), custom_end=flow.get("period_end_date"))
        context.user_data[AWAITING_TEXT] = None
        await show_analysis_mode(update, context)
        return True
    return False


def ensure_default_modules(update: Update, context: ContextTypes.DEFAULT_TYPE, flow: dict[str, Any]) -> None:
    if flow.get("modules"):
        return
    settings = get_context_settings(context)
    with connect(settings.db_path) as conn:
        configured = get_user_settings(conn, bot_user_id(update)).get("default_modules") or []
    flow["modules"] = normalize_module_selection(list(configured))


def ai_unavailable_reason(settings) -> str | None:
    if not settings.ai_enabled:
        return "ai_disabled"
    if not settings.openai_api_key:
        return "missing_api_key"
    if not settings.ai_model:
        return "missing_model"
    if find_spec("openai") is None:
        return "openai_sdk_missing"
    return None


def get_browser(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    browser = context.user_data.setdefault(CHAT_BROWSER, {})
    if not isinstance(browser, dict):
        browser = {}
        context.user_data[CHAT_BROWSER] = browser
    browser.setdefault("conversations", [])
    browser.setdefault("filtered", browser["conversations"])
    browser.setdefault("folders", [])
    browser.setdefault("page", 0)
    return browser


def folder_title(browser: dict[str, Any], folder_id: str) -> str:
    for folder in browser.get("folders") or []:
        if str(folder.folder_id) == str(folder_id):
            return folder.title
    return "Telegram folder"


async def load_folder_conversations(update: Update, context: ContextTypes.DEFAULT_TYPE, folder_id: int) -> list[ConversationRef]:
    settings = get_context_settings(context)
    ensure_mtproto_ready(settings)
    conversations = await list_conversations(settings, limit=GUIDED_DIALOG_FETCH_LIMIT, folder_id=folder_id)
    user_id = bot_user_id(update)
    with connect(settings.db_path) as conn:
        for conversation in conversations:
            save_user_chat(conn, user_id, conversation)
    return conversations


def parse_folder_id(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def category_title(category: str) -> str:
    return {
        "all": "All chats",
        "private": "People",
        "groups": "Groups",
        "channels": "Channels",
        "unread": "Unread chats",
        "favorites": "Favorite chats",
        "recent": "Recently analyzed",
    }.get(category, "Chats")


def get_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    settings = get_context_settings(context)
    with connect(settings.db_path) as conn:
        return get_user_settings(conn, bot_user_id(update)).get("language", "en")
