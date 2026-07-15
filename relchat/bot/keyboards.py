from __future__ import annotations

from collections.abc import Sequence

from relchat.bot.formatters import clip_text, sanitize_label
from relchat.bot.localization import LANGUAGES, t
from relchat.bot.state import ANALYSIS_MODULES, PERIOD_OPTIONS, RUNNABLE_MODULE_IDS
from relchat.core.models import ConversationRef, DialogFolder


CB_MAIN = "rc:nav:main"
CB_CANCEL = "rc:cancel"


def main_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(language, "button_analyze"), callback_data="rc:nav:analyze")],
            [
                InlineKeyboardButton(t(language, "button_my_chats"), callback_data="rc:nav:chats"),
                InlineKeyboardButton(t(language, "button_reports"), callback_data="rc:nav:reports"),
            ],
            [
                InlineKeyboardButton(t(language, "button_reminders"), callback_data="rc:nav:reminders"),
                InlineKeyboardButton(t(language, "button_settings"), callback_data="rc:nav:settings"),
            ],
            [InlineKeyboardButton(t(language, "button_help"), callback_data="rc:nav:help")],
        ]
    )


def back_main_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)]])


def onboarding_keyboard(step: int, *, connected: bool, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if step < 3:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Continue", callback_data=f"rc:onb:{step + 1}")]])
    rows = []
    if not connected:
        rows.append([InlineKeyboardButton("Check again", callback_data="rc:onb:3")])
    rows.append([InlineKeyboardButton("Continue to RelChat", callback_data="rc:onb:done")])
    return InlineKeyboardMarkup(rows)


def help_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("What RelChat can analyze", callback_data="rc:help:analyze")],
            [InlineKeyboardButton("How privacy works", callback_data="rc:help:privacy")],
            [InlineKeyboardButton("Why Telegram authorization is required", callback_data="rc:help:auth")],
            [InlineKeyboardButton("What metrics mean", callback_data="rc:help:metrics")],
            [InlineKeyboardButton("What RelChat cannot know", callback_data="rc:help:limits")],
            [InlineKeyboardButton("Troubleshooting", callback_data="rc:help:trouble")],
            [InlineKeyboardButton("About", callback_data="rc:help:about")],
            [InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)],
        ]
    )


def my_chats_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(language, "button_favorites"), callback_data="rc:chats:sec:favorites")],
            [InlineKeyboardButton(t(language, "button_recently_analyzed"), callback_data="rc:chats:sec:recent")],
            [InlineKeyboardButton(t(language, "button_saved_chats"), callback_data="rc:chats:sec:saved")],
            [InlineKeyboardButton(t(language, "button_browse_all"), callback_data="rc:nav:analyze")],
            [InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)],
        ]
    )


