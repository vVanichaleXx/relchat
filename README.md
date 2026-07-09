# RelChat

RelChat is a privacy-first conversation intelligence platform.

Telegram is the first supported source. The architecture is designed so future importers can support WhatsApp, Signal, Discord, Messenger, JSON exports, TXT exports, email, and other sources without tying the core product logic to Telegram.

The current codebase is a local CLI foundation. It uses Telethon / MTProto to access Telegram only after the user authorizes their own Telegram account, imports selected chats into a local SQLite database, and computes basic conversation metrics over normalized domain objects.

The product direction is a private Telegram bot experience where each user interacts with their own bot chat to connect an account, choose chats, import messages, run analysis, and receive reports. Full bot logic is intentionally not implemented yet.

## Privacy Baseline

- Local-first by default: data stays on the user's machine.
- Only user-selected chats should be imported.
- Telegram sessions, SQLite databases, exports, logs, and `.env` files must never be committed.
- Raw Telegram payload storage is disabled in the MVP.
- The CLI does not print message text by default. Use `--show-text` only when you explicitly want local text snippets in the terminal.
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
- `relchat/bot`: future bot interface boundary
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

## Local CLI Commands

Initialize local SQLite:

```bash
python3 -m relchat db init
```

Log in with Telegram Client API / MTProto:

```bash
python3 -m relchat auth login --phone +1234567890
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
