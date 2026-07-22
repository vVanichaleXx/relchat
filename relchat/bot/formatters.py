from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone
from typing import Any

from relchat.core.models import ConversationEvent, ConversationRef, Message
from relchat.events.extractor import summarize_events
from relchat.bot.localization import t
from relchat.bot.services.chat_home_service import build_chat_home_view_model
from relchat.bot.services.context import context_label, context_score_label, low_confidence_context_note
from relchat.bot.services.evidence_service import build_why_conclusion_panels
from relchat.bot.services.period_comparison import format_period_comparison_compact, format_period_comparison_full
from relchat.bot.services.timeline_service import RelationshipTimeline, TimelineEntry, TimelinePage, TimelineStoryItem, TimelineStoryPage, paginate_timeline_story
from relchat.bot.state import module_labels
from relchat.bot.ui_components import DIVIDER, render_empty_state, render_field, render_loading_state, render_section, render_status


MAX_BOT_MESSAGE_LENGTH = 3800
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")


def chunk_text(text: str, *, limit: int = MAX_BOT_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in text.splitlines():
        line_length = len(line) + 1
        if current and current_length + line_length > limit:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        if line_length > limit:
            chunks.extend(split_long_line(line, limit=limit))
            continue
        current.append(line)
        current_length += line_length
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def split_long_line(line: str, *, limit: int) -> list[str]:
    return [line[index : index + limit] for index in range(0, len(line), limit)]


def sanitize_label(value: str | None, *, fallback: str = "unknown", limit: int = 80) -> str:
    text = " ".join((value or "").split())
    if not text:
        return fallback
    return clip_text(PHONE_RE.sub("[redacted phone]", text), limit=limit)


def clip_text(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return f"{value[: limit - 3]}..."


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_start() -> str:
    return (
        "RelChat\n\n"
        "Choose an action below."
    )


def format_help() -> str:
    return (
        "RelChat help\n\n"
        "RelChat can analyze selected Telegram conversations with local metrics, detected events, report sections, "
        "and optional reminder suggestions.\n\n"
        "It cannot read private chats through the Bot API. Chat history is loaded locally through your own "
        "Telegram account after local authorization.\n\n"
        "RelChat reports are based on observed message metadata and aggregate patterns. They do not claim hidden "
        "intentions, feelings, diagnoses, or psychological explanations."
    )


def format_commands() -> str:
    return "\n".join(
        [
            "/start - show the bot summary",
            "/help - show all commands",
            "/status - show local setup status",
            "/chats [private|groups|channels] [limit] - list conversations",
            "/import <chat_id> - import 90 days, up to 5000 messages",
            "/metrics <chat_id> - show basic local metrics",
            "/events <chat_id> - show Event Engine v0 summary",
        ]
    )


def format_status(
    *,
    database_exists: bool,
    mtproto_session_exists: bool,
    mtproto_credentials_exist: bool,
    bot_restricted: bool,
    allowed_user_count: int,
) -> str:
    return "\n".join(
        [
            "RelChat status",
            "",
            f"Database exists: {yes_no(database_exists)}",
            f"Telegram MTProto session exists: {yes_no(mtproto_session_exists)}",
            f"Telegram API credentials exist: {yes_no(mtproto_credentials_exist)}",
            f"Bot restricted to allowed user IDs: {yes_no(bot_restricted)} ({allowed_user_count} configured)",
        ]
    )


def format_main_menu(
    *,
    language: str,
    telegram_connected: bool,
    saved_chats: int,
    reports: int,
    followups: int = 0,
    running_jobs: int,
) -> str:
    status = t(language, "main_connected") if telegram_connected else t(language, "main_not_connected")
    running = t(language, "main_running") if running_jobs else t(language, "main_idle")
    return "\n".join(
        [
            t(language, "main_title"),
            "",
            status,
            f"{t(language, 'main_saved_chats')}: {saved_chats}",
            f"{t(language, 'main_reports')}: {reports}",
            f"{t(language, 'main_followups')}: {followups}",
            f"{running}: {running_jobs}" if running_jobs else running,
        ]
    )


def format_onboarding(step: int, *, language: str, telegram_connected: bool) -> str:
    if step == 1:
        return "\n\n".join([t(language, "onboarding_1_title"), t(language, "onboarding_1_body")])
    if step == 2:
        return "\n\n".join([t(language, "onboarding_2_title"), t(language, "onboarding_2_body")])
    connection = t(language, "onboarding_3_connected") if telegram_connected else t(language, "onboarding_3_missing")
    return "\n\n".join(["Telegram", connection, t(language, "onboarding_safe_auth")])


def format_help_page(page: str, *, language: str = "en") -> str:
    pages = {
        "analyze": (
            "What RelChat can analyze",
            [
                "RelChat can count participation, session starts, response timing, activity patterns, unanswered questions, plans, follow-up candidates, and explicit reminder candidates.",
                "Reports are generated from selected chats and selected periods only.",
            ],
        ),
        "privacy": (
            t(language, "privacy_title"),
            [
                "RelChat stores local data in SQLite on this machine.",
                "Bot replies avoid raw message text, tokens, session contents, phone numbers, and private chat history.",
                "Deleting local RelChat data never deletes Telegram conversations.",
            ],
        ),
        "auth": (
            t(language, "auth_title"),
            [
                "Telegram bots cannot read your private chat history through the Bot API.",
                "RelChat uses one local authorization of your own Telegram account to load chats locally.",
                "Never send login codes, passwords, API hashes, bot tokens, session files, or phone numbers to the bot.",
            ],
        ),
        "metrics": (
            t(language, "metrics_title"),
            [
                "Balance shows how message counts are distributed between participants.",
                "Initiation estimates who started new conversation sessions after quiet gaps.",
                "Response patterns summarize observed reply timing when the speaker changed.",
                "Questions and plans are rule-based candidates, not claims about intent.",
            ],
        ),
        "limits": (
            t(language, "limits_title"),
            [
                "RelChat cannot know hidden intentions, attraction, love, manipulation, attachment style, or psychological diagnoses.",
                "It can only summarize observed data in the selected local messages.",
                "Short or incomplete history can make patterns unreliable.",
            ],
        ),
        "trouble": (
            t(language, "troubleshooting_title"),
            [
                "If chats do not load, check the local Telegram authorization and network connection.",
                "If Telegram asks RelChat to wait, retry later.",
                "If no report appears, confirm that the selected period contains messages.",
            ],
        ),
        "about": (
            t(language, "about_title"),
            [
                "RelChat is a local-first open-source conversation analysis project.",
                "The current product focuses on Telegram import, local metrics, report history, and reminder foundations.",
            ],
        ),
    }
    title, lines = pages.get(page, pages["analyze"])
    return "\n\n".join([title, "\n".join(lines)])


def format_my_chats_home(counts: dict[str, int], *, language: str = "en") -> str:
    return "\n".join(
        [
            t(language, "my_chats_title"),
            "",
            f"{t(language, 'important_chats_title')}: {counts.get('important', 0)}",
            f"{t(language, 'my_chats_favorites')}: {counts.get('favorites', 0)}",
            f"{t(language, 'my_chats_recent')}: {counts.get('recent', 0)}",
            f"{t(language, 'my_chats_saved')}: {counts.get('saved', 0)}",
            "",
            t(language, "my_chats_choose_section"),
        ]
    )


def format_saved_chat_section(title: str, chats: Sequence[dict], *, language: str = "en", section: str | None = None) -> str:
    lines = [title, ""]
    if not chats:
        if section == "recent":
            lines.append(t(language, "empty_no_recent_chats"))
        else:
            lines.append(t(language, "empty_no_analyzed_chats"))
        return "\n".join(lines)
    lines.append(t(language, "my_chats_choose"))
    return "\n".join(lines)


def format_saved_chat_detail(chat: dict) -> str:
    lines = [
        sanitize_label(chat.get("title"), fallback="Untitled chat"),
        "",
        f"Type: {readable_chat_type(chat.get('chat_type'))}",
        f"Favorite: {yes_no(bool(chat.get('is_favorite')))}",
        f"Recently analyzed: {sanitize_label(chat.get('recent_analyzed_at'), fallback='not yet', limit=30)}",
    ]
    if chat.get("last_report_id"):
        lines.append("Latest report: available")
    return "\n".join(lines)


def format_important_chats(chats: Sequence[dict], *, page: int = 0, language: str = "en") -> str:
    lines = [t(language, "important_chats_title"), ""]
    if not chats:
        lines.append(t(language, "important_empty"))
        return "\n".join(lines)
    lines.append(t(language, "my_chats_choose"))
    return "\n".join(lines)


def format_important_chat_detail(chat: dict, *, language: str = "en") -> str:
    title = sanitize_label(chat.get("title"), fallback=t(language, "chat_type_unknown"), limit=80)
    auto = t(language, "yes") if chat.get("automatic_analysis_enabled") else t(language, "no")
    last = sanitize_label(chat.get("last_automatic_analysis_at"), fallback=t(language, "not_available"), limit=40)
    pending = int(chat.get("pending_new_message_count") or 0)
    return "\n".join(
        [
            title,
            "",
            t(language, "important_chat_label"),
            f"{t(language, 'automation_analysis')}: {auto}",
            f"{t(language, 'automation_last')}: {last}",
            f"{t(language, 'automation_pending_count')}: {pending}",
        ]
    )


def format_chat_home(
    chat: dict,
    *,
    report: dict | None = None,
    pending_followups: int = 0,
    running: bool = False,
    language: str = "en",
) -> str:
    if "state" in chat and "activity" in chat and "analysis" in chat:
        return format_chat_home_view(chat, language=language)
    view_model = build_chat_home_view_model(
        chat=chat,
        reports=[report] if report is not None else [],
        running=running,
        language=language,
    )
    if pending_followups:
        view_model["attention"]["open_follow_up_count"] = max(
            int(view_model["attention"].get("open_follow_up_count") or 0),
            pending_followups,
        )
        if view_model["attention"].get("primary_action_label") is None:
            view_model["attention"]["primary_action_label"] = t(language, "button_followups")
    return format_chat_home_view(view_model, language=language)


def format_chat_home_view(view_model: dict[str, Any], *, language: str = "en") -> str:
    chat = view_model.get("chat") or {}
    attention = view_model.get("attention") or {}
    analysis = view_model.get("analysis") or {}
    state = view_model.get("state") or {}
    chat_type = chat.get("chat_type")
    title = sanitize_label(chat.get("title"), fallback=t(language, "chat_type_unknown"), limit=80)
    score = analysis.get("latest_score")
    score_line = f"{float(score):.1f} / 10" if isinstance(score, (int, float)) else t(language, "not_available")
    if chat_type in {"group", "channel"}:
        score_title = t(language, "ai_activity_score")
    else:
        score_title = t(language, "ai_communication_score")
    headline = sanitize_label(
        state.get("headline") or state.get("explanation"),
        fallback=t(language, "chat_home_v4_state_no_analysis"),
        limit=180,
    )
    if not analysis.get("has_report") and not analysis.get("latest_score"):
        headline = f"{headline} {t(language, 'chat_home_v4_no_analysis_body')}"
    lines = [
        title,
        readable_chat_type(chat_type, language=language),
        "",
        headline,
        "",
        render_field(score_title, score_line, sanitize_label(analysis.get("score_confidence_label"), fallback=analysis.get("data_confidence_label") or t(language, "not_available"), limit=40)),
        "",
        render_field(
            t(language, "chat_home_v4_last_analysis"),
            sanitize_label(analysis.get("last_analysis_label"), fallback=t(language, "not_available"), limit=40),
            sanitize_label(analysis.get("last_period_label"), fallback=t(language, "not_available"), limit=40),
        ),
        "",
        render_field(t(language, "chat_home_v4_followup_title"), chat_home_attention_line(attention, language=language)),
    ]
    if analysis.get("running"):
        lines.extend(["", t(language, "chat_home_running")])
    return "\n".join(lines)


def format_chat_home_details_menu(*, language: str = "en") -> str:
    return "\n\n".join([t(language, "chat_home_details_title"), t(language, "chat_home_details_body")])


def format_context_correction_prompt(chat: dict[str, Any] | None = None, *, language: str = "en") -> str:
    title = sanitize_label((chat or {}).get("title") or (chat or {}).get("display_title"), fallback=t(language, "chat_type_unknown"), limit=80)
    return "\n\n".join([title, t(language, "context_change_title"), t(language, "context_change_body")])


def format_analysis_mode_prompt(*, chat_title: str | None, language: str = "en") -> str:
    return "\n\n".join(
        [
            t(language, "analysis_mode_title"),
            sanitize_label(chat_title, fallback=t(language, "chat_type_unknown"), limit=80),
            t(language, "analysis_mode_body"),
        ]
    )


def format_ai_consent_prompt(*, language: str = "en") -> str:
    return t(language, "ai_consent_prompt")


def format_ai_unavailable(reason: str, *, language: str = "en") -> str:
    key = {
        "ai_disabled": "ai_error_disabled",
        "missing_api_key": "ai_error_missing_key",
        "missing_model": "ai_error_missing_model",
        "openai_sdk_missing": "ai_error_sdk_missing",
    }.get(reason, "ai_error_generic")
    return "\n\n".join([t(language, key), t(language, "ai_offer_local")])


def format_ai_result_overview(analysis: dict[str, Any], *, chat_title: str | None = None, language: str = "en") -> str:
    result = analysis.get("result") or analysis
    title = sanitize_label(chat_title or analysis.get("chat_title"), fallback=t(language, "chat_type_unknown"), limit=80)
    score_state = result.get("score_state") or {}
    score = result.get("overall_score")
    confidence = result.get("score_confidence") or result.get("confidence") or analysis.get("confidence") or "low"
    participants = normalized_participants(result)
    positive = pattern_bullets(result.get("positive_patterns"), limit=3)
    problems = pattern_bullets(result.get("problem_patterns"), limit=3)
    direct = direct_findings_bullets(result.get("direct_findings"), limit=3, language=language)
    verdict = result.get("verdict") if isinstance(result.get("verdict"), dict) else {}
    advice = result.get("advice") or []
    main_advice = advice[0] if advice else {}
    coverage = result.get("coverage") or analysis.get("coverage") or {}
    coverage_line = format_ai_coverage_line(coverage, language=language)
    comparison = analysis.get("comparison") or result.get("period_comparison")
    context = result.get("context") if isinstance(result.get("context"), dict) else {}
    context_category = context.get("category")
    individualized = result.get("individualized_story") if isinstance(result.get("individualized_story"), dict) else {}
    distinctive_text = format_selected_patterns_compact(result.get("selected_patterns"), language=language, limit=3)
    feedback = result.get("personalized_feedback") if isinstance(result.get("personalized_feedback"), dict) else {}
    score_explanation = format_score_explanation_compact(result.get("score_explanation"), language=language)
    history_text = format_history_segments_compact(result.get("history_segments"), language=language)
    if context_category == "work":
        return format_work_result_overview(analysis, chat_title=title, language=language)
    lines = [title, "", t(language, "ai_communication_analysis"), context_label(context_category, language=language), ""]
    context_note = low_confidence_context_note(context, language=language) if context else ""
    if context_note:
        lines.extend([context_note, ""])
    lines.extend(
        [
            context_score_label(context_category, language=language),
            f"{float(score):.1f} / 10" if isinstance(score, (int, float)) else t(language, "ai_score_unreliable"),
            t(language, "ai_confidence_line", confidence=t(language, f"confidence_{confidence}") if confidence in {"low", "medium", "high"} else confidence),
            "",
        ]
    )
    story_intro = format_individualized_story_overview(individualized, language=language)
    if story_intro:
        lines.extend([story_intro, ""])
    else:
        summary = sanitize_label(result.get("summary"), fallback="", limit=700)
        if summary and not is_meta_filler(summary):
            lines.extend([t(language, "ai_summary_title"), summary, ""])
    if distinctive_text:
        lines.extend([t(language, "individual_distinctive_title"), distinctive_text, ""])
    headline = sanitize_label(verdict.get("headline"), fallback="", limit=180)
    explanation = sanitize_label(verdict.get("explanation"), fallback="", limit=360)
    if not individualized and (headline or explanation):
        lines.extend([t(language, "ai_verdict_title"), "\n".join(item for item in [headline, explanation] if item), ""])
    story = result.get("communication_story") if isinstance(result.get("communication_story"), dict) else {}
    happening = sanitize_label(story.get("what_is_happening"), fallback="", limit=420)
    if happening and not individualized and not is_meta_filler(happening):
        lines.extend([t(language, "story_what_is_happening_title"), happening, ""])
    if history_text:
        lines.extend([t(language, "history_section_title"), history_text, ""])
    if direct:
        lines.extend([t(language, "ai_direct_findings_title"), direct, ""])
    profile = result.get("personal_profile") if isinstance(result.get("personal_profile"), dict) else {}
    profile_text = format_personal_profile_compact(profile, story=individualized, language=language)
    profile_contains_user_role = bool(profile_text and individualized.get("user_role"))
    if profile_text and context_category not in {"group_social", "channel_or_broadcast"}:
        lines.extend([t(language, "personal_profile_title"), profile_text, ""])
    if context_category not in {"group_social", "channel_or_broadcast"}:
        balance_text = format_participation_balance(result, participants, language=language)
        has_asymmetry = any(
            isinstance(row, dict) and row.get("participant_scope") in {"you", "other"} and not row.get("generic")
            for row in (result.get("selected_patterns") if isinstance(result.get("selected_patterns"), list) else [])
        )
        participation = result.get("participation_interpretation") if isinstance(result.get("participation_interpretation"), dict) else {}
        if balance_text and (participation.get("has_scope_difference") or not has_asymmetry):
            lines.extend([t(language, "participation_balance_title"), balance_text, ""])
        you_patterns = sanitize_label(individualized.get("user_role"), fallback="", limit=420)
        if not you_patterns:
            you_patterns = participant_pattern_bullets(participants.get("you", {}).get("observable_patterns"), participants.get("other", {}).get("observable_patterns"), side="you", limit=4)
        if you_patterns and not profile_contains_user_role:
            lines.extend([t(language, "ai_you_title"), you_patterns, ""])
        other_patterns = sanitize_label(individualized.get("other_role"), fallback="", limit=420)
        if not other_patterns:
            other_patterns = participant_pattern_bullets(participants.get("other", {}).get("observable_patterns"), participants.get("you", {}).get("observable_patterns"), side="other", limit=4)
        if other_patterns:
            lines.extend([t(language, "ai_other_title"), other_patterns, ""])
    if positive:
        lines.extend([t(language, "ai_strengths_title"), positive, ""])
    if problems:
        lines.extend([t(language, "ai_weakens_title"), problems, ""])
    main_title = sanitize_label(feedback.get("recommendation") if feedback.get("action_needed") else main_advice.get("title"), fallback="", limit=160)
    main_explanation = sanitize_label(feedback.get("reason") if feedback.get("action_needed") else main_advice.get("explanation"), fallback="", limit=360)
    if main_title or main_explanation:
        lines.extend([t(language, "ai_main_advice"), "\n".join(item for item in [main_title, main_explanation] if item)])
    if score_state.get("insufficient_data"):
        if score_explanation:
            lines.extend(["", score_explanation])
        else:
            lines.extend(["", score_state_explanation(score_state, language=language)])
    elif score_explanation:
        lines.extend(["", score_explanation])
    if isinstance(comparison, dict):
        lines.extend(["", format_period_comparison_compact(comparison, language=language)])
    if coverage_line:
        lines.extend(["", t(language, "ai_data_title"), coverage_line])
    limitations = compact_limitations(result.get("limitations"), language=language)
    if limitations:
        lines.extend(["", t(language, "ai_limitations_title"), limitations])
    return dedupe_report_text(lines, language=language)


def format_work_result_overview(analysis: dict[str, Any], *, chat_title: str, language: str = "en") -> str:
    result = analysis.get("result") or analysis
    score = result.get("overall_score")
    confidence = result.get("score_confidence") or result.get("confidence") or "low"
    score_line = f"{float(score):.1f} / 10" if isinstance(score, (int, float)) else t(language, "ai_score_unreliable")
    participants = normalized_participants(result)
    story = result.get("communication_story") if isinstance(result.get("communication_story"), dict) else {}
    individualized = result.get("individualized_story") if isinstance(result.get("individualized_story"), dict) else {}
    happening = sanitize_label(
        individualized.get("overall_picture") or story.get("what_is_happening") or result.get("summary"),
        fallback="",
        limit=620,
    )
    distinctive = format_selected_patterns_compact(result.get("selected_patterns"), language=language, limit=3)
    you_patterns = participant_pattern_bullets(participants.get("you", {}).get("observable_patterns"), participants.get("other", {}).get("observable_patterns"), side="you", limit=4)
    if individualized.get("user_role"):
        you_patterns = sanitize_label(individualized.get("user_role"), fallback="", limit=420)
    other_patterns = participant_pattern_bullets(participants.get("other", {}).get("observable_patterns"), participants.get("you", {}).get("observable_patterns"), side="other", limit=4)
    if individualized.get("other_role"):
        other_patterns = sanitize_label(individualized.get("other_role"), fallback="", limit=420)
    if not you_patterns:
        you_patterns = work_user_summary_from_profile(result.get("personal_profile"), language=language)
    helps = pattern_bullets(result.get("positive_patterns"), limit=3)
    weakens = pattern_bullets(result.get("problem_patterns"), limit=3)
    advice_rows = result.get("advice") if isinstance(result.get("advice"), list) else []
    advice = advice_rows[0] if advice_rows and isinstance(advice_rows[0], dict) else {}
    feedback = result.get("personalized_feedback") if isinstance(result.get("personalized_feedback"), dict) else {}
    history = result.get("history_segments") if isinstance(result.get("history_segments"), dict) else {}
    recent_change = sanitize_label(individualized.get("historical_note") or history.get("recent_change"), fallback="", limit=300)
    score_explanation = format_score_explanation_compact(result.get("score_explanation"), language=language)
    coverage_line = format_ai_coverage_line(result.get("coverage") or analysis.get("coverage") or {}, language=language)
    limitations = compact_limitations(result.get("limitations"), language=language)
    lines = [
        chat_title,
        "",
        context_label("work", language=language),
        "",
        context_score_label("work", language=language),
        score_line,
        t(language, "ai_confidence_line", confidence=confidence_label(confidence, language=language)),
        "",
    ]
    headline = sanitize_label(individualized.get("headline"), fallback="", limit=180)
    if headline:
        lines.extend([headline, ""])
    if happening and not is_meta_filler(happening):
        lines.extend([t(language, "work_report_happening_title"), happening, ""])
    if distinctive:
        lines.extend([t(language, "individual_distinctive_title"), distinctive, ""])
    if you_patterns:
        lines.extend([t(language, "work_report_you_title"), you_patterns, ""])
    if other_patterns:
        lines.extend([t(language, "work_report_other_title"), other_patterns, ""])
    if helps:
        lines.extend([t(language, "work_report_helps_title"), helps, ""])
    if weakens:
        lines.extend([t(language, "work_report_blocks_title"), weakens, ""])
    advice_text = "\n".join(
        item
        for item in [
            sanitize_label(feedback.get("recommendation") if feedback.get("action_needed") else advice.get("title"), fallback="", limit=180),
            sanitize_label(feedback.get("reason") if feedback.get("action_needed") else advice.get("explanation"), fallback="", limit=460),
        ]
        if item
    )
    if advice_text:
        lines.extend([t(language, "ai_main_advice"), advice_text, ""])
    if recent_change:
        lines.extend([t(language, "work_report_changes_title"), recent_change, ""])
    if score_explanation:
        lines.extend([score_explanation, ""])
    data_lines = "\n".join(item for item in [coverage_line, limitations] if item)
    if data_lines:
        lines.extend([t(language, "work_report_data_title"), data_lines])
    return dedupe_report_text(lines, language=language)


def format_ai_result_section(analysis: dict[str, Any], section: str, *, language: str = "en") -> str:
    result = analysis.get("result") or analysis
    if section == "why":
        return format_why_conclusion_section(result, language=language)
    if section == "advice":
        lines = [t(language, "ai_advice_title"), ""]
        advice_rows = result.get("advice") or []
        if not advice_rows:
            feedback = result.get("personalized_feedback") if isinstance(result.get("personalized_feedback"), dict) else {}
            message = sanitize_label(feedback.get("recommendation") or feedback.get("omitted_reason"), fallback=t(language, "feedback_no_action_general"), limit=420)
            lines.append(message)
            return "\n".join(lines).strip()
        for item in advice_rows[:5]:
            lines.extend([
                f"{int(item.get('priority') or 1)}. {sanitize_label(item.get('title'), fallback=t(language, 'not_available'), limit=160)}",
                sanitize_label(item.get("explanation"), fallback="", limit=500),
            ])
            if item.get("example"):
                lines.append(f"{t(language, 'ai_example')}: {sanitize_label(item.get('example'), fallback='', limit=240)}")
            lines.append("")
        return "\n".join(lines).strip()
    if section == "weak":
        lines = [t(language, "ai_weak_replies_title"), "", t(language, "ai_no_raw_text_note"), ""]
        weak = result.get("weak_reply_patterns") or []
        if not weak:
            lines.append(t(language, "ai_no_weak_replies"))
            return "\n".join(lines)
        for item in weak[:10]:
            reference = sanitize_label(item.get("anonymous_message_reference") or item.get("message_reference"), fallback="", limit=40)
            if language == "ru" and reference == "local-question-candidate":
                reference = t(language, "ai_local_reference")
            lines.extend(
                [
                    f"• {weak_reply_category_label(str(item.get('category')), language=language)}",
                    f"{t(language, 'ai_severity')}: {severity_label(item.get('severity'), language=language)}",
                    sanitize_label(item.get("explanation"), fallback="", limit=500),
                    "",
                ]
            )
            if reference:
                lines.insert(-1, f"{t(language, 'ai_reference')}: {reference}")
        return "\n".join(lines).strip()
    if section == "scores":
        explanation = format_score_explanation_full(result.get("score_explanation"), language=language)
        lines = [t(language, "ai_scores_title"), ""]
        if explanation:
            lines.extend([explanation, ""])
        for key, row in (result.get("dimensions") or {}).items():
            if not isinstance(row, dict):
                continue
            if row.get("score") is None:
                if str(key) in {"sarcasm_intensity", "hostility", "dismissiveness"}:
                    continue
                reason = unavailable_dimension_text(str(key), row, language=language)
                if reason:
                    lines.extend([reason, ""])
                continue
            lines.extend(
                [
                    f"{dimension_label(str(key), language=language)}: {float(row.get('score') or 0):.1f} / 10",
                    f"{t(language, 'ai_confidence_short')}: {confidence_label(row.get('confidence'), language=language)} · {t(language, 'ai_evidence_count')}: {int(row.get('evidence_count') or 0)}",
                    dimension_explanation(str(key), row, language=language),
                    "",
                ]
            )
        limitations = compact_limitations(result.get("limitations"), language=language)
        if limitations:
            lines.extend([t(language, "ai_limitations_title"), limitations])
        return "\n".join(lines).strip()
    if section == "comparison":
        comparison = analysis.get("comparison") or result.get("period_comparison")
        if not isinstance(comparison, dict):
            comparison = {"status": "insufficient_data"}
        return format_period_comparison_full(comparison, language=language)
    context = result.get("context") if isinstance(result.get("context"), dict) else {}
    context_category = context.get("category")
    lines = [
        t(language, "ai_full_analysis_title"),
        "",
        context_label(context_category, language=language),
        context_score_label(context_category, language=language),
        format_score_line(result, language=language),
        t(language, "ai_confidence_line", confidence=t(language, f"confidence_{result.get('score_confidence', 'low')}")),
        "",
    ]
    context_note = low_confidence_context_note(context, language=language) if context else ""
    if context_note:
        lines.extend([context_note, ""])
    individualized = result.get("individualized_story") if isinstance(result.get("individualized_story"), dict) else {}
    story_overview = format_individualized_story_overview(individualized, language=language)
    if story_overview:
        lines.extend([t(language, "story_what_is_happening_title"), story_overview, ""])
    verdict_text = verdict_line(result, language=language)
    if verdict_text and not individualized:
        lines.extend([t(language, "ai_verdict_title"), verdict_text, ""])
    summary = sanitize_label(result.get("summary"), fallback="", limit=900)
    if summary and not individualized and not is_meta_filler(summary):
        lines.extend([t(language, "ai_summary_title"), summary, ""])
    distinctive = format_selected_patterns_compact(result.get("selected_patterns"), language=language, limit=6)
    if distinctive:
        lines.extend([t(language, "individual_distinctive_title"), distinctive, ""])
    story = result.get("communication_story") if isinstance(result.get("communication_story"), dict) else {}
    story_text = format_communication_story(story, language=language)
    if story_text and not individualized:
        lines.extend([t(language, "communication_story_title"), story_text, ""])
    history_text = format_history_segments_full(result.get("history_segments"), language=language)
    if history_text:
        lines.extend([t(language, "history_section_title"), history_text, ""])
    profile_text = format_personal_profile_detail(
        result.get("personal_profile") if isinstance(result.get("personal_profile"), dict) else {},
        story=individualized,
        language=language,
    )
    profile_contains_user_role = bool(profile_text and individualized.get("user_role"))
    if profile_text and context_category not in {"group_social", "channel_or_broadcast"}:
        lines.extend([t(language, "personal_profile_title"), profile_text, ""])
    coverage_text = format_ai_coverage_line(result.get("coverage") or analysis.get("coverage") or {}, language=language)
    if coverage_text:
        lines.extend([t(language, "ai_data_title"), coverage_text, ""])
    participants = normalized_participants(result)
    if context_category not in {"group_social", "channel_or_broadcast"}:
        balance_text = format_participation_balance(result, participants, language=language)
        if balance_text:
            lines.extend([t(language, "participation_balance_title"), balance_text, ""])
        for participant_key, title_key in [("you", "ai_you_title"), ("other", "ai_other_title")]:
            if participant_key == "you" and profile_contains_user_role:
                continue
            block = participants.get(participant_key) or {}
            other_key = "other" if participant_key == "you" else "you"
            story_key = "user_role" if participant_key == "you" else "other_role"
            story_line = sanitize_label(individualized.get(story_key), fallback="", limit=420)
            block_lines = [
                story_line or sanitize_label(block.get("summary"), fallback="", limit=360),
                "" if story_line else participant_pattern_bullets(block.get("observable_patterns"), participants.get(other_key, {}).get("observable_patterns"), side=participant_key, limit=5),
            ]
            block_text = "\n".join(item for item in block_lines if item)
            if block_text:
                lines.extend([t(language, title_key), block_text, ""])
    score_explanation = format_score_explanation_full(result.get("score_explanation"), language=language)
    if score_explanation:
        lines.extend([score_explanation, ""])
    strengths = pattern_bullets(result.get("positive_patterns"), limit=6)
    if strengths:
        lines.extend([t(language, "ai_strengths_title"), strengths, ""])
    weaknesses = pattern_bullets(result.get("problem_patterns"), limit=6)
    if weaknesses:
        lines.extend([t(language, "ai_weakens_title"), weaknesses, ""])
    direct = direct_findings_bullets(result.get("direct_findings"), limit=8, language=language)
    if direct:
        lines.extend([t(language, "ai_direct_findings_title"), direct, ""])
    weak_section = format_ai_result_section(analysis, "weak", language=language)
    if weak_section and t(language, "ai_no_weak_replies") not in weak_section:
        lines.extend([weak_section, ""])
    advice_section = format_ai_result_section(analysis, "advice", language=language)
    if advice_section:
        lines.extend([advice_section, ""])
    limitations = compact_limitations(result.get("limitations"), language=language)
    if limitations:
        lines.extend([t(language, "ai_limitations_title"), limitations])
    return dedupe_report_text(lines, language=language)


def format_automation_suggestion(
    chat: dict[str, Any],
    *,
    message_count: int,
    language: str = "en",
    ai_consent_missing: bool = False,
) -> str:
    title = sanitize_label(chat.get("title") or chat.get("display_title"), fallback=t(language, "chat_type_unknown"), limit=80)
    lines = [
        t(language, "conversation_paused_title"),
        "",
        title,
        t(language, "conversation_paused_question"),
        f"{t(language, 'analysis_result_messages')}: {int(message_count)}",
    ]
    if ai_consent_missing:
        lines.extend(["", t(language, "automation_ai_consent_required")])
    return "\n".join(lines)


def format_automatic_analysis_result(
    chat: dict[str, Any],
    *,
    analysis: dict[str, Any] | None,
    ai_failed: bool = False,
    language: str = "en",
) -> str:
    if not analysis:
        return "\n\n".join([t(language, "automation_completed"), t(language, "comparison_not_enough")])
    result = analysis.get("result") or analysis
    score = result.get("overall_score")
    context = result.get("context") if isinstance(result.get("context"), dict) else {}
    verdict = result.get("verdict") if isinstance(result.get("verdict"), dict) else {}
    advice = result.get("recommended_action") or {}
    lines = [
        t(language, "automation_completed"),
        "",
        context_score_label(context.get("category"), language=language),
        f"{float(score):.1f} / 10" if isinstance(score, (int, float)) else t(language, "ai_score_unreliable"),
    ]
    summary = sanitize_label(result.get("summary"), fallback="", limit=520)
    if summary:
        lines.extend(["", t(language, "ai_summary_title"), summary])
    headline = sanitize_label(verdict.get("headline"), fallback="", limit=180)
    if headline:
        lines.extend(["", t(language, "ai_verdict_title"), headline])
    comparison = analysis.get("comparison") or result.get("period_comparison")
    if isinstance(comparison, dict):
        lines.extend(["", format_period_comparison_compact(comparison, language=language)])
    recommendation = sanitize_label(advice.get("explanation"), fallback="", limit=420)
    if recommendation:
        lines.extend(["", t(language, "ai_main_advice"), recommendation])
    if ai_failed:
        lines.extend(["", t(language, "analysis_result_ai_partial")])
    return "\n".join(lines).strip()


def format_individualized_story_overview(story: dict[str, Any], *, language: str) -> str:
    if not story:
        return ""
    headline = sanitize_label(story.get("headline"), fallback="", limit=180)
    overall = sanitize_label(story.get("overall_picture"), fallback="", limit=620)
    dynamic = sanitize_label(story.get("distinctive_dynamic"), fallback="", limit=420)
    rows = []
    if headline and not is_meta_filler(headline):
        rows.append(headline)
    if overall and not is_meta_filler(overall) and semantic_text_key(overall) != semantic_text_key(headline):
        rows.append(overall)
    if dynamic and not is_meta_filler(dynamic) and semantic_text_key(dynamic) not in {semantic_text_key(headline), semantic_text_key(overall)}:
        rows.append(dynamic)
    return "\n".join(rows).strip()


def format_selected_patterns_compact(value: Any, *, language: str, limit: int = 3) -> str:
    del language
    rows = value if isinstance(value, list) else []
    bullets: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("generic") and len(rows) > 1:
            continue
        text = sanitize_label(row.get("observation"), fallback="", limit=260)
        consequence = sanitize_label(row.get("consequence"), fallback="", limit=220)
        if not text or is_meta_filler(text):
            continue
        if consequence and semantic_text_key(consequence) not in {semantic_text_key(text), "none"}:
            text = f"{text} {consequence}"
        key = semantic_text_key(text)
        if key in seen:
            continue
        seen.add(key)
        bullets.append(f"• {text}")
        if len(bullets) >= limit:
            break
    return "\n".join(bullets)


def format_personal_profile_compact(profile: dict[str, Any], *, story: dict[str, Any] | None = None, language: str) -> str:
    if not profile:
        return ""
    story = story if isinstance(story, dict) else {}
    story_role = sanitize_label(story.get("user_role"), fallback="", limit=360)
    summary = sanitize_label(story_role or profile.get("summary"), fallback="", limit=360)
    if is_meta_filler(summary):
        summary = ""
    dimensions = profile.get("dimensions") if isinstance(profile.get("dimensions"), list) else []
    bullets = []
    for row in dimensions[:3]:
        if not isinstance(row, dict):
            continue
        observation = sanitize_label(row.get("observation"), fallback="", limit=240)
        if observation and not is_meta_filler(observation) and semantic_text_key(observation) != semantic_text_key(summary):
            bullets.append(f"• {observation}")
    return "\n".join([item for item in [summary, "\n".join(bullets)] if item]).strip()


def format_personal_profile_detail(profile: dict[str, Any], *, story: dict[str, Any] | None = None, language: str) -> str:
    if not profile:
        return ""
    lines: list[str] = []
    story = story if isinstance(story, dict) else {}
    summary = sanitize_label(story.get("user_role") or profile.get("summary"), fallback="", limit=420)
    if summary and not is_meta_filler(summary):
        lines.append(summary)
    for row in (profile.get("dimensions") or [])[:10]:
        if not isinstance(row, dict):
            continue
        label = t(language, f"profile_dimension_{row.get('dimension') or 'unknown'}")
        observation = sanitize_label(row.get("observation"), fallback="", limit=300)
        if observation and not is_meta_filler(observation) and semantic_text_key(observation) != semantic_text_key(summary):
            lines.append(f"• {label}: {observation}")
    limitations = compact_limitations(profile.get("limitations"), language=language)
    if limitations:
        lines.extend(["", limitations])
    return "\n".join(lines).strip()


def format_communication_story(story: dict[str, Any], *, language: str) -> str:
    if not story:
        return ""
    rows = [
        ("story_what_is_happening_title", story.get("what_is_happening")),
        ("story_main_driver_title", story.get("main_driver")),
        ("story_you_title", story.get("how_you_communicate")),
        ("story_other_title", story.get("how_other_responds")),
    ]
    lines: list[str] = []
    for title_key, value in rows:
        text = sanitize_label(value, fallback="", limit=420)
        if text:
            lines.extend([t(language, title_key), text, ""])
    semantic = string_bullets(story.get("semantic_dynamics"), limit=4)
    if semantic:
        lines.extend([t(language, "story_semantic_dynamics_title"), semantic, ""])
    uncertainties = string_bullets(story.get("uncertainties"), limit=3)
    if uncertainties:
        lines.extend([t(language, "story_uncertainties_title"), uncertainties])
    return "\n".join(lines).strip()


def format_why_conclusion_section(result: dict[str, Any], *, language: str) -> str:
    panels = build_why_conclusion_panels(result, language=language, limit=5)
    if not panels:
        return "\n\n".join([t(language, "why_conclusion_title"), t(language, "why_no_evidence_findings")])
    lines = [t(language, "why_conclusion_title"), ""]
    for panel in panels:
        lines.append(sanitize_label(panel.get("title"), fallback=t(language, "why_conclusion_title"), limit=180))
        observed = sanitize_label(panel.get("observed"), fallback="", limit=500)
        interpretation = sanitize_label(panel.get("interpretation"), fallback="", limit=500)
        evidence = panel.get("supporting_evidence") or []
        alternatives = panel.get("alternative_interpretations") or []
        limitations = panel.get("limitations") or []
        if observed:
            lines.extend([t(language, "why_observed_title"), observed])
        if interpretation:
            lines.extend([t(language, "why_interpretation_title"), interpretation])
        if evidence:
            lines.extend([t(language, "why_supporting_evidence_title"), string_bullets(evidence, limit=6)])
        if alternatives:
            lines.extend([t(language, "why_alternative_title"), string_bullets(alternatives, limit=3)])
        scope = sanitize_label(panel.get("evidence_scope"), fallback="selected_period", limit=60)
        if scope:
            scope_label = t(language, f"evidence_scope_{scope}") if scope in {"full_history", "recent_window", "recurring_across_periods", "selected_period"} else scope
            lines.append(f"{t(language, 'why_scope_title')}: {scope_label}")
        lines.append(f"{t(language, 'why_confidence_title')}: {confidence_label(panel.get('confidence'), language=language)}")
        if limitations:
            lines.extend([t(language, "why_limitations_title"), string_bullets(limitations, limit=3)])
        lines.append("")
    return "\n".join(lines).strip()


def format_unified_analysis_result(
    report: dict[str, Any],
    *,
    ai_analysis: dict[str, Any] | None = None,
    ai_failed: bool = False,
    chat_type: str | None = None,
    language: str = "en",
) -> str:
    if ai_analysis and ai_analysis.get("status") == "completed":
        lines = [
            t(language, "analysis_result_title"),
            "",
            format_ai_result_overview(ai_analysis, chat_title=report.get("chat_title"), language=language),
            "",
            result_data_quality_line(report, language=language),
        ]
        return "\n".join(line for line in lines if line is not None).strip()

    metrics = report.get("metrics_summary") or {}
    quality = report.get("data_quality") or {}
    count = int(report.get("imported_message_count") or metrics.get("message_count") or 0)
    stands_out = compact_result_stands_out(metrics, chat_type=chat_type, language=language)
    attention = compact_attention_lines(report, confirmed_reminders=0, language=language)
    lines = [
        sanitize_label(report.get("chat_title"), fallback=t(language, "chat_type_unknown"), limit=80),
        "",
        t(language, "analysis_result_title"),
        t(language, "analysis_result_local_mode"),
        "",
        current_snapshot_sentence(metrics, chat_type=chat_type, language=language) if count else t(language, "overview_no_messages"),
        "",
        f"{t(language, 'analysis_result_period')}: {sanitize_label(report.get('period_label'), fallback=t(language, 'not_available'), limit=60)}",
        f"{t(language, 'analysis_result_messages')}: {count}",
        "",
        t(language, "analysis_result_stands_out"),
        *(stands_out or [t(language, "empty")]),
        "",
        t(language, "analysis_result_attention"),
        *(attention or [t(language, "overview_no_attention")]),
        "",
        t(language, "analysis_result_quality"),
        f"{t(language, 'report_confidence')}: {sanitize_label(quality.get('confidence'), fallback=t(language, 'not_available'), limit=40)}",
        f"{t(language, 'report_completeness')}: {sanitize_label(quality.get('completeness'), fallback=t(language, 'not_available'), limit=80)}",
    ]
    if ai_failed:
        lines.extend(["", t(language, "analysis_result_ai_partial")])
    return "\n".join(lines)


def compact_result_stands_out(metrics: dict[str, Any], *, chat_type: str | None, language: str) -> list[str]:
    result: list[str] = []
    for line in compact_balance_lines(metrics, chat_type=chat_type, language=language):
        if line != t(language, "overview_planning_balance_unavailable"):
            result.append(f"• {line}")
        if len(result) >= 2:
            break
    for line in compact_response_lines(metrics, language=language):
        result.append(f"• {line}")
        if len(result) >= 4:
            break
    return result


def result_data_quality_line(report: dict[str, Any], *, language: str) -> str:
    quality = report.get("data_quality") or {}
    count = int(report.get("imported_message_count") or 0)
    return (
        f"{t(language, 'analysis_result_period')}: {sanitize_label(report.get('period_label'), fallback=t(language, 'not_available'), limit=60)}\n"
        f"{t(language, 'analysis_result_messages')}: {count}\n"
        f"{t(language, 'report_confidence')}: {sanitize_label(quality.get('confidence'), fallback=t(language, 'not_available'), limit=40)}"
    )


def string_bullets(values: Any, *, limit: int) -> str:
    rows = values if isinstance(values, list) else []
    bullets: list[str] = []
    for item in rows[:limit]:
        if isinstance(item, dict):
            text = sanitize_label(item.get("text") or item.get("title") or item.get("summary"), fallback="", limit=220)
        else:
            text = sanitize_label(str(item), fallback="", limit=220)
        if text:
            bullets.append(f"• {text}")
    return "\n".join(bullets)


def work_user_summary_from_profile(value: Any, *, language: str) -> str:
    profile = value if isinstance(value, dict) else {}
    rows = profile.get("dimensions") if isinstance(profile.get("dimensions"), list) else []
    bullets: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dimension = str(row.get("dimension") or "")
        if dimension not in {"directness", "planning_clarity", "question_engagement", "responsiveness"}:
            continue
        observation = sanitize_label(row.get("observation"), fallback="", limit=220)
        if observation:
            bullets.append(f"• {observation}")
        if len(bullets) >= 3:
            break
    return "\n".join(bullets)


def dedupe_report_text(lines: list[str], *, language: str) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line is None:
            continue
        text = normalize_composed_text(str(line))
        if not text:
            result.append(text)
            continue
        key = semantic_text_key(text)
        if key in {"no_meaningful_change", "similar_recent_rhythm"} and key in seen:
            continue
        if key in seen and len(text) > 40 and not text.startswith("•"):
            continue
        seen.add(key)
        result.append(text)
    rendered = "\n".join(line for line in result if line is not None).strip()
    if language == "ru":
        rendered = rendered.replace("кандидата на вопрос", "вопроса").replace("кандидатов на вопросы", "вопросов")
    return normalize_composed_text(rendered)


def normalize_composed_text(text: str) -> str:
    result = text
    repeated_prefixes = (
        "In this chat,",
        "In this work chat,",
        "In work topics,",
        "В этой переписке",
        "В этом рабочем чате",
        "В рабочих вопросах",
    )
    for prefix in repeated_prefixes:
        escaped = re.escape(prefix)
        result = re.sub(rf"({escaped}\s*){{2,}}", f"{prefix} ", result, flags=re.IGNORECASE)
    result = re.sub(r"\b(pattern)\s+\1\b", r"\1", result, flags=re.IGNORECASE)
    result = re.sub(r"\b(паттерн)\s+\1\b", r"\1", result, flags=re.IGNORECASE)
    result = dedupe_adjacent_sentences(result)
    return re.sub(r"[ \t]{2,}", " ", result).strip()


def dedupe_adjacent_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])[ \t]+", text)
    if len(parts) <= 1:
        return text
    result: list[str] = []
    previous_key = ""
    for part in parts:
        key = semantic_text_key(part)
        if key and key == previous_key:
            continue
        result.append(part)
        previous_key = key
    return " ".join(result)


