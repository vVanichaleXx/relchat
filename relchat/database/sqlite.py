from __future__ import annotations

import sqlite3
from pathlib import Path

from relchat.utils.files import ensure_private_parent


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS chats (
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  chat_type TEXT NOT NULL,
  chat_title TEXT,
  selected_for_analysis INTEGER NOT NULL DEFAULT 0,
  import_range_start TEXT,
  import_range_end TEXT,
  last_imported_message_id INTEGER,
  live_updates_enabled INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(source, chat_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL DEFAULT 'telegram',
  message_id INTEGER NOT NULL,
  chat_id TEXT NOT NULL,
  sender_id TEXT,
  sender_name TEXT,
  timestamp TEXT NOT NULL,
  text TEXT,
  message_type TEXT NOT NULL,
  reply_to_message_id INTEGER,
  reactions TEXT,
  media_type TEXT,
  media_duration REAL,
  forward_info TEXT,
  edit_date TEXT,
  is_outgoing INTEGER NOT NULL,
  raw_platform_payload_reference TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source, chat_id, message_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_source_chat
  ON chats(source, chat_id);

CREATE INDEX IF NOT EXISTS idx_messages_chat_time
  ON messages(chat_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_messages_chat_sender
  ON messages(chat_id, sender_id);

CREATE INDEX IF NOT EXISTS idx_messages_source_chat_time
  ON messages(source, chat_id, timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_source_chat_message
  ON messages(source, chat_id, message_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    ensure_private_parent(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        migrate_schema(conn)


def migrate_schema(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "chats", "source", "TEXT NOT NULL DEFAULT 'telegram'")
    ensure_column(conn, "messages", "source", "TEXT NOT NULL DEFAULT 'telegram'")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_source_chat ON chats(source, chat_id)")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_source_chat_message
          ON messages(source, chat_id, message_id)
        """
    )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in columns:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
