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

## What The MVP Does Not Do

- It does not upload chats to a hosted RelChat service.
- It does not run AI analysis.
- It does not include a dashboard or web server.
- It does not include a web UI.
- It does not use the Bot API to read private Telegram chats.
- It does not expose a public unrestricted bot.
- It does not store raw Telegram API payload objects.
- It does not download or store media files.
- It does not print message text in CLI summaries unless `--show-text` is passed.
- It does not print message text in bot replies.

## Local Storage

By default, local data is stored under:

```text
./data/
```

This directory is ignored by git. It may contain:

- `relchat.sqlite3`: local normalized database
- `telegram.session`: local Telethon authorization session

The current MVP stores normalized message text because Phase 1 metrics use text length and question detection. Future minimization work should make text retention configurable before broader product use.

## Telegram Bot Interface

Bot Interface v0 is a private UI for local RelChat operations. It can show setup
status, list conversation references, import selected chat history through
Telethon / MTProto, and render basic metrics and Event Engine v0 summaries.

Bot replies are restricted to allowed Telegram user IDs configured in
`RELCHAT_ALLOWED_USER_IDS`. If that list is empty, bot startup refuses. The bot
does not send message text, raw payloads, bot tokens, API hashes, phone numbers,
or session contents.

## Architectural Privacy Boundary

Telegram-specific code must normalize data before it reaches storage,
analytics, event extraction, memory, reports, or any future AI layer. Future
source adapters should follow the same rule.

The future AI layer must never consume Telethon objects, raw Telegram payloads,
Telegram sessions, or raw platform transports directly.

## User Control

Users should be able to:

- choose which chats are imported
- delete local databases and sessions
- avoid raw payload and media storage
- review privacy-sensitive behavior before enabling it

Deleting `data/` removes the local database and Telegram session for the default configuration.