GENERIC_STRENGTH_KEYS = {
    "both_participated",
    "visible_activity",
    "messages_found",
    "similar_visible_volume",
}


def pattern_bullets(values: Any, *, limit: int) -> str:
    rows = values if isinstance(values, list) else []
    bullets: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            title = sanitize_label(item.get("title"), fallback="", limit=140)
            explanation = sanitize_label(item.get("explanation"), fallback="", limit=220)
            text = title if not explanation else f"{title}: {explanation}"
        else:
            text = sanitize_label(str(item), fallback="", limit=220)
        if text and semantic_text_key(text) not in GENERIC_STRENGTH_KEYS:
            bullets.append(f"• {text}")
        if len(bullets) >= limit:
            break
    return "\n".join(bullets)


def participant_pattern_bullets(values: Any, comparison_values: Any, *, side: str, limit: int) -> str:
    rows = [str(item) for item in (values if isinstance(values, list) else []) if str(item).strip()]
    comparison_keys = {semantic_text_key(str(item)) for item in (comparison_values if isinstance(comparison_values, list) else [])}
    bullets: list[str] = []
    seen: set[str] = set()
    for row in rows:
        key = semantic_text_key(row)
        if key in {"similar_visible_volume", "both_participated", "visible_activity"}:
            continue
        if key in comparison_keys and key != "none":
            continue
        if key in seen:
            continue
        seen.add(key)
        bullets.append(f"• {sanitize_label(row, fallback='', limit=220)}")
        if len(bullets) >= limit:
            break
    return "\n".join(bullets)


