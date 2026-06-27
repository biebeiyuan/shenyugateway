from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from typing import Any, Optional

from ..runtime import dt_to_iso, iso_now, json_dumps, now
from ._base import _canonical_tool_call_ids_json


class PendingTurnsMixin:

    def _pending_gateway_tool_turn_from_row(self, row: sqlite3.Row | dict) -> dict:
        item = dict(row)
        item["client_tool_call_ids"] = json.loads(item.get("client_tool_call_ids_json") or "[]")
        item["original_assistant_message"] = json.loads(item.get("original_assistant_json") or "{}")
        item["gateway_tool_messages"] = json.loads(item.get("gateway_tool_messages_json") or "[]")
        return item

    def create_pending_gateway_tool_turn(
        self,
        session_id: str,
        session_tag: str,
        client_tool_call_ids: list[str],
        original_assistant_message: dict,
        gateway_tool_messages: list[dict],
        ttl_minutes: int = 1440,
    ) -> dict:
        normalized_ids, ids_json = _canonical_tool_call_ids_json(client_tool_call_ids)
        pending_id = f"pgt_{uuid.uuid4().hex[:12]}"
        created_at = iso_now()
        expires_at = dt_to_iso(now() + timedelta(minutes=int(ttl_minutes or 1440)))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_gateway_tool_turns (
                    id, session_id, session_tag, client_tool_call_ids_json,
                    original_assistant_json, gateway_tool_messages_json,
                    created_at, expires_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    pending_id,
                    session_id,
                    session_tag,
                    ids_json,
                    json_dumps(original_assistant_message),
                    json_dumps(gateway_tool_messages),
                    created_at,
                    expires_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM pending_gateway_tool_turns WHERE id = ?",
                (pending_id,),
            ).fetchone()
        return self._pending_gateway_tool_turn_from_row(row)

    def find_pending_gateway_tool_turn(
        self,
        session_id: str,
        client_tool_call_ids: list[str],
    ) -> Optional[dict]:
        expected, ids_json = _canonical_tool_call_ids_json(client_tool_call_ids)
        if not expected:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM pending_gateway_tool_turns
                WHERE session_id = ?
                    AND consumed_at IS NULL
                    AND expires_at >= ?
                    AND client_tool_call_ids_json = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id, iso_now(), ids_json),
            ).fetchone()
        return self._pending_gateway_tool_turn_from_row(row) if row else None

    def count_pending_gateway_tool_turns(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM pending_gateway_tool_turns
                WHERE session_id = ?
                    AND consumed_at IS NULL
                    AND expires_at >= ?
                """,
                (session_id, iso_now()),
            ).fetchone()
        return int(row["count"] or 0) if row else 0

    def mark_pending_gateway_tool_turns_consumed(self, pending_ids: list[str]) -> int:
        ids = [str(item) for item in pending_ids if item]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE pending_gateway_tool_turns
                SET consumed_at = ?
                WHERE consumed_at IS NULL AND id IN ({placeholders})
                """,
                (iso_now(), *ids),
            )
            return int(cursor.rowcount or 0)

    def prune_pending_gateway_tool_turns(self, session_id: Optional[str] = None) -> int:
        where = "WHERE (consumed_at IS NOT NULL OR expires_at < ?)"
        params: list[Any] = [iso_now()]
        if session_id:
            where += " AND session_id = ?"
            params.append(session_id)
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM pending_gateway_tool_turns {where}",
                tuple(params),
            )
            return int(cursor.rowcount or 0)

    def get_pending_gateway_tool_turns(self, session_id: str, limit: int = 1000) -> list[dict]:
        limit = max(1, min(int(limit or 1000), 5000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM pending_gateway_tool_turns
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._pending_gateway_tool_turn_from_row(row) for row in rows]
