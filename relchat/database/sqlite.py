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

CREATE TABLE IF NOT EXISTS message_owners (
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(bot_user_id, source, chat_id, message_id)
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

CREATE INDEX IF NOT EXISTS idx_message_owners_user_chat
  ON message_owners(bot_user_id, source, chat_id);

CREATE TABLE IF NOT EXISTS bot_user_profiles (
  bot_user_id INTEGER PRIMARY KEY,
  onboarding_completed INTEGER NOT NULL DEFAULT 0,
  language TEXT NOT NULL DEFAULT 'en',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_settings (
  bot_user_id INTEGER PRIMARY KEY,
  language TEXT NOT NULL DEFAULT 'en',
  default_period TEXT NOT NULL DEFAULT '30d',
  default_modules TEXT NOT NULL DEFAULT '["balance","initiation","response_times","activity","questions","plans","followups","reminders"]',
  progress_notifications INTEGER NOT NULL DEFAULT 1,
  show_technical_details INTEGER NOT NULL DEFAULT 0,
  data_retention_days INTEGER,
  confirm_before_delete INTEGER NOT NULL DEFAULT 1,
  automatic_analysis_master_enabled INTEGER NOT NULL DEFAULT 0,
  automatic_default_notification_enabled INTEGER NOT NULL DEFAULT 1,
  automatic_default_minimum_new_messages INTEGER NOT NULL DEFAULT 10,
  automatic_default_inactivity_minutes INTEGER NOT NULL DEFAULT 45,
  automatic_default_cooldown_hours INTEGER NOT NULL DEFAULT 12,
  automatic_default_quiet_hours_enabled INTEGER NOT NULL DEFAULT 1,
  automatic_default_quiet_hours_start TEXT NOT NULL DEFAULT '23:00',
  automatic_default_quiet_hours_end TEXT NOT NULL DEFAULT '08:00',
  automatic_default_preferred_analysis_mode TEXT NOT NULL DEFAULT 'local',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_chats (
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  chat_type TEXT NOT NULL,
  display_title TEXT,
  local_title TEXT,
  username TEXT,
  folder_id INTEGER,
  last_message_at TEXT,
  unread_count INTEGER NOT NULL DEFAULT 0,
  is_saved INTEGER NOT NULL DEFAULT 0,
  is_favorite INTEGER NOT NULL DEFAULT 0,
  recent_analyzed_at TEXT,
  last_report_id TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(bot_user_id, source, chat_id)
);

CREATE TABLE IF NOT EXISTS dialog_folders (
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  folder_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(bot_user_id, source, folder_id)
);

CREATE TABLE IF NOT EXISTS dialog_folder_memberships (
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  folder_id INTEGER NOT NULL,
  chat_id TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(bot_user_id, source, folder_id, chat_id)
);

CREATE TABLE IF NOT EXISTS analysis_jobs (
  job_id TEXT PRIMARY KEY,
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  chat_title TEXT,
  period_id TEXT NOT NULL,
  period_label TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT,
  modules TEXT NOT NULL,
  status TEXT NOT NULL,
  progress_percent INTEGER NOT NULL DEFAULT 0,
  imported_message_count INTEGER NOT NULL DEFAULT 0,
  error_reference TEXT,
  error_message TEXT,
  report_id TEXT,
  progress_chat_id INTEGER,
  progress_message_id INTEGER,
  analysis_mode TEXT NOT NULL DEFAULT 'local',
  ai_analysis_id TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TEXT,
  completed_at TEXT,
  elapsed_seconds INTEGER
);

CREATE TABLE IF NOT EXISTS ai_consents (
  bot_user_id INTEGER NOT NULL,
  consent_type TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  accepted_at TEXT,
  revoked_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(bot_user_id, consent_type, policy_version)
);

CREATE TABLE IF NOT EXISTS ai_analyses (
  analysis_id TEXT PRIMARY KEY,
  bot_user_id INTEGER NOT NULL,
  report_id TEXT,
  job_id TEXT,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  chat_title TEXT,
  model_name TEXT,
  analysis_mode TEXT NOT NULL DEFAULT 'ai',
  status TEXT NOT NULL,
  period_id TEXT,
  period_label TEXT,
  period_start TEXT,
  period_end TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  message_count_sent INTEGER NOT NULL DEFAULT 0,
  char_count_sent INTEGER NOT NULL DEFAULT 0,
  coverage TEXT NOT NULL DEFAULT '{}',
  result_json TEXT,
  dimensions_json TEXT NOT NULL DEFAULT '{}',
  overall_score REAL,
  confidence TEXT,
  consent_version TEXT,
  token_usage TEXT,
  error_code TEXT
);

CREATE TABLE IF NOT EXISTS reports (
  report_id TEXT PRIMARY KEY,
  bot_user_id INTEGER NOT NULL,
  job_id TEXT,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  chat_title TEXT,
  period_id TEXT NOT NULL,
  period_label TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  imported_message_count INTEGER NOT NULL DEFAULT 0,
  modules TEXT NOT NULL,
  job_status TEXT NOT NULL,
  metrics_summary TEXT NOT NULL,
  event_summary TEXT NOT NULL,
  data_quality TEXT NOT NULL,
  is_favorite INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reminders (
  reminder_id TEXT PRIMARY KEY,
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT,
  chat_title TEXT,
  report_id TEXT,
  event_type TEXT,
  title TEXT NOT NULL,
  reminder_time TEXT,
  status TEXT NOT NULL DEFAULT 'suggested',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS important_chat_settings (
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  is_important INTEGER NOT NULL DEFAULT 0,
  automatic_analysis_enabled INTEGER NOT NULL DEFAULT 0,
  automatic_notification_enabled INTEGER NOT NULL DEFAULT 1,
  minimum_new_messages INTEGER,
  inactivity_threshold_minutes INTEGER,
  cooldown_hours INTEGER,
  quiet_hours_enabled INTEGER NOT NULL DEFAULT 1,
  quiet_hours_start TEXT,
  quiet_hours_end TEXT,
  preferred_analysis_mode TEXT,
  automatic_delivery_mode TEXT NOT NULL DEFAULT 'suggest',
  last_automatic_analysis_at TEXT,
  last_observed_message_at TEXT,
  last_automatic_message_id INTEGER,
  automation_paused_until TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(bot_user_id, source, chat_id)
);

CREATE TABLE IF NOT EXISTS automation_states (
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  observed_message_cursor INTEGER,
  last_observed_message_at TEXT,
  last_automatic_message_id INTEGER,
  last_automatic_analysis_at TEXT,
  last_notification_at TEXT,
  pending_new_message_count INTEGER NOT NULL DEFAULT 0,
  pending_range_start_message_id INTEGER,
  pending_range_end_message_id INTEGER,
  pending_deliver_after TEXT,
  last_pause_candidate_at TEXT,
  suppressed_reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(bot_user_id, source, chat_id)
);

CREATE TABLE IF NOT EXISTS automatic_analysis_ranges (
  range_id TEXT PRIMARY KEY,
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  start_message_id INTEGER NOT NULL,
  end_message_id INTEGER NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0,
  action TEXT NOT NULL,
  analysis_id TEXT,
  report_id TEXT,
  completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(bot_user_id, source, chat_id, start_message_id, end_message_id)
);

CREATE TABLE IF NOT EXISTS pending_automatic_notifications (
  notification_id TEXT PRIMARY KEY,
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  chat_title TEXT,
  range_start_message_id INTEGER NOT NULL,
  range_end_message_id INTEGER NOT NULL,
  notification_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  deliver_after TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS period_comparisons (
  comparison_id TEXT PRIMARY KEY,
  bot_user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram',
  chat_id TEXT NOT NULL,
  comparison_type TEXT NOT NULL,
  current_report_id TEXT,
  previous_report_id TEXT,
  current_analysis_id TEXT,
  previous_analysis_id TEXT,
  status TEXT NOT NULL,
  quality TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_chats_user_saved
  ON user_chats(bot_user_id, is_saved, updated_at);

CREATE INDEX IF NOT EXISTS idx_user_chats_user_favorite
  ON user_chats(bot_user_id, is_favorite, updated_at);

CREATE INDEX IF NOT EXISTS idx_dialog_folder_memberships_user_folder
  ON dialog_folder_memberships(bot_user_id, source, folder_id);

CREATE INDEX IF NOT EXISTS idx_analysis_jobs_user_status
  ON analysis_jobs(bot_user_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_ai_analyses_user_chat
  ON ai_analyses(bot_user_id, source, chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_reports_user_created
  ON reports(bot_user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_reports_user_chat
  ON reports(bot_user_id, source, chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_reminders_user_status
  ON reminders(bot_user_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_important_chats_user
  ON important_chat_settings(bot_user_id, is_important, updated_at);

CREATE INDEX IF NOT EXISTS idx_automation_states_user_chat
  ON automation_states(bot_user_id, source, chat_id);

CREATE INDEX IF NOT EXISTS idx_pending_automatic_notifications_due
  ON pending_automatic_notifications(status, deliver_after);

CREATE INDEX IF NOT EXISTS idx_period_comparisons_user_chat
  ON period_comparisons(bot_user_id, source, chat_id, created_at);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    ensure_private_parent(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        pre_migrate_legacy_schema(conn)
        conn.executescript(SCHEMA)
        migrate_schema(conn)


def pre_migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    if table_exists(conn, "chats"):
        ensure_column(conn, "chats", "source", "TEXT NOT NULL DEFAULT 'telegram'")
    if table_exists(conn, "messages"):
        ensure_column(conn, "messages", "source", "TEXT NOT NULL DEFAULT 'telegram'")


def migrate_schema(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "chats", "source", "TEXT NOT NULL DEFAULT 'telegram'")
    ensure_column(conn, "messages", "source", "TEXT NOT NULL DEFAULT 'telegram'")
    ensure_column(conn, "user_chats", "username", "TEXT")
    ensure_column(conn, "user_chats", "folder_id", "INTEGER")
    ensure_column(conn, "user_chats", "last_message_at", "TEXT")
    ensure_column(conn, "user_chats", "unread_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "user_chats", "recent_analyzed_at", "TEXT")
    ensure_column(conn, "user_chats", "last_report_id", "TEXT")
    ensure_column(conn, "user_settings", "automatic_analysis_master_enabled", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "user_settings", "automatic_default_notification_enabled", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "user_settings", "automatic_default_minimum_new_messages", "INTEGER NOT NULL DEFAULT 10")
    ensure_column(conn, "user_settings", "automatic_default_inactivity_minutes", "INTEGER NOT NULL DEFAULT 45")
    ensure_column(conn, "user_settings", "automatic_default_cooldown_hours", "INTEGER NOT NULL DEFAULT 12")
    ensure_column(conn, "user_settings", "automatic_default_quiet_hours_enabled", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "user_settings", "automatic_default_quiet_hours_start", "TEXT NOT NULL DEFAULT '23:00'")
    ensure_column(conn, "user_settings", "automatic_default_quiet_hours_end", "TEXT NOT NULL DEFAULT '08:00'")
    ensure_column(conn, "user_settings", "automatic_default_preferred_analysis_mode", "TEXT NOT NULL DEFAULT 'local'")
    ensure_column(conn, "analysis_jobs", "progress_chat_id", "INTEGER")
    ensure_column(conn, "analysis_jobs", "progress_message_id", "INTEGER")
    ensure_column(conn, "analysis_jobs", "elapsed_seconds", "INTEGER")
    ensure_column(conn, "analysis_jobs", "analysis_mode", "TEXT NOT NULL DEFAULT 'local'")
    ensure_column(conn, "analysis_jobs", "ai_analysis_id", "TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_source_chat ON chats(source, chat_id)")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_source_chat_message
          ON messages(source, chat_id, message_id)
        """
    )


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in columns:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
