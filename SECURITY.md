# Security Policy

RelChat handles highly sensitive personal conversation data. Treat every feature as privacy-sensitive by default.

## Core Rules

- Never commit Telegram `.session` files.
- Never commit SQLite databases.
- Never commit personal chat exports.
- Never commit `.env` files, API credentials, bot tokens, phone numbers, or local logs.
- Never log message text by default.
- Do not store raw Telegram API payloads by default.
- Store only normalized data that is needed for the current feature.
- Make privacy-sensitive behavior explicit through CLI flags, configuration, and documentation.
- Keep Telegram-specific transport objects out of analytics, memory, reports, and future AI layers.

## Local Secrets

Telethon sessions grant access to the authorized Telegram account. Keep them local, private, and ignored by git. The MVP stores sessions under `data/` by default and attempts to restrict file permissions.

Telegram sessions should remain separate from normalized message storage. Do not
copy session contents into SQLite, reports, logs, exports, analytics fixtures, or
debug output.

## Sensitive Data Boundaries

Never log by default:

- message text
- raw platform payloads
- media contents or download paths
- API hashes, bot tokens, authorization codes, session contents
- phone numbers and credentials
- database contents, exports, report bodies, memory items

Encryption should be added at the storage adapter boundary when broader product
work begins. Raw payload storage, if ever enabled, should use a separate
encrypted store with explicit opt-in and retention rules.

## Sensitive Features

Any feature that exports data, uploads data, stores raw payloads, sends data to an AI provider, enables live updates, or exposes a web interface must be opt-in and documented before it is merged.

## Reporting Issues

If you find a security or privacy issue, do not include real chat contents, session files, databases, API hashes, or phone numbers in the report. Share a minimal reproduction with synthetic data.