def saved_chat_list_keyboard(chats: Sequence[dict], *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for index, chat in enumerate(chats):
        rows.append(
            [
                InlineKeyboardButton(
                    chat_row_label_from_dict(chat, index=index),
                    callback_data=f"rc:chat:item:{index}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:chats")])
    return InlineKeyboardMarkup(rows)


def saved_chat_actions_keyboard(chat: dict, index: int, *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    favorite_label = "Remove favorite" if chat.get("is_favorite") else "Add favorite"
    rows = [
        [InlineKeyboardButton("Analyze", callback_data=f"rc:chat:analyze:{index}")],
        [InlineKeyboardButton("View latest report", callback_data=f"rc:chat:report:{index}")],
        [InlineKeyboardButton(favorite_label, callback_data=f"rc:chat:fav:{index}")],
        [InlineKeyboardButton("Rename locally", callback_data=f"rc:chat:rename:{index}")],
        [InlineKeyboardButton("Remove from RelChat", callback_data=f"rc:chat:remove:{index}")],
        [InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:chats")],
    ]
    return InlineKeyboardMarkup(rows)


def chat_home_keyboard(chat: dict, *, has_report: bool, running: bool = False, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    rows.extend(primary_chat_home_actions(has_report=has_report, running=running, language=language))
    rows.extend(secondary_chat_home_actions(language=language))
    rows.extend(utility_chat_home_actions(language=language))
    rows.append(
        [
            InlineKeyboardButton(t(language, "button_back"), callback_data="rc:home:back"),
            InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN),
        ]
    )
    return InlineKeyboardMarkup(rows)


def primary_chat_home_actions(*, has_report: bool, running: bool, language: str):
    from telegram import InlineKeyboardButton

    if running:
        return [[InlineKeyboardButton(t(language, "main_running"), callback_data="rc:noop")]]
    label = t(language, "button_update_analysis") if has_report else t(language, "button_run_analysis")
    return [[InlineKeyboardButton(f"▶ {label}", callback_data="rc:home:run")]]


def secondary_chat_home_actions(*, language: str):
    from telegram import InlineKeyboardButton

    return [
        [
            InlineKeyboardButton(t(language, "button_timeline"), callback_data="rc:home:sec:timeline"),
            InlineKeyboardButton(t(language, "button_activity"), callback_data="rc:home:sec:activity"),
        ],
        [
            InlineKeyboardButton(t(language, "button_insights"), callback_data="rc:home:sec:overview"),
            InlineKeyboardButton(t(language, "button_followups"), callback_data="rc:home:sec:followups"),
        ],
    ]


def utility_chat_home_actions(*, language: str):
    from telegram import InlineKeyboardButton

    return [
        [
            InlineKeyboardButton(t(language, "button_chat_reports_short"), callback_data="rc:home:sec:reports"),
            InlineKeyboardButton(t(language, "button_chat_settings"), callback_data="rc:home:sec:settings"),
        ],
        [InlineKeyboardButton(t(language, "button_delete_local_data"), callback_data="rc:set:data")],
    ]


def chat_home_section_keyboard(chat: dict, *, language: str = "en", section: str | None = None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    if section == "overview":
        rows.append([InlineKeyboardButton(t(language, "button_details"), callback_data="rc:home:details")])
    rows.append(
        [
            InlineKeyboardButton(t(language, "button_back"), callback_data="rc:home:open"),
            InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN),
        ]
    )
    return InlineKeyboardMarkup(rows)


def chat_home_reports_keyboard(reports: Sequence[dict], *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for index, report in enumerate(reports[:10]):
        rows.append([InlineKeyboardButton(report_button_label(report), callback_data=f"rc:home:report:{index}")])
    rows.append(
        [
            InlineKeyboardButton(t(language, "button_back"), callback_data="rc:home:open"),
            InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN),
        ]
    )
    return InlineKeyboardMarkup(rows)


def timeline_summary_keyboard(*, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(language, "button_browse_timeline"), callback_data="rc:tl:page:0")],
            [InlineKeyboardButton(t(language, "button_timeline_chart"), callback_data="rc:tl:chart")],
            [
                InlineKeyboardButton(t(language, "button_chat_home"), callback_data="rc:home:open"),
                InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN),
            ],
        ]
    )


