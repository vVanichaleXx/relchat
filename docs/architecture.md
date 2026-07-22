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
  bot/services/context.py
                 Context classification, labels, and context-aware framework selection
  bot/services/period_comparison.py
                 Comparable-period rules and metric-specific comparison logic
  bot/services/semantic_interpretation.py
                 Three-level semantic interpretation for explicit/strongly supported/ambiguous findings
  bot/services/canonical_findings.py
                 Canonical validated finding model shared by score, advice, tone, memory, timeline, and evidence UI
  bot/services/work_analysis.py
                 Work-effectiveness findings and local work score policy
  bot/services/report_consistency.py
                 Final contradiction validator for score/finding/advice/report integrity
  bot/services/analysis_frameworks.py
                 Registry for extensible communication frameworks and future tutorial modules
  bot/services/personal_profile.py
                 Period-specific user communication profile and cross-chat aggregate profile
  bot/services/story_builder.py
                 Human-readable communication story assembled from validated evidence
  bot/services/evidence_service.py
                 “Why this conclusion?” panels from safe evidence metadata
  bot/services/advice_routing.py
                 Typed finding-to-advice mapping and validation
  bot/services/question_metrics.py
                 Filtered direct-question metrics with denominators
  bot/services/history_segmentation.py
                 Bounded long-history segmentation and recent-vs-baseline summaries
  bot/services/conversation_fingerprint.py
                 Deterministic selected-chat fingerprint for individualized reports
  bot/services/pattern_selector.py
                 Ranks distinctive evidence and filters generic repeated observations
  bot/services/individualized_story.py
                 Conversation-specific story arc built from selected patterns
  bot/services/personalized_feedback.py
                 Evidence-linked recommendation generation and advice omission
  bot/services/specificity_validator.py
                 Non-template report quality gate and safe genericness cleanup
  bot/services/chat_types.py
                 Telegram metadata-based chat type/category classification
  bot/services/chat_ranking.py
                 Private-first deterministic chat ranking and quick access selection
  bot/services/chat_search.py
                 Unicode-safe metadata-only chat search ranking
  bot/services/native_navigation.py
                 Per-user Telegram navigation stack and short callback token registry
  bot/services/score_explanation.py
                 User-facing score contributor and cap summaries
  bot/services/retry_policy.py
                 Safe failure classification and transient retry decisions
  bot/services/telethon_lifecycle.py
                 Owned Telethon/client task cleanup helpers
  bot/services/analysis_memory.py
                 Promotion and persistence orchestration for recurring validated observations
  bot/services/communication_timeline.py
                 Safe semantic timeline-event generation
  bot/services/automation.py
                 Optional important-chat scheduled polling and automatic analysis orchestration
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

Reserved for source-agnostic durable memory contracts. Product UX v12 implements
the current storage and promotion logic in `bot/services/analysis_memory.py`
because it is tied to the bot-visible analysis result and SQLite repositories.
Memory stores recurring validated observations, occurrence counts, contradiction
counts, and active/inactive state. It must not store raw messages or permanent
personality labels.

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

Product UX v13 makes Telegram navigation a first-class bot concern. The main
menu is private-chat-first: private chats, favorites, recents, and search are
primary; groups, channels, bots, and settings are secondary. Quick access uses
per-user pinned, favorite, recently opened, and recently analyzed private chats.
It never ranks chats by emotional importance and never uses message content.

Chat discovery uses Telegram metadata normalized into cached chat types:
private human, bot, group/supergroup, channel, self/saved messages, unavailable,
or unknown. `chat_types.py`, `chat_ranking.py`, and `chat_search.py` keep this
classification, ranking, and search policy out of handlers. `native_navigation.py`
keeps a bounded per-user back stack and short callback tokens in bot state; stale
tokens fall back to a localized stale-menu screen with a Main Menu button.

Paginated screens use one row per chat, bounded pages, arrow controls, a visible
page indicator, and a clear Main Menu exit. Handlers prefer editing the current
menu message and fall back to sending a replacement if Telegram rejects the edit.
Callback data must not contain Telegram chat IDs, bot user IDs, usernames,
phone numbers, report text, or search queries.

