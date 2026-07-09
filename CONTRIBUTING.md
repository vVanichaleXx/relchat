# Contributing

RelChat is early-stage and privacy-sensitive. Keep contributions small, readable, and explicit.

## Expectations

- Keep changes focused on the current phase.
- Prefer simple, local-first code over infrastructure.
- Do not add dashboard, AI analysis, cloud sync, or background live updates unless the roadmap phase calls for it.
- Do not add bot logic, web UI, or new product features as part of architecture-only changes.
- Do not introduce hidden network calls.
- Do not log message text by default.
- Do not store raw Telegram payloads by default.
- Keep business logic source-agnostic. Telegram code should normalize into core domain objects before storage or analysis.
- Do not add broad data exports without explicit user action.
- Update docs when behavior affects privacy, security, storage, or authorization.

## Code Style

- Use clear names and boring control flow.
- Keep modules small.
- Avoid unnecessary abstractions.
- Keep interface code thin. CLI and future bot code should orchestrate, not own business logic.
- Keep analytics independent of Telegram and SQLite.
- Add comments only where they explain a non-obvious decision.
- Keep generated files, caches, databases, sessions, and personal exports out of git.

## Before Opening A Pull Request

Run a syntax check:

```bash
python3 -B -m relchat --help
```

If your change touches imports, storage, metrics, authorization, or privacy-sensitive output, include focused tests or a clear manual verification note.
