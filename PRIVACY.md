# Privacy

RelChat is designed to be local-first, source-agnostic, and user-controlled.

## What The MVP Does

- Uses Telethon / MTProto only after the user authorizes their own Telegram account.
- Imports only chats the user selects.
- Normalizes Telegram messages before storage or analytics.
- Stores normalized message rows in a local SQLite database.
- Stores Telegram session files locally.
- Computes basic metrics locally.

## What The MVP Does Not Do

- It does not upload chats to a hosted RelChat service.
- It does not run AI analysis.
- It does not include a dashboard or web server.
- It does not include a web UI.
- It does not include bot logic yet.
- It does not store raw Telegram API payload objects.
- It does not download or store media files.
- It does not print message text in CLI summaries unless `--show-text` is passed.

## Local Storage

By default, local data is stored under:

```text
./data/
```

This directory is ignored by git. It may contain:

- `relchat.sqlite3`: local normalized database
- `telegram.session`: local Telethon authorization session

The current MVP stores normalized message text because Phase 1 metrics use text length and question detection. Future minimization work should make text retention configurable before broader product use.

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