Report presentation is also part of the bot boundary. Compact results show the
chat title, context/period metadata, score or local-mode state, the main story,
the strongest supported profile/friction/strength, one recommendation when
useful, and a short data/limitations note. Full analysis, evidence, comparison,
score explanation, timeline, memory, settings, and deletion controls stay behind
secondary Chat Home or detail actions.

Optional AI-enhanced Communication analysis is composed from this layer through
`bot/services/ai_analysis.py`, but the service itself consumes source-agnostic
messages/events and settings. It uses the official OpenAI Responses API only
when enabled by configuration and after persisted user consent. The OpenAI SDK
is optional; bot startup and local deterministic analysis must work without it.
Provider output is structured interpretation only; deterministic dimensions and
the final 0-10 score are calculated locally before persistence/rendering.

Context classification is a first-class input to communication analysis. The
classifier supports romantic, friendship, family, work, customer/service,
group, channel/broadcast, mixed, and unknown contexts. User-confirmed context is
stored on `user_chats` per `bot_user_id`, source, and chat, and overrides
automatic classification until changed. Automatic classification may use chat
type, saved category, title/type, deterministic topic signals, and the
anonymized sample already used by AI interpretation. It must not infer context
from gender, names, or stereotypes.

Score quality is also local. `ai_analysis.py` gates score confidence by message
count, text-message coverage, available dimensions, AI sample coverage,
deterministic evidence count, period coverage, and context confidence. Equal
message volume is capped as shallow evidence; unavailable dimensions must stay
unavailable and must not inflate a score.

Semantic interpretation uses a three-level model:

- directly observed: explicit wording or visible behavior, such as an insult,
  refusal, threat, direct invitation, or repeated command
- strongly supported interpretation: several independent indicators or repeated
  comparable sequences point to the same interpretation
- unsupported or ambiguous: evidence is weak, contradictory, not applicable, or
  insufficient

Sarcasm, aggression, assertiveness, pressure, persuasion, possible manipulation
patterns, and possible interest are not globally forbidden. They are available
only when evidence supports them. The result model carries observation,
interpretation, confidence, evidence count/type, alternatives, period scope,
context scope, and limitations. Ambiguous dimensions stay ambiguous or
insufficient instead of rendering false `0.0` risk scores.

Product UX v12.1 adds semantic source routing:

- `explicit_rule`: direct wording such as explicit insults, threats, refusals,
  ultimatums, repeated urgent commands, or explicit sarcasm/irony markers
- `local_pattern`: cautious local pattern evidence; wording stays suggestive
  unless repeated independent signals support the same interpretation
- `ai_interpretation`: contextual semantic interpretation after consent
- `historical_pattern` and `combined`: reserved for memory and future combined
  evidence flows

Each semantic result also carries `semantic_depth` (`direct`, `suggestive`, or
`contextual`). Memory promotion ignores weak suggestive local patterns, and
score dimensions inherit the semantic source/depth that made them available.

`question_metrics.py` replaces raw `?` totals in user-facing reports with
filtered direct-question rates. It excludes URL query strings, code-like
snippets, quoted/forwarded text, repeated punctuation, and rhetorical candidates
before presenting counts with denominators and participant comparison.

`history_segmentation.py` activates for large full-history selections, long date
ranges, or many visible sessions. It builds bounded monthly or activity-based
windows and surfaces current picture, long-term baseline, and recent change so
the report does not average away current deterioration or improvement.

`advice_routing.py` validates that each recommendation references a supported
finding type and severity. Sarcasm advice, aggression boundary advice,
unanswered-question advice, and work task-clarity advice are separate routes.
The formatter also deduplicates symmetric participant facts into one
participation-balance section and removes generic strengths such as “both sides
participated.”

Product UX v12.2 makes canonical validated findings the shared contract between
score calculation, score explanations, advice, adaptive tone, long-term memory,
timeline events, evidence panels, and report rendering. `canonical_findings.py`
normalizes finding status, severity, semantic source/depth, score effect,
advice category, evidence IDs, and memory eligibility. `report_consistency.py`
is the final safety pass before output: it drops unsupported score contributors
and advice, prevents serious tone from ambiguous local evidence, removes
hostility/aggression/devaluation claims without matching findings, and
deduplicates repeated conclusions.

`work_analysis.py` adds work-effectiveness findings inside the existing
analysis result. It focuses on task clarity, owner/deadline clarity, answer
completion, repeated clarification, decisions, follow-through, status quality,
response consistency, and tone impact on execution. Work scores are not
relationship scores; balanced message volume is mostly informational.

