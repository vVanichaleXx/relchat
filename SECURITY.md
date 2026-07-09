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
- Keep the Telegram Bot API as an interface only. It must not be used to read private chat history.
- Run the bot only with `RELCHAT_ALLOWED_USER_IDS` configured. An empty list must refuse startup.

## Local Secrets

Telethon sessions grant access to the authorized Telegram account. Keep them local, private, and ignored by git. The MVP stores sessions under `data/` by default and attempts to restrict file permissions.

Telegram sessions should remain separate from normalized message storage. Do not
copy session contents into SQLite, reports, logs, exports, analytics fixtures, or
debug output.

Telegram bot tokens are also secrets. Store them in `.env` or the environment,
never in git, issue reports, terminal transcripts, or generated docs.

## Bot Access Control

Bot Interface v0 only responds to configured Telegram user IDs and replies only
in private bot chats. It calls the existing local Telethon importer,
repositories, analytics, and event engine. It must not expose a public bot, raw
Telegram payloads, session contents, phone numbers, or message text.

The Bot API cannot read private Telegram chat history. RelChat imports selected
chats through the local user-authorized MTProto session instead.

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
