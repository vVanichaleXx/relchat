# Roadmap

## Phase 0: Architecture Foundation

- Keep Telegram as the first importer, not a core dependency.
- Normalize platform messages before storage, analytics, reports, memory, or future AI.
- Maintain explicit module boundaries for integrations, storage, events, memory, analytics, reports, bot, CLI, and utilities.
- Keep the project runnable while avoiding new product features.

## Phase 1: Local CLI Import, Events, And Metrics

- Keep the local CLI working.
- Import selected Telegram chats through Telethon / MTProto.
- Store normalized messages locally in SQLite.
- Extract deterministic Event Engine v0 events from normalized messages only.
- Compute basic metrics from normalized domain objects without AI analysis.
- Keep sessions, databases, exports, and logs out of git.

## Phase 2: Telegram Bot Setup Assistant

- Add a Telegram bot as the user-facing setup surface.
- Guide users through privacy expectations and local-first storage.
- Help users provide Telegram API credentials when needed.
- Guide MTProto login without exposing secrets in logs.

## Phase 3: Chat Selection Through Bot

- Show available chats in the private bot chat.
- Let users select chats for import.
- Persist selected chat metadata locally.
- Make imports explicit and reversible.

## Phase 4: Reports Inside Bot

- Run local metrics from normalized domain objects and send reports back through the bot.
- Avoid message text in reports unless explicitly requested.
- Keep report generation local-first.

## Phase 5: Reminders And Live Updates

- Add optional reminders and live update processing.
- Require explicit opt-in for background behavior.
- Document storage, retention, and notification behavior.

## Phase 6: Dashboard / Web UI Optional

- Consider a local dashboard only after the Telegram bot workflow is stable.
- Keep any web UI local by default.
- Do not add hosted sync without a separate security and privacy review.
