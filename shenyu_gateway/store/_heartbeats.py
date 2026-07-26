from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Optional

from ..runtime import dt_to_iso, iso_now, now
from ._base import HEARTBEAT_ENTRIES_TABLE


class HeartbeatsMixin:
    def append_heartbeat(self, session_id: str, content: str, turn_number: int = 0) -> dict:
        heartbeat_id = f"hb_{uuid.uuid4().hex[:12]}"
        created_at = iso_now()
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {HEARTBEAT_ENTRIES_TABLE} (id, session_id, content, turn_number, created_at)
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

    def get_pending_heartbeats(self, session_id: Optional[str] = None, limit: int = 10) -> list[dict]:
        where = "injected_at IS NULL"
        params: list[Any] = []
        if session_id:
            where = "session_id = ? AND " + where
            params.append(session_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {HEARTBEAT_ENTRIES_TABLE}
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
    ):
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
                UPDATE {HEARTBEAT_ENTRIES_TABLE}
                SET injected_at = ?
                WHERE {where}
                """,
                (iso_now(), *params),
            )

    def get_latest_heartbeat_digest(self, session_id: Optional[str] = None, limit: int = 10) -> str:
        where = "injected_at IS NOT NULL"
        params: list[Any] = []
        if session_id:
            where = "session_id = ? AND " + where
            params.append(session_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT content FROM {HEARTBEAT_ENTRIES_TABLE}
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
    ) -> list[dict]:
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
                SELECT * FROM {HEARTBEAT_ENTRIES_TABLE}
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
    ) -> int:
        heartbeat_ids = [item for item in (heartbeat_ids or []) if item]
        with self._connect() as conn:
            if delete_all:
                if session_id:
                    cursor = conn.execute(f"DELETE FROM {HEARTBEAT_ENTRIES_TABLE} WHERE session_id = ?", (session_id,))
                else:
                    cursor = conn.execute(f"DELETE FROM {HEARTBEAT_ENTRIES_TABLE}")
                return int(cursor.rowcount or 0)
            if not heartbeat_ids:
                return 0
            placeholders = ",".join("?" for _ in heartbeat_ids)
            if session_id:
                cursor = conn.execute(
                    f"DELETE FROM {HEARTBEAT_ENTRIES_TABLE} WHERE session_id = ? AND id IN ({placeholders})",
                    (session_id, *heartbeat_ids),
                )
            else:
                cursor = conn.execute(
                    f"DELETE FROM {HEARTBEAT_ENTRIES_TABLE} WHERE id IN ({placeholders})",
                    tuple(heartbeat_ids),
                )
            return int(cursor.rowcount or 0)

    def get_all_heartbeats(self, session_id: Optional[str] = None) -> list[dict]:
        # External contract: home-frontend reads /api/gateway/heartbeats and expects
        # heartbeats[].content/created_at in ascending order.
        where = ""
        params: tuple[Any, ...] = ()
        if session_id:
            where = "WHERE session_id = ?"
            params = (session_id,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {HEARTBEAT_ENTRIES_TABLE}
                {where}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_settled_unsynced_heartbeats(self, settle_hours: int, limit: int = 200) -> list[dict]:
        cutoff = dt_to_iso(now() - timedelta(hours=max(int(settle_hours or 0), 0)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {HEARTBEAT_ENTRIES_TABLE}
                WHERE synced_at IS NULL AND created_at <= ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (cutoff, max(1, min(int(limit or 200), 1000))),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_heartbeats_synced(self, heartbeat_ids: list[str]):
        heartbeat_ids = [item for item in (heartbeat_ids or []) if item]
        if not heartbeat_ids:
            return
        placeholders = ",".join("?" for _ in heartbeat_ids)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE {HEARTBEAT_ENTRIES_TABLE} SET synced_at = ? WHERE id IN ({placeholders})",
                (iso_now(), *heartbeat_ids),
            )

    def get_all_heartbeat_ids(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT id FROM {HEARTBEAT_ENTRIES_TABLE}").fetchall()
            return {row["id"] for row in rows}