def timeline_page_keyboard(
    *,
    filter_id: str,
    page: int,
    has_newer: bool,
    has_older: bool,
    language: str = "en",
):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [
            InlineKeyboardButton(timeline_filter_button("all", filter_id, language), callback_data="rc:tl:filter:all"),
            InlineKeyboardButton(timeline_filter_button("activity", filter_id, language), callback_data="rc:tl:filter:activity"),
            InlineKeyboardButton(timeline_filter_button("questions", filter_id, language), callback_data="rc:tl:filter:questions"),
        ],
        [
            InlineKeyboardButton(timeline_filter_button("plans", filter_id, language), callback_data="rc:tl:filter:plans"),
            InlineKeyboardButton(timeline_filter_button("followups", filter_id, language), callback_data="rc:tl:filter:followups"),
            InlineKeyboardButton(timeline_filter_button("silences", filter_id, language), callback_data="rc:tl:filter:silences"),
        ],
    ]
    navigation = []
    if has_newer:
        navigation.append(InlineKeyboardButton(t(language, "button_newer"), callback_data=f"rc:tl:page:{max(0, page - 1)}"))
    if has_older:
        navigation.append(InlineKeyboardButton(t(language, "button_older"), callback_data=f"rc:tl:page:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(t(language, "button_timeline_chart"), callback_data="rc:tl:chart")])
    rows.append(
        [
            InlineKeyboardButton(t(language, "button_back"), callback_data="rc:home:sec:timeline"),
            InlineKeyboardButton(t(language, "button_chat_home"), callback_data="rc:home:open"),
        ]
    )
    rows.append([InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)])
    return InlineKeyboardMarkup(rows)


def timeline_filter_button(filter_id: str, selected_filter: str, language: str) -> str:
    label = {
        "all": t(language, "timeline_filter_all"),
        "activity": t(language, "timeline_filter_activity"),
        "questions": t(language, "timeline_filter_questions"),
        "plans": t(language, "timeline_filter_plans"),
        "followups": t(language, "timeline_filter_followups"),
        "silences": t(language, "timeline_filter_silences"),
    }.get(filter_id, filter_id)
    return f"{t(language, 'selected_prefix')} {label}" if filter_id == selected_filter else label


def remove_chat_confirmation_keyboard(index: int, *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Remove local data", callback_data=f"rc:chat:remove_confirm:{index}")],
            [InlineKeyboardButton(t(language, "button_cancel"), callback_data=f"rc:chat:item:{index}")],
        ]
    )


def category_keyboard(folders: Sequence[DialogFolder] = (), *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [InlineKeyboardButton("All chats", callback_data="rc:browse:cat:all")],
        [
            InlineKeyboardButton("Person", callback_data="rc:browse:cat:private"),
            InlineKeyboardButton("Group", callback_data="rc:browse:cat:groups"),
        ],
        [
            InlineKeyboardButton("Channel", callback_data="rc:browse:cat:channels"),
            InlineKeyboardButton("Unread", callback_data="rc:browse:cat:unread"),
        ],
        [
            InlineKeyboardButton("Favorites", callback_data="rc:browse:cat:favorites"),
            InlineKeyboardButton("Recently analyzed", callback_data="rc:browse:cat:recent"),
        ],
    ]
    for folder in folders:
        rows.append(
            [
                InlineKeyboardButton(
                    clip_text(sanitize_label(folder.title, fallback=f"Folder {folder.folder_id}"), 40),
                    callback_data=f"rc:browse:folder:{folder.folder_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("Search", callback_data="rc:browse:search"),
            InlineKeyboardButton(t(language, "button_cancel"), callback_data=CB_CANCEL),
        ]
    )
    return InlineKeyboardMarkup(rows)


def chat_list_keyboard(
    conversations: Sequence[ConversationRef],
    *,
    page: int,
    page_size: int,
    has_previous: bool,
    has_next: bool,
    selected_chat_id: str | None = None,
    language: str = "en",
):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    page_start = page * page_size
    for index, conversation in enumerate(conversations, start=page_start):
        rows.append(
            [
                InlineKeyboardButton(
                    chat_button_label(conversation, index=index, selected=conversation.conversation_id == selected_chat_id),
                    callback_data=f"rc:browse:select:{index}",
                )
            ]
        )
    navigation = []
    if has_previous:
        navigation.append(InlineKeyboardButton("Previous", callback_data="rc:browse:page:previous"))
    if has_next:
        navigation.append(InlineKeyboardButton("Next", callback_data="rc:browse:page:next"))
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton("Search", callback_data="rc:browse:search"),
            InlineKeyboardButton(t(language, "button_back"), callback_data="rc:browse:back:categories"),
        ]
    )
    rows.append([InlineKeyboardButton(t(language, "button_cancel"), callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(rows)


def search_prompt_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(language, "button_back"), callback_data="rc:browse:back:list")],
            [InlineKeyboardButton(t(language, "button_cancel"), callback_data=CB_CANCEL)],
        ]
    )