def format_participation_balance(result: dict[str, Any], participants: dict[str, Any], *, language: str) -> str:
    participation = result.get("participation_interpretation") if isinstance(result.get("participation_interpretation"), dict) else {}
    if participation.get("summary"):
        return sanitize_label(participation.get("summary"), fallback="", limit=420)
    balance = result.get("participation_balance") if isinstance(result.get("participation_balance"), dict) else {}
    summary = sanitize_label(balance.get("summary"), fallback="", limit=300)
    if summary:
        return summary
    you_patterns = participants.get("you", {}).get("observable_patterns") if isinstance(participants.get("you"), dict) else []
    other_patterns = participants.get("other", {}).get("observable_patterns") if isinstance(participants.get("other"), dict) else []
    you_keys = {semantic_text_key(str(item)) for item in (you_patterns if isinstance(you_patterns, list) else [])}
    other_keys = {semantic_text_key(str(item)) for item in (other_patterns if isinstance(other_patterns, list) else [])}
    if "similar_visible_volume" in you_keys & other_keys:
        return t(language, "participation_balance_similar_volume_length")
    return ""


def semantic_text_key(text: str) -> str:
    lowered = " ".join(text.casefold().split())
    if any(fragment in lowered for fragment in ("no meaningful change", "существенных изменений нет", "нет значимых изменений", "похож на предыдущ")):
        return "no_meaningful_change"
    if any(fragment in lowered for fragment in ("recent rhythm looks similar", "недавний ритм похож")):
        return "similar_recent_rhythm"
    if any(fragment in lowered for fragment in ("both sides participated", "обе стороны участв")):
        return "both_participated"
    if any(fragment in lowered for fragment in ("messages were found", "activity exists", "visible activity", "видимая активность")):
        return "visible_activity"
    if any(fragment in lowered for fragment in ("similar visible message volume", "comparable visible message volume", "roughly balanced", "activity is balanced", "похожим видимым объемом", "сопоставимым видимым объемом", "примерно равномер", "примерно одинаков", "примерно сбаланс")):
        return "similar_visible_volume"
    if any(fragment in lowered for fragment in ("carries most visible", "несет большую часть")):
        return "carries_volume"
    if any(fragment in lowered for fragment in ("fewer visible", "меньшим количеством")):
        return "fewer_messages"
    if any(fragment in lowered for fragment in ("longer messages", "сообщения обычно подробнее", "длиннее")):
        return "longer_messages"
    return lowered[:80] if lowered else "none"


