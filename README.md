# RelChat

RelChat is a privacy-first conversation intelligence platform.

Telegram is the first supported source. The architecture is designed so future importers can support WhatsApp, Signal, Discord, Messenger, JSON exports, TXT exports, email, and other sources without tying the core product logic to Telegram.

The current codebase is a local CLI foundation plus a Telegram Bot interface. It uses Telethon / MTProto to access Telegram only after the user authorizes their own Telegram account, imports selected chats into a local SQLite database, and computes basic conversation metrics over normalized domain objects.

The bot is only a user interface. It does not read private chats through the Bot API. It calls the same local importers, repositories, analytics, and event engine used by the CLI.

## Privacy Baseline

- Local-first by default: data stays on the user's machine.
- Only user-selected chats should be imported.
- Telegram sessions, SQLite databases, exports, logs, and `.env` files must never be committed.
- Raw Telegram payload storage is disabled in the MVP.
- The CLI does not print message text by default. Use `--show-text` only when you explicitly want local text snippets in the terminal.
- The bot refuses to start unless `RELCHAT_ALLOWED_USER_IDS` is configured.
- Bot replies do not include message text, raw payloads, secrets, phone numbers, or session contents.
- No AI analysis, dashboard, web UI, cloud sync, or hosted service is included in this foundation.

Read [SECURITY.md](SECURITY.md) and [PRIVACY.md](PRIVACY.md) before adding features that touch personal data.

## Architecture

RelChat is organized around source-agnostic domain objects:

```text
Telegram -> importer -> normalized messages -> events -> memory -> analytics -> reports -> bot
```

The AI layer, when added later, must never depend directly on Telegram. It should consume normalized messages, extracted events, memory, metrics, or reports.

Current package boundaries:

- `relchat/core`: source-agnostic domain models
- `relchat/telegram`: Telegram client, importer, and normalizer
- `relchat/database`: SQLite schema and repositories
- `relchat/analytics`: metrics over normalized messages
- `relchat/events`: future event extraction boundary
- `relchat/memory`: future memory boundary
- `relchat/reports`: future report boundary
- `relchat/bot`: Telegram Bot interface boundary
- `relchat/cli`: developer/debug CLI
- `relchat/utils`: low-level shared helpers

The Bot API alone cannot read a user's private chat history. A bot can only receive messages sent to the bot, or messages from chats where the bot is present and permitted to receive updates. RelChat therefore needs user-authorized MTProto access for imports.

See [docs/architecture.md](docs/architecture.md) for details.

## Setup

1. Create Telegram API credentials at `https://my.telegram.org/apps`.
2. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

3. Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

4. Fill in:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
```

To run the Telegram Bot interface, also fill in:

```text
TELEGRAM_BOT_TOKEN=
RELCHAT_ALLOWED_USER_IDS=123456789
```

`RELCHAT_ALLOWED_USER_IDS` is a comma-separated list of numeric Telegram user IDs. If it is empty, the bot refuses to start.

## Local CLI Commands

Initialize local SQLite:

```bash
python3 -m relchat db init
```

Log in with Telegram Client API / MTProto:

```bash
python3 -m relchat auth login --phone <phone>
```

List chats:

```bash
python3 -m relchat chats list --limit 50
```

Select a chat:

```bash
python3 -m relchat chats select <chat_id>
```

Import history:

```bash
python3 -m relchat import chat <chat_id> --since 90d --limit 5000
```

Print basic metrics:

```bash
python3 -m relchat metrics summary <chat_id>
```

Print basic source-agnostic events:

```bash
python3 -m relchat events summary <chat_id>
```

Include local message text snippets in unanswered-question output only when explicitly requested:

```bash
python3 -m relchat metrics summary <chat_id> --show-text
```

Event summaries also hide message text by default:

```bash
python3 -m relchat events summary <chat_id> --show-text
```

## Telegram Bot Interface

Run the private bot UI:

```bash
python3 -m relchat bot
```

Equivalent explicit form:

```bash
python3 -m relchat bot run
```

Normal bot flow:

1. Open `/start`.
2. Complete the short onboarding screens.
3. Use the main menu:

```text
Analyze a chat
My chats
Reports
Reminders
Settings
Help
```

The guided analysis flow lets a user browse Telegram folders/categories, search chats, choose a period, choose analysis modules, review settings, and start a background import/analysis job. Reports, saved chats, favorites, settings, job metadata, and reminders are persisted in SQLite across bot restarts.

Developer/debug commands remain available but are no longer required for normal use:

```text
/start
/help
/status
/chats [private|groups|channels] [limit]
/import <chat_id>
/metrics <chat_id>
/events <chat_id>
```

`/import <chat_id>` uses safe defaults: `since=90d` and `limit=5000`. `/chats` defaults to 30 rows and supports examples such as `/chats private 50`, `/chats groups 50`, and `/chats channels 50`.

The bot requires the same local MTProto setup as the CLI. Run `python3 -m relchat auth login --phone <phone>` before using bot features that list or import Telegram conversations. Do not send Telegram login codes, passwords, API hashes, bot tokens, phone numbers, or session files through the bot.

The bot only deletes local RelChat data when asked. It does not delete Telegram chats, Telegram messages, Telegram accounts, or Telegram session files.

## Implemented Metrics

- Message count by sender
- Initiation balance using 12-hour session gaps
- Median response time by responder
- Active-window median response time
- Average text message length
- Unanswered question count

## Implemented Events

- Question
- Unanswered question
- Long silence
- Plan candidate
- Promise candidate
- Health candidate
- Follow-up candidate

## Project Status

This repository is intentionally small. The goal of this extraction is a clean, safe, open-source base for a long-term platform, not a full product.

See [docs/roadmap.md](docs/roadmap.md) for planned phases.
