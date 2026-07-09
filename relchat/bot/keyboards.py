from __future__ import annotations


def main_keyboard():
    from telegram import ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        [
            ["/status", "/chats"],
            ["/help"],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
