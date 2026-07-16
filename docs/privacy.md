# Privacy Notes

RelChat is local-first. Telegram chat history is imported through the locally authorized user Telegram session, normalized, and stored in the local SQLite database under the configured data directory.

## Communication Analysis

Communication analysis describes observable messaging behavior in the selected period. It is not a psychological diagnosis, relationship diagnosis, attachment analysis, mental-health assessment, compatibility score, or hidden-feelings prediction.

Local analysis stays on this machine. Optional AI-enhanced analysis runs only when enabled by configuration and after explicit persisted consent.

## Optional OpenAI Use

When AI-enhanced analysis is used, RelChat sends only minimized data for the selected chat and period:

- anonymous participant labels such as `YOU`, `OTHER`, or `PARTICIPANT_1`
- selected message text within configured message and character limits
- timestamps, message type, and reply references where useful
- local metric summaries, event summaries, deterministic dimensions, and coverage metadata

RelChat does not send Telegram phone numbers, Telegram IDs, bot user IDs, database IDs, API hashes, bot tokens, session data, raw Telethon objects, media files, unrelated chats, debug logs, or deleted messages.

The final communication score is calculated locally from deterministic dimensions. The AI may explain observable patterns, but it does not choose the numeric score.

## Storage

RelChat stores validated structured analysis results, score metadata, dimensions, coverage, consent version, safe usage metadata, timestamps, and safe error states. It does not store raw OpenAI request payloads, raw provider responses, API keys, session files, or a duplicate full message transcript inside analysis records.

If a conversation is too large, local metrics cover the imported selected period while AI receives only the configured representative sample. The report must disclose partial AI coverage.