META_FILLER_FRAGMENTS = (
    "your visible communication style can be described",
    "visible data show",
    "visible metrics show",
    "this section describes",
    "there are several factors",
    "communication contains certain patterns",
    "the conversation contains a point of friction",
    "видимый стиль общения можно описать",
    "видимые данные показывают",
    "видимые метрики показывают",
    "этот раздел описывает",
    "есть несколько факторов",
    "переписка содержит определенные паттерны",
    "в переписке есть заметная точка трения",
)


def is_meta_filler(text: str) -> bool:
    lowered = " ".join(str(text or "").casefold().split())
    return any(fragment in lowered for fragment in META_FILLER_FRAGMENTS)


def format_score_explanation_compact(value: Any, *, language: str) -> str:
    row = value if isinstance(value, dict) else {}
    title = sanitize_label(row.get("title"), fallback="", limit=80)
    negative = string_bullets(row.get("negative_contributors"), limit=3)
    balance = sanitize_label(row.get("balance_note"), fallback="", limit=260)
    cap = sanitize_label(row.get("semantic_mode_cap") or row.get("confidence_cap"), fallback="", limit=260)
    body = "\n".join(item for item in [negative, balance, cap] if item)
    if not title or not body:
        return ""
    return "\n".join([title, body]).strip()


def format_score_explanation_full(value: Any, *, language: str) -> str:
    row = value if isinstance(value, dict) else {}
    title = sanitize_label(row.get("title"), fallback="", limit=100)
    if not title:
        return ""
    lines = [title]
    for section_key, values in [
        ("score_positive_title", row.get("positive_contributors")),
        ("score_negative_title", row.get("negative_contributors")),
        ("score_unavailable_title", row.get("unavailable_dimensions")),
    ]:
        bullets = string_bullets(values, limit=4)
        if bullets:
            lines.extend(["", t(language, section_key), bullets])
    for key in ("balance_note", "confidence_cap", "semantic_mode_cap", "historical_adjustment"):
        text = sanitize_label(row.get(key), fallback="", limit=320)
        if text:
            lines.extend(["", text])
    return "\n".join(lines).strip()


def format_history_segments_compact(value: Any, *, language: str) -> str:
    row = value if isinstance(value, dict) else {}
    if not row.get("segmented"):
        return ""
    lines = [
        sanitize_label(row.get("scope_note"), fallback="", limit=300),
        sanitize_label(row.get("current_picture"), fallback="", limit=300),
        sanitize_label(row.get("recent_change"), fallback="", limit=300),
    ]
    return "\n".join(item for item in lines if item).strip()


def format_history_segments_full(value: Any, *, language: str) -> str:
    row = value if isinstance(value, dict) else {}
    if not row.get("segmented"):
        return ""
    lines = []
    scope_note = sanitize_label(row.get("scope_note"), fallback="", limit=360)
    if scope_note:
        lines.extend([scope_note, ""])
    for title_key, value_key in [
        ("history_current_picture_title", "current_picture"),
        ("history_long_term_pattern_title", "long_term_pattern"),
        ("history_recent_change_title", "recent_change"),
    ]:
        text = sanitize_label(row.get(value_key), fallback="", limit=420)
        if text:
            lines.extend([t(language, title_key), text, ""])
    window_count = int(row.get("window_count") or 0)
    if window_count:
        lines.append(t(language, "history_window_count", count=window_count))
    return "\n".join(lines).strip()


def direct_findings_bullets(values: Any, *, limit: int, language: str = "en") -> str:
    rows = values if isinstance(values, list) else []
    bullets: list[str] = []
    for item in rows[:limit]:
        if not isinstance(item, dict):
            continue
        finding = sanitize_label(item.get("finding"), fallback="", limit=260)
        if not finding:
            continue
        severity_key = sanitize_label(item.get("severity"), fallback="low", limit=20)
        confidence_key = sanitize_label(item.get("confidence"), fallback="low", limit=20)
        severity = t(language, f"severity_{severity_key}") if severity_key in {"low", "medium", "high"} else severity_key
        confidence = t(language, f"confidence_{confidence_key}") if confidence_key in {"low", "medium", "high"} else confidence_key
        bullets.append(f"• {finding} ({severity}, {confidence})")
    return "\n".join(bullets)


def verdict_line(result: dict[str, Any], *, language: str) -> str:
    verdict = result.get("verdict") if isinstance(result.get("verdict"), dict) else {}
    headline = sanitize_label(verdict.get("headline"), fallback=t(language, "not_available"), limit=180)
    explanation = sanitize_label(verdict.get("explanation"), fallback="", limit=520)
    level = verdict.get("level")
    prefix = t(language, f"verdict_{level}") if level else ""
    if prefix and prefix != f"verdict_{level}":
        headline = f"{prefix}: {headline}"
    return f"{headline}\n{explanation}".strip()


def normalized_participants(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("participant_analysis"), dict):
        return result["participant_analysis"]
    legacy = result.get("participants") if isinstance(result.get("participants"), dict) else {}
    return {
        "you": legacy_participant_block(legacy.get("you")),
        "other": legacy_participant_block(legacy.get("other")),
    }


def legacy_participant_block(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "summary": "",
        "observable_patterns": row.get("observable_patterns") or row.get("communication_style") or [],
        "strengths": row.get("strengths") or [],
        "possible_improvements": row.get("possible_improvements") or row.get("problems") or [],
    }


def format_score_line(result: dict[str, Any], *, language: str) -> str:
    score = result.get("overall_score")
    if isinstance(score, (int, float)):
        return f"{float(score):.1f} / 10"
    return t(language, "ai_score_unreliable")


def score_state_explanation(score_state: dict[str, Any], *, language: str) -> str:
    reason = str(score_state.get("cap_reason") or "")
    if score_state.get("insufficient_data"):
        return t(language, "ai_score_insufficient_explanation")
    key = {
        "shallow_local_metrics": "ai_score_cap_shallow",
        "deterministic_without_text_interpretation": "ai_score_cap_deterministic",
        "sampled_ai_text_coverage": "ai_score_cap_sampled_ai",
        "low_context_confidence": "ai_score_cap_context",
        "limited_independent_dimensions": "ai_score_cap_limited_dimensions",
    }.get(reason)
    if key:
        return t(language, key)
    return sanitize_label(score_state.get("explanation"), fallback="", limit=260)


def compact_limitations(value: Any, *, language: str) -> str:
    rows = value if isinstance(value, list) else []
    cleaned: list[str] = []
    for item in rows[:5]:
        text = sanitize_label(str(item), fallback="", limit=260)
        if not text:
            continue
        if language == "ru" and looks_like_english_fallback(text):
            continue
        cleaned.append(text)
    return "\n".join(f"• {item}" for item in cleaned)


def looks_like_english_fallback(text: str) -> bool:
    lowered = text.casefold()
    fragments = [
        "used local deterministic metrics",
        "no ai text interpretation",
        "the reason cannot be determined",
        "not enough messages",
        "too few supported",
    ]
    return any(fragment in lowered for fragment in fragments)


def dimension_explanation(key: str, row: dict[str, Any], *, language: str) -> str:
    if language == "ru":
        mapped = t(language, f"ai_dimension_{key}_explanation")
        if mapped != f"ai_dimension_{key}_explanation":
            return mapped
    return sanitize_label(row.get("explanation"), fallback="", limit=400)


def unavailable_dimension_text(key: str, row: dict[str, Any], *, language: str) -> str:
    if key == "sarcasm_intensity":
        return t(language, "ai_sarcasm_unavailable")
    if key == "hostility":
        return t(language, "ai_hostility_unavailable")
    if key == "dismissiveness":
        return t(language, "ai_dismissiveness_unavailable")
    reason = sanitize_label(row.get("unavailable_reason") or row.get("explanation"), fallback="", limit=320)
    if not reason:
        return ""
    if language == "ru" and looks_like_english_fallback(reason):
        reason = t(language, "ai_dimension_unavailable")
    return f"{dimension_label(key, language=language)}: {reason}"


def severity_label(value: Any, *, language: str) -> str:
    key = sanitize_label(value, fallback="low", limit=20)
    return t(language, f"severity_{key}") if key in {"low", "medium", "high"} else key


def confidence_label(value: Any, *, language: str) -> str:
    key = sanitize_label(value, fallback="low", limit=20)
    return t(language, f"confidence_{key}") if key in {"low", "medium", "high"} else key


def format_ai_coverage_line(coverage: dict[str, Any], *, language: str) -> str:
    if not isinstance(coverage, dict) or not coverage:
        return ""
    available = coverage.get("available_messages")
    period = sanitize_label(str(coverage.get("requested_period") or ""), fallback="", limit=80)
    if isinstance(available, int):
        base = t(language, "ai_coverage_messages", count=available)
    else:
        base = t(language, "ai_selected_period_analyzed")
    if period:
        base = f"{base} {period}."
    if coverage.get("partial"):
        sent = coverage.get("sent_messages")
        if isinstance(sent, int):
            base = f"{base} {t(language, 'ai_sample_used_count', count=sent)}"
        else:
            base = f"{base} {t(language, 'ai_sample_used')}"
    return base.strip()


def dimension_label(key: str, *, language: str) -> str:
    return t(language, f"ai_dimension_{key}")


def weak_reply_category_label(key: str, *, language: str) -> str:
    return t(language, f"ai_weak_{key}")


def format_chat_home_loading(*, language: str = "en") -> str:
    return render_loading_state(language=language)


def chat_home_rhythm_title(chat_type: str | None, *, language: str) -> str:
    if chat_type == "group":
        return t(language, "chat_home_v4_group_rhythm")
    if chat_type == "channel":
        return t(language, "chat_home_v4_posting_cadence")
    return t(language, "chat_home_v4_communication_rhythm")


def chat_home_activity_title(chat_type: str | None, *, language: str) -> str:
    if chat_type == "channel":
        return t(language, "chat_home_v4_current_posting")
    if chat_type == "group":
        return t(language, "chat_home_v4_current_group_activity")
    return t(language, "chat_home_v4_current_activity")


def chat_home_attention_line(attention: dict[str, Any], *, language: str) -> str:
    count = int(attention.get("open_follow_up_count") or 0)
    if count <= 0:
        return t(language, "chat_home_v4_no_followups_value")
    return t(language, "chat_home_v4_followups_count", count=count)


def next_reminder_line(attention: dict[str, Any], *, language: str) -> str:
    reminder = attention.get("next_reminder")
    if not isinstance(reminder, dict):
        return t(language, "chat_home_v4_no_reminder_value")
    return sanitize_label(reminder.get("label"), fallback=t(language, "not_available"), limit=40)


def communication_subtitle(communication: dict[str, Any], *, chat_type: str | None, language: str) -> str | None:
    if chat_type == "channel":
        return None
    summary = communication.get("reply_summary")
    if not summary:
        return None
    return sanitize_label(summary, fallback=t(language, "empty"), limit=120)


def trend_line(activity: dict[str, Any], *, language: str) -> str:
    change = str(activity.get("recent_change") or "unknown")
    icon = {"up": "↑", "down": "↓", "stable": "→", "unknown": "·"}.get(change, "·")
    return f"{icon} {sanitize_label(activity.get('recent_change_label'), fallback=t(language, 'not_available'), limit=90)}"


