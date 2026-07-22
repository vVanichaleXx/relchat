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
- Local deterministic analysis is the default. Optional AI-enhanced communication analysis is available only when explicitly configured and consented to in the bot.
- No dashboard, web UI, cloud sync, or hosted RelChat service is included in this foundation.

Read [SECURITY.md](SECURITY.md) and [PRIVACY.md](PRIVACY.md) before adding features that touch personal data.

## Architecture

RelChat is organized around source-agnostic domain objects:

```text
Telegram -> importer -> normalized messages -> events -> memory -> analytics -> reports -> bot
```

The optional AI layer does not depend directly on Telegram. It consumes minimized normalized messages plus local metrics/events, and it must never receive Telethon objects, Telegram sessions, credentials, unrelated chats, media files, or raw platform payloads.

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
See [docs/scoring.md](docs/scoring.md) for context categories, evidence gates, and score caps.
See [docs/analysis.md](docs/analysis.md) for observation-vs-interpretation rules, semantic analysis, memory, and timeline behavior.

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

Optional AI-enhanced analysis uses the official OpenAI Python SDK and the Responses API. Local deterministic analysis works without it.

```text
OPENAI_API_KEY=
RELCHAT_AI_ENABLED=false
RELCHAT_AI_MODEL=
RELCHAT_AI_MAX_MESSAGES=300
RELCHAT_AI_MAX_CHARS=30000
RELCHAT_AI_TIMEOUT_SECONDS=90
RELCHAT_AUTOMATION_ENABLED=false
RELCHAT_AUTOMATION_POLL_SECONDS=300
RELCHAT_AUTOMATION_MAX_NOTIFICATIONS_PER_DAY=5
RELCHAT_AUTOMATION_DEFAULT_INACTIVITY_MINUTES=45
RELCHAT_AUTOMATION_DEFAULT_MIN_MESSAGES=10
RELCHAT_AUTOMATION_DEFAULT_COOLDOWN_HOURS=12
```

Install the optional SDK only if AI analysis is enabled:

```bash
python3 -m pip install openai
```

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
Settings
```

The guided analysis flow lets a user browse Telegram folders/categories, search chats, choose a period, choose local or AI-enhanced analysis, and start a background import/analysis job. Reports, saved chats, favorites, settings, job metadata, reminders, AI consent, and AI analysis metadata are persisted in SQLite across bot restarts.

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

## Communication Analysis

RelChat’s normal result is called **Communication analysis**. It combines local deterministic metrics, rule-based events, optional AI interpretation, and a deterministic score into one readable report. It describes visible messaging behavior only. It is not a psychological diagnosis, personality diagnosis, relationship diagnosis, mental-health assessment, compatibility score, or prediction of hidden feelings.

Local analysis stays on this machine and remains available without OpenAI. AI-enhanced analysis is optional.

The analysis policy is intentionally direct. RelChat should say when a visible conversation is weak, uneven, dismissive, low-effort, or worse than a comparable period if the data supports that conclusion. It should not add unsupported comfort, invented excuses, hidden-feeling claims, diagnoses, or insults. Conclusions criticize observable communication behavior, not a participant’s human value.

Before analysis, RelChat classifies the communication context as romantic, friendship, family, work, customer/service, group, channel/broadcast, mixed, or unknown. The classifier can use a user-confirmed category, saved chat metadata, chat type/title, deterministic topic signals, and, in AI mode, the anonymized sample already being sent for interpretation. It must not infer context from gender, names, or stereotypes. Users can correct the context from Chat Home or the analysis details; a user-confirmed category is stored per `bot_user_id` and chat and overrides automatic classification until changed.

The selected context changes the language and framework. Work chats use efficiency, task ownership, clarity, commitments, and blocking language. Romantic chats use observable reciprocity, effort, directness, planning cooperation, and boundaries without attraction promises, pickup tactics, jealousy advice, or gender stereotypes. Family, friendship, customer/service, group, and channel contexts have their own observable frameworks. Groups and channels do not receive a two-person relationship score.

Reports are personalized through a deterministic conversation fingerprint, not
random template variation. RelChat first identifies what is distinctive about
the selected chat and period, such as participant asymmetry, topic differences,
recent changes, recurring validated findings, and safe aggregate comparisons.
The report then selects a small number of high-value patterns and builds a
story arc around them. Generic participation facts like “both sides
participated” or equal message volume are informational only and are not treated
as strengths by themselves.

Advice is optional. If the user's current wording already looks clear or no
actionable issue is supported, RelChat can omit a recommendation instead of
giving generic advice. When advice is shown, it is linked to the strongest
validated finding and the selected context, for example task clarity in a work
chat or returning to a direct question after supported sarcasm.

Scores are evidence-gated. Equal message volume is only activity balance; it does not prove interest, warmth, respectfulness, relationship health, or work effectiveness. Message-volume balance can contribute no more than 15% of the positive score. Missing dimensions do not become positive evidence, and unmeasured risks such as sarcasm or hostility remain unavailable instead of becoming `0.0`. Shallow local metrics are capped, deterministic metrics without text interpretation are capped, sampled AI coverage is capped, and low context confidence caps score confidence.

RelChat uses a three-level interpretation model. Directly observed findings come from explicit wording or visible behavior. Strongly supported interpretations require several independent indicators or repeated comparable episodes. Unsupported or ambiguous areas stay marked as ambiguous, insufficient, or not applicable rather than becoming false zero scores. Sarcasm, aggression, pressure, persuasion, possible manipulation patterns, and possible personal interest are analyzed when evidence supports them, with confidence, alternatives, and limitations.

Semantic findings also carry source and depth metadata. `explicit_rule` can support direct wording such as insults, threats, refusals, ultimatums, and explicit sarcasm markers. `local_pattern` is cautious and suggestive unless repeated independent signals support the same interpretation. `ai_interpretation` can evaluate contextual sarcasm, pressure, influence, dismissiveness, or possible interest only after consent and with the selected anonymized sample.

Question metrics are normalized for long reports. RelChat filters URL query strings, code-like snippets, quoted text, forwarded text, repeated punctuation, and obvious rhetorical candidates before presenting direct-question rates. Large histories show counts with denominators and per-message rates instead of raw `?` totals.

Full-history reports are segmented when the selected period is large, long, or has many visible sessions. The main result prioritizes the current picture, long-term baseline, and recent change so recent deterioration or improvement is not averaged away.

Scores include a compact explanation of positive contributors, negative contributors, unavailable dimensions, and confidence or semantic-mode caps. Shallow local-only evidence is capped below the “good” verdict threshold, so balanced message volume alone cannot create a good or strong result.

Advice is routed from validated finding types. Sarcasm receives sarcasm-specific advice, explicit aggression receives boundary advice, unanswered questions receive question advice, and work ambiguity receives task-clarity advice. The renderer omits generic “both participated” strengths and deduplicates symmetric participant observations into one participation-balance section.

The result also includes a personal communication profile for the authenticated user in that chat and period, a short human communication story, and evidence-backed findings. “Why this conclusion?” explains what was observed, how it was interpreted, the evidence type, confidence, alternatives, and limitations. Long-term memory stores only recurring validated observations and safe aggregates, not raw messages or permanent personality labels. Timeline entries may show safe communication changes such as recurring pressure, dismissive sarcasm, repair, or possible-interest signals without turning them into certain relationship milestones.

## Period Comparison

RelChat can compare comparable periods for the same chat: current session vs previous session, last 7 days vs previous 7 days, last 30 days vs previous 30 days, a selected report vs a previous report with similar duration, and the latest saved analysis vs an earlier compatible analysis.

Comparisons are shown only when both periods have enough messages, similar duration, known coverage, the same chat, and compatible analysis versions. If those rules are not met, the UI says there is not enough comparable data. More messages alone is not treated as better; each metric has its own direction rule.

## Important Chats And Optional Automation

Users can mark selected chats as important. Important status and automation settings are stored per `bot_user_id`, source, and chat. New users have automation disabled by default.

Automatic analysis is opt-in at two levels:

- `RELCHAT_AUTOMATION_ENABLED=true` must be set for the background service to run.
- The user-level master switch and the chat-level automatic analysis switch must both be on.

Default automation settings are conservative: 10 minimum new messages, 45 minutes with no new messages, 12 hour cooldown, quiet hours from 23:00 to 08:00, and suggestion mode rather than fully automatic analysis. The heuristic never knows that a conversation definitely ended; it only treats a recent active conversation as appearing to have paused.

Users can disable automation for one chat, pause a chat for 24 hours, or disable all automatic analysis from Settings. Quiet hours delay delivery instead of sending notifications immediately.

AI automation never bypasses existing consent. If AI-enhanced automation is selected and consent is missing or revoked, RelChat does not send messages to OpenAI silently.

## Optional AI Communication Analysis

AI-enhanced analysis is off unless `RELCHAT_AI_ENABLED=true`, `OPENAI_API_KEY` is set, and `RELCHAT_AI_MODEL` names the configured model. The first AI-enhanced run asks for explicit consent in the bot:

```text
AI-enhanced analysis sends the selected conversation messages to OpenAI.
You can continue with local-only analysis instead.
```

The user can revoke consent in Settings. Revoked consent makes future AI-enhanced runs ask again.

What may be sent to OpenAI for the selected chat and period:

- ordered message text, minimized to configured message/character limits
- anonymous participant labels such as `YOU`, `OTHER`, or `PARTICIPANT_1`
- timestamps, message type, and reply references where useful
- local deterministic summaries such as message counts, response metrics, event counts, and deterministic communication dimensions

What is not sent:

- Telegram phone numbers, usernames unless already present inside selected message text after redaction, Telegram IDs, bot user IDs, database IDs
- Telegram session data, API hashes, bot tokens, OpenAI API keys, raw Telethon objects
- media files, unrelated chats, debug logs, deleted messages, or full database exports

The communication score is a 0-10 description of visible communication quality during the selected period. It is calculated locally from weighted observable dimensions such as reciprocity, initiative balance, reply quality, topic continuation, respectfulness, question engagement, and planning cooperation, then reduced by risk dimensions such as pressure risk, hostility, dismissiveness, unanswered-question rate, and harmful sarcasm intensity. The AI may explain patterns, but it does not choose the final numeric score. When there is too little data or the evidence is too shallow, RelChat shows an insufficient-data state or a capped score instead of a precise-looking high score.

AI output is validated as structured JSON before persistence or rendering. Malformed output, refusals, timeouts, rate limits, disabled AI, missing keys, or model/API failures are handled safely and local analysis remains available. Large histories are limited by `RELCHAT_AI_MAX_MESSAGES` and `RELCHAT_AI_MAX_CHARS`; local metrics still cover the selected imported period, while AI receives only the configured representative sample. Partial coverage is displayed instead of pretending the whole chat was sent to AI.

Local-only analysis clearly states its limitation: it can see conversation structure, but it does not understand the meaning of every reply. It should remain neutral unless several supported dimensions justify a stronger conclusion.

Analysis jobs persist granular states such as `loading_messages`, `analyzing_structure`, `analyzing_semantics`, `building_report`, `retrying`, `failed`, and `cancelled`. Transient Telegram, DNS, provider timeout/rate-limit, and database-lock failures are retried with bounded backoff under the same job identity. Permanent auth, validation, deleted-chat, or revoked-consent failures are not retried. Telethon clients are disconnected in `finally` blocks and analysis-owned background tasks are awaited during bot shutdown.

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