When AI analysis fails and local fallback is used, the fallback report is
rebuilt from local canonical findings only. Partial or invalid AI-derived
semantic claims are not preserved in local score contributors, advice, or tone.

Product UX v12.3 adds a deterministic personalization layer without creating a
parallel report flow. `conversation_fingerprint.py` builds a safe fingerprint
from the same canonical findings, question metrics, long-history segments, and
aggregate profile data that already feed the report. `pattern_selector.py`
chooses a small set of distinctive observations and penalizes generic activity
facts. `individualized_story.py` turns those selected patterns into the visible
story arc, and `personalized_feedback.py` produces one tailored action or
explicitly omits advice when no useful change is supported.

`specificity_validator.py` runs after report consistency. It checks for generic
filler, insufficient evidence-linked observations, duplicated semantic content,
untethered advice, weak context relevance, and uncertainty mismatches. On
failure it removes or rebuilds generic sections using validated findings only;
it never invents chat-specific detail. This keeps AI and local reports on the
same result object while making output specific to the selected chat and
period.

`analysis_frameworks.py` is the extension point for future tutorial and
coaching modules. A framework declares `framework_id`, supported contexts,
dimensions, evidence rules, interpretation rules, advice rules, forbidden
actions, localization keys, and evaluation fixture tags. Future modules such as
negotiation, boundary setting, flirting, leadership, sales, or conflict
de-escalation should register a framework rather than editing one giant prompt.

Personal profile, story, evidence, memory, and timeline services operate on the
validated unified analysis result. They do not create a parallel report flow.
Profile snapshots describe how the authenticated user communicated in a single
chat/period. Cross-chat profile uses aggregate snapshots only and never exposes
raw text from one chat inside another.

`bot/services/period_comparison.py` compares only comparable periods for the same
chat. It rejects weak comparisons when message counts are too low, duration is
not comparable, coverage is unknown, or analysis versions differ. It does not
treat every numerical increase as improvement.

`bot/services/automation.py` is an optional scheduled polling service for
important chats. It starts with the bot only when `RELCHAT_AUTOMATION_ENABLED`
is true, stops during application shutdown, uses stored cursors and completed
ranges after restart, and keeps normal bot handlers non-blocking. The current
implementation uses polling instead of MTProto live updates because it is easier
to bound, restart, and test in the existing architecture.

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
  -> schema validation, semantic validation, safety checks, privacy redaction
  -> local score calculation and evidence-quality caps
  -> profile/story/evidence/memory/timeline artifact persistence
  -> SQLite communication analysis metadata/result
  -> relchat.bot privacy-safe formatting
```

Analysis job reliability flow:

```text
analysis job
  -> loading_messages
  -> analyzing_structure
  -> analyzing_semantics or building_report
  -> completed
```

Transient failures such as Telegram temporary/internal errors, Telegram rate
limits, DNS failures, provider timeouts/rate limits, and SQLite busy errors are
classified and retried with bounded backoff under the same job identity and
idempotency key. Permanent failures such as Telegram auth loss, revoked consent,
validation errors, deleted/forbidden chats, and cancellation are not retried.
Final failure messages are localized by category and never expose stack traces,
IDs, exception class names, or exception text.

Telethon lifecycle ownership is explicit: importers create a client, start it,
and disconnect via `safe_disconnect` in `finally`. Bot shutdown stops automation
and awaits analysis-owned task cancellation before the application exits.

Optional important-chat automation flow:

```text
Bot startup
  -> automation service starts if env flag is enabled
  -> load important chats with user master switch and chat switch enabled
  -> poll Telegram through one MTProto client per cycle
  -> save new normalized messages with bot_user_id ownership
  -> evaluate pause heuristic using cursors, thresholds, cooldown, quiet hours, and completed ranges
  -> send suggestion or run local/AI analysis according to chat settings and consent
  -> persist reports, unified analysis result, comparison metadata, and completed automatic range
```

Restart behavior depends on persisted `automation_states`,
`automatic_analysis_ranges`, pending notifications, user settings, and
important-chat settings. Queued/running analysis jobs are marked failed safely by
the existing startup cleanup if the bot restarts mid-job. The heuristic may miss
activity while Telegram is unavailable and does not prove that a conversation
ended.

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
