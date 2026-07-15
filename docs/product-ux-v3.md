# Product UX v3

RelChat is a local-first Telegram communication analytics assistant. Product UX
v3 keeps the Telegram Bot as the normal user interface, but organizes the
experience around people and chats instead of developer commands, database
concepts, importer details, or analytics internals.

This document is a product UX and information architecture specification. It
does not define new backend architecture, new storage schema, or new analytics
features.

## UX Principles

- Chat-first, report-aware: the main experience should start from a selected
  person or chat, with reports as history and evidence.
- Observable behavior only: every insight must be grounded in message timing,
  counts, sessions, detected questions, plans, promises, follow-ups, and other
  explicit communication events.
- No hidden-mind claims: RelChat must not claim to know feelings, intentions,
  attraction, attachment style, manipulation, personality type, or diagnoses.
- No manipulation mechanics: avoid features framed as "make them reply",
  "make them chase", pickup tactics, pressure tactics, or emotional leverage.
- Confidence is part of the answer: data completeness, period coverage, message
  count, enabled modules, and confidence should be visible near every summary.
- No fake precision: use ranges and cautious language. Prefer "usually within
  a few hours" over exact-looking predictions when the data is limited.
- No raw message text by default: normal screens should show aggregates,
  metadata, and event categories. Evidence snippets can be a future explicit
  opt-in, not the default.
- Telegram-friendly screens: one readable message per screen, compact inline
  keyboards, shallow navigation, and clear Back/Main paths.
- Private by design: do not show raw Telegram chat IDs, secrets, phone numbers,
  session details, API hashes, tokens, or raw message history in normal UI or
  callback data.
- Developer commands are secondary: normal users should not need `/status`,
  `/chats`, `/import`, `/metrics`, or `/events`.

## Product Navigation Model

RelChat should use a hybrid model centered on the selected person/chat.

Primary object:

- Private chat: "Person"
- Group: "Group"
- Channel: "Channel"

Primary workflow:

```text
Main menu
  -> choose or resume a chat
  -> chat/person home
  -> run or open analysis
  -> explore report sections
  -> confirm follow-ups/reminders
```

Why this model:

- Users think in terms of "Alice", "Project group", or "News channel", not
  "analysis jobs" or "reports".
- The most valuable screen is a current state for one relationship or chat.
- Reports remain important as the durable evidence/history behind the chat
  home screen.
- Feature modules should be entry points inside a selected chat, not the main
  navigation structure.

Reports remain a top-level action because users need history, failed analyses,
favorites, and run-again behavior across chats.

## Main Menu

The main menu should have at most six primary actions:

1. Analyze a chat
2. My chats
3. Reports
4. Follow-ups
5. Settings
6. Help

Main message summary:

- Telegram connected or not connected
- Saved chats count
- Reports count
- Active analysis status
- Pending follow-ups/reminders count

Do not show:

- MTProto
- Telethon
- database path
- API credentials
- session filename
- raw Telegram IDs

Recommended copy:

```text
RelChat

Telegram connected
Saved chats: 4
Reports: 12
Follow-ups: 3 pending
No analysis running
```

Buttons:

```text
[Analyze a chat]
[My chats] [Reports]
[Follow-ups] [Settings]
[Help]
```

## Chat And Person Home

The chat home is the main product screen after a user selects a private chat.
It should answer four questions immediately:

- What is happening now?
- What changed recently?
- What needs attention?
- Where can I explore more?

### Private Chat Home

Purpose:

- Give a compact, current communication snapshot for one person.
- Let the user run a fresh analysis or open the latest report.
- Surface follow-ups without making psychological claims.

Title:

```text
Alice
```

Information shown:

- Current state:
  - latest analyzed period
  - message count
  - data completeness and confidence
  - recent activity trend
- What changed recently:
  - activity up/down/stable
  - response rhythm faster/slower/stable
  - initiation split changed or stable
- Needs attention:
  - unresolved questions
  - promised follow-ups
  - plans with no confirmed next step
  - suggested reminders awaiting confirmation