def chat_observable_summary(chat_type: str | None, metrics: dict, *, language: str) -> str:
    count = int(metrics.get("message_count") or 0)
    if chat_type == "group":
        return f"{t(language, 'chat_summary_group')} {t(language, 'chat_summary_messages')}: {count}."
    if chat_type == "channel":
        return f"{t(language, 'chat_summary_channel')} {t(language, 'chat_summary_messages')}: {count}."
    return f"{t(language, 'chat_summary_private')} {t(language, 'chat_summary_messages')}: {count}."


def attention_summary(metrics: dict, pending_followups: int, *, language: str) -> str:
    unanswered = len(metrics.get("unanswered_questions") or [])
    parts = []
    if unanswered:
        parts.append(f"{t(language, 'chat_attention_questions')}: {unanswered}.")
    if pending_followups:
        parts.append(f"{pending_followups} {t(language, 'button_followups').casefold()}")
    return " ".join(parts) if parts else t(language, "chat_attention_clear")


def format_chat_home_section(
    section: str,
    *,
    chat: dict,
    report: dict | None,
    pending_followups: int = 0,
    important_settings: dict | None = None,
    language: str = "en",
) -> str:
    if section == "settings":
        rendered_chat = {**chat, "important_settings": important_settings} if important_settings else chat
        return format_chat_settings(rendered_chat, language=language)
    if report is None:
        return "\n\n".join(
            [
                section_title(section, language=language),
                t(language, "empty_no_report"),
            ]
        )
    chat_type = chat.get("chat_type")
    modules = set(report.get("modules") or [])
    if section == "overview":
        return format_report_overview(report)
    if section == "timeline":
        return "\n\n".join([section_title(section, language=language), t(language, "timeline_empty")])
    if section == "habits":
        return unavailable_section(section, t(language, "module_coming_soon"), t(language, "section_coming_soon_body"), language=language)
    if section == "response" and chat_type == "channel":
        return unavailable_section(section, t(language, "module_not_included"), t(language, "section_channel_hidden_body"), language=language)
    if section == "activity":
        if "activity" not in modules:
            return unavailable_section(section, t(language, "module_not_included"), t(language, "section_unavailable_body"), language=language)
        return format_report_section(report, "activity")
    if section == "response":
        if "response_times" not in modules:
            return unavailable_section(section, t(language, "module_not_included"), t(language, "section_unavailable_body"), language=language)
        return format_report_section(report, "response")
    if section == "followups":
        lines = [
            section_title(section, language=language),
            "",
            f"{t(language, 'chat_home_pending_followups')}: {pending_followups}",
        ]
        if "followups" not in modules and "reminders" not in modules:
            lines.extend(["", t(language, "module_not_included"), t(language, "section_unavailable_body")])
        elif not pending_followups:
            lines.extend(["", t(language, "empty_no_followups")])
        return "\n".join(lines)
    return format_report_overview(report)


def format_chat_settings(chat: dict, *, language: str = "en") -> str:
    favorite = t(language, "yes") if chat.get("is_favorite") else t(language, "no")
    important = t(language, "yes") if chat.get("is_important") else t(language, "no")
    lines = [
        t(language, "chat_settings_title"),
        "",
        f"{sanitize_label(chat.get('title'), fallback=t(language, 'chat_type_unknown'), limit=80)}",
        f"{t(language, 'chat_settings_favorite')}: {favorite}",
        f"{t(language, 'important_chat_label')}: {important}",
    ]
    automation = chat.get("important_settings") if isinstance(chat.get("important_settings"), dict) else None
    if automation:
        lines.extend(
            [
                "",
                t(language, "automation_analysis"),
                f"{t(language, 'automation_analysis')}: {t(language, 'yes') if automation.get('automatic_analysis_enabled') else t(language, 'no')}",
                f"{t(language, 'automation_notifications')}: {t(language, 'yes') if automation.get('automatic_notification_enabled') else t(language, 'no')}",
                f"{t(language, 'inactivity_threshold')}: {int(automation.get('inactivity_threshold_minutes') or 45)} min",
                f"{t(language, 'minimum_new_messages')}: {int(automation.get('minimum_new_messages') or 10)}",
                f"{t(language, 'automation_cooldown')}: {int(automation.get('cooldown_hours') or 12)}h",
                f"{t(language, 'quiet_hours')}: {t(language, 'yes') if automation.get('quiet_hours_enabled') else t(language, 'no')} {sanitize_label(automation.get('quiet_hours_start'), fallback='23:00', limit=5)}-{sanitize_label(automation.get('quiet_hours_end'), fallback='08:00', limit=5)}",
                f"{t(language, 'automation_analysis_mode')}: {t(language, 'automation_mode_ai') if automation.get('preferred_analysis_mode') == 'ai' else t(language, 'automation_mode_local')}",
            ]
        )
    lines.extend(["", t(language, "chat_settings_body"), t(language, "chat_settings_manage_hint")])
    return "\n".join(lines)


def format_timeline_summary(timeline: RelationshipTimeline, *, chat: dict, language: str = "en") -> str:
    page = paginate_timeline_story(timeline.story_items, filter_id="all", page=0)
    return format_timeline_story_page(page, chat=chat, language=language)


def format_timeline_page(page: TimelinePage | TimelineStoryPage, *, chat: dict, language: str = "en") -> str:
    if isinstance(page, TimelineStoryPage) or (page.entries and isinstance(page.entries[0], TimelineStoryItem)):
        return format_timeline_story_page(page, chat=chat, language=language)
    chat_type = chat.get("chat_type")
    lines = [
        t(language, "section_timeline_title"),
        f"{t(language, 'timeline_filter')}: {timeline_filter_label(page.filter_id, language=language)}",
        timeline_page_range(page, language=language),
        "",
    ]
    if not page.entries:
        lines.extend([t(language, "timeline_empty_filter"), "", t(language, "timeline_privacy_note")])
        return "\n".join(lines)
    for entry in page.entries:
        lines.extend(format_timeline_entry(entry, chat_type=chat_type, language=language))
    lines.extend(["", t(language, "timeline_privacy_note")])
    return "\n".join(lines)


