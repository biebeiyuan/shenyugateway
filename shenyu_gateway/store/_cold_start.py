from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Optional

from ..runtime import iso_now, json_dumps
from ._base import NEXT_REQUEST_COLD_START_TAG


class ColdStartMixin:

    def _cold_start_snapshot_from_row(self, row: sqlite3.Row | dict) -> dict:
        item = dict(row)
        item["sources"] = json.loads(item.get("sources_json") or "[]")
        item["source_session_tags"] = json.loads(item.get("source_session_tags_json") or "[]")
        item["active"] = bool(item.get("active", 1))
        return item

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
            "active": True,
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
                WHERE session_id = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return self._cold_start_snapshot_from_row(row)

    def latest_next_request_cold_start_snapshot(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM cold_start_snapshots
                WHERE session_tag = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (NEXT_REQUEST_COLD_START_TAG,),
            ).fetchone()
        if not row:
            return None
        return self._cold_start_snapshot_from_row(row)

    def mark_cold_start_injected(self, snapshot_id: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE cold_start_snapshots
                SET injected_count = injected_count + 1,
                    active = CASE
                        WHEN injected_count + 1 >= max_injections THEN 0
                        ELSE active
                    END
                WHERE id = ? AND active = 1
                """,
                (snapshot_id,),
            )

    def complete_cold_start_snapshot(self, snapshot_id: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE cold_start_snapshots
                SET active = 0,
                    injected_count = max(injected_count, max_injections)
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
        return self._cold_start_snapshot_from_row(row)

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
            snapshots.append(self._cold_start_snapshot_from_row(row))
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
            snapshots.append(self._cold_start_snapshot_from_row(row))
        return snapshots
