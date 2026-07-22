# Privacy Notes

RelChat is local-first. Telegram chat history is imported through the locally authorized user Telegram session, normalized, and stored in the local SQLite database under the configured data directory.

## Communication Analysis

Communication analysis describes observable messaging behavior in the selected period. It is not a psychological diagnosis, relationship diagnosis, attachment analysis, mental-health assessment, compatibility score, or hidden-feelings prediction.

Local analysis stays on this machine. Optional AI-enhanced analysis runs only when enabled by configuration and after explicit persisted consent.

The analysis tone is factual and direct. RelChat may describe weak conversation, unbalanced dialogue, low-effort replies, dismissive answers, or worse-than-usual performance when supported by observable evidence. It must not invent comforting explanations, diagnose people, claim hidden feelings, or insult participants.

RelChat classifies the communication context before analysis. Supported contexts are romantic, friendship, family, work, customer/service, group, channel/broadcast, mixed, and unknown. The classifier must not use gender, names, or stereotypes. Users can correct the context; confirmed context is stored per `bot_user_id`, source, and chat, and overrides automatic classification until changed.

Local-only analysis can see structure such as participation, session starts, response opportunities, questions, plans, and follow-up candidates. It does not understand the meaning of every reply and must not turn missing tone dimensions into positive evidence. Unmeasured sarcasm, hostility, dismissiveness, or emotional warmth remain unavailable unless text interpretation supports them.

V12 keeps semantic interpretation explicit. Sarcasm, aggression, assertiveness, pressure, persuasion, possible manipulation patterns, and possible personal interest may be analyzed when evidence is sufficient. The result must distinguish directly observed behavior from interpretation, include confidence and alternatives where ambiguity matters, and avoid presenting hidden feelings or motives as proven facts.

Scores are evidence-gated. Equal message volume does not prove interest, warmth, respectfulness, relationship health, or work effectiveness. Shallow local metrics, deterministic metrics without text interpretation, sampled AI coverage, and low context confidence can cap score and confidence.

V12.1 adds semantic source/depth metadata. Local-only semantic claims are cautious unless evidence is explicit or repeated through independent signals. Weak local sarcasm, pressure, manipulation, or attraction candidates stay ambiguous and are not promoted into long-term memory.

Question metrics are normalized before display. URL query strings, code-like text, quoted or forwarded text, repeated punctuation, and rhetorical candidates are filtered out of direct-question rates. Full-history reports show counts with denominators instead of raw question-mark totals.

## Period Comparisons

Period comparison uses observable metrics only and only compares ranges from the same chat when message counts, durations, coverage, and analysis versions are comparable. If those checks fail, RelChat shows that there is not enough comparable data.

More messages alone is not treated as better. Metrics such as unanswered-question rate, pressure risk, initiative balance, response timing, reply length, and communication score each have their own interpretation rules.

## Important Chats And Automation

Important chats are user-owned settings scoped by `bot_user_id`, source, and chat. Automation is disabled by default for new users. It runs only when the environment flag, user master switch, and chat-level automatic analysis switch are all enabled.

The conversation-pause heuristic is cautious. It checks minimum new messages, inactivity duration, previous completed ranges, cooldown, quiet hours, and daily notification limits. It does not know that a conversation definitely ended.

Automatic analysis can either suggest analysis first or run automatically if explicitly configured. AI-enhanced automatic analysis never bypasses consent. If consent is missing or revoked, RelChat must not send messages to OpenAI silently.

## Optional OpenAI Use

When AI-enhanced analysis is used, RelChat sends only minimized data for the selected chat and period:

- anonymous participant labels such as `YOU`, `OTHER`, or `PARTICIPANT_1`
- selected message text within configured message and character limits
- timestamps, message type, and reply references where useful
- local metric summaries, filtered question aggregates, long-history segmentation metadata, event summaries, deterministic dimensions, and coverage metadata

RelChat does not send Telegram phone numbers, Telegram IDs, bot user IDs, database IDs, API hashes, bot tokens, session data, raw Telethon objects, media files, unrelated chats, debug logs, or deleted messages.

The final communication score is calculated locally from deterministic dimensions. The AI may explain observable patterns, but it does not choose the numeric score.

## Storage

RelChat stores validated structured analysis results, score metadata, dimensions, coverage, consent version, safe usage metadata, timestamps, and safe error states. It does not store raw OpenAI request payloads, raw provider responses, API keys, session files, or a duplicate full message transcript inside analysis records.

Automation stores settings, cursors, completed automatic ranges, pending delayed notifications, and comparison metadata. It does not create duplicate full transcript copies.

V12 stores safe interpretation artifacts: profile snapshots for the authenticated user’s behavior in one chat/period, evidence-backed findings, evidence metadata without raw text, recurring observation memory, framework settings, semantic settings, and communication timeline events. These records are scoped by `bot_user_id`, source, and chat. Long-term memory stores recurring validated observations, occurrence counts, contradiction counts, and active/inactive state; it must not store raw messages or permanent personality labels.

V12.1 stores retry metadata on the existing analysis job row: attempt count, safe failure category, and idempotency key. UX audit may record safe retry and fallback metadata, segmentation window count, semantic source, and semantic confidence. It must not record exception text, stack traces, report bodies, prompts, raw provider responses, participant identities, Telegram IDs, or message text.

V12.3 personalization stores structured fingerprints and selected pattern
metadata inside the existing analysis result. The fingerprint contains context,
period, participant-asymmetry summaries, topic/recent-change summaries,
validated finding references, coverage scores, and uncertainty notes. It is not
a raw transcript and not a permanent personality record. Cross-chat
personalization may use aggregate profile snapshots only; it never exposes
message text or examples from another chat.

Specificity audit fields are numeric or categorical only, such as specificity
score, distinctive finding count, comparison count, duplicate count, advice
generated/omitted, context category, and evidence depth. Audit logs must not
include the report body, message text, personalized recommendation text, AI
prompt, raw provider response, participant identity, usernames, phone numbers,
or Telegram IDs.

If a conversation is too large, local metrics cover the imported selected period while AI receives only the configured representative sample. The report must disclose partial AI coverage.
