from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from .runtime import dt_to_iso, iso_now, json_dumps, now, parse_ts


HEARTBEAT_ENTRIES_TABLE = "heartbeat_entries"
HISENSE_HEARTBEAT_TABLE = "hisense_heartbeat"


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
                """
            )

    def get_or_create_session(self, session_tag: str, client_name: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_sessions WHERE session_tag = ?",
                (session_tag,),
            ).fetchone()
            if row:
                if client_name and (row["client_name"] or "") != client_name:
                    conn.execute(
                        "UPDATE gateway_sessions SET client_name = ? WHERE id = ?",
                        (client_name, row["id"]),
                    )
                    row = conn.execute("SELECT * FROM gateway_sessions WHERE id = ?", (row["id"],)).fetchone()
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
        limit = max(1, min(int(limit or 12), 5000))
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

    def get_recent_dialogue_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit or 100), 5000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gateway_messages
                WHERE session_id = ? AND role IN ('user', 'assistant')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def dedupe_messages(self, session_id: Optional[str] = None) -> dict[str, int]:
        params: list[Any] = []
        where = ""
        if session_id:
            where = "WHERE session_id = ?"
            params.append(session_id)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                DELETE FROM gateway_messages
                WHERE id IN (
                    SELECT id
                    FROM (
                        SELECT
                            id,
                            ROW_NUMBER() OVER (
                                PARTITION BY session_id, role, COALESCE(content, ''), COALESCE(tool_name, '')
                                ORDER BY created_at DESC, id DESC
                            ) AS rn
                        FROM gateway_messages
                        {where}
                    )
                    WHERE rn > 1
                )
                """,
                params,
            )
            deleted = int(cursor.rowcount or 0)
            session_filter = "WHERE id = ?" if session_id else ""
            session_params: tuple[Any, ...] = (session_id,) if session_id else ()
            rows = conn.execute(f"SELECT id FROM gateway_sessions {session_filter}", session_params).fetchall()
            for row in rows:
                sid = row["id"]
                conn.execute(
                    """
                    UPDATE gateway_sessions
                    SET message_count = (
                        SELECT COUNT(*) FROM gateway_messages WHERE session_id = ?
                    )
                    WHERE id = ?
                    """,
                    (sid, sid),
                )

            raw_cursor = conn.execute(
                f"""
                DELETE FROM raw_request_windows
                WHERE id IN (
                    SELECT id
                    FROM (
                        SELECT
                            id,
                            ROW_NUMBER() OVER (
                                PARTITION BY session_id, COALESCE(messages_json, '')
                                ORDER BY created_at DESC, id DESC
                            ) AS rn
                        FROM raw_request_windows
                        {where}
                    )
                    WHERE rn > 1
                )
                """,
                params,
            )
            raw_deleted = int(raw_cursor.rowcount or 0)
        return {"gateway_messages": deleted, "raw_request_windows": raw_deleted}

    def get_all_messages(self, session_id: str, limit: int = 5000) -> list[dict]:
        limit = max(1, min(int(limit or 5000), 50000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gateway_messages
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_latest_message_by_role(self, session_id: str, role: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM gateway_messages
                WHERE session_id = ? AND role = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id, role),
            ).fetchone()
            return dict(row) if row else None

    def get_recent_context_snapshots(self, session_id: str, limit: int = 5) -> list[dict]:
        limit = max(1, min(int(limit or 5), 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM request_context_snapshots
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        snapshots = []
        for row in rows:
            item = dict(row)
            item["messages"] = json.loads(item.get("messages_json") or "[]")
            snapshots.append(item)
        return snapshots

    def get_all_context_snapshots(self, session_id: str, limit: int = 1000) -> list[dict]:
        limit = max(1, min(int(limit or 1000), 5000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM request_context_snapshots
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        snapshots = []
        for row in rows:
            item = dict(row)
            item["messages"] = json.loads(item.get("messages_json") or "[]")
            snapshots.append(item)
        return snapshots

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
                    COALESCE(m.stored_message_count, 0) AS stored_message_count,
                    m.last_message_at,
                    COALESCE(m.user_message_count, 0) AS user_message_count,
                    COALESCE(m.assistant_message_count, 0) AS assistant_message_count,
                    COALESCE(m.tool_message_count, 0) AS tool_message_count,
                    COALESCE(r.context_snapshot_count, 0) AS context_snapshot_count,
                    COALESCE(rw.raw_request_window_count, 0) AS raw_request_window_count,
                    COALESCE(c.cold_start_snapshot_count, 0) AS cold_start_snapshot_count,
                    COALESCE(h.heartbeat_count, 0) AS heartbeat_count,
                    COALESCE(hh.hisense_heartbeat_count, 0) AS hisense_heartbeat_count,
                    latest_user.content AS latest_user_text
                FROM gateway_sessions s
                LEFT JOIN (
                    SELECT
                        session_id,
                        COUNT(id) AS stored_message_count,
                        MAX(created_at) AS last_message_at,
                        SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_message_count,
                        SUM(CASE WHEN role = 'assistant' THEN 1 ELSE 0 END) AS assistant_message_count,
                        SUM(CASE WHEN role = 'tool' THEN 1 ELSE 0 END) AS tool_message_count
                    FROM gateway_messages
                    GROUP BY session_id
                ) m ON m.session_id = s.id
                LEFT JOIN (
                    SELECT session_id, COUNT(id) AS context_snapshot_count
                    FROM request_context_snapshots
                    GROUP BY session_id
                ) r ON r.session_id = s.id
                LEFT JOIN (
                    SELECT session_id, COUNT(id) AS raw_request_window_count
                    FROM raw_request_windows
                    GROUP BY session_id
                ) rw ON rw.session_id = s.id
                LEFT JOIN (
                    SELECT session_id, COUNT(id) AS cold_start_snapshot_count
                    FROM cold_start_snapshots
                    GROUP BY session_id
                ) c ON c.session_id = s.id
                LEFT JOIN (
                    SELECT session_id, COUNT(id) AS heartbeat_count
                    FROM heartbeat_entries
                    GROUP BY session_id
                ) h ON h.session_id = s.id
                LEFT JOIN (
                    SELECT session_id, COUNT(id) AS hisense_heartbeat_count
                    FROM hisense_heartbeat
                    GROUP BY session_id
                ) hh ON hh.session_id = s.id
                LEFT JOIN gateway_messages latest_user ON latest_user.id = (
                    SELECT id FROM gateway_messages
                    WHERE session_id = s.id AND role = 'user'
                    ORDER BY created_at DESC
                    LIMIT 1
                )
                {where if query.strip() else ""}
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
            heartbeat_count = conn.execute(
                "SELECT COUNT(*) AS count FROM heartbeat_entries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            hisense_heartbeat_count = conn.execute(
                "SELECT COUNT(*) AS count FROM hisense_heartbeat WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            cold_count = conn.execute(
                "SELECT COUNT(*) AS count FROM cold_start_snapshots WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            snapshot_count = conn.execute(
                "SELECT COUNT(*) AS count FROM request_context_snapshots WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            raw_window_count = conn.execute(
                "SELECT COUNT(*) AS count FROM raw_request_windows WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return {
                "messages": int(message_counts["total"] or 0),
                "user_messages": int(message_counts["user_count"] or 0),
                "assistant_messages": int(message_counts["assistant_count"] or 0),
                "tool_messages": int(message_counts["tool_count"] or 0),
                "heartbeats": int(heartbeat_count["count"] or 0),
                "hisense_heartbeats": int(hisense_heartbeat_count["count"] or 0),
                "cold_start_snapshots": int(cold_count["count"] or 0),
                "context_snapshots": int(snapshot_count["count"] or 0),
                "raw_request_windows": int(raw_window_count["count"] or 0),
            }

    def delete_session(self, session_id: str) -> dict:
        tables = [
            "hisense_heartbeat",
            "heartbeat_entries",
            "cold_start_snapshots",
            "raw_request_windows",
            "request_context_snapshots",
            "gateway_messages",
            "gateway_sessions",
        ]
        deleted: dict[str, int] = {}
        with self._connect() as conn:
            existing_tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for legacy_table in ("frozen_windows", "conversation_summaries"):
                if legacy_table in existing_tables:
                    cursor = conn.execute(f"DELETE FROM {legacy_table} WHERE session_id = ?", (session_id,))
                    deleted[legacy_table] = int(cursor.rowcount or 0)
            for table in tables:
                if table == "gateway_sessions":
                    cursor = conn.execute("DELETE FROM gateway_sessions WHERE id = ?", (session_id,))
                else:
                    cursor = conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
                deleted[table] = int(cursor.rowcount or 0)
        return deleted

    def write_raw_request_window(
        self,
        session_id: str,
        session_tag: str,
        client_name: Optional[str],
        messages: list[dict],
        latest_user_text: str,
    ) -> dict:
        window_id = f"rrw_{uuid.uuid4().hex[:12]}"
        created_at = iso_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_request_windows (
                    id, session_id, session_tag, client_name, messages_json,
                    message_count, latest_user_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    window_id,
                    session_id,
                    session_tag,
                    client_name,
                    json_dumps(messages),
                    len(messages),
                    latest_user_text,
                    created_at,
                ),
            )
        return {
            "id": window_id,
            "session_id": session_id,
            "session_tag": session_tag,
            "client_name": client_name,
            "messages": messages,
            "message_count": len(messages),
            "latest_user_text": latest_user_text,
            "created_at": created_at,
        }

    def write_request_context_snapshot(
        self,
        session_id: str,
        session_tag: str,
        client_name: Optional[str],
        messages: list[dict],
        latest_user_text: str,
    ) -> dict:
        snapshot_id = f"rcs_{uuid.uuid4().hex[:12]}"
        created_at = iso_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO request_context_snapshots (
                    id, session_id, session_tag, client_name, messages_json,
                    message_count, latest_user_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    session_id,
                    session_tag,
                    client_name,
                    json_dumps(messages),
                    len(messages),
                    latest_user_text,
                    created_at,
                ),
            )
        return {
            "id": snapshot_id,
            "session_id": session_id,
            "session_tag": session_tag,
            "client_name": client_name,
            "messages": messages,
            "message_count": len(messages),
            "latest_user_text": latest_user_text,
            "created_at": created_at,
        }

    def get_recent_raw_request_windows(self, session_id: str, limit: int = 5) -> list[dict]:
        limit = max(1, min(int(limit or 5), 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM raw_request_windows
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        windows = []
        for row in rows:
            item = dict(row)
            item["messages"] = json.loads(item.get("messages_json") or "[]")
            windows.append(item)
        return windows

    def get_all_raw_request_windows(self, session_id: str, limit: int = 1000) -> list[dict]:
        limit = max(1, min(int(limit or 1000), 5000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM raw_request_windows
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        windows = []
        for row in rows:
            item = dict(row)
            item["messages"] = json.loads(item.get("messages_json") or "[]")
            windows.append(item)
        return windows

    def latest_request_context_snapshots(self, limit: int = 5, session_tag: Optional[str] = None) -> list[dict]:
        limit = max(1, min(int(limit or 5), 50))
        with self._connect() as conn:
            if session_tag:
                rows = conn.execute(
                    """
                    SELECT r.*, s.last_active_at, s.message_count AS stored_message_count
                    FROM request_context_snapshots r
                    JOIN gateway_sessions s ON s.id = r.session_id
                    WHERE r.session_tag = ?
                    ORDER BY r.created_at DESC
                    LIMIT 1
                    """,
                    (session_tag,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT r.*, s.last_active_at, s.message_count AS stored_message_count
                    FROM request_context_snapshots r
                    JOIN (
                        SELECT session_tag, MAX(created_at) AS latest_created_at
                        FROM request_context_snapshots
                        GROUP BY session_tag
                    ) latest
                        ON latest.session_tag = r.session_tag
                        AND latest.latest_created_at = r.created_at
                    JOIN gateway_sessions s ON s.id = r.session_id
                    ORDER BY r.created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        snapshots = []
        for row in rows:
            item = dict(row)
            item["messages"] = json.loads(item.get("messages_json") or "[]")
            snapshots.append(item)
        return snapshots

    def recent_cross_session_context(
        self,
        exclude_session_id: Optional[str],
        since: Optional[str],
        limit_messages: int = 8,
        limit_sessions: int = 4,
    ) -> list[dict]:
        limit_messages = max(1, min(int(limit_messages or 8), 50))
        limit_sessions = max(1, min(int(limit_sessions or 4), 20))
        where = []
        params: list[Any] = []
        if exclude_session_id:
            where.append("session_id != ?")
            params.append(exclude_session_id)
        if since:
            where.append("created_at > ?")
            params.append(since)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT r.*, s.session_tag AS resolved_session_tag, s.client_name AS resolved_client_name
                FROM request_context_snapshots r
                JOIN (
                    SELECT session_id, MAX(created_at) AS latest_created_at
                    FROM request_context_snapshots
                    {where_sql}
                    GROUP BY session_id
                ) latest
                    ON latest.session_id = r.session_id
                    AND latest.latest_created_at = r.created_at
                JOIN gateway_sessions s ON s.id = r.session_id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (*params, limit_sessions),
            ).fetchall()

        remaining = limit_messages
        sources = []
        for row in rows:
            item = dict(row)
            raw_messages = json.loads(item.get("messages_json") or "[]")
            messages = [
                {"role": msg.get("role"), "content": msg.get("content")}
                for msg in raw_messages
                if msg.get("role") in {"user", "assistant"} and msg.get("content")
            ]
            if not messages:
                continue
            selected = messages[-remaining:]
            remaining -= len(selected)
            sources.append(
                {
                    "session_id": item.get("session_id"),
                    "session_tag": item.get("resolved_session_tag") or item.get("session_tag"),
                    "client_name": item.get("resolved_client_name") or item.get("client_name"),
                    "snapshot_at": item.get("created_at"),
                    "latest_user_text": item.get("latest_user_text"),
                    "messages": selected,
                }
            )
            if remaining <= 0:
                break
        return sources

    def latest_cross_session_context(
        self,
        exclude_session_id: Optional[str],
        since: Optional[str],
        limit_messages: int,
    ) -> list[dict]:
        limit_messages = max(1, min(int(limit_messages or 1), 500))
        where = []
        params: list[Any] = []
        if exclude_session_id:
            where.append("r.session_id != ?")
            params.append(exclude_session_id)
        if since:
            where.append("r.created_at > ?")
            params.append(since)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT r.*, s.session_tag AS resolved_session_tag, s.client_name AS resolved_client_name
                FROM request_context_snapshots r
                JOIN gateway_sessions s ON s.id = r.session_id
                {where_sql}
                ORDER BY r.created_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if not row:
            return []

        item = dict(row)
        raw_messages = json.loads(item.get("messages_json") or "[]")
        messages = [
            {"role": msg.get("role"), "content": msg.get("content")}
            for msg in raw_messages
            if msg.get("role") in {"user", "assistant"} and msg.get("content")
        ]
        selected = messages[-limit_messages:]
        if not selected:
            return []
        return [
            {
                "session_id": item.get("session_id"),
                "session_tag": item.get("resolved_session_tag") or item.get("session_tag"),
                "client_name": item.get("resolved_client_name") or item.get("client_name"),
                "snapshot_at": item.get("created_at"),
                "latest_user_text": item.get("latest_user_text"),
                "messages": selected,
            }
        ]

    def write_cold_start_snapshot(
        self,
        session_id: str,
        session_tag: str,
        reason: str,
        sources: list[dict],
        trigger_last_active_at: Optional[str],
        max_injections: int,
    ) -> dict:
        snapshot_id = f"csnap_{uuid.uuid4().hex[:12]}"
        source_tags = sorted({source.get("session_tag") for source in sources if source.get("session_tag")})
        source_message_count = sum(len(source.get("messages") or []) for source in sources)
        created_at = iso_now()
        row = {
            "id": snapshot_id,
            "session_id": session_id,
            "session_tag": session_tag,
            "reason": reason,
            "sources": sources,
            "source_session_tags": source_tags,
            "source_message_count": source_message_count,
            "trigger_last_active_at": trigger_last_active_at,
            "injected_count": 0,
            "max_injections": max(1, int(max_injections or 1)),
            "created_at": created_at,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cold_start_snapshots (
                    id, session_id, session_tag, reason, sources_json,
                    source_session_tags_json, source_message_count,
                    trigger_last_active_at, injected_count, max_injections, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    snapshot_id,
                    session_id,
                    session_tag,
                    reason,
                    json_dumps(sources),
                    json_dumps(source_tags),
                    source_message_count,
                    trigger_last_active_at,
                    row["max_injections"],
                    created_at,
                ),
            )
        return row

    def latest_active_cold_start_snapshot(self, session_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM cold_start_snapshots
                WHERE session_id = ? AND injected_count < max_injections
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["sources"] = json.loads(item.get("sources_json") or "[]")
        item["source_session_tags"] = json.loads(item.get("source_session_tags_json") or "[]")
        return item

    def mark_cold_start_injected(self, snapshot_id: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE cold_start_snapshots
                SET injected_count = injected_count + 1
                WHERE id = ? AND injected_count < max_injections
                """,
                (snapshot_id,),
            )

    def complete_cold_start_snapshot(self, snapshot_id: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE cold_start_snapshots
                SET injected_count = max_injections
                WHERE id = ?
                """,
                (snapshot_id,),
            )

    def latest_cold_start_snapshot(self, session_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM cold_start_snapshots
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["sources"] = json.loads(item.get("sources_json") or "[]")
        item["source_session_tags"] = json.loads(item.get("source_session_tags_json") or "[]")
        return item

    def recent_cold_start_snapshots(self, session_id: str, limit: int = 5) -> list[dict]:
        limit = max(1, min(int(limit or 5), 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM cold_start_snapshots
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        snapshots = []
        for row in rows:
            item = dict(row)
            item["sources"] = json.loads(item.get("sources_json") or "[]")
            item["source_session_tags"] = json.loads(item.get("source_session_tags_json") or "[]")
            snapshots.append(item)
        return snapshots

    def all_cold_start_snapshots(self, session_id: str, limit: int = 1000) -> list[dict]:
        limit = max(1, min(int(limit or 1000), 5000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM cold_start_snapshots
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        snapshots = []
        for row in rows:
            item = dict(row)
            item["sources"] = json.loads(item.get("sources_json") or "[]")
            item["source_session_tags"] = json.loads(item.get("source_session_tags_json") or "[]")
            snapshots.append(item)
        return snapshots

    def gateway_overview(self) -> dict:
        today = now().date().isoformat()
        with self._connect() as conn:
            message_counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS today,
                    MIN(created_at) AS earliest,
                    MAX(created_at) AS latest
                FROM gateway_messages
                """,
                (today,),
            ).fetchone()
            session_count = conn.execute("SELECT COUNT(*) AS count FROM gateway_sessions").fetchone()
            cold_count = conn.execute("SELECT COUNT(*) AS count FROM cold_start_snapshots").fetchone()
            snapshot_count = conn.execute("SELECT COUNT(*) AS count FROM request_context_snapshots").fetchone()
            raw_window_count = conn.execute("SELECT COUNT(*) AS count FROM raw_request_windows").fetchone()
            heartbeat_count = conn.execute("SELECT COUNT(*) AS count FROM heartbeat_entries").fetchone()
            hisense_heartbeat_count = conn.execute("SELECT COUNT(*) AS count FROM hisense_heartbeat").fetchone()
            cache_count = conn.execute("SELECT COUNT(*) AS count FROM cache_entries").fetchone()
        return {
            "messages_total": int(message_counts["total"] or 0),
            "messages_today": int(message_counts["today"] or 0),
            "earliest_message_at": message_counts["earliest"],
            "latest_message_at": message_counts["latest"],
            "sessions_total": int(session_count["count"] or 0),
            "cold_start_snapshots": int(cold_count["count"] or 0),
            "context_snapshots": int(snapshot_count["count"] or 0),
            "raw_request_windows": int(raw_window_count["count"] or 0),
            "heartbeats": int(heartbeat_count["count"] or 0),
            "hisense_heartbeats": int(hisense_heartbeat_count["count"] or 0),
            "cache_entries": int(cache_count["count"] or 0),
        }

    def prune_runtime_state(
        self,
        session_id: Optional[str] = None,
        message_retention: int = 2000,
        context_snapshot_retention: int = 3,
        raw_window_retention: Optional[int] = None,
        cold_start_retention: int = 20,
    ) -> dict[str, int]:
        message_retention = max(1, int(message_retention or 2000))
        context_snapshot_retention = max(1, int(context_snapshot_retention or 3))
        raw_window_retention = max(1, int(raw_window_retention or context_snapshot_retention))
        cold_start_retention = max(1, int(cold_start_retention or 20))
        deleted = {
            "gateway_messages": 0,
            "request_context_snapshots": 0,
            "raw_request_windows": 0,
            "cold_start_snapshots": 0,
            "cache_entries": 0,
        }
        session_filter = "WHERE id = ?" if session_id else ""
        session_params: tuple[Any, ...] = (session_id,) if session_id else ()
        with self._connect() as conn:
            session_rows = conn.execute(f"SELECT id FROM gateway_sessions {session_filter}", session_params).fetchall()
            for row in session_rows:
                sid = row["id"]
                cursor = conn.execute(
                    """
                    DELETE FROM gateway_messages
                    WHERE session_id = ?
                    AND id NOT IN (
                        SELECT id FROM gateway_messages
                        WHERE session_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                    """,
                    (sid, sid, message_retention),
                )
                deleted["gateway_messages"] += int(cursor.rowcount or 0)
                conn.execute(
                    """
                    UPDATE gateway_sessions
                    SET message_count = (
                        SELECT COUNT(*) FROM gateway_messages WHERE session_id = ?
                    )
                    WHERE id = ?
                    """,
                    (sid, sid),
                )

                cursor = conn.execute(
                    """
                    DELETE FROM request_context_snapshots
                    WHERE session_id = ?
                    AND id NOT IN (
                        SELECT id FROM request_context_snapshots
                        WHERE session_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                    """,
                    (sid, sid, context_snapshot_retention),
                )
                deleted["request_context_snapshots"] += int(cursor.rowcount or 0)

                cursor = conn.execute(
                    """
                    DELETE FROM raw_request_windows
                    WHERE session_id = ?
                    AND id NOT IN (
                        SELECT id FROM raw_request_windows
                        WHERE session_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                    """,
                    (sid, sid, raw_window_retention),
                )
                deleted["raw_request_windows"] += int(cursor.rowcount or 0)

                cursor = conn.execute(
                    """
                    DELETE FROM cold_start_snapshots
                    WHERE session_id = ?
                    AND injected_count >= max_injections
                    AND id NOT IN (
                        SELECT id FROM cold_start_snapshots
                        WHERE session_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                    """,
                    (sid, sid, cold_start_retention),
                )
                deleted["cold_start_snapshots"] += int(cursor.rowcount or 0)

            cursor = conn.execute("DELETE FROM cache_entries WHERE expires_at < ?", (iso_now(),))
            deleted["cache_entries"] = int(cursor.rowcount or 0)
        return deleted

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

    def _heartbeat_table(self, hisense: bool = False) -> str:
        return HISENSE_HEARTBEAT_TABLE if hisense else HEARTBEAT_ENTRIES_TABLE

    def append_heartbeat(self, session_id: str, content: str, turn_number: int = 0, hisense: bool = False) -> dict:
        table = self._heartbeat_table(hisense)
        heartbeat_id = f"{'hhb' if hisense else 'hb'}_{uuid.uuid4().hex[:12]}"
        created_at = iso_now()
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {table} (id, session_id, content, turn_number, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (heartbeat_id, session_id, content, turn_number, created_at),
            )
        return {
            "id": heartbeat_id,
            "session_id": session_id,
            "content": content,
            "turn_number": turn_number,
            "created_at": created_at,
            "injected_at": None,
        }

    def get_pending_heartbeats(self, session_id: Optional[str] = None, limit: int = 10, hisense: bool = False) -> list[dict]:
        table = self._heartbeat_table(hisense)
        where = "injected_at IS NULL"
        params: list[Any] = []
        if session_id:
            where = "session_id = ? AND " + where
            params.append(session_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {table}
                WHERE {where}
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_heartbeats_injected(
        self,
        session_id: Optional[str] = None,
        heartbeat_ids: Optional[list[str]] = None,
        hisense: bool = False,
    ):
        table = self._heartbeat_table(hisense)
        heartbeat_ids = [item for item in (heartbeat_ids or []) if item]
        if not heartbeat_ids:
            return
        placeholders = ",".join("?" for _ in heartbeat_ids)
        where = f"injected_at IS NULL AND id IN ({placeholders})"
        params: list[Any] = [*heartbeat_ids]
        if session_id:
            where = "session_id = ? AND " + where
            params.insert(0, session_id)
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {table}
                SET injected_at = ?
                WHERE {where}
                """,
                (iso_now(), *params),
            )

    def get_latest_heartbeat_digest(self, session_id: Optional[str] = None, limit: int = 10, hisense: bool = False) -> str:
        table = self._heartbeat_table(hisense)
        where = "injected_at IS NOT NULL"
        params: list[Any] = []
        if session_id:
            where = "session_id = ? AND " + where
            params.append(session_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT content FROM {table}
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            if not rows:
                return ""
            return "\n".join(row["content"] for row in reversed(rows))

    def read_heartbeats(
        self,
        session_id: Optional[str],
        state: str = "all",
        limit: int = 10,
        order: str = "desc",
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        hisense: bool = False,
    ) -> list[dict]:
        table = self._heartbeat_table(hisense)
        state = (state or "all").strip().lower()
        order_sql = "ASC" if (order or "").strip().lower() == "asc" else "DESC"
        where = "1=1"
        params: list[Any] = []
        if session_id:
            where += " AND session_id = ?"
            params.append(session_id)
        if state == "pending":
            where += " AND injected_at IS NULL"
        elif state == "injected":
            where += " AND injected_at IS NOT NULL"
        if created_from:
            where += " AND created_at >= ?"
            params.append(created_from)
        if created_to:
            where += " AND created_at < ?"
            params.append(created_to)
        limit = max(1, min(int(limit or 10), 500))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {table}
                WHERE {where}
                ORDER BY created_at {order_sql}
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_heartbeats(
        self,
        session_id: Optional[str] = None,
        heartbeat_ids: Optional[list[str]] = None,
        delete_all: bool = False,
        hisense: bool = False,
    ) -> int:
        table = self._heartbeat_table(hisense)
        heartbeat_ids = [item for item in (heartbeat_ids or []) if item]
        with self._connect() as conn:
            if delete_all:
                if session_id:
                    cursor = conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
                else:
                    cursor = conn.execute(f"DELETE FROM {table}")
                return int(cursor.rowcount or 0)
            if not heartbeat_ids:
                return 0
            placeholders = ",".join("?" for _ in heartbeat_ids)
            if session_id:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE session_id = ? AND id IN ({placeholders})",
                    (session_id, *heartbeat_ids),
                )
            else:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE id IN ({placeholders})",
                    tuple(heartbeat_ids),
                )
            return int(cursor.rowcount or 0)

    def get_all_heartbeats(self, session_id: Optional[str] = None, hisense: bool = False) -> list[dict]:
        table = self._heartbeat_table(hisense)
        where = ""
        params: tuple[Any, ...] = ()
        if session_id:
            where = "WHERE session_id = ?"
            params = (session_id,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {table}
                {where}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def export_session_bundle(self, session_tag: str) -> Optional[dict]:
        session = self.get_session_by_tag(session_tag)
        if not session:
            return None
        session_id = session["id"]
        return {
            "exported_at": iso_now(),
            "session": session,
            "stats": self.get_session_stats(session_id),
            "messages": self.get_all_messages(session_id),
            "context_snapshots": self.get_all_context_snapshots(session_id),
            "raw_request_windows": self.get_all_raw_request_windows(session_id),
            "cold_start_snapshots": self.all_cold_start_snapshots(session_id),
            "heartbeats": self.get_all_heartbeats(session_id),
            "hisense_heartbeats": self.get_all_heartbeats(session_id, hisense=True),
        }
