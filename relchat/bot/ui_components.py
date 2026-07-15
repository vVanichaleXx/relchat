from __future__ import annotations

from collections.abc import Iterable

from relchat.bot.localization import t


DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━"


def render_status(*, icon: str, title: str, explanation: str) -> str:
    return "\n".join([f"{icon} {clean_text(title, limit=80)}", clean_text(explanation, limit=160)])


def render_section(title: str | None, rows: Iterable[str]) -> str:
    content = [row for row in rows if row]
    if title:
        return "\n".join([clean_text(title, limit=80), "", *content])
    return "\n".join(content)


def render_field(title: str, value: str, subtitle: str | None = None) -> str:
    lines = [clean_text(title, limit=80), clean_text(value, limit=120)]
    if subtitle:
        lines.append(clean_text(subtitle, limit=160))
    return "\n".join(lines)


def render_empty_state(title: str, body: str) -> str:
    return "\n".join([clean_text(title, limit=80), clean_text(body, limit=180)])


def render_loading_state(*, language: str = "en") -> str:
    return "\n\n".join(
        [
            t(language, "chat_home_loading_title"),
            render_section(
                None,
                [
                    f"· {t(language, 'chat_home_loading_chat')}",
                    f"· {t(language, 'chat_home_loading_report')}",
                    f"· {t(language, 'chat_home_loading_reminders')}",
                ],
            ),
        ]
    )


def clean_text(value: object, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[: limit - 3]}..."