def period_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [[InlineKeyboardButton(option.label, callback_data=f"rc:analysis:period:{option.period_id}")] for option in PERIOD_OPTIONS]
    rows.append([InlineKeyboardButton(t(language, "button_back"), callback_data="rc:browse:back:list")])
    rows.append([InlineKeyboardButton(t(language, "button_cancel"), callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(rows)


def custom_end_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("No end date", callback_data="rc:analysis:custom_end:none")],
            [InlineKeyboardButton(t(language, "button_cancel"), callback_data=CB_CANCEL)],
        ]
    )


def module_keyboard(selected: Sequence[str], *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    selected_set = set(selected)
    rows = []
    for module in ANALYSIS_MODULES:
        if module.coming_soon:
            label = f"{module.label} (Coming soon)"
            callback_data = "rc:noop"
        else:
            mark = "Selected" if module.module_id in selected_set else "Not selected"
            label = f"{mark}: {module.label}"
            callback_data = f"rc:analysis:module:{module.module_id}"
        rows.append([InlineKeyboardButton(label, callback_data=callback_data)])
    rows.append(
        [
            InlineKeyboardButton("Select all", callback_data="rc:analysis:modules:all"),
            InlineKeyboardButton("Clear all", callback_data="rc:analysis:modules:clear"),
        ]
    )
    rows.append([InlineKeyboardButton("Continue", callback_data="rc:analysis:modules:continue")])
    rows.append([InlineKeyboardButton(t(language, "button_cancel"), callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(rows)


def review_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Start analysis", callback_data="rc:analysis:start")],
            [
                InlineKeyboardButton(t(language, "button_back"), callback_data="rc:analysis:back:modules"),
                InlineKeyboardButton(t(language, "button_cancel"), callback_data=CB_CANCEL),
            ],
        ]
    )


def job_progress_keyboard(job_id: str, *, can_cancel: bool = True, failed: bool = False, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    if can_cancel:
        rows.append([InlineKeyboardButton("Cancel analysis", callback_data=f"rc:job:cancel:{job_id}")])
    if failed:
        rows.append([InlineKeyboardButton(t(language, "button_retry"), callback_data=f"rc:job:retry:{job_id}")])
    rows.append([InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)])
    return InlineKeyboardMarkup(rows)


def reports_home_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Latest reports", callback_data="rc:reports:list:latest")],
            [InlineKeyboardButton("Reports by chat", callback_data="rc:reports:list:by_chat")],
            [InlineKeyboardButton("Favorite reports", callback_data="rc:reports:list:favorites")],
            [InlineKeyboardButton("Failed analyses", callback_data="rc:reports:list:failed")],
            [InlineKeyboardButton("Clear report history", callback_data="rc:reports:clear")],
            [InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)],
        ]
    )


