# Product UX v13

V13 focuses on native Telegram navigation and report presentation. It does not
replace import, persistence, analysis jobs, semantic analysis, scoring, memory,
timeline, privacy, or localization.

## Navigation Hierarchy

The Main Menu prioritizes the most common user path:

- Private chats
- Favorites
- Recent
- Find chat
- Groups
- Channels
- Bots
- Settings

Private one-to-one chats are shown first by default. Channels, groups, and bots
have separate categories so high-volume broadcast content does not bury personal
conversations.

## Quick Access

Quick access may show up to five private chats from per-user metadata:
pinned chats, favorites, recently analyzed chats, and recently opened RelChat
chats. It does not include channels by default and must not be described as
emotional importance or closeness.

## Chat Ranking And Search

Ranking uses safe metadata only:

- RelChat pinned
- favorite
- recently analyzed
- recently opened in RelChat
- recent Telegram activity
- title for deterministic tie-breaking

Search is case-insensitive, Unicode-aware, and metadata-only. Exact private
matches rank first, followed by private prefix and substring matches, then
groups, channels, and bots.

## Back Stack And Pagination

Navigation uses a bounded per-user stack and short callback tokens. Back returns
to the previous logical screen when state is still valid. Stale callbacks show a
localized stale-menu message and a Main Menu button.

Paginated lists use one chat per row, arrow controls, a visible page indicator,
and a Main Menu exit. Page changes edit the existing bot message when Telegram
allows it and fall back to sending a replacement when editing fails.

## Chat Home

Chat Home is compact:

- primary context-aware analysis action
- history and comparison when a report exists
- Why this conclusion
- More
- Back to chats
- Menu

Secondary features such as context correction, favorites, pins, automation
settings, privacy, technical details, and deletion controls live under More or
chat settings.

## Reports

Compact reports show a readable hierarchy: title, context/period metadata,
score or local-mode state, the main story, supported user pattern, main
friction/strength, one recommendation when useful, and data/limitations once.

Full analysis is a secondary action. It may include evidence panels, score
explanation, comparison, history, memory, timeline, and detailed limitations.

Report body emoji use is restrained. Buttons may use one scanning icon each;
section headings should rely mostly on text hierarchy.

## Privacy

Callback data must not include Telegram chat IDs, bot user IDs, usernames,
phone numbers, chat titles, search queries, message text, or report text. Report
buttons use per-user callback tokens in newly generated messages. Older report
ID callbacks remain accepted for backwards compatibility with existing Telegram
messages.

Deleting user data removes favorites, pins, recents, navigation state, report
callback tokens, and ranking metadata. Deleting a chat detaches associated local
UI metadata without deleting Telegram content.