- Explore:
  - latest report
  - timeline
  - habits
  - follow-ups

Recommended copy:

```text
Alice

Current snapshot
Conversation was active in the last 30 days.
Both people contributed regularly.
Replies were usually fast while the conversation was active.

Changed recently
Activity is slightly lower than the previous period.
Initiation split looks similar to before.

Needs attention
2 questions may still need a response.
1 follow-up candidate is waiting for confirmation.

Data quality
30 days analyzed, 482 messages, medium confidence.
```

Buttons:

```text
[Analyze again]
[Latest report] [Timeline]
[Follow-ups] [Habits]
[Favorite] [Rename]
[Back] [Main menu]
```

Empty state:

```text
Alice

No analysis yet.
Run an analysis to create a snapshot, report, timeline, and follow-up list.
```

Buttons:

```text
[Run analysis]
[Back] [Main menu]
```

Loading state:

```text
Loading chat summary...
```

Error state:

```text
This chat summary is not available right now.
You can retry, run a new analysis, or return to My chats.
```

Buttons:

```text
[Retry]
[Run analysis]
[Back] [Main menu]
```

Message behavior:

- Edit current message when navigating from My chats or a report.
- Send a new message only when opening from a command or after a completed
  background job if the original progress message is no longer editable.

## Group And Channel Behavior

Private chats, groups, and channels should share the same shell but differ in
labels, modules, and interpretation.

### Private Chats

Primary framing:

- Person
- Conversation
- Reply rhythm
- Initiation split
- Follow-ups
- Plans and promises

Useful modules:

- Snapshot
- Timeline
- Balance
- Response rhythm
- Follow-ups
- Habits
- Activity

Avoid:

- Relationship diagnosis
- intent claims
- emotional scoring

### Groups

Primary framing:

- Group activity
- participant balance
- active periods
- unanswered group questions
- planning and follow-up coordination

Differences:

- "Both people" becomes "Participants".
- Initiation split becomes "Session starts by participant".
- Response rhythm should be aggregate or top-participant based.
- Follow-ups should be framed as group coordination.
- Private-chat habits should become group activity habits.

Buttons:

```text
[Analyze again]
[Latest report] [Activity]
[Questions] [Plans]
[Participants]
[Back] [Main menu]
```

### Channels

Primary framing:

- Publishing activity
- posting rhythm
- quiet periods
- media distribution
- topic insights when available

Differences:

- No response rhythm unless replies/comments are explicitly imported later.
- No initiation balance.
- Questions are published-question candidates, not unanswered interpersonal
  questions.
- Follow-ups are content or event reminders, not reciprocal obligations.

Buttons:

```text
[Analyze again]
[Latest report] [Activity]
[Calendar]
[Media]
[Back] [Main menu]
```

## Navigation Map

Exact screen tree:

```text
Main menu
  Analyze a chat
    Onboarding gate if needed
    Chat browser
      Categories
        All chats
        People
        Groups
        Channels
        Unread
        Favorites
        Recently analyzed
        Telegram folders
      Search results
      Chat selected
        Period selection
          Presets
          Custom date range
        Module selection
        Review
        Job progress
        Report overview

  My chats
    Favorites
      Chat home
    Recently analyzed
      Chat home
    Saved chats
      Chat home
    Browse all chats
      Chat browser

  Reports
    Latest reports
      Report overview
      Report section
    Reports by chat
      Chat report list
      Report overview
      Report section
    Favorite reports
      Report overview
      Report section
    Failed analyses
      Failed job detail
    Clear report history
      Confirmation

  Follow-ups
    Suggested
      Follow-up detail
    Confirmed
      Follow-up detail
    Completed
      Follow-up detail
    Dismissed
      Follow-up detail

  Settings
    Language
    Default period
    Default modules
    Progress notifications
    Technical details
    Data retention
    Delete confirmations
    Reset onboarding
    Local data management
      Storage summary
      Delete one chat's local data
      Delete report history
      Delete reminders
      Delete all local RelChat user data

  Help
    What RelChat can analyze
    Privacy
    Telegram authorization
    Metrics
    What RelChat cannot know
    Troubleshooting
    About
```