def report_list_keyboard(reports: Sequence[dict], *, prefix: str = "rc:rep:open", language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for report in reports:
        rows.append(
            [
                InlineKeyboardButton(
                    report_button_label(report),
                    callback_data=f"{prefix}:{report['report_id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:reports")])
    return InlineKeyboardMarkup(rows)


def report_sections_keyboard(report: dict, *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    report_id = report["report_id"]
    fav_label = "Unfavorite" if report.get("is_favorite") else "Favorite"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Overview", callback_data=f"rc:rep:sec:{report_id}:overview"),
                InlineKeyboardButton("Balance", callback_data=f"rc:rep:sec:{report_id}:balance"),
            ],
            [
                InlineKeyboardButton("Activity", callback_data=f"rc:rep:sec:{report_id}:activity"),
                InlineKeyboardButton("Response patterns", callback_data=f"rc:rep:sec:{report_id}:response"),
            ],
            [
                InlineKeyboardButton("Questions", callback_data=f"rc:rep:sec:{report_id}:questions"),
                InlineKeyboardButton("Plans and follow-ups", callback_data=f"rc:rep:sec:{report_id}:plans"),
            ],
            [
                InlineKeyboardButton("Reminders", callback_data=f"rc:rep:sec:{report_id}:reminders"),
                InlineKeyboardButton("Data quality", callback_data=f"rc:rep:sec:{report_id}:quality"),
            ],
            [
                InlineKeyboardButton("Run again", callback_data=f"rc:rep:again:{report_id}"),
                InlineKeyboardButton(fav_label, callback_data=f"rc:rep:fav:{report_id}"),
            ],
            [InlineKeyboardButton("Delete local report", callback_data=f"rc:rep:delete:{report_id}")],
            [InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:reports")],
        ]
    )


def delete_report_confirmation_keyboard(report_id: str, *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Delete local report", callback_data=f"rc:rep:delete_confirm:{report_id}")],
            [InlineKeyboardButton(t(language, "button_cancel"), callback_data=f"rc:rep:open:{report_id}")],
        ]
    )


def reminders_home_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Suggested", callback_data="rc:rem:list:suggested")],
            [InlineKeyboardButton("Confirmed", callback_data="rc:rem:list:confirmed")],
            [InlineKeyboardButton("Completed", callback_data="rc:rem:list:completed")],
            [InlineKeyboardButton("Dismissed", callback_data="rc:rem:list:dismissed")],
            [InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)],
        ]
    )


def reminder_list_keyboard(reminders: Sequence[dict], *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for reminder in reminders:
        rows.append(
            [
                InlineKeyboardButton(
                    reminder_button_label(reminder),
                    callback_data=f"rc:rem:open:{reminder['reminder_id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:reminders")])
    return InlineKeyboardMarkup(rows)


def reminder_actions_keyboard(reminder: dict, *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    reminder_id = reminder["reminder_id"]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm", callback_data=f"rc:rem:status:{reminder_id}:confirmed"),
                InlineKeyboardButton("Dismiss", callback_data=f"rc:rem:status:{reminder_id}:dismissed"),
            ],
            [
                InlineKeyboardButton("Edit date/time", callback_data=f"rc:rem:edit:{reminder_id}"),
                InlineKeyboardButton("Mark completed", callback_data=f"rc:rem:status:{reminder_id}:completed"),
            ],
            [InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:reminders")],
        ]
    )


def settings_keyboard(settings: dict, *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    progress = "On" if settings.get("progress_notifications") else "Off"
    tech = "On" if settings.get("show_technical_details") else "Off"
    confirm = "On" if settings.get("confirm_before_delete") else "Off"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Language", callback_data="rc:set:language")],
            [InlineKeyboardButton("Default import period", callback_data="rc:set:period")],
            [InlineKeyboardButton("Default analysis modules", callback_data="rc:set:modules")],
            [InlineKeyboardButton(f"Progress notifications: {progress}", callback_data="rc:set:toggle:progress_notifications")],
            [InlineKeyboardButton(f"Show technical details: {tech}", callback_data="rc:set:toggle:show_technical_details")],
            [InlineKeyboardButton("Data retention period", callback_data="rc:set:retention")],
            [InlineKeyboardButton(f"Confirm before deleting: {confirm}", callback_data="rc:set:toggle:confirm_before_delete")],
            [InlineKeyboardButton("Reset onboarding", callback_data="rc:set:reset_onboarding")],
            [InlineKeyboardButton("Local data management", callback_data="rc:set:data")],
            [InlineKeyboardButton(t(language, "button_main"), callback_data=CB_MAIN)],
        ]
    )