def format_timeline_story_page(page: TimelineStoryPage, *, chat: dict, language: str = "en", now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    title = t(language, "section_timeline_title")
    filter_label = timeline_filter_label(page.filter_id, language=language)
    if not page.entries:
        return "\n\n".join(
            [
                title,
                timeline_empty_story_text(page.filter_id, language=language),
                t(language, "timeline_privacy_note"),
            ]
        )
    lines = [title]
    if page.filter_id != "all":
        lines.append(filter_label)
    lines.append("")
    last_month = None
    for entry in page.entries:
        month = month_title(parse_timeline_date(entry.timestamp), language=language)
        if month != last_month:
            if last_month is not None:
                lines.append("")
            lines.append(month)
            lines.append("")
            last_month = month
        lines.extend(format_timeline_story_item(entry, chat=chat, language=language, now=current))
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", t(language, "timeline_privacy_note")])
    if page.total > page.page_size:
        lines.append(f"{t(language, 'timeline_showing')}: {page.page * page.page_size + 1}-{min(page.total, page.page * page.page_size + len(page.entries))} / {page.total}")
    return "\n".join(lines)


def format_timeline_story_item(entry: TimelineStoryItem, *, chat: dict, language: str, now: datetime) -> list[str]:
    title = timeline_story_title(entry, chat=chat, language=language)
    body = timeline_story_body(entry, chat=chat, language=language)
    lines = [
        timeline_story_date_label(entry.timestamp, now=now, language=language),
        f"● {title}",
    ]
    if body:
        lines.append(body)
    detail = timeline_story_detail(entry, language=language)
    if detail:
        lines.append(detail)
    return lines


def parse_timeline_date(value: str) -> date:
    if not value:
        return date.fromtimestamp(0)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def timeline_story_date_label(value: str, *, now: datetime, language: str) -> str:
    current = parse_timeline_date(value)
    delta = (current - now.date()).days
    if delta == 0:
        return t(language, "relative_today")
    if delta == -1:
        return t(language, "relative_yesterday")
    return f"{current.day} {t(language, f'month_day_{current.month:02d}')}"


def month_title(value: date, *, language: str) -> str:
    return f"{t(language, f'month_title_{value.month:02d}')} {value.year}"


def timeline_days(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0"
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.1f}"


def timeline_story_title(entry: TimelineStoryItem, *, chat: dict, language: str) -> str:
    chat_type = chat.get("chat_type")
    if entry.story_type == "activity_day":
        if chat_type == "group":
            return t(language, "timeline_story_group_active")
        if chat_type == "channel":
            return t(language, "timeline_story_channel_active")
        return t(language, "timeline_story_conversation_active")
    return {
        "conversation_resumed": t(language, "timeline_story_resumed"),
        "quiet_started": t(language, "timeline_story_quiet_period"),
        "activity_increased": t(language, "timeline_story_activity_increased"),
        "activity_decreased": t(language, "timeline_story_activity_decreased"),
        "question_detected": t(language, "timeline_story_question"),
        "unanswered_question": t(language, "timeline_story_unanswered_question"),
        "plan_mentioned": t(language, "timeline_story_plan"),
        "promise_mentioned": t(language, "timeline_story_promise"),
        "followup_suggested": t(language, "timeline_story_followup"),
        "reminder_suggested": t(language, "timeline_story_reminder_suggested"),
        "reminder_confirmed": t(language, "timeline_story_reminder_confirmed"),
        "reminder_completed": t(language, "timeline_story_reminder_completed"),
        "reminder_dismissed": t(language, "timeline_story_reminder_dismissed"),
        "analysis_completed": t(language, "timeline_story_analysis"),
        "semantic_sarcasm_playful": t(language, "timeline_story_semantic_sarcasm_playful"),
        "semantic_sarcasm_dismissive": t(language, "timeline_story_semantic_sarcasm_dismissive"),
        "semantic_sarcasm_changed": t(language, "timeline_story_semantic_sarcasm_changed"),
        "semantic_aggression_visible": t(language, "timeline_story_semantic_aggression_visible"),
        "semantic_pressure_pattern": t(language, "timeline_story_semantic_pressure_pattern"),
        "semantic_influence_pattern": t(language, "timeline_story_semantic_influence_pattern"),
        "semantic_persuasion_visible": t(language, "timeline_story_semantic_persuasion_visible"),
        "semantic_possible_interest": t(language, "timeline_story_semantic_possible_interest"),
    }.get(entry.story_type, t(language, "timeline_story_event"))


def timeline_story_body(entry: TimelineStoryItem, *, chat: dict, language: str) -> str:
    metadata = entry.metadata or {}
    chat_type = chat.get("chat_type")
    if entry.story_type == "activity_day":
        count = int(metadata.get("message_count") or 0)
        active_periods = int(metadata.get("active_periods") or 0)
        if chat_type == "channel":
            return t(
                language,
                "timeline_story_activity_channel_body",
                posts=timeline_count_phrase(count, "post", language=language),
                periods=timeline_count_phrase(active_periods, "period", language=language),
            )
        return t(
            language,
            "timeline_story_activity_body",
            messages=timeline_count_phrase(count, "message", language=language),
            periods=timeline_count_phrase(active_periods, "period", language=language),
        )
    if entry.story_type == "conversation_resumed":
        return t(language, "timeline_story_resumed_body", days=timeline_days(metadata.get("gap_days")))
    if entry.story_type == "quiet_started":
        return t(language, "timeline_story_quiet_body", days=timeline_days(metadata.get("gap_days")))
    if entry.story_type == "activity_increased":
        return t(language, "timeline_story_activity_increased_body")
    if entry.story_type == "activity_decreased":
        return t(language, "timeline_story_activity_decreased_body")
    if entry.story_type == "unanswered_question":
        return t(language, "timeline_story_unanswered_question_body")
    if entry.story_type == "question_detected":
        return t(language, "timeline_story_question_body")
    if entry.story_type == "plan_mentioned":
        return t(language, "timeline_story_plan_body")
    if entry.story_type == "promise_mentioned":
        return t(language, "timeline_story_promise_body")
    if entry.story_type == "followup_suggested":
        return t(language, "timeline_story_followup_body")
    if entry.story_type.startswith("reminder_"):
        return t(language, "timeline_story_reminder_body")
    if entry.story_type == "analysis_completed":
        return t(
            language,
            "timeline_story_analysis_body",
            period=timeline_period_adjective(sanitize_label(str(metadata.get("period_label") or ""), fallback=t(language, "not_available"), limit=40), language=language),
        )
    if entry.story_type.startswith("semantic_"):
        return sanitize_label(metadata.get("summary"), fallback=t(language, "timeline_story_semantic_body"), limit=300)
    return ""


def timeline_story_detail(entry: TimelineStoryItem, *, language: str) -> str:
    metadata = entry.metadata or {}
    if entry.story_type == "activity_day" and metadata.get("day_part"):
        return t(language, f"timeline_day_part_{metadata['day_part']}")
    if entry.story_type in {"activity_increased", "activity_decreased"}:
        current = int(metadata.get("current_count") or 0)
        previous = int(metadata.get("previous_count") or 0)
        return t(language, "timeline_story_change_counts", current=current, previous=previous)
    if entry.story_type.startswith("semantic_") and metadata.get("evidence_count"):
        return t(language, "ai_evidence_count") + f": {int(metadata.get('evidence_count') or 0)}"
    return ""


def timeline_count_phrase(count: int, kind: str, *, language: str) -> str:
    if language == "ru":
        return str(count)
    if kind == "message":
        return t(language, "timeline_count_message_one") if count == 1 else t(language, "timeline_count_message_many", count=count)
    if kind == "post":
        return t(language, "timeline_count_post_one") if count == 1 else t(language, "timeline_count_post_many", count=count)
    if kind == "period":
        return t(language, "timeline_count_period_one") if count == 1 else t(language, "timeline_count_period_many", count=count)
    return str(count)


def timeline_period_adjective(value: str, *, language: str) -> str:
    text = value.strip()
    if language == "en" and text.endswith(" days") and text.split()[0].isdigit():
        return f"{text.split()[0]}-day"
    if language == "en" and text == "1 year":
        return "1-year"
    return text


def timeline_empty_story_text(filter_id: str, *, language: str) -> str:
    if filter_id == "all":
        return t(language, "timeline_empty_story")
    return t(language, "timeline_empty_filter")


def format_timeline_chart_fallback(*, language: str = "en") -> str:
    return "\n\n".join(
        [
            t(language, "section_timeline_title"),
            t(language, "timeline_chart_failed"),
        ]
    )


def format_timeline_entry(entry: TimelineEntry, *, chat_type: str | None, language: str) -> list[str]:
    label = timeline_entry_label(entry.entry_type, language=language)
    timestamp = timeline_entry_time(entry)
    sender = timeline_sender_label(entry.sender_ref, chat_type=chat_type, language=language)
    details = timeline_entry_details(entry, language=language)
    lines = [f"{timestamp} - {label}"]
    if sender:
        lines.append(f"  {t(language, 'timeline_sender')}: {sender}")
    if details:
        lines.append(f"  {details}")
    confidence = sanitize_label(entry.confidence, fallback=t(language, "not_available"), limit=30)
    lines.append(f"  {t(language, 'report_confidence')}: {confidence}")
    return lines


def timeline_entry_details(entry: TimelineEntry, *, language: str) -> str:
    parts = []
    metadata = entry.metadata or {}
    if metadata.get("bucket_label"):
        parts.append(f"{t(language, 'timeline_period')}: {sanitize_label(str(metadata.get('bucket_label')), fallback='period', limit=30)}")
    if "message_count" in metadata:
        parts.append(f"{t(language, 'report_messages')}: {int(metadata.get('message_count') or 0)}")
    if isinstance(metadata.get("gap_hours"), (int, float)):
        parts.append(f"{t(language, 'timeline_gap')}: {human_duration(float(metadata['gap_hours']) * 3600)}")
    if metadata.get("period_label"):
        parts.append(f"{t(language, 'timeline_report_period')}: {sanitize_label(str(metadata.get('period_label')), fallback='period', limit=40)}")
    if entry.source_message_id is not None and entry.entry_type not in {"activity_period", "quiet_period", "analysis_completed"}:
        parts.append(f"{t(language, 'timeline_source_message')}: #{entry.source_message_id}")
    if entry.rule_source:
        parts.append(f"{t(language, 'timeline_rule_source')}: {sanitize_label(entry.rule_source, fallback='rule', limit=24)}")
    return "; ".join(parts)


def timeline_entry_label(entry_type: str, *, language: str) -> str:
    return {
        "activity_period": t(language, "timeline_event_activity"),
        "quiet_period": t(language, "timeline_event_quiet"),
        "long_silence": t(language, "timeline_event_silence"),
        "question": t(language, "timeline_event_question"),
        "unanswered_question": t(language, "timeline_event_unanswered"),
        "plan_candidate": t(language, "timeline_event_plan"),
        "promise_candidate": t(language, "timeline_event_promise"),
        "follow_up_candidate": t(language, "timeline_event_followup"),
        "confirmed_reminder": t(language, "timeline_event_reminder"),
        "analysis_completed": t(language, "timeline_event_analysis"),
    }.get(entry_type, sanitize_label(entry_type, fallback=t(language, "empty")))


def timeline_sender_label(sender_ref: str | None, *, chat_type: str | None, language: str) -> str | None:
    if not sender_ref:
        return None
    if sender_ref == "channel":
        return t(language, "chat_type_channel")
    if sender_ref.startswith("member_"):
        return f"{t(language, 'timeline_member')} {sender_ref.rsplit('_', 1)[-1]}"
    if sender_ref.startswith("participant_"):
        return f"{t(language, 'timeline_participant')} {sender_ref.rsplit('_', 1)[-1]}"
    if chat_type == "group":
        return t(language, "timeline_member")
    return t(language, "timeline_participant")


def timeline_chat_type_note(chat_type: str | None, *, language: str) -> str:
    if chat_type == "group":
        return t(language, "timeline_group_note")
    if chat_type == "channel":
        return t(language, "timeline_channel_note")
    return t(language, "timeline_private_note")


def timeline_filter_label(filter_id: str, *, language: str) -> str:
    return {
        "all": t(language, "timeline_filter_all"),
        "activity": t(language, "timeline_filter_activity"),
        "questions": t(language, "timeline_filter_questions"),
        "plans": t(language, "timeline_filter_plans"),
        "followups": t(language, "timeline_filter_followups"),
        "silences": t(language, "timeline_filter_silences"),
    }.get(filter_id, t(language, "timeline_filter_all"))


def timeline_recent_change_label(value: str, *, language: str) -> str:
    return {
        "higher": t(language, "timeline_recent_higher"),
        "lower": t(language, "timeline_recent_lower"),
        "similar": t(language, "timeline_recent_similar"),
        "limited": t(language, "timeline_recent_limited"),
        "unavailable": t(language, "timeline_recent_unavailable"),
    }.get(value, t(language, "timeline_recent_unavailable"))


def timeline_period_label(start: str | None, end: str | None, *, language: str) -> str:
    if not start and not end:
        return t(language, "not_available")
    if start and end:
        return f"{timeline_short_date(start)} - {timeline_short_date(end)}"
    return timeline_short_date(start or end or "")


def timeline_short_date(value: str) -> str:
    if not value:
        return ""
    return sanitize_label(value.split("T", 1)[0], fallback="date", limit=16)


def timeline_entry_time(entry: TimelineEntry) -> str:
    return timeline_short_date(entry.timestamp)


def timeline_duration(hours: float | None, *, language: str) -> str:
    if hours is None:
        return t(language, "not_available")
    return human_duration(hours * 3600) or t(language, "not_available")


def timeline_page_range(page: TimelinePage, *, language: str) -> str:
    if page.total == 0:
        return t(language, "timeline_no_entries")
    start = page.page * page.page_size + 1
    end = min(page.total, start + len(page.entries) - 1)
    return f"{t(language, 'timeline_showing')}: {start}-{end} / {page.total}"


def unavailable_section(section: str, status: str, body: str, *, language: str) -> str:
    return "\n".join([section_title(section, language=language), "", status, body])


def section_title(section: str, *, language: str) -> str:
    return {
        "overview": t(language, "button_overview"),
        "timeline": t(language, "section_timeline_title"),
        "activity": t(language, "section_activity_title"),
        "response": t(language, "section_response_title"),
        "followups": t(language, "section_followups_title"),
        "habits": t(language, "section_habits_title"),
        "reports": t(language, "section_reports_title"),
        "settings": t(language, "chat_settings_title"),
    }.get(section, sanitize_label(section, fallback=t(language, "chat_type_unknown")))


def format_remove_chat_confirmation(chat: dict) -> str:
    return "\n\n".join(
        [
            f"Remove {sanitize_label(chat.get('title'), fallback='this chat')} from RelChat?",
            "This removes local RelChat records and imported local data for this chat. It does not delete or modify the Telegram conversation.",
        ]
    )


def format_chat_list(
    conversations: Sequence[ConversationRef],
    *,
    chat_filter: str | None,
    requested_limit: int,
    fetched_count: int,
) -> str:
    label = chat_filter or "all"
    lines = [
        f"Telegram conversations ({label})",
        f"Showing {len(conversations)} of up to {requested_limit} requested; fetched {fetched_count}.",
        "Use /chats private 50, /chats groups 50, or /chats channels 50 to request more.",
        "",
        "chat_id | type | last_message_at | title",
    ]
    if not conversations:
        lines.append("No conversations matched.")
        return "\n".join(lines)

    for conversation in conversations:
        lines.append(
            " | ".join(
                [
                    conversation.conversation_id,
                    sanitize_label(conversation.conversation_type, fallback="unknown", limit=16),
                    sanitize_label(conversation.last_message_at, fallback="unknown", limit=25),
                    sanitize_label(conversation.title, fallback="untitled", limit=60),
                ]
            )
        )
    return "\n".join(lines)


def format_import_result(
    *,
    chat_id: str,
    count: int,
    since: str,
    limit: int | None,
    range_start: str | None,
    range_end: str | None,
) -> str:
    lines = [
        "Import complete",
        "",
        f"Chat: {chat_id}",
        f"Messages imported: {count}",
        f"Since: {since}",
        f"Limit: {limit if limit is not None else 'none'}",
    ]
    if range_start or range_end:
        lines.extend(["", f"Imported range start: {range_start or 'unknown'}", f"Imported range end: {range_end or 'unknown'}"])
    return "\n".join(lines)


def format_metrics(summary: dict, *, chat_label: str | None = None) -> str:
    lines = [
        "Metrics summary",
        "",
        f"Chat: {sanitize_label(chat_label, fallback=str(summary['chat_id'])) if chat_label else summary['chat_id']}",
        f"Messages imported: {summary['message_count']}",
        "",
        "Message count by sender",
    ]
    append_limited_mapping(lines, summary["message_count_by_sender"], value_suffix="")

    initiation = summary["initiation_balance"]
    lines.extend(
        [
            "",
            f"Initiation balance ({initiation['session_count']} sessions, gap > {initiation['gap_hours']}h)",
        ]
    )
    for sender, count in limited_items(initiation["by_sender"]):
        share = initiation["share"].get(sender, 0) * 100
        lines.append(f"{sanitize_label(sender)}: {count} starts ({share:.1f}%)")

    lines.extend(["", "Median response time by responder"])
    for sender, row in limited_items(summary["response_times"]):
        lines.append(
            f"{sanitize_label(sender)}: {row['median_readable'] or 'n/a'} "
            f"({row['count']} replies); active {row['active_median_readable'] or 'n/a'}"
        )

    lines.extend(["", "Average message length"])
    for sender, row in limited_items(summary["average_message_length"]):
        lines.append(f"{sanitize_label(sender)}: {row['avg_chars']} chars over {row['message_count']} text messages")

    unanswered = summary["unanswered_questions"]
    lines.extend(["", f"Unanswered questions: {len(unanswered)}"])
    for item in unanswered[:10]:
        lines.append(
            f"{sanitize_label(item.get('timestamp'), fallback='unknown', limit=25)} "
            f"{sanitize_label(item.get('sender'), fallback='unknown')} "
            f"message_id={item.get('message_id')}"
        )
    if len(unanswered) > 10:
        lines.append(f"...and {len(unanswered) - 10} more")
    return "\n".join(lines)


def format_events(
    chat_id: str,
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
    *,
    chat_label: str | None = None,
) -> str:
    lines = [
        "Event Engine v0 summary",
        "",
        f"Chat: {sanitize_label(chat_label, fallback=chat_id) if chat_label else chat_id}",
        f"Messages scanned: {len(messages)}",
        f"Events detected: {len(events)}",
    ]
    if not events:
        return "\n".join(lines)

    lines.extend(["", "Event count by type"])
    append_limited_mapping(lines, summarize_events(events), value_suffix="")

    lines.extend(["", "Recent events"])
    for event in events[-20:]:
        details = event_details(event)
        suffix = f" {details}" if details else ""
        lines.append(
            f"{sanitize_label(event.timestamp, fallback='unknown', limit=25)} "
            f"{sanitize_label(event.event_type, fallback='event', limit=30)} "
            f"{event_sender_label(event)}{suffix}"
        )
    return "\n".join(lines)


def format_category_prompt(*, folder_count: int = 0) -> str:
    lines = [
        "Analyze a chat",
        "",
        "Choose where to browse.",
    ]
    if folder_count:
        lines.append(f"Telegram folders found: {folder_count}")
    return "\n".join(lines)


def format_chat_page(
    *,
    title: str,
    first_item: int,
    last_item: int,
    total: int,
    search_query: str | None = None,
) -> str:
    lines = ["Select a chat", "", sanitize_label(title, fallback="Chats")]
    if search_query:
        lines.append(f"Search: {sanitize_label(search_query, fallback='query', limit=60)}")
    if total:
        lines.append(f"Showing {first_item}-{last_item} of {total}.")
    else:
        lines.append("No chats matched. Try another section or search.")
    return "\n".join(lines)


def format_search_prompt() -> str:
    return (
        "Search chat\n\n"
        "Send a title, display name, or username. Message contents are not searched."
    )


def format_period_prompt(*, chat_title: str | None, chat_type: str | None) -> str:
    return "\n".join(
        [
            "Choose a time period",
            "",
            f"Chat: {sanitize_label(chat_title, fallback='untitled')}",
            f"Type: {readable_chat_type(chat_type)}",
        ]
    )


def format_confirmation(
    *,
    chat_title: str | None,
    period_label: str,
    warning: str | None = None,
) -> str:
    lines = [
        "Confirm import and analysis",
        "",
        f"Chat: {sanitize_label(chat_title, fallback='untitled')}",
        f"Period: {sanitize_label(period_label, fallback='unknown', limit=40)}",
    ]
    if warning:
        lines.extend(["", sanitize_label(warning, fallback="Warning", limit=120)])
    lines.extend(["", "No import will start until you press Start import."])
    return "\n".join(lines)


def format_recent_reports(entries: Sequence[dict]) -> str:
    lines = ["Recent reports", ""]
    if not entries:
        lines.append("No reports yet.")
        return "\n".join(lines)
    for index, entry in enumerate(entries[:5], start=1):
        title = sanitize_label(entry.get("chat_title"), fallback="untitled", limit=50)
        period = sanitize_label(entry.get("period_label"), fallback="unknown", limit=30)
        message_count = entry.get("message_count", 0)
        event_count = entry.get("event_count", 0)
        lines.append(f"{index}. {title} - {period}; {message_count} messages; {event_count} events")
    return "\n".join(lines)


def format_import_progress(*, chat_title: str | None, period_label: str, count: int) -> str:
    return "\n".join(
        [
            "Importing chat",
            "",
            f"Chat: {sanitize_label(chat_title, fallback='untitled')}",
            f"Period: {sanitize_label(period_label, fallback='unknown', limit=40)}",
            f"Messages imported: {count}",
        ]
    )


def format_custom_start_prompt(chat_title: str | None) -> str:
    return "\n".join(
        [
            "Custom date range",
            "",
            f"Chat: {sanitize_label(chat_title, fallback='untitled')}",
            "Send a start date or duration.",
            "",
            "Examples: 2026-07-01, 01.07.2026, 7 days, 30 days",
        ]
    )


def format_custom_end_prompt(start_date: str) -> str:
    return "\n".join(
        [
            "Custom date range",
            "",
            f"Start: {sanitize_label(start_date, fallback='selected date', limit=30)}",
            "Send an optional end date, or choose no end date.",
            "",
            "Examples: 2026-07-13, 13.07.2026",
        ]
    )


def format_invalid_date_message() -> str:
    return (
        "I could not read that date.\n\n"
        "Try one of these formats:\n"
        "2026-07-01\n"
        "01.07.2026\n"
        "7 days\n"
        "30 days"
    )


def format_module_selection(selected_modules: Sequence[str]) -> str:
    lines = [
        "Choose analysis modules",
        "",
        "Selected modules:",
    ]
    if selected_modules:
        lines.extend(f"- {label}" for label in module_labels(list(selected_modules)))
    else:
        lines.append("- none")
    lines.extend(["", "Topic analysis is coming soon and will not run yet."])
    return "\n".join(lines)


def format_analysis_review(flow: dict) -> str:
    modules = module_labels(list(flow.get("modules") or []))
    lines = [
        "Review analysis",
        "",
        f"Chat: {sanitize_label(flow.get('chat_title'), fallback='untitled')}",
        f"Period: {sanitize_label(flow.get('period_label'), fallback='unknown', limit=60)}",
        f"Modules: {', '.join(modules) if modules else 'none'}",
        "",
        "RelChat will import local normalized messages for this selection, calculate the selected modules where available, and create a sectioned report.",
    ]
    if flow.get("period_id") == "full":
        lines.append("Full history can take longer for large chats.")
    return "\n".join(lines)


def format_job_progress(job: dict, *, language: str = "en") -> str:
    status = sanitize_label(job.get("status"), fallback="queued")
    percent = int(job.get("progress_percent") or 0)
    count = int(job.get("imported_message_count") or 0)
    elapsed = job.get("elapsed_seconds")
    lines = [
        t(language, "job_progress_title"),
        "",
        f"{t(language, 'job_progress_chat')}: {sanitize_label(job.get('chat_title'), fallback=t(language, 'chat_type_unknown'))}",
        f"{t(language, 'analysis_result_period')}: {sanitize_label(job.get('period_label'), fallback=t(language, 'not_available'))}",
        f"{t(language, 'job_progress_status')}: {job_status_label(status, language=language)}",
        f"{t(language, 'job_progress_percent')}: {percent}%",
        f"{t(language, 'job_progress_imported')}: {count}",
    ]
    if elapsed is not None:
        lines.append(f"{t(language, 'job_progress_elapsed')}: {human_duration(float(elapsed)) or '0s'}")
    if status == "retrying":
        retry_attempt = min(3, int(job.get("retry_attempt_count") or 0) + 1)
        lines.append(t(language, "job_progress_retrying_attempt", attempt=retry_attempt, total=3))
    return "\n".join(lines)


def format_job_failure(job: dict, *, language: str = "en") -> str:
    reason = failure_reason_text(str(job.get("error_message") or ""), language=language)
    lines = [
        t(language, "job_failed_title"),
        "",
        f"{t(language, 'job_progress_chat')}: {sanitize_label(job.get('chat_title'), fallback=t(language, 'chat_type_unknown'))}",
        f"{t(language, 'job_failure_reason')}: {reason}",
        f"{t(language, 'job_progress_imported')}: {int(job.get('imported_message_count') or 0)}",
    ]
    lines.append(t(language, "job_failure_retry_hint"))
    return "\n".join(lines)


def job_status_label(status: str, *, language: str) -> str:
    key = f"job_status_{status}"
    translated = t(language, key)
    return translated if translated != key else sanitize_label(status.replace("_", " "), fallback=status)


def failure_reason_text(category: str, *, language: str) -> str:
    key = {
        "no_messages": "failure_no_messages",
        "flood_wait": "failure_telegram_rate_limit",
        "auth_expired": "failure_telegram_auth",
        "network_unavailable": "failure_network_dns",
        "chat_inaccessible": "failure_chat_inaccessible",
        "telegram_temporary": "failure_telegram_temporary_final",
        "telegram_rate_limit": "failure_telegram_rate_limit",
        "telegram_internal": "failure_telegram_temporary_final",
        "telegram_auth": "failure_telegram_auth",
        "network_dns": "failure_network_dns",
        "provider_timeout": "failure_provider_timeout",
        "provider_rate_limit": "failure_provider_rate_limit",
        "provider_invalid_response": "failure_provider_invalid_response",
        "database_locked": "failure_database_locked",
        "validation_error": "failure_validation_error",
        "cancelled": "failure_cancelled",
    }.get(category, "failure_unknown")
    return t(language, key)


def format_reports_home(counts: dict[str, int]) -> str:
    return "\n".join(
        [
            "Reports",
            "",
            f"Latest reports: {counts.get('reports', 0)}",
            f"Favorite reports: {counts.get('favorite_reports', 0)}",
            f"Failed analyses: {counts.get('failed_jobs', 0)}",
            "",
            "Choose a section.",
        ]
    )


def format_report_list(title: str, reports: Sequence[dict], *, language: str = "en") -> str:
    lines = [title, ""]
    if not reports:
        lines.append(t(language, "empty_no_report"))
    else:
        lines.append(t(language, "my_chats_choose"))
    return "\n".join(lines)


def format_failed_jobs(jobs: Sequence[dict]) -> str:
    lines = ["Failed analyses", ""]
    if not jobs:
        lines.append("No failed analyses.")
        return "\n".join(lines)
    for index, job in enumerate(jobs[:10], start=1):
        lines.append(
            f"{index}. {sanitize_label(job.get('chat_title'), fallback='untitled')} - "
            f"{sanitize_label(job.get('period_label'), fallback='period')} "
            f"({sanitize_label(job.get('error_reference'), fallback='no reference')})"
        )
    return "\n".join(lines)


def format_chat_overview(
    report: dict | None,
    *,
    previous_report: dict | None = None,
    chat: dict | None = None,
    confirmed_reminders: int = 0,
    language: str = "en",
) -> str:
    if report is None:
        return "\n\n".join([t(language, "overview_title"), t(language, "overview_no_report")])
    metrics = report.get("metrics_summary") or {}
    quality = report.get("data_quality") or {}
    count = int(report.get("imported_message_count") or metrics.get("message_count") or 0)
    if count <= 0:
        return "\n\n".join([t(language, "overview_title"), t(language, "overview_no_messages")])
    chat_type = (chat or {}).get("chat_type")
    lines = [
        t(language, "overview_title"),
        "",
        t(language, "overview_current_snapshot"),
        current_snapshot_sentence(metrics, chat_type=chat_type, language=language),
        "",
        t(language, "overview_recent_change"),
        recent_change_sentence(report, previous_report, language=language),
        "",
        t(language, "overview_balance"),
    ]
    lines.extend(compact_balance_lines(metrics, chat_type=chat_type, language=language))
    response_lines = compact_response_lines(metrics, language=language)
    if response_lines:
        lines.extend(["", t(language, "overview_response"), *response_lines])
    attention_lines = compact_attention_lines(report, confirmed_reminders=confirmed_reminders, language=language)
    lines.extend(["", t(language, "overview_attention"), *attention_lines])
    lines.extend(
        [
            "",
            t(language, "overview_data_quality"),
            f"{sanitize_label(report.get('period_label'), fallback='unknown', limit=50)}; {t(language, 'report_messages')}: {count}",
            f"{t(language, 'report_completeness')}: {sanitize_label(quality.get('completeness'), fallback='unknown', limit=50)}",
            f"{t(language, 'report_confidence')}: {sanitize_label(quality.get('confidence'), fallback='unknown', limit=40)}",
        ]
    )
    if count < 30:
        lines.append(t(language, "overview_limited_sample"))
    return "\n".join(lines)


def format_chat_overview_details(
    report: dict | None,
    *,
    previous_report: dict | None = None,
    chat: dict | None = None,
    confirmed_reminders: int = 0,
    language: str = "en",
) -> str:
    if report is None:
        return "\n\n".join([t(language, "overview_details_title"), t(language, "overview_no_report")])
    metrics = report.get("metrics_summary") or {}
    events = report.get("event_summary") or {}
    quality = report.get("data_quality") or {}
    count = int(report.get("imported_message_count") or metrics.get("message_count") or 0)
    lines = [
        t(language, "overview_details_title"),
        "",
        f"{t(language, 'report_messages')}: {count}",
        f"{t(language, 'chat_home_last_period')}: {sanitize_label(report.get('period_label'), fallback='unknown', limit=50)}",
        f"{t(language, 'overview_imported_range')}: {sanitize_label(quality.get('range_start'), fallback='unknown', limit=30)} - {sanitize_label(quality.get('range_end'), fallback='unknown', limit=30)}",
        "",
        t(language, "overview_balance"),
    ]
    lines.extend(detailed_balance_lines(metrics, language=language))
    lines.extend(["", t(language, "overview_response")])
    lines.extend(detailed_response_lines(metrics, language=language))
    lines.extend(["", t(language, "overview_attention")])
    lines.extend(detailed_attention_lines(metrics, events, confirmed_reminders=confirmed_reminders, language=language))
    lines.extend(["", t(language, "overview_data_quality")])
    lines.append(f"{t(language, 'report_completeness')}: {sanitize_label(quality.get('completeness'), fallback='unknown', limit=50)}")
    lines.append(f"{t(language, 'report_confidence')}: {sanitize_label(quality.get('confidence'), fallback='unknown', limit=40)}")
    if count < 30:
        lines.append(t(language, "overview_not_enough_for_percent"))
    if previous_report is None:
        lines.append(t(language, "overview_recent_missing"))
    return "\n".join(lines)


def current_snapshot_sentence(metrics: dict, *, chat_type: str | None, language: str) -> str:
    count = int(metrics.get("message_count") or 0)
    if count < 30:
        return t(language, "overview_limited_sample")
    if chat_type == "group":
        return t(language, "overview_group")
    if chat_type == "channel":
        return t(language, "overview_channel")
    initiation = metrics.get("initiation_balance") or {}
    share = initiation.get("share") or {}
    if share and max(float(value) for value in share.values()) >= 0.65:
        return t(language, "overview_private_one_sided_initiation")
    counts = metrics.get("message_count_by_sender") or {}
    if counts and contribution_top_share(counts) < 0.6:
        return t(language, "overview_private_balanced")
    return t(language, "overview_private_active")


def recent_change_sentence(report: dict, previous_report: dict | None, *, language: str) -> str:
    if previous_report is None:
        return t(language, "overview_recent_missing")
    current_count = int(report.get("imported_message_count") or (report.get("metrics_summary") or {}).get("message_count") or 0)
    previous_count = int(previous_report.get("imported_message_count") or (previous_report.get("metrics_summary") or {}).get("message_count") or 0)
    if report.get("period_id") != previous_report.get("period_id") or current_count < 30 or previous_count < 30:
        return t(language, "overview_recent_limited")
    if previous_count == 0:
        return t(language, "overview_recent_limited")
    ratio = current_count / previous_count
    if ratio >= 1.25:
        return t(language, "overview_recent_higher")
    if ratio <= 0.75:
        return t(language, "overview_recent_lower")
    return t(language, "overview_recent_similar")


def compact_balance_lines(metrics: dict, *, chat_type: str | None, language: str) -> list[str]:
    lines = []
    initiation = metrics.get("initiation_balance") or {}
    session_count = int(initiation.get("session_count") or 0)
    initiation_by_sender = initiation.get("by_sender") or {}
    if chat_type != "channel" and initiation_by_sender:
        lines.append(f"{t(language, 'overview_initiation_split')}: {compact_mapping(initiative_display(initiation_by_sender, session_count), limit=2)}")
    counts = metrics.get("message_count_by_sender") or {}
    if counts:
        label = t(language, "overview_reply_participation")
        lines.append(f"{label}: {compact_mapping(participation_display(counts), limit=3)}")
    lines.append(t(language, "overview_planning_balance_unavailable"))
    return lines


def detailed_balance_lines(metrics: dict, *, language: str) -> list[str]:
    lines = []
    initiation = metrics.get("initiation_balance") or {}
    session_count = int(initiation.get("session_count") or 0)
    if initiation.get("by_sender"):
        lines.append(f"{t(language, 'overview_initiation_split')} ({session_count}): {compact_mapping(initiative_display(initiation['by_sender'], session_count), limit=6)}")
    counts = metrics.get("message_count_by_sender") or {}
    if counts:
        lines.append(f"{t(language, 'overview_reply_participation')}: {compact_mapping(participation_display(counts), limit=6)}")
    lengths = metrics.get("average_message_length") or {}
    if lengths:
        values = []
        for sender, row in list(lengths.items())[:6]:
            values.append(f"{sanitize_label(sender)} {row.get('avg_chars', 0)}")
        lines.append(f"{t(language, 'overview_average_length')}: {', '.join(values)}")
    if not lines:
        lines.append(t(language, "empty"))
    return lines


def compact_response_lines(metrics: dict, *, language: str) -> list[str]:
    response = response_rollup(metrics)
    if response is None:
        return [t(language, "overview_response_limited")]
    typical, active, consistent = response
    return [
        f"{t(language, 'overview_typical_response')}: {response_bucket(typical, language=language)}",
        f"{t(language, 'overview_active_response')}: {response_bucket(active, language=language)}",
        t(language, "overview_consistent") if consistent else t(language, "overview_varied"),
    ]


def detailed_response_lines(metrics: dict, *, language: str) -> list[str]:
    response_times = metrics.get("response_times") or {}
    if not response_times:
        return [t(language, "overview_response_limited")]
    lines = []
    for sender, row in list(response_times.items())[:6]:
        lines.append(
            f"{sanitize_label(sender)}: {row.get('median_readable') or t(language, 'not_available')}; "
            f"{t(language, 'overview_active_response')}: {row.get('active_median_readable') or t(language, 'not_available')}; "
            f"{t(language, 'overview_count')}={int(row.get('count') or 0)}"
        )
    return lines


def compact_attention_lines(report: dict, *, confirmed_reminders: int, language: str) -> list[str]:
    metrics = report.get("metrics_summary") or {}
    events = report.get("event_summary") or {}
    by_type = events.get("by_type") or {}
    unanswered = len(metrics.get("unanswered_questions") or [])
    plans = int(by_type.get("plan_candidate") or 0)
    promises = int(by_type.get("promise_candidate") or 0)
    followups = int(by_type.get("follow_up_candidate") or 0)
    if not any([unanswered, plans, promises, followups, confirmed_reminders]):
        return [t(language, "overview_no_attention")]
    lines = []
    if unanswered:
        lines.append(f"{t(language, 'overview_unanswered_questions')}: {unanswered}")
    if plans:
        lines.append(f"{t(language, 'overview_unresolved_plans')}: {plans}")
    if promises or followups:
        lines.append(f"{t(language, 'overview_promises_followups')}: {promises + followups}")
    if confirmed_reminders:
        lines.append(f"{t(language, 'overview_confirmed_reminders')}: {confirmed_reminders}")
    return lines


def detailed_attention_lines(metrics: dict, events: dict, *, confirmed_reminders: int, language: str) -> list[str]:
    by_type = events.get("by_type") or {}
    lines = compact_attention_lines(
        {"metrics_summary": metrics, "event_summary": events},
        confirmed_reminders=confirmed_reminders,
        language=language,
    )
    long_silences = int(by_type.get("long_silence") or 0)
    if long_silences:
        lines.append(f"{t(language, 'overview_long_silences')}: {long_silences}")
    return lines


def participation_display(counts: dict) -> dict[str, str]:
    total = sum(int(value) for value in counts.values()) or 0
    enough = total >= 30
    out = {}
    for sender, count in counts.items():
        if enough:
            out[str(sender)] = f"{count} ({(int(count) / total) * 100:.0f}%)"
        else:
            out[str(sender)] = str(count)
    return out


def initiative_display(counts: dict, total: int) -> dict[str, str]:
    enough = total >= 5
    out = {}
    for sender, count in counts.items():
        if enough and total:
            out[str(sender)] = f"{count} ({(int(count) / total) * 100:.0f}%)"
        else:
            out[str(sender)] = str(count)
    return out


def compact_mapping(mapping: dict, *, limit: int) -> str:
    return ", ".join(f"{sanitize_label(key)} {value}" for key, value in list(mapping.items())[:limit]) or "n/a"


def contribution_top_share(counts: dict) -> float:
    total = sum(int(value) for value in counts.values()) or 1
    return max(int(value) for value in counts.values()) / total


def response_rollup(metrics: dict) -> tuple[float | None, float | None, bool] | None:
    rows = list((metrics.get("response_times") or {}).values())
    medians = [float(row["median_seconds"]) for row in rows if row.get("median_seconds") is not None and int(row.get("count") or 0) > 0]
    active = [float(row["active_median_seconds"]) for row in rows if row.get("active_median_seconds") is not None and int(row.get("active_count") or 0) > 0]
    if not medians:
        return None
    typical = sum(medians) / len(medians)
    active_value = sum(active) / len(active) if active else None
    consistent = True
    if len(medians) >= 2 and min(medians) > 0:
        consistent = max(medians) / min(medians) <= 2.5
    return typical, active_value, consistent


def response_bucket(seconds: float | None, *, language: str) -> str:
    if seconds is None:
        return t(language, "not_available")
    if seconds < 5 * 60:
        return t(language, "response_bucket_minutes")
    if seconds < 60 * 60:
        return t(language, "response_bucket_hour")
    if seconds < 6 * 60 * 60:
        return t(language, "response_bucket_hours")
    if seconds < 24 * 60 * 60:
        return t(language, "response_bucket_day")
    return t(language, "response_bucket_over_day")


def format_report_overview(report: dict) -> str:
    metrics = report.get("metrics_summary") or {}
    events = report.get("event_summary") or {}
    quality = report.get("data_quality") or {}
    count = int(report.get("imported_message_count") or 0)
    lines = [
        "Report overview",
        "",
        f"Chat: {sanitize_label(report.get('chat_title'), fallback='untitled')}",
        f"Period: {sanitize_label(report.get('period_label'), fallback='unknown', limit=60)}",
        f"Messages analyzed: {count}",
        f"Modules: {', '.join(module_labels(list(report.get('modules') or [])))}",
        "",
        "Observed facts",
        f"- {count} local messages were included.",
        f"- {len(metrics.get('message_count_by_sender') or {})} senders contributed during this period.",
        f"- {int(events.get('total_events') or 0)} rule-based events were detected.",
        "",
        "Cautious interpretation",
        f"- {balance_sentence(metrics)}",
        f"- {initiation_sentence(metrics)}",
        f"- {questions_sentence(metrics)}",
        "",
        "Data limitation",
        f"- Completeness: {sanitize_label(quality.get('completeness'), fallback='unknown')}.",
        f"- Confidence: {sanitize_label(quality.get('confidence'), fallback='unknown')}.",
        "- This report summarizes observed local data only.",
    ]
    return "\n".join(lines)


def format_report_section(report: dict, section: str) -> str:
    if section == "overview":
        return format_report_overview(report)
    required_module = {
        "balance": "balance",
        "activity": "activity",
        "response": "response_times",
        "questions": "questions",
        "plans": "plans",
        "reminders": "reminders",
    }.get(section)
    if required_module and required_module not in set(report.get("modules") or []):
        return "\n".join(
            [
                section.replace("_", " ").title(),
                "",
                "This module was not enabled for this report.",
                "",
                "Run the analysis again and select this module to include it.",
            ]
        )
    metrics = report.get("metrics_summary") or {}
    events = report.get("event_summary") or {}
    quality = report.get("data_quality") or {}
    if section == "balance":
        return section_with_blocks(
            "Balance",
            facts=balance_facts(metrics),
            interpretation=[balance_sentence(metrics)],
            limitations=["Message count does not measure care, intent, or emotional importance."],
        )
    if section == "activity":
        return section_with_blocks(
            "Activity",
            facts=activity_facts(metrics),
            interpretation=["Activity shows when messages were present in the selected local data."],
            limitations=["Deleted messages, missing history, and media-only exchanges can change this picture."],
        )
    if section == "response":
        return section_with_blocks(
            "Response patterns",
            facts=response_facts(metrics),
            interpretation=[response_sentence(metrics)],
            limitations=["Response time is affected by sleep, work, travel, notifications, and many unknown factors."],
        )
    if section == "questions":
        return section_with_blocks(
            "Questions",
            facts=question_facts(metrics),
            interpretation=[questions_sentence(metrics)],
            limitations=["A later message can answer a question indirectly, and RelChat does not infer hidden meaning."],
        )
    if section == "plans":
        return section_with_blocks(
            "Plans and follow-ups",
            facts=event_facts(events, ["plan_candidate", "promise_candidate", "follow_up_candidate"]),
            interpretation=["These are explicit keyword-based candidates that may be useful to review."],
            limitations=["RelChat does not know whether a plan or promise was fulfilled unless the local messages make it explicit."],
        )
    if section == "reminders":
        return section_with_blocks(
            "Reminders",
            facts=event_facts(events, ["follow_up_candidate", "plan_candidate", "promise_candidate"]),
            interpretation=["Reminder suggestions are based only on explicit detected events and require confirmation before use."],
            limitations=["RelChat does not automatically schedule every candidate."],
        )
    if section == "quality":
        return section_with_blocks(
            "Data quality",
            facts=[
                f"Messages analyzed: {int(report.get('imported_message_count') or 0)}",
                f"Range start: {sanitize_label(quality.get('range_start'), fallback='unknown', limit=30)}",
                f"Range end: {sanitize_label(quality.get('range_end'), fallback='unknown', limit=30)}",
                f"Completeness: {sanitize_label(quality.get('completeness'), fallback='unknown')}",
                f"Confidence: {sanitize_label(quality.get('confidence'), fallback='unknown')}",
            ],
            interpretation=["More complete selected history usually makes aggregate patterns more useful."],
            limitations=["RelChat only sees messages imported locally for the selected chat and period."],
        )
    return format_report_overview(report)


def section_with_blocks(title: str, *, facts: Sequence[str], interpretation: Sequence[str], limitations: Sequence[str]) -> str:
    lines = [title, "", "Observed facts"]
    lines.extend(f"- {item}" for item in (facts or ["No data available."]))
    lines.extend(["", "Cautious interpretation"])
    lines.extend(f"- {item}" for item in (interpretation or ["No interpretation available."]))
    lines.extend(["", "Data limitation"])
    lines.extend(f"- {item}" for item in (limitations or ["The selected data may be incomplete."]))
    return "\n".join(lines)


def balance_facts(metrics: dict) -> list[str]:
    counts = metrics.get("message_count_by_sender") or {}
    if not counts:
        return ["No sender balance data was available."]
    total = sum(int(value) for value in counts.values()) or 1
    return [
        f"{sanitize_label(sender)}: {count} messages ({(int(count) / total) * 100:.1f}%)"
        for sender, count in list(counts.items())[:8]
    ]


def activity_facts(metrics: dict) -> list[str]:
    count = int(metrics.get("message_count") or 0)
    lengths = metrics.get("average_message_length") or {}
    lines = [f"Messages in selected period: {count}"]
    for sender, row in list(lengths.items())[:6]:
        lines.append(
            f"{sanitize_label(sender)} averaged {row.get('avg_chars', 0)} text characters across {row.get('message_count', 0)} text messages."
        )
    return lines


def response_facts(metrics: dict) -> list[str]:
    response_times = metrics.get("response_times") or {}
    if not response_times:
        return ["No response timing data was available."]
    lines = []
    for sender, row in list(response_times.items())[:8]:
        lines.append(
            f"{sanitize_label(sender)}: median {row.get('median_readable') or 'n/a'} over {row.get('count', 0)} observed replies."
        )
    return lines


def question_facts(metrics: dict) -> list[str]:
    unanswered = metrics.get("unanswered_questions") or []
    return [f"Potential unanswered questions: {len(unanswered)}"]


def event_facts(events: dict, keys: Sequence[str]) -> list[str]:
    by_type = events.get("by_type") or {}
    lines = []
    for key in keys:
        lines.append(f"{key.replace('_', ' ')}: {int(by_type.get(key) or 0)}")
    return lines


def balance_sentence(metrics: dict) -> str:
    counts = metrics.get("message_count_by_sender") or {}
    if len(counts) < 2:
        return "There is not enough sender data to compare contribution balance."
    values = list(counts.values())
    total = sum(int(value) for value in values) or 1
    top_share = max(int(value) for value in values) / total
    if top_share < 0.6:
        return "Both people contributed regularly during this period."
    return "One participant sent more of the messages in this selected period."


def initiation_sentence(metrics: dict) -> str:
    initiation = metrics.get("initiation_balance") or {}
    by_sender = initiation.get("by_sender") or {}
    if not by_sender:
        return "There is not enough session data to summarize who started conversations."
    sender, count = next(iter(by_sender.items()))
    sessions = int(initiation.get("session_count") or 0)
    if sessions <= 1:
        return "Only one conversation session was visible in this period."
    return f"{sanitize_label(sender)} started {count} of {sessions} observed sessions."


def response_sentence(metrics: dict) -> str:
    response_times = metrics.get("response_times") or {}
    if not response_times:
        return "There is not enough alternating-message data to summarize replies."
    readable = [row.get("active_median_readable") for row in response_times.values() if row.get("active_median_readable")]
    if readable:
        return "Replies were usually fast while the conversation was active."
    return "Most observed reply gaps were outside the active conversation window."


def questions_sentence(metrics: dict) -> str:
    count = len(metrics.get("unanswered_questions") or [])
    if count == 0:
        return "No unanswered-question candidates were found."
    if count == 1:
        return "One question may still need a response."
    return f"{count} questions may still need a response."


def format_reminders_home(counts: dict[str, int]) -> str:
    return "\n".join(
        [
            "Reminders",
            "",
            f"Suggested: {counts.get('suggested', 0)}",
            f"Confirmed: {counts.get('confirmed', 0)}",
            f"Completed: {counts.get('completed', 0)}",
            f"Dismissed: {counts.get('dismissed', 0)}",
            "",
            "RelChat suggests reminders only from explicit detected events. Confirm the ones you want to keep.",
        ]
    )


def format_reminder_list(title: str, reminders: Sequence[dict]) -> str:
    lines = [title, ""]
    lines.append("Choose a reminder." if reminders else "No reminders here.")
    return "\n".join(lines)


def format_reminder_detail(reminder: dict) -> str:
    return "\n".join(
        [
            sanitize_label(reminder.get("title"), fallback="Reminder"),
            "",
            f"Status: {sanitize_label(reminder.get('status'), fallback='suggested')}",
            f"When: {sanitize_label(reminder.get('reminder_time'), fallback='not set', limit=30)}",
            f"Chat: {sanitize_label(reminder.get('chat_title'), fallback='not linked')}",
            "",
            "Confirm only if this reminder is useful.",
        ]
    )


def format_settings(settings: dict) -> str:
    language = str(settings.get("language") or "en")
    retention = settings.get("data_retention_days")
    retention_label = f"{retention} days" if retention else "Keep until deleted"
    consent_label = (
        t(language, "settings_ai_consent_active")
        if settings.get("ai_consent_active")
        else t(language, "settings_ai_consent_not_active")
    )
    return "\n".join(
        [
            "Settings",
            "",
            f"Language: {settings.get('language', 'en')}",
            f"Default period: {settings.get('default_period', '30d')}",
            f"Default modules: {', '.join(module_labels(list(settings.get('default_modules') or [])))}",
            f"Progress notifications: {yes_no(bool(settings.get('progress_notifications')))}",
            f"Show technical details: {yes_no(bool(settings.get('show_technical_details')))}",
            f"Data retention: {retention_label}",
            f"Confirm before deleting local data: {yes_no(bool(settings.get('confirm_before_delete')))}",
            f"{t(language, 'ai_consent_status')}: {consent_label}",
            "",
            t(language, "automation_defaults_title"),
            f"{t(language, 'automation_master_switch')}: {yes_no(bool(settings.get('automatic_analysis_master_enabled')))}",
            f"{t(language, 'automation_notifications')}: {yes_no(bool(settings.get('automatic_default_notification_enabled')))}",
            f"{t(language, 'inactivity_threshold')}: {int(settings.get('automatic_default_inactivity_minutes') or 45)} min",
            f"{t(language, 'minimum_new_messages')}: {int(settings.get('automatic_default_minimum_new_messages') or 10)}",
            f"{t(language, 'automation_cooldown')}: {int(settings.get('automatic_default_cooldown_hours') or 12)}h",
            f"{t(language, 'quiet_hours')}: {yes_no(bool(settings.get('automatic_default_quiet_hours_enabled')))} {settings.get('automatic_default_quiet_hours_start') or '23:00'}-{settings.get('automatic_default_quiet_hours_end') or '08:00'}",
            f"{t(language, 'automation_analysis_mode')}: {t(language, 'automation_mode_ai') if settings.get('automatic_default_preferred_analysis_mode') == 'ai' else t(language, 'automation_mode_local')}",
        ]
    )


def format_data_management() -> str:
    return "\n\n".join(
        [
            "Local data management",
            "These actions affect only local RelChat data. They never delete Telegram chats, Telegram messages, or the Telegram session.",
        ]
    )


def format_storage_summary(summary: dict[str, int]) -> str:
    return "\n".join(
        [
            "Local storage summary",
            "",
            f"Known chats: {summary.get('known_chats', 0)}",
            f"Saved chats: {summary.get('saved_chats', 0)}",
            f"Imported messages: {summary.get('messages', 0)}",
            f"Reports: {summary.get('reports', 0)}",
            f"Jobs: {summary.get('jobs', 0)}",
            f"Active reminders: {summary.get('active_reminders', 0)}",
        ]
    )


def format_destructive_confirmation(action_label: str) -> str:
    return "\n\n".join(
        [
            f"Confirm: {sanitize_label(action_label, fallback='delete local data')}",
            "This only deletes local RelChat data. It never deletes Telegram chats, messages, account authorization, or session files.",
        ]
    )


def readable_chat_type(chat_type: str | None, *, language: str = "en") -> str:
    return {
        "one_to_one": t(language, "chat_type_person"),
        "group": t(language, "chat_type_group"),
        "channel": t(language, "chat_type_channel"),
    }.get(chat_type or "", t(language, "chat_type_unknown"))


def human_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def format_combined_report(
    *,
    chat_id: str,
    chat_title: str | None,
    period_label: str,
    count: int,
    range_start: str | None,
    range_end: str | None,
    metrics_summary: dict,
    messages: Sequence[Message],
    events: Sequence[ConversationEvent],
) -> str:
    chat_label = sanitize_label(chat_title, fallback="untitled")
    lines = [
        "RelChat analysis complete",
        "",
        f"Chat: {chat_label}",
        f"Period: {sanitize_label(period_label, fallback='unknown', limit=40)}",
        f"Messages imported: {count}",
    ]
    if range_start or range_end:
        lines.extend(
            [
                f"Imported range start: {sanitize_label(range_start, fallback='unknown', limit=30)}",
                f"Imported range end: {sanitize_label(range_end, fallback='unknown', limit=30)}",
            ]
        )
    lines.extend(
        [
            "",
            format_metrics(metrics_summary, chat_label=chat_label),
            "",
            format_events(chat_id, messages, events, chat_label=chat_label),
        ]
    )
    return "\n".join(lines)


def format_flood_wait(seconds: int | None) -> str:
    if seconds is None:
        return "Telegram asked RelChat to wait before continuing. Try again later."
    return f"Telegram asked RelChat to wait {seconds} seconds before continuing. Try again later."


def append_limited_mapping(lines: list[str], mapping: dict, *, value_suffix: str, limit: int = 10) -> None:
    if not mapping:
        lines.append("none")
        return
    items = list(mapping.items())
    for key, value in items[:limit]:
        lines.append(f"{sanitize_label(str(key))}: {value}{value_suffix}")
    if len(items) > limit:
        lines.append(f"...and {len(items) - limit} more")


def limited_items(mapping: dict, *, limit: int = 10) -> Iterable[tuple]:
    return list(mapping.items())[:limit]


def event_sender_label(event: ConversationEvent) -> str:
    if event.sender_name:
        return sanitize_label(event.sender_name)
    if event.sender_id:
        return f"user:{event.sender_id}"
    return "unknown"


def event_details(event: ConversationEvent) -> str:
    details = []
    if event.source_message_id is not None:
        details.append(f"message_id={event.source_message_id}")
    if event.related_message_id is not None:
        details.append(f"related_message_id={event.related_message_id}")
    gap_hours = event.metadata.get("gap_hours")
    if gap_hours is not None:
        details.append(f"gap={gap_hours}h")
    response_window = event.metadata.get("response_window_hours")
    if response_window is not None:
        details.append(f"response_window={response_window}h")
    return " ".join(details)