Back behavior:

- Back from a detail screen returns to the previous list.
- Back from a report section returns to report overview.
- Back from report overview returns to the report list or chat home that opened
  it.
- Back from chat home returns to the previous chat list.
- Back from module selection returns to period selection.
- Back from review returns to module selection.
- Cancel during analysis setup returns to Main menu and clears temporary wizard
  state.
- Cancel during a running job asks for job cancellation and keeps imported data
  safely.
- Main menu is always available on major screens.

Callback behavior:

- Callback data should use short route names and opaque indexes or local IDs.
- Do not include raw Telegram chat IDs, message text, usernames as secrets,
  phone numbers, tokens, session paths, or API credentials.
- Keep callback data below Telegram's 64-byte limit.

## Screen Specifications

### Main Menu

Purpose:

- Start the main product flow.
- Show local connection and product state at a glance.

Title:

- `RelChat`

Information shown:

- Telegram connection state
- saved chats count
- report count
- active jobs
- pending follow-ups

Inline buttons:

- Analyze a chat
- My chats
- Reports
- Follow-ups
- Settings
- Help

Empty state:

- Same screen with zero counts and a prompt to analyze a chat.

Loading state:

- Not needed unless counts are slow; if needed, show `Loading RelChat...`.

Error state:

- `RelChat is available, but local summary data could not be loaded.`
- Buttons: Retry, Help

Message behavior:

- Edit current message.

### Onboarding

Purpose:

- Explain what RelChat does.
- Explain local Telegram authorization and privacy.
- Confirm readiness.

Title:

- `Welcome to RelChat`

Information shown:

- What RelChat analyzes
- Bot API limitation
- Local account authorization requirement
- Safe warning not to send secrets through the bot

Inline buttons:

- Continue
- Check again
- Continue to RelChat

Empty state:

- Not applicable.

Loading state:

- `Checking local Telegram connection...`

Error state:

- `Telegram is not connected locally yet. Complete local authorization, then check again.`

Message behavior:

- Edit current message.

### Chat Browser

Purpose:

- Let users find a chat without knowing IDs.

Title:

- `Choose a chat`

Information shown:

- current category or folder
- page range
- selected chat indicator if returning from a substep
- empty result message

Inline buttons:

- Chat rows, one per row
- Previous, Next
- Search
- Back
- Cancel

Empty state:

- `No chats found here. Try another section or search.`

Loading state:

- `Loading chats...`

Error state:

- `Could not load chats. Check the local Telegram connection and try again.`
- Buttons: Retry, Cancel

Message behavior:

- Edit current message.

### Chat Home

Purpose:

- Show current state and entry points for a selected chat/person/group/channel.

Title:

- private chat: person display name
- group: group title
- channel: channel title

Information shown:

- latest analyzed period
- short current summary
- recent change summary
- needs attention
- data quality

Inline buttons:

- Analyze again
- Latest report
- Timeline
- Follow-ups
- Habits or Participants
- Favorite or Unfavorite
- Rename
- Back
- Main menu

Empty state:

- `No analysis yet. Run an analysis to create a snapshot.`

Loading state:

- `Loading chat summary...`

Error state:

- `This chat summary is not available right now.`
- Buttons: Retry, Run analysis, Back, Main menu

Message behavior:

- Edit current message.

### Period Selection

Purpose:

- Choose the time range for an analysis.

Title:

- `Choose a time period`

Information shown:

- selected chat title
- chat type
- optional default period

Inline buttons:

- 7 days
- 30 days
- 90 days
- 1 year
- Full history
- Custom date range
- Back
- Cancel

Empty state:

- Not applicable.

Loading state:

- Not needed.

Error state:

- `Choose a chat before selecting a period.`

Message behavior:

- Edit current message.

### Custom Date Range

Purpose:

- Let users enter practical dates without strict technical syntax.

Title:

- `Custom date range`

Information shown:

- selected chat
- accepted examples
- current entered start date when entering end date

Inline buttons:

- No end date
- Cancel

Empty state:

- Not applicable.

Loading state:

- Not needed.

Error state:

- `I could not read that date. Try 2026-07-01, 01.07.2026, 7 days, or 30 days.`

Message behavior:

- Edit current message for prompts.
- User sends date as a text message.
- Bot edits the flow message when possible after receiving input.

### Module Selection

Purpose:

- Let users choose what to calculate and show.

Title:

- `Choose analysis modules`

Information shown:

- selected modules
- Coming soon modules are visible but disabled

Inline buttons:

- Conversation snapshot
- Balance
- Activity
- Response rhythm
- Timeline
- Follow-ups
- Habits
- Data quality
- Topic insights (Coming soon)
- Communication forecast (Experimental or Coming soon)
- Select all
- Clear all
- Continue
- Cancel

Empty state:

- If all cleared: `No modules selected. Select at least one or use Select all.`

Loading state:

- Not needed.

Error state:

- `This module is not available yet.`

Message behavior:

- Edit current message.

### Review Analysis

Purpose:

- Confirm before import/analysis starts.

Title:

- `Review analysis`

Information shown:

- chat title
- period
- enabled modules
- expected privacy behavior
- full-history warning when applicable

Inline buttons:

- Start analysis
- Back
- Cancel

Empty state:

- Not applicable.

Loading state:

- Not needed.

Error state:

- `Choose a chat, period, and at least one module before starting.`

Message behavior:

- Edit current message.

### Job Progress

Purpose:

- Keep the bot responsive while import and analysis run.

Title:

- `Analysis progress`

Information shown:

- status: queued, loading, importing, analyzing, completed, failed, cancelled
- approximate progress
- imported message count
- elapsed time
- selected period

Inline buttons:

- Cancel analysis while running
- Retry after failure
- Main menu

Empty state:

- Not applicable.

Loading state:

- Same screen, status changes over time.

Error state:

- Safe reason label and local error reference.
- No stack traces or message text.

Message behavior:

- Edit current progress message with throttling.
- Send a new message only if editing fails or the original message is gone.

### Reports Home

Purpose:

- Find completed, favorite, by-chat, and failed analyses.

Title:

- `Reports`

Information shown:

- latest report count
- favorite report count
- failed analysis count

Inline buttons:

- Latest reports
- Reports by chat
- Favorite reports
- Failed analyses
- Clear report history
- Main menu

Empty state:

- `No reports yet. Analyze a chat to create the first report.`

Loading state:

- `Loading reports...`

Error state:

- `Reports could not be loaded right now.`

Message behavior:

- Edit current message.

### Report Overview

Purpose:

- Present a completed analysis in one readable summary.

Title:

- `Report overview`

Information shown:

- chat title
- period
- creation time
- messages analyzed
- enabled modules
- top observed facts
- cautious interpretation
- data limitation
- confidence and completeness

Inline buttons:

- Overview
- Balance
- Activity
- Response rhythm
- Timeline
- Follow-ups
- Habits
- Data quality
- Run again
- Favorite or Unfavorite
- Delete local report
- Back

Empty state:

- Not applicable.

Loading state:

- `Opening report...`

Error state:

- `This local report is no longer available.`

Message behavior:

- Edit current message.

### Follow-ups Home

Purpose:

- Manage suggested, confirmed, completed, and dismissed follow-ups/reminders.

Title:

- `Follow-ups`

Information shown:

- suggested count
- confirmed count
- completed count
- dismissed count
- reminder privacy note

Inline buttons:

- Suggested
- Confirmed
- Completed
- Dismissed
- Main menu

Empty state:

- `No follow-ups yet. Future analyses can suggest explicit questions, plans, or promises to review.`

Loading state:

- `Loading follow-ups...`

Error state:

- `Follow-ups could not be loaded right now.`

Message behavior:

- Edit current message.

