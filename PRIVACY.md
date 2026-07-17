# Privacy

RelChat is designed to be local-first, source-agnostic, and user-controlled.

## What The MVP Does

- Uses Telethon / MTProto only after the user authorizes their own Telegram account.
- Imports only chats the user selects.
- Normalizes Telegram messages before storage or analytics.
- Stores normalized message rows in a local SQLite database.
- Stores Telegram session files locally.
- Computes basic metrics locally.
- Provides a restricted Telegram Bot interface that calls the same local import, metrics, and event logic.
- Optionally sends minimized selected-message data to OpenAI for AI-enhanced communication analysis, only after explicit bot consent and only when configured by environment variables.
- Lets users mark chats as important and, only when explicitly enabled, monitor those chats for a cautious “appears to have paused” automation heuristic.

## What The MVP Does Not Do

- It does not upload chats to a hosted RelChat service.
- It does not run AI analysis unless `RELCHAT_AI_ENABLED=true`, an OpenAI API key/model are configured, and the user confirms consent in the bot.
- It does not include a dashboard or web server.
- It does not include a web UI.
- It does not use the Bot API to read private Telegram chats.
- It does not expose a public unrestricted bot.
- It does not store raw Telegram API payload objects.
- It does not download or store media files.
- It does not print message text in CLI summaries unless `--show-text` is passed.
- It does not print message text in bot replies.
- It does not send Telegram sessions, API hashes, bot tokens, phone numbers, raw Telethon objects, media files, unrelated chats, debug logs, or full database exports to OpenAI.
- It does not claim to know when a conversation definitely ended.
- It does not monitor normal chats automatically. Automation is limited to important chats with user-level and chat-level switches enabled.

## Local Storage

By default, local data is stored under:

```text
./data/
```

This directory is ignored by git. It may contain:

- `relchat.sqlite3`: local normalized database
- `telegram.session`: local Telethon authorization session

The current MVP stores normalized message text because Phase 1 metrics use text length and question detection. Future minimization work should make text retention configurable before broader product use.

AI analysis records store metadata, score dimensions, validated structured output, coverage, model name, consent version, and safe error state. They do not store a second full copy of raw message text or raw OpenAI requests/responses.

Important-chat automation stores per-user settings, message cursors, completed automatic message ranges, delayed notification metadata, cooldown state, and comparison metadata. It does not duplicate full message transcripts.

## Telegram Bot Interface

Bot Interface v0 is a private UI for local RelChat operations. It can show setup
status, list conversation references, import selected chat history through
Telethon / MTProto, and render basic metrics and Event Engine v0 summaries.

Bot replies are restricted to allowed Telegram user IDs configured in
`RELCHAT_ALLOWED_USER_IDS`. If that list is empty, bot startup refuses. The bot
does not send message text, raw payloads, bot tokens, API hashes, phone numbers,
or session contents.

When a user selects AI-enhanced analysis for the first time, the bot explains
that selected conversation messages are sent to OpenAI and offers local-only
analysis instead. Consent can be revoked in Settings.

UX audit logs record safe interaction metadata such as mode selection,
started/completed/failed state, duration, and usage counts. They must not record
conversation prompts, source messages, API keys, or full private AI analysis
text.

Automatic-analysis audit events may record safe metadata such as important-chat enabled/disabled, automation started, pause candidate detected, notification suppressed with a safe reason, local or AI mode, duration, and message counts. They must not record source message text, AI prompts, full reports, raw provider responses, API keys, sessions, or phone numbers.

## Architectural Privacy Boundary

Telegram-specific code must normalize data before it reaches storage,
analytics, event extraction, memory, reports, or the optional AI layer. Future
source adapters should follow the same rule.

The optional AI layer must never consume Telethon objects, raw Telegram
payloads, Telegram sessions, or raw platform transports directly. It receives
source-agnostic normalized messages, local metrics, and source-agnostic events
after participant anonymization and configured input limits.

## User Control

Users should be able to:

- choose which chats are imported
- delete local databases and sessions
- avoid raw payload and media storage
- review privacy-sensitive behavior before enabling it
- choose local-only analysis instead of AI-enhanced analysis
- revoke AI consent from Settings
- disable automation for a chat, pause it for 24 hours, or disable all automatic analysis

Deleting `data/` removes the local database and Telegram session for the default configuration.