def language_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [[InlineKeyboardButton(label, callback_data=f"rc:set:language:{code}")] for code, label in LANGUAGES.items()]
    rows.append([InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:settings")])
    return InlineKeyboardMarkup(rows)


def settings_period_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [[InlineKeyboardButton(option.label, callback_data=f"rc:set:period:{option.period_id}")] for option in PERIOD_OPTIONS if not option.custom]
    rows.append([InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:settings")])
    return InlineKeyboardMarkup(rows)


def data_management_keyboard(language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Show local storage summary", callback_data="rc:data:summary")],
            [InlineKeyboardButton("Delete imported data for one chat", callback_data="rc:data:delete_chat")],
            [InlineKeyboardButton("Delete report history", callback_data="rc:data:delete_reports")],
            [InlineKeyboardButton("Delete reminders", callback_data="rc:data:delete_reminders")],
            [InlineKeyboardButton("Delete all local RelChat user data", callback_data="rc:data:delete_all")],
            [InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:settings")],
        ]
    )


def destructive_confirmation_keyboard(action: str, *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Confirm local deletion", callback_data=f"rc:data:confirm:{action}")],
            [InlineKeyboardButton(t(language, "button_cancel"), callback_data="rc:set:data")],
        ]
    )


def module_settings_keyboard(selected: Sequence[str], *, language: str = "en"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    selected_set = set(selected)
    rows = []
    for module in ANALYSIS_MODULES:
        if module.coming_soon:
            rows.append([InlineKeyboardButton(f"{module.label} (Coming soon)", callback_data="rc:noop")])
            continue
        mark = "Selected" if module.module_id in selected_set else "Not selected"
        rows.append([InlineKeyboardButton(f"{mark}: {module.label}", callback_data=f"rc:set:module:{module.module_id}")])
    rows.append(
        [
            InlineKeyboardButton("Select all", callback_data="rc:set:modules:all"),
            InlineKeyboardButton("Clear all", callback_data="rc:set:modules:clear"),
        ]
    )
    rows.append([InlineKeyboardButton("Save", callback_data="rc:set:modules:save")])
    rows.append([InlineKeyboardButton(t(language, "button_back"), callback_data="rc:nav:settings")])
    return InlineKeyboardMarkup(rows)


def chat_button_label(conversation: ConversationRef, *, index: int, selected: bool = False) -> str:
    title = sanitize_label(conversation.title, fallback="untitled", limit=44)
    type_label = type_indicator(conversation.conversation_type)
    prefix = "Selected: " if selected else ""
    if type_label:
        return f"{index + 1}. {prefix}{type_label} {title}"
    return f"{index + 1}. {prefix}{title}"


def type_indicator(conversation_type: str | None) -> str:
    return {
        "one_to_one": "Person",
        "group": "Group",
        "channel": "Channel",
    }.get(conversation_type or "", "")


def chat_row_label_from_dict(chat: dict, *, index: int) -> str:
    title = sanitize_label(chat.get("title"), fallback="untitled", limit=44)
    favorite = "Favorite: " if chat.get("is_favorite") else ""
    return f"{index + 1}. {favorite}{type_indicator(chat.get('chat_type'))} {title}".strip()


def report_button_label(report: dict) -> str:
    title = sanitize_label(report.get("chat_title"), fallback="untitled", limit=34)
    period = sanitize_label(report.get("period_label"), fallback="period", limit=20)
    count = int(report.get("imported_message_count") or 0)
    return f"{title} - {period}, {count} messages"


def reminder_button_label(reminder: dict) -> str:
    title = sanitize_label(reminder.get("title"), fallback="Reminder", limit=44)
    when = sanitize_label(reminder.get("reminder_time"), fallback="no date", limit=18)
    return f"{title} - {when}"


# Compatibility aliases used by older tests and developer command paths.
def main_menu_keyboard():
    return main_keyboard()


def confirmation_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Start analysis", callback_data="rc:analysis:start")],
            [InlineKeyboardButton("Cancel", callback_data=CB_CANCEL)],
        ]
    )
