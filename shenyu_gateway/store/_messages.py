from __future__ import annotations

import uuid
from typing import Any, Optional

from ..runtime import iso_now, json_dumps


class MessagesMixin:

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

    def get_message_count(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM gateway_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return int(row["count"]) if row else 0

    def count_messages_since(self, session_id: str, since: str, role: Optional[str] = None) -> int:
        where = "session_id = ? AND created_at > ?"
        params: list[Any] = [session_id, since]
        if role:
            where += " AND role = ?"
            params.append(role)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM gateway_messages WHERE {where}",
                tuple(params),
            ).fetchone()
            return int(row["count"]) if row else 0