### Follow-up Detail

Purpose:

- Let users confirm, edit, complete, or dismiss one explicit candidate.

Title:

- follow-up title

Information shown:

- source chat label
- event type
- status
- suggested date/time if known
- confidence/completeness if available

Inline buttons:

- Confirm
- Edit date/time
- Dismiss
- Mark completed
- Back

Empty state:

- Not applicable.

Loading state:

- `Opening follow-up...`

Error state:

- `This follow-up is no longer available.`

Message behavior:

- Edit current message.

### Settings

Purpose:

- Manage personal preferences and local data.

Title:

- `Settings`

Information shown:

- language
- default import period
- default modules
- progress notifications
- technical details visibility
- retention setting
- deletion confirmation setting

Inline buttons:

- Language
- Default period
- Default modules
- Progress notifications on/off
- Technical details on/off
- Data retention
- Confirm before deleting on/off
- Reset onboarding
- Local data management
- Main menu

Empty state:

- Not applicable.

Loading state:

- `Loading settings...`

Error state:

- `Settings could not be loaded right now.`

Message behavior:

- Edit current message.

### Local Data Management

Purpose:

- Let users inspect and delete local RelChat data without affecting Telegram.

Title:

- `Local data management`

Information shown:

- explicit privacy warning:
  - local RelChat data only
  - never Telegram chats
  - never Telegram messages
  - never Telegram account
  - never Telegram session files

Inline buttons:

- Show local storage summary
- Delete imported data for one chat
- Delete report history
- Delete follow-ups/reminders
- Delete all local RelChat user data
- Back

Empty state:

- Storage summary can show zero counts.

Loading state:

- `Loading local storage summary...`

Error state:

- `Local storage summary could not be loaded right now.`

Message behavior:

- Edit current message.

## Report Structure

One completed analysis should be presented as a sectioned report, not a giant
technical text dump.

### Overview

Immediate summary:

- chat title
- period
- messages analyzed
- enabled modules
- current state sentence
- recent trend sentence
- needs attention count
- confidence and completeness

Example language:

- `Both people contributed regularly during this period.`
- `Activity was lower than the previous period.`
- `Three questions may still need a response.`
- `Data completeness is medium because only the selected 30-day period was analyzed.`

### Balance

Show:

- message count split
- sender share
- initiation split
- changes from previous comparable period when available

Avoid:

- "who cares more"
- emotional score
- dominance score

### Activity

Show:

- message activity timeline
- active days
- quiet periods
- media distribution
- calendar-style summary when available

Telegram text view:

- top active days
- quiet periods
- media totals

Mini App or generated image:

- calendar heatmap
- timeline chart

### Response Rhythm

Show:

- normal response window
- active-conversation response rhythm
- trend faster/slower/stable
- unusual silence marker when available

Avoid:

- exact promises of when someone will reply
- anxiety-inducing labels

### Timeline

Show:

- weekly/monthly communication history
- active and quiet periods
- important plans
- questions
- promises
- follow-ups
- changes in rhythm

Telegram text view:

- current month summary
- notable weeks
- top events

Mini App or generated image:

- scrollable timeline
- month/week chart

### Follow-ups

Show:

- unresolved questions
- promises
- plans
- explicit "remind me" events
- confirmed reminders

Actions:

- confirm
- edit date/time
- dismiss
- mark complete

### Habits

Show:

- typical active hours
- active weekdays
- normal response rhythm
- preferred message/media patterns
- recurring communication habits

Avoid:

- personality traits
- emotional judgments

### Data Quality

Show:

- analyzed period
- message count
- modules enabled
- import completeness
- confidence
- known limitations
- last analysis time

## Progressive Disclosure

Immediately visible:

- chat/person current snapshot
- recent trend
- needs attention
- data quality
- primary actions

After one tap:

- report sections
- follow-up lists
- timeline summary
- habits summary
- activity summary
- failed analysis detail

Detailed view only:

