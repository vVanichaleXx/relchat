from __future__ import annotations

from relchat.bot.localization.en import STRINGS as EN
from relchat.bot.localization.ru import STRINGS as RU


LANGUAGES = {
    "en": "English",
    "ru": "Russian",
}

CATALOGS = {
    "en": EN,
    "ru": RU,
}


def normalize_language(value: str | None) -> str:
    return value if value in CATALOGS else "en"


def t(language: str | None, key: str, **kwargs: object) -> str:
    normalized = normalize_language(language)
    text = CATALOGS.get(normalized, EN).get(key, EN.get(key, key))
    return text.format(**kwargs) if kwargs else text
