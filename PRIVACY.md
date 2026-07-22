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
- Optionally sends minimized selected-message data to OpenAI for AI-enhanced communication analysis, only after explicit bot consent and only when configured by environment variables.
- Lets users mark chats as important and, only when explicitly enabled, monitor those chats for a cautious “appears to have paused” automation heuristic.
- Classifies communication context before analysis and lets the user correct it per chat.
- Stores evidence-backed interpretation findings, personal-profile snapshots, safe timeline events, and recurring observation memory without duplicating full transcripts.

## What The MVP Does Not Do

- It does not upload chats to a hosted RelChat service.
- It does not run AI analysis unless `RELCHAT_AI_ENABLED=true`, an OpenAI API key/model are configured, and the user confirms consent in the bot.
- It does not include a dashboard or web server.
- It does not include a web UI.
- It does not use the Bot API to read private Telegram chats.
- It does not expose a public unrestricted bot.
- It does not store raw Telegram API payload objects.
- It does not download or store media files.
- It does not print message text in CLI summaries unless `--show-text` is passed.
- It does not print message text in bot replies.
- It does not send Telegram sessions, API hashes, bot tokens, phone numbers, raw Telethon objects, media files, unrelated chats, debug logs, or full database exports to OpenAI.
- It does not claim to know when a conversation definitely ended.
- It does not monitor normal chats automatically. Automation is limited to important chats with user-level and chat-level switches enabled.
- It does not infer romantic, work, family, or friendship context from gender, names, or stereotypes.
- It does not treat equal message counts as proof of interest, respectfulness, relationship health, or work effectiveness.
- It does not display unmeasured sarcasm, hostility, or dismissiveness as `0.0`.
- It does not store raw message text inside long-term interpretation memory, timeline events, profile snapshots, or evidence links.
- It does not present possible sarcasm, pressure, manipulation, or attraction as proven when the evidence is ambiguous.

## Local Storage

By default, local data is stored under:

```text
./data/
```

This directory is ignored by git. It may contain:

- `relchat.sqlite3`: local normalized database
- `telegram.session`: local Telethon authorization session

The current MVP stores normalized message text because Phase 1 metrics use text length and question detection. Future minimization work should make text retention configurable before broader product use.

AI analysis records store metadata, score dimensions, validated structured output, coverage, model name, consent version, and safe error state. They do not store a second full copy of raw message text or raw OpenAI requests/responses.

Important-chat automation stores per-user settings, message cursors, completed automatic message ranges, delayed notification metadata, cooldown state, and comparison metadata. It does not duplicate full message transcripts.

Confirmed communication context is stored on the per-user chat record. It is scoped by `bot_user_id`, source, and chat, so one user cannot change another user’s category for the same Telegram chat.

Product UX v12 adds structured interpretation artifacts:

- `interpretation_findings`: validated observation/interpretation/advice records with confidence, evidence counts, scope, alternatives, and limitations.
- `interpretation_evidence_links`: safe evidence metadata such as evidence type, anonymous sender role, and message marker; no message text.
- `communication_profile_snapshots`: period-specific descriptions of how the authenticated user communicated in one chat.
- `communication_memories`: recurring validated observations only, with occurrence and contradiction counters.
- `communication_timeline_events`: safe semantic timeline entries such as pressure pattern, dismissive sarcasm, or possible-interest signals.

All of these tables are scoped by `bot_user_id`, source, and chat where applicable.

Product UX v12.1 adds no raw transcript duplication. It stores retry metadata on the existing analysis job row (`retry_attempt_count`, `failure_category`, and `idempotency_key`) and may audit safe aggregate fields such as attempt count, retry category, final status, fallback usage, segmentation window count, semantic source, and semantic confidence. It must not audit exception text, stack traces, message text, report bodies, participant identities, raw semantic examples, Telegram IDs, or provider prompts/responses.

Long-history segmentation stores and renders aggregate windows only: message counts, participant counts, question rates, pause counts, and date ranges. Normalized question metrics filter URL query strings, code-like text, quotes, forwarded text, repeated punctuation, and rhetorical candidates before user-facing rates are shown.

Product UX v12.3 adds conversation fingerprints, selected distinctive patterns,
individualized story fields, personalized-feedback metadata, and specificity
scores inside the existing structured analysis result. These are derived from
the selected chat, validated findings, safe aggregate comparisons, and
long-history windows. They do not store complete personalized prose as
long-term memory, do not expose raw text from other chats, and do not rank
people. UX audit may record counts and scores such as specificity score,
distinctive finding count, duplicate count, advice generated/omitted, context,
and evidence depth; it must not record report text or recommendation text.

## Telegram Bot Interface

Bot Interface v0 is a private UI for local RelChat operations. It can show setup
status, list conversation references, import selected chat history through
Telethon / MTProto, and render basic metrics and Event Engine v0 summaries.

Bot replies are restricted to allowed Telegram user IDs configured in
`RELCHAT_ALLOWED_USER_IDS`. If that list is empty, bot startup refuses. The bot
does not send message text, raw payloads, bot tokens, API hashes, phone numbers,
or session contents.

When a user selects AI-enhanced analysis for the first time, the bot explains
that selected conversation messages are sent to OpenAI and offers local-only
analysis instead. Consent can be revoked in Settings.

AI-enhanced communication analysis receives the confirmed or estimated context,
anonymous participant labels, deterministic metrics, event summaries, selected
period, coverage limits, filtered question aggregates, long-history segmentation metadata, and a bounded representative message sample. The prompt
requires direct, context-aware, evidence-backed language. It may analyze
sarcasm, aggression, pressure, persuasion, possible manipulation patterns,
possible interest, and indirect meaning when supported. It must separate
observation from interpretation, include confidence and alternatives, and still
forbid diagnoses, hidden-feeling certainty, gender-based classification, pickup
tactics, coercion, deception, and clinical authority claims.

AI provider timeouts or invalid responses do not expose stack traces to users. If local messages are available, RelChat falls back to the local structural report and says that semantic analysis did not complete. Telegram authentication and forbidden/deleted-chat failures are treated as permanent until the user fixes access.

UX audit logs record safe interaction metadata such as mode selection,
started/completed/failed state, duration, and usage counts. They must not record
conversation prompts, source messages, API keys, or full private AI analysis
text.

Automatic-analysis audit events may record safe metadata such as important-chat enabled/disabled, automation started, pause candidate detected, notification suppressed with a safe reason, local or AI mode, duration, and message counts. They must not record source message text, AI prompts, full reports, raw provider responses, API keys, sessions, or phone numbers.

## Architectural Privacy Boundary

Telegram-specific code must normalize data before it reaches storage,
analytics, event extraction, memory, reports, or the optional AI layer. Future
source adapters should follow the same rule.

The optional AI layer must never consume Telethon objects, raw Telegram
payloads, Telegram sessions, or raw platform transports directly. It receives
source-agnostic normalized messages, local metrics, and source-agnostic events
after participant anonymization and configured input limits.

## User Control

Users should be able to:

- choose which chats are imported
- delete local databases and sessions
- avoid raw payload and media storage
- review privacy-sensitive behavior before enabling it
- choose local-only analysis instead of AI-enhanced analysis
- revoke AI consent from Settings
- correct the communication context for a chat
- disable automation for a chat, pause it for 24 hours, or disable all automatic analysis

Deleting `data/` removes the local database and Telegram session for the default configuration.
