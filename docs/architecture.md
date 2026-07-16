# Architecture

RelChat is a privacy-first conversation intelligence platform. Telegram is the
first importer, not the product boundary. The core domain must remain usable by
future importers such as WhatsApp, Signal, Discord, Messenger, JSON exports, TXT
exports, email, and sources that do not exist yet.

The key rule is simple:

```text
platform source -> importer -> normalized messages -> events -> memory -> analytics -> reports -> interfaces
```

The optional AI layer consumes minimized normalized domain objects, extracted
events, local metrics, deterministic dimensions, and reports. It may explain
observable communication patterns, but the final communication score is
calculated locally. It must never read Telethon objects, Telegram payloads,
Telegram sessions, credentials, unrelated chats, media files, or raw
platform-specific transports directly.

## Current Package Map

```text
relchat/
  core/          Source-agnostic domain models and future contracts
  telegram/      Telegram MTProto client, importer, and Telegram normalizer
  database/      SQLite connection, schema, and repositories
  analytics/     Metrics over normalized domain objects
  events/        Rule-based source-agnostic event extraction
  memory/        Future durable memory boundary
  reports/       Future report rendering boundary
  bot/           Telegram Bot user interface boundary
  bot/services/ai_analysis.py
                 Optional OpenAI Responses API composition over normalized data
  cli/           Developer/debug command-line interface
  utils/         Low-level helpers with no product logic
  config.py      Application settings loaded from env and .env
```

## Module Responsibilities

### `core/`

Owns source-agnostic domain concepts. Current code includes the minimal
`ConversationRef`, `Message`, and `ConversationEvent` objects needed to keep the
importer, storage, event extraction, and analytics layers decoupled. Future
domain models belong here only when they are not tied to Telegram, SQLite, a
bot, or a CLI.

`core` should depend only on the Python standard library and other pure domain
code. It should not import `telegram`, `database`, `analytics`, `bot`, or `cli`.

### `telegram/`

Owns Telegram-specific integration code.

- `client.py`: Telethon loading, credential validation, client construction,
  login, and session file permission handling.
- `normalizer.py`: conversion from Telethon entities/messages into normalized
  domain objects.
- `importer.py`: source adapter that lists Telegram conversations and yields
  normalized `Message` objects.

Telegram may depend on core models because adapters point inward. Core code must
not depend on Telegram.

### `database/`

Owns persistent storage.

- `sqlite.py`: SQLite connection setup and schema initialization.
- `repositories.py`: maps normalized domain objects to SQLite rows and maps rows
  back into normalized domain objects.

Storage must not talk to Telethon, parse Telegram payloads, or compute product
metrics. It should persist already-normalized data.

### `analytics/`

Owns metric calculations over normalized messages. Analytics should accept
domain objects and return plain result structures that reports, CLI, bot, and
future APIs can render. It must not load from Telegram or SQLite directly.

### `events/`

Owns source-agnostic conversation event extraction from normalized messages.
Event Engine v0 is a deterministic rule-based extractor in `extractor.py`.

Current event types:

- `question`
- `unanswered_question`
- `long_silence`
- `plan_candidate`
- `promise_candidate`
- `health_candidate`
- `follow_up_candidate`

Candidate events are simple text-pattern signals, not psychological
interpretation. The extractor imports only `relchat.core` models and standard
library modules. It must not import Telegram, SQLite, bot, CLI, AI, or report
code.

### `memory/`

Reserved for durable memory derived from events, user choices, and retention
rules. Memory should be explicit and inspectable; it should not become a hidden
cache of raw messages.

No memory implementation is included yet.

### `reports/`

Reserved for turning metrics, memory, timelines, and events into user-facing
report objects. Reports should not fetch Telegram data directly.

No report implementation is included yet.

### `bot/`

Owns the Telegram Bot interface. The bot is an interface layer only: it handles
commands, access control, compact formatting, and Telegram message chunking. It
calls the existing Telethon importer, SQLite repositories, analytics, and event
engine.

