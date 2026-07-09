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

- Add Bot Interface v0 as a restricted Telegram user interface.
- Show setup status and local-first privacy expectations.
- Keep MTProto login in the local CLI for now without exposing secrets in logs.
- Refuse bot startup unless allowed Telegram user IDs are configured.

## Phase 3: Chat Selection Through Bot

- Show available chats in the private bot chat.
- Import selected chats through explicit `/import <chat_id>` commands.
- Persist selected chat metadata locally.
- Make imports explicit and reversible.

## Phase 4: Reports Inside Bot

- Run local metrics and Event Engine v0 summaries from normalized domain objects and send compact summaries through the bot.
- Avoid message text in bot reports.
- Keep report generation local-first.

## Phase 5: Reminders And Live Updates

- Add optional reminders and live update processing.
- Require explicit opt-in for background behavior.
- Document storage, retention, and notification behavior.

## Phase 6: Dashboard / Web UI Optional

- Consider a local dashboard only after the Telegram bot workflow is stable.
- Keep any web UI local by default.
- Do not add hosted sync without a separate security and privacy review.