- exact per-sender counts
- response-time breakdowns
- weekly/monthly timeline details
- media distribution
- all detected follow-up candidates
- local storage counts
- technical details if the setting is enabled

Never shown by default:

- raw message text
- raw Telegram chat IDs
- session paths
- phone numbers
- API credentials
- bot tokens
- stack traces

## Terminology

| Developer term | English label | Russian label |
|---|---|---|
| Bot UI | RelChat | RelChat |
| ConversationRef | Chat | Чат |
| one_to_one | Person | Человек |
| group | Group | Группа |
| channel | Channel | Канал |
| import | Load messages | Загрузить сообщения |
| analysis job | Analysis | Анализ |
| queued | Waiting | В очереди |
| loading | Loading | Загрузка |
| importing | Loading messages | Загрузка сообщений |
| analyzing | Analyzing | Анализ |
| completed | Completed | Завершено |
| failed | Failed | Ошибка |
| cancelled | Cancelled | Отменено |
| metrics | Insights | Выводы |
| Event Engine v0 | Detected events | Найденные события |
| unanswered_question | Unanswered question | Вопрос без ответа |
| plan_candidate | Possible plan | Возможный план |
| promise_candidate | Possible promise | Возможное обещание |
| follow_up_candidate | Follow-up candidate | Кандидат для уточнения |
| health_candidate | Health mention | Упоминание здоровья |
| long_silence | Quiet period | Тихий период |
| report | Report | Отчет |
| report overview | Overview | Обзор |
| response_times | Response rhythm | Ритм ответов |
| initiation_balance | Session starts | Начало сессий |
| message balance | Contribution balance | Баланс участия |
| data_quality | Data quality | Качество данных |
| confidence | Confidence | Уверенность |
| data completeness | Data completeness | Полнота данных |
| reminders | Follow-ups | Напоминания |
| suggested | Suggested | Предложено |
| confirmed | Confirmed | Подтверждено |
| completed | Completed | Выполнено |
| dismissed | Dismissed | Отклонено |
| Topic analysis | Topic insights (Coming soon) | Темы (скоро) |
| forecast | Communication forecast (Experimental) | Прогноз общения (экспериментально) |
| database | Local storage | Локальное хранилище |
| MTProto session | Telegram connection | Подключение Telegram |
| API credentials | Telegram setup | Настройка Telegram |

## Telegram Bot Vs Mini App Responsibilities

| Capability | Telegram Bot | Mini App | Generated image/chart | Downloadable report | Text-only |
|---|---:|---:|---:|---:|---:|
| Main menu | Yes | Optional | No | No | Yes |
| Onboarding | Yes | Optional | No | No | Yes |
| Chat browser | Yes | Later for large accounts | No | No | Yes |
| Chat/person home | Yes | Later richer dashboard | Optional | No | Yes |
| Analysis wizard | Yes | Optional | No | No | Yes |
| Job progress | Yes | Optional | No | No | Yes |
| Report overview | Yes | Optional | No | Optional | Yes |
| Balance section | Yes | Optional | Optional | Optional | Yes |
| Activity timeline | Limited | Yes | Yes | Optional | Partial |
| Calendar heatmap | Uncomfortable | Yes | Yes | Optional | No |
| Relationship timeline | Limited summary | Yes | Yes | Optional | Partial |
| Follow-up management | Yes | Optional | No | No | Yes |
| Habits summary | Yes | Optional | Optional | Optional | Yes |
| Topic insights | Coming soon | Later | Optional | Optional | Partial |
| Communication forecast | Experimental later | Later | Optional | Optional | Partial |
| Local data management | Yes | Optional | No | No | Yes |
| Full long report | Limited sections | Optional | Optional | Yes | Partial |

Telegram Bot should remain the control surface. Mini App should be considered
for visual density, timelines, calendars, comparisons, and large report
exploration.

## Telegram Limitations

Uncomfortable in Telegram Bot:

- dense timelines
- calendar heatmaps
- multi-series charts
- comparing many months
- large participant lists in groups
- exploring repeated topics
- long report reading
- interactive filters
- side-by-side period comparison