The Bot API must not be treated as a data access layer. It cannot read a user's
private chat history by itself. RelChat imports selected chats through the local
user-authorized Telethon / MTProto session.

Optional AI-enhanced Communication analysis is composed from this layer through
`bot/services/ai_analysis.py`, but the service itself consumes source-agnostic
messages/events and settings. It uses the official OpenAI Responses API only
when enabled by configuration and after persisted user consent. The OpenAI SDK
is optional; bot startup and local deterministic analysis must work without it.
Provider output is structured interpretation only; deterministic dimensions and
the final 0-10 score are calculated locally before persistence/rendering.

### `cli/`

Owns the local command-line surface. The CLI is for setup, development, and
debugging. Long term, users should not need it after initial setup. CLI code may
orchestrate adapters but should stay thin and avoid business logic.

### `utils/`

Owns small helpers that are not product concepts, such as filesystem permission
helpers. Utilities must stay low-level and should not become a dumping ground
for domain or integration logic.

### `config.py`

Loads environment variables and `.env` values into application settings. It is
kept outside `core` because current settings include Telegram credentials and
local filesystem paths.

## Dependency Rules

Allowed direction:

```text
cli, bot -> application/adapters -> core
telegram -> core
database -> core
analytics -> core
reports -> analytics, memory, events, core
memory -> events, core
events -> core
```

Forbidden direction:

```text
core -> telegram/database/bot/cli
analytics -> telegram/database
events -> telegram/database
memory -> telegram
reports -> telegram
bot -> Telethon internals
```

Practical checks:

- Business logic must consume `core` domain objects, not Telethon objects.
- Telegram code must normalize before storage or analysis.
- Storage code must persist normalized objects, not raw transport payloads.
- Interface code must render results, not compute them.
- New adapters must expose the same normalized concepts as Telegram.

## Current Runtime Flow

Current CLI import flow:

```text
Telethon/MTProto
  -> relchat.telegram.importer
  -> relchat.telegram.normalizer
  -> relchat.core.Message
  -> relchat.database.repositories
  -> SQLite
```

Current CLI metrics flow:

```text
SQLite
  -> relchat.database.repositories
  -> relchat.core.Message
  -> relchat.analytics.metrics
  -> relchat.cli formatting
```

Current CLI event flow:

```text
SQLite
  -> relchat.database.repositories
  -> relchat.core.Message
  -> relchat.events.extractor
  -> relchat.core.ConversationEvent
  -> relchat.cli formatting
```

Current bot list/import flow:

```text
Telegram Bot command
  -> relchat.bot handlers
  -> relchat.telegram.importer over Telethon/MTProto
  -> relchat.database.repositories
  -> relchat.bot formatting
```

Current bot metrics/event flow:

```text
Telegram Bot command
  -> relchat.bot handlers
  -> SQLite repositories
  -> analytics or events
  -> relchat.bot privacy-safe formatting
```

Optional bot AI flow:

```text
Telegram Bot analysis mode
  -> persisted user consent check
  -> local import and deterministic report
  -> deterministic dimensions and local score
  -> minimized normalized messages + local summaries + anonymous labels
  -> OpenAI Responses API structured JSON
  -> schema validation, safety checks, privacy redaction
  -> SQLite communication analysis metadata/result
  -> relchat.bot privacy-safe formatting
```

Target product flow:

```text
Telegram or other source
  -> importer
  -> normalized messages
  -> conversation events
  -> memory
  -> analytics
  -> reports
  -> Telegram bot
```

## Domain Model Direction

Only the minimal current models are implemented. The long-term domain should be
designed around these concepts before feature work expands:

- `Message`: normalized message content and metadata.
- `Conversation`: source-agnostic container for messages and participants.
- `Participant`: stable identity inside a conversation, separate from platform
  user IDs where possible.
