from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from .runtime import dt_to_iso, iso_now, json_dumps, now, parse_ts


class GatewayStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gateway_sessions (
                    id TEXT PRIMARY KEY,
                    session_tag TEXT NOT NULL UNIQUE,
                    client_name TEXT,
                    started_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    first_message_at TEXT NOT NULL,
                    last_summary_at TEXT,
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

                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    summary_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    covered_message_from INTEGER,
                    covered_message_to INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS frozen_windows (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    window_index INTEGER NOT NULL,
                    messages_json TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    retired_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES gateway_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS surface_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    trigger_text TEXT NOT NULL,
                    surfaced_type TEXT NOT NULL,
                    surfaced_ids_json TEXT NOT NULL,
                    chosen_ids_json TEXT,
                    reasons_json TEXT,
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
                """
            )

    def get_or_create_session(self, session_tag: str, client_name: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_sessions WHERE session_tag = ?",
                (session_tag,),
            ).fetchone()
            if row:
                return dict(row)

            session_id = f"gs_{uuid.uuid4().hex[:12]}"
            timestamp = iso_now()
            conn.execute(
                """
                INSERT INTO gateway_sessions (
                    id, session_tag, client_name, started_at, last_active_at,
                    first_message_at, message_count, context_state_json
                ) VALUES (?, ?, ?, ?, ?, ?, 0, '{}')
                """,
                (session_id, session_tag, client_name, timestamp, timestamp, timestamp),
            )
            row = conn.execute("SELECT * FROM gateway_sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row)

    def touch_session(self, session_id: str, message_increment: int = 0):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE gateway_sessions
                SET last_active_at = ?, message_count = message_count + ?
                WHERE id = ?
                """,
                (iso_now(), message_increment, session_id),
            )

    def update_summary_marker(self, session_id: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE gateway_sessions SET last_summary_at = ? WHERE id = ?",
                (iso_now(), session_id),
            )

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_name: Optional[str] = None,
        tool_args: Optional[dict] = None,
        tool_result_summary: Optional[str] = None,
        source_table: Optional[str] = None,
        source_id: Optional[str] = None,
    ):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_messages (
                    id, session_id, role, content, tool_name, tool_args_json,
                    tool_result_summary, source_table, source_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"gm_{uuid.uuid4().hex[:12]}",
                    session_id,
                    role,
                    content,
                    tool_name,
                    json_dumps(tool_args) if tool_args is not None else None,
                    tool_result_summary,
                    source_table,
                    source_id,
                    iso_now(),
                ),
            )

    def get_recent_messages(self, session_id: str, limit: int = 12) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gateway_messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def get_message_count(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM gateway_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return int(row["count"]) if row else 0

    def list_sessions(self, limit: int = 100, query: str = "") -> list[dict]:
        limit = max(1, min(int(limit or 100), 500))
        pattern = f"%{query.strip()}%"
        where = "WHERE s.session_tag LIKE ? OR COALESCE(s.client_name, '') LIKE ?"
        params: tuple[Any, ...] = (pattern, pattern, limit) if query.strip() else (limit,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    s.*,
                    COUNT(m.id) AS stored_message_count,
                    MAX(m.created_at) AS last_message_at,
                    SUM(CASE WHEN m.role = 'user' THEN 1 ELSE 0 END) AS user_message_count,
                    SUM(CASE WHEN m.role = 'assistant' THEN 1 ELSE 0 END) AS assistant_message_count,
                    SUM(CASE WHEN m.role = 'tool' THEN 1 ELSE 0 END) AS tool_message_count
                FROM gateway_sessions s
                LEFT JOIN gateway_messages m ON m.session_id = s.id
                {where if query.strip() else ""}
                GROUP BY s.id
                ORDER BY s.last_active_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_session_by_tag(self, session_tag: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_sessions WHERE session_tag = ?",
                (session_tag,),
            ).fetchone()
            return dict(row) if row else None

    def get_session_stats(self, session_id: str) -> dict:
        with self._connect() as conn:
            message_counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_count,
                    SUM(CASE WHEN role = 'assistant' THEN 1 ELSE 0 END) AS assistant_count,
                    SUM(CASE WHEN role = 'tool' THEN 1 ELSE 0 END) AS tool_count
                FROM gateway_messages
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            summary_count = conn.execute(
                "SELECT COUNT(*) AS count FROM conversation_summaries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            frozen_count = conn.execute(
                "SELECT COUNT(*) AS count FROM frozen_windows WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            surface_count = conn.execute(
                "SELECT COUNT(*) AS count FROM surface_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            heartbeat_count = conn.execute(
                "SELECT COUNT(*) AS count FROM heartbeat_entries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return {
                "messages": int(message_counts["total"] or 0),
                "user_messages": int(message_counts["user_count"] or 0),
                "assistant_messages": int(message_counts["assistant_count"] or 0),
                "tool_messages": int(message_counts["tool_count"] or 0),
                "summaries": int(summary_count["count"] or 0),
                "frozen_windows": int(frozen_count["count"] or 0),
                "surface_events": int(surface_count["count"] or 0),
                "heartbeats": int(heartbeat_count["count"] or 0),
            }

    def delete_session(self, session_id: str) -> dict:
        tables = [
            "heartbeat_entries",
            "surface_events",
            "frozen_windows",
            "conversation_summaries",
            "gateway_messages",
            "gateway_sessions",
        ]
        deleted: dict[str, int] = {}
        with self._connect() as conn:
            for table in tables:
                if table == "gateway_sessions":
                    cursor = conn.execute("DELETE FROM gateway_sessions WHERE id = ?", (session_id,))
                else:
                    cursor = conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
                deleted[table] = int(cursor.rowcount or 0)
        return deleted

    def write_summary(
        self,
        session_id: str,
        summary_type: str,
        content: str,
        covered_from: Optional[int],
        covered_to: Optional[int],
    ):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_summaries (
                    id, session_id, summary_type, content,
                    covered_message_from, covered_message_to, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"cs_{uuid.uuid4().hex[:12]}",
                    session_id,
                    summary_type,
                    content,
                    covered_from,
                    covered_to,
                    iso_now(),
                ),
            )
        self.update_summary_marker(session_id)

    def latest_summary(self, session_id: str, summary_type: str = "rolling") -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM conversation_summaries
                WHERE session_id = ? AND summary_type = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id, summary_type),
            ).fetchone()
            return dict(row) if row else None

    def write_frozen_window(self, session_id: str, messages: list[dict], token_estimate: int):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(window_index), 0) AS max_idx FROM frozen_windows WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            next_index = int(row["max_idx"]) + 1 if row else 1
            conn.execute(
                """
                INSERT INTO frozen_windows (
                    id, session_id, window_index, messages_json,
                    token_estimate, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"fw_{uuid.uuid4().hex[:12]}",
                    session_id,
                    next_index,
                    json_dumps(messages),
                    token_estimate,
                    iso_now(),
                ),
            )

    def latest_frozen_window(self, session_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM frozen_windows
                WHERE session_id = ?
                ORDER BY window_index DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["messages"] = json.loads(item["messages_json"])
            return item

    def write_surface_event(
        self,
        session_id: str,
        trigger_text: str,
        surfaced_type: str,
        surfaced_items: list[dict],
        reasons: Optional[list[str]] = None,
    ):
        ids = []
        for item in surfaced_items:
            if item.get("source_id"):
                ids.append(f"{item.get('source_table')}:{item.get('source_id')}")
            elif item.get("id"):
                ids.append(str(item["id"]))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO surface_events (
                    id, session_id, trigger_text, surfaced_type,
                    surfaced_ids_json, chosen_ids_json, reasons_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"se_{uuid.uuid4().hex[:12]}",
                    session_id,
                    trigger_text,
                    surfaced_type,
                    json_dumps(ids),
                    None,
                    json_dumps(reasons or []),
                    iso_now(),
                ),
            )

    def cache_get(self, key: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cache_entries WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            expires_at = parse_ts(row["expires_at"])
            if expires_at and expires_at < now():
                conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
                return None
            return {
                "cache_key": row["cache_key"],
                "cache_type": row["cache_type"],
                "payload": json.loads(row["payload_json"]),
                "expires_at": row["expires_at"],
            }

    def cache_set(self, key: str, cache_type: str, payload: Any, ttl_minutes: int):
        expires_at = now() + timedelta(minutes=ttl_minutes)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache_entries (
                    cache_key, cache_type, payload_json, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    cache_type = excluded.cache_type,
                    payload_json = excluded.payload_json,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at
                """,
                (key, cache_type, json_dumps(payload), dt_to_iso(expires_at), iso_now()),
            )

    def append_heartbeat(self, session_id: str, content: str, turn_number: int = 0):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO heartbeat_entries (id, session_id, content, turn_number, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"hb_{uuid.uuid4().hex[:12]}", session_id, content, turn_number, iso_now()),
            )

    def get_pending_heartbeats(self, session_id: str, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM heartbeat_entries
                WHERE session_id = ? AND injected_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def mark_heartbeats_injected(self, session_id: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE heartbeat_entries
                SET injected_at = ?
                WHERE session_id = ? AND injected_at IS NULL
                """,
                (iso_now(), session_id),
            )

    def get_latest_heartbeat_digest(self, session_id: str, limit: int = 10) -> str:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT content FROM heartbeat_entries
                WHERE session_id = ? AND injected_at IS NOT NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            if not rows:
                return ""
            return "\n".join(row["content"] for row in reversed(rows))
