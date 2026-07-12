from __future__ import annotations

import uuid
from typing import Any, Optional

from ..runtime import iso_now


class SessionsMixin:
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
            pending_count = conn.execute(
                "SELECT COUNT(*) AS count FROM pending_gateway_tool_turns WHERE session_id = ? AND consumed_at IS NULL",
                (session_id,),
            ).fetchone()
            window_event_count = conn.execute(
                "SELECT COUNT(*) AS count FROM context_window_events WHERE session_id = ?",
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
                "pending_gateway_tool_turns": int(pending_count["count"] or 0),
                "context_window_events": int(window_event_count["count"] or 0),
            }

    def delete_session(self, session_id: str) -> dict:
        tables = [
            "context_window_events",
            "context_window_states",
            "tool_error_log",
            "room_trace",
            "hisense_heartbeat",
            "heartbeat_entries",
            "pending_gateway_tool_turns",
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
