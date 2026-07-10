from __future__ import annotations

import json
import sqlite3
import uuid
from collections import deque
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from ..runtime import dt_to_iso, iso_now, json_dumps, now, parse_ts


HEARTBEAT_ENTRIES_TABLE = "heartbeat_entries"
HISENSE_HEARTBEAT_TABLE = "hisense_heartbeat"
NEXT_REQUEST_COLD_START_TAG = "__next_request__"


def _canonical_tool_call_ids_json(values: Any) -> tuple[list[str], str]:
    raw_values = values if isinstance(values, (list, tuple, set)) else [values]
    ids_set: set[str] = set()
    for item in raw_values or []:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            ids_set.add(text)
    ids = sorted(ids_set)
    return ids, json_dumps(ids)


class BaseStoreMixin:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gateway_sessions (
                    id TEXT PRIMARY KEY,
                    session_tag TEXT NOT NULL UNIQUE,
                    client_name TEXT,
                    started_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    first_message_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    context_state_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS gateway_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_name TEXT,
                    tool_args_json TEXT,
                    tool_result_summary TEXT,
                    source_table TEXT,
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    cache_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS heartbeat_entries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    turn_number INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    injected_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS hisense_heartbeat (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    turn_number INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    injected_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS request_context_snapshots (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    session_tag TEXT NOT NULL,
                    client_name TEXT,
                    messages_json TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    latest_user_text TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_request_context_snapshots_session_created
                    ON request_context_snapshots(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_request_context_snapshots_tag_created
                    ON request_context_snapshots(session_tag, created_at DESC);

                CREATE TABLE IF NOT EXISTS raw_request_windows (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    session_tag TEXT NOT NULL,
                    client_name TEXT,
                    messages_json TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    latest_user_text TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_raw_request_windows_session_created
                    ON raw_request_windows(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_raw_request_windows_tag_created
                    ON raw_request_windows(session_tag, created_at DESC);

                CREATE TABLE IF NOT EXISTS context_window_states (
                    session_id TEXT PRIMARY KEY,
                    epoch_id TEXT NOT NULL,
                    base_limit INTEGER,
                    overflow_messages INTEGER NOT NULL DEFAULT 0,
                    high_water INTEGER,
                    window_start_index INTEGER NOT NULL DEFAULT 0,
                    island_anchor_offset INTEGER NOT NULL DEFAULT 0,
                    raw_protected_turns INTEGER NOT NULL DEFAULT 0,
                    island_state_json TEXT NOT NULL DEFAULT '{}',
                    last_event_class TEXT NOT NULL DEFAULT '',
                    reset_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS context_window_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    session_tag TEXT NOT NULL,
                    event_class TEXT NOT NULL,
                    epoch_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_context_window_events_session_created
                    ON context_window_events(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_context_window_events_created
                    ON context_window_events(created_at DESC);

                CREATE TABLE IF NOT EXISTS cold_start_snapshots (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    session_tag TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    source_session_tags_json TEXT NOT NULL,
                    source_message_count INTEGER NOT NULL DEFAULT 0,
                    trigger_last_active_at TEXT,
                    injected_count INTEGER NOT NULL DEFAULT 0,
                    max_injections INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_cold_start_snapshots_session_created
                    ON cold_start_snapshots(session_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS pending_gateway_tool_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    session_tag TEXT NOT NULL,
                    client_tool_call_ids_json TEXT NOT NULL,
                    original_assistant_json TEXT NOT NULL,
                    gateway_tool_messages_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_pending_gateway_tool_turns_session
                    ON pending_gateway_tool_turns(session_id, consumed_at, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_pending_gateway_tool_turns_lookup
                    ON pending_gateway_tool_turns(session_id, consumed_at, client_tool_call_ids_json, expires_at, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_pending_gateway_tool_turns_expires
                    ON pending_gateway_tool_turns(expires_at);

                CREATE TABLE IF NOT EXISTS chat_archive_seen (
                    session_tag TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_tag, content_hash)
                );

                CREATE INDEX IF NOT EXISTS idx_chat_archive_seen_tag_created
                    ON chat_archive_seen(session_tag, created_at);

                CREATE TABLE IF NOT EXISTS config_overrides (
                    env_key TEXT PRIMARY KEY,
                    env_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_error_log (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    session_tag TEXT,
                    tool_name TEXT NOT NULL,
                    target_tool TEXT,
                    args_json TEXT,
                    error_text TEXT NOT NULL,
                    error_source TEXT NOT NULL DEFAULT 'execute',
                    error_kind TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tool_error_log_created
                    ON tool_error_log(created_at DESC);

                CREATE TABLE IF NOT EXISTS room_trace (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail_json TEXT,
                    scribble TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_room_trace_created
                    ON room_trace(created_at DESC);

                CREATE TABLE IF NOT EXISTS room_locked_drawer (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS room_scribbles (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS room_pins (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    done_at TEXT
                );

                CREATE TABLE IF NOT EXISTS room_drawer_notes (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    read_at TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, HEARTBEAT_ENTRIES_TABLE, "synced_at", "TEXT")
            self._ensure_column(conn, HISENSE_HEARTBEAT_TABLE, "synced_at", "TEXT")
            self._ensure_column(
                conn,
                "tool_error_log",
                "error_kind",
                "TEXT NOT NULL DEFAULT 'unknown'",
            )
            cold_start_active_added = self._ensure_column(
                conn,
                "cold_start_snapshots",
                "active",
                "INTEGER NOT NULL DEFAULT 1",
            )
            if cold_start_active_added:
                conn.execute(
                    """
                    UPDATE cold_start_snapshots
                    SET active = 0
                    WHERE injected_count >= max_injections
                    """
                )
            rows = conn.execute(
                "SELECT id, client_tool_call_ids_json FROM pending_gateway_tool_turns"
            ).fetchall()
            for row in rows:
                try:
                    raw_ids = json.loads(row["client_tool_call_ids_json"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    raw_ids = []
                _, canonical_json = _canonical_tool_call_ids_json(raw_ids)
                if canonical_json != row["client_tool_call_ids_json"]:
                    conn.execute(
                        "UPDATE pending_gateway_tool_turns SET client_tool_call_ids_json = ? WHERE id = ?",
                        (canonical_json, row["id"]),
                    )

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, decl: str):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            return True
        return False