- `ImportSession`: import source, selected scope, time range, status, and audit
  metadata.
- `Event`: implemented minimally as `ConversationEvent`, a text-free reference
  to an extracted fact such as a question, silence, or follow-up candidate.
- `Reminder`: user-approved reminder derived from events or explicit input.
- `Topic`: conversation theme or thread, derived without coupling to a source.
- `Metric`: computed measurement with provenance and time range.
- `Report`: user-facing summary assembled from metrics, events, and memory.
- `MemoryItem`: durable, inspectable fact retained under privacy rules.
- `FollowUp`: unresolved action or conversational thread.
- `RelationshipTimeline`: ordered events, metrics, and milestones.

These models should be introduced incrementally as real behavior needs them.
Avoid creating empty abstractions just to match names.

## Security And Privacy Boundaries

RelChat handles highly sensitive personal conversation data. The architecture
must make private data locations explicit.

Sensitive local state:

- Telegram sessions live outside the database under `RELCHAT_SESSION_PATH`.
- SQLite databases live under `RELCHAT_DB_PATH`.
- Both default under `RELCHAT_DATA_DIR`, which is ignored by git.
- Session files grant account access and must be treated like secrets.
- Message text in SQLite is sensitive conversation content.
- AI analysis rows store structured Communication analysis summaries,
  deterministic dimensions, score metadata, coverage,
  consent version, and safe errors. They must not store raw OpenAI requests,
  raw OpenAI responses containing message text, or a second full copy of
  conversation messages.
- Conversation events must not store message text. They may reference source
  message IDs and carry non-text metadata such as thresholds or gap duration.
- Telegram bot tokens are secrets and must not be logged or committed.
- `RELCHAT_ALLOWED_USER_IDS` must be configured before the bot starts.

Recommended encryption boundaries:

- Add encryption at the storage adapter boundary, not inside analytics or
  Telegram importer code.
- Encrypt SQLite or selected sensitive columns before enabling broader product
  use.
- Store raw payloads, if ever enabled, in a separate encrypted blob store with
  explicit retention and opt-in controls.
- Keep Telegram sessions separate from normalized message storage. Prefer OS
  keychain or an encrypted local secrets store when that work begins.

Never log by default:

- message text
- raw platform payloads
- media contents or download paths
- API hashes, bot tokens, authorization codes, session contents
- phone numbers and credentials
- database contents, exports, report bodies, memory items

Secrets handling:

- Load local secrets from environment variables or `.env`.
- Never commit `.env`, session files, databases, exports, or logs.
- Do not pass secrets through analytics, events, memory, or report layers.
- Keep credentials at integration boundaries and clear documentation points.

Import isolation:

- Importers should yield normalized objects and avoid direct persistence side
  effects.
- Selection of conversations must be explicit.
- Raw payload retention, media downloads, live updates, cloud sync, AI provider
  calls, and exports require opt-in behavior and updated security docs before
  implementation.
- Bot output must stay compact and must not include message text by default.
- AI requests must use anonymous participant labels, configured message/character
  limits, and selected-period scope. They must not include Telegram IDs, bot user
  IDs, database IDs, credentials, session paths, unrelated chats, media files, or
  debug logs.
- Communication scores describe visible communication quality for the selected
  period only and are calculated locally from available dimensions. They must
  not be presented as feelings, compatibility, truthfulness, mental health,
  hidden intentions, or personal value. If evidence is too limited, the UI must
  show an insufficient-data state instead of a precise-looking score.

## Developer Experience

Keep the codebase easy to contribute to:

- Prefer small packages with obvious ownership over deep nesting.
- Add interfaces only when multiple implementations or tests need them.
- Keep CLI and bot code thin.
- Put platform-specific code in platform packages.
- Put persistence code in storage adapters.
- Put calculations in analytics or event extraction modules.
- Update this document when a change affects dependency direction, storage,
  privacy, or user-facing data flow.