Better as Telegram Mini App:

- Relationship Timeline
- Activity Analytics dashboard
- People Insights dashboard
- topic exploration
- multi-period comparisons

Better as generated image/chart:

- weekly/monthly activity timeline
- calendar-style activity heatmap
- response-time trend chart
- media distribution chart

Better as downloadable report:

- full long-form report
- monthly archive
- export for personal notes

Remain text-only in bot:

- current snapshot
- follow-up list
- report overview
- data quality
- settings
- local data confirmations

## Recommended Staged Implementation

Each stage should remain independently usable.

### Stage 1: Navigation Rename And Chat Home Shell

Goal:

- Move normal UX toward chat-centered navigation without new analytics.

Scope:

- Main menu wording: Follow-ups instead of Reminders if chosen.
- Add chat home shell using latest existing report metadata.
- Add private/group/channel label variants.
- Keep existing report sections.

Usable outcome:

- Users can pick a chat and land on a readable home screen.

### Stage 2: Snapshot From Existing Metrics

Goal:

- Build Conversation Snapshot using already available metrics and events.

Scope:

- current communication state
- initiation split
- response rhythm summary
- unresolved questions count
- follow-up count
- data quality block

No new analytics required:

- Use existing metrics and Event Engine v0.

Usable outcome:

- Private chat home answers "what is happening now" from existing reports.

### Stage 3: Report IA Refresh

Goal:

- Reorganize report sections into user-facing names.

Scope:

- Overview
- Balance
- Activity
- Response rhythm
- Follow-ups
- Data quality
- Timeline placeholder
- Habits placeholder

Usable outcome:

- Reports become easier to read and future-ready.

### Stage 4: Follow-ups UX Consolidation

Goal:

- Make follow-ups the normal wording and keep reminders as a status/action.

Scope:

- Suggested, confirmed, completed, dismissed
- confirm/edit/dismiss/complete
- show source report and data quality

Usable outcome:

- Users can manage explicit follow-up candidates without extra analytics.

### Stage 5: Timeline Summary

Goal:

- Add text-first Relationship Timeline from existing message timestamps and
  events.

Scope:

- weekly/monthly summaries
- active and quiet periods
- plans/questions/promises/follow-ups by period
- change language without fake precision

Usable outcome:

- Timeline section works in Telegram text, with chart-ready data later.

### Stage 6: Habits Summary

Goal:

- Add People Insights from observable behavior.

Scope:

- typical active hours
- active weekdays
- response rhythm
- message/media patterns
- recurring communication habits

Usable outcome:

- Habits section helps users understand normal patterns without psychology.

### Stage 7: Visual Artifacts

Goal:

- Improve dense analytics without forcing them into Telegram messages.

Scope:

- generated activity charts
- timeline images
- downloadable report option

Usable outcome:

- Telegram remains usable while visual insights become clearer.

### Stage 8: Mini App Exploration

Goal:

- Move high-density exploration to a richer interface if needed.

Scope:

- calendar heatmap
- scrollable relationship timeline
- multi-period comparisons
- topic exploration when available

Usable outcome:

- Bot remains the command and notification surface; Mini App handles dense
  exploration.

## Features Intentionally Marked Coming Soon

Topic Insights:

- warm topics
- neutral topics
- topics handled carefully
- repeated topics
- topic continuation

Status:

- Coming soon.
- Must not run fake topic analysis.
- Must not infer emotions or hidden meanings.

Communication Forecast:

- likely active time
- expected response window
- unusual silence detection

Status:

- Experimental or Coming soon.
- Must show confidence and data completeness.
- Must avoid exact predictions or anxiety-inducing claims.
- Must be framed as observed-pattern estimation, not certainty.

Evidence snippets:

- Not default.
- Future explicit opt-in only.
- Must avoid exposing raw private chat history through normal bot reports.

Mini App dashboards:

- Future optional interface.
- Bot remains the primary control surface until Telegram text UX becomes the
  limiting factor.
