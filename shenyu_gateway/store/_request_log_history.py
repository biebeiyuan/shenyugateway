from __future__ import annotations

import json
from typing import Any, Optional

from ..request_logs import _persistent_request_log_snapshot
from ..runtime import iso_now, json_dumps


_ACTIVE_REQUEST_LOG_STATUSES = ("preparing", "pending", "streaming", "streaming_tools")


class RequestLogHistoryMixin:
    def upsert_request_log(self, item: dict[str, Any], retention: int = 200) -> None:
        self.upsert_request_logs([item], retention=retention)

    def upsert_request_logs(self, items: list[dict[str, Any]], retention: int = 200) -> None:
        retention = max(1, min(int(retention or 200), 5000))
        rows: list[tuple[str, Optional[str], str, Optional[str], str, str, str]] = []
        updated_at = iso_now()
        for item in items:
            if not isinstance(item, dict) or not item.get("id") or not item.get("timestamp"):
                continue
            snapshot = _persistent_request_log_snapshot(item)
            rows.append(
                (
                    str(snapshot.get("id") or item["id"]),
                    str(snapshot.get("request_id")) if snapshot.get("request_id") else None,
                    str(snapshot.get("timestamp") or item["timestamp"]),
                    str(snapshot.get("session_tag")) if snapshot.get("session_tag") is not None else None,
                    str(snapshot.get("status") or "unknown"),
                    json_dumps(snapshot),
                    updated_at,
                )
            )
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO request_log_history
                    (id, request_id, timestamp, session_tag, status, detail_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    request_id = excluded.request_id,
                    timestamp = excluded.timestamp,
                    session_tag = excluded.session_tag,
                    status = excluded.status,
                    detail_json = excluded.detail_json,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            conn.execute(
                """
                DELETE FROM request_log_history
                WHERE id NOT IN (
                    SELECT id FROM request_log_history
                    ORDER BY timestamp DESC, updated_at DESC
                    LIMIT ?
                )
                """,
                (retention,),
            )

    def list_request_logs(self, limit: int = 30) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 30), 5000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT detail_json FROM request_log_history
                ORDER BY timestamp DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [item for row in rows if (item := self._request_log_from_json(row["detail_json"])) is not None]

    def get_request_log(self, log_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT detail_json FROM request_log_history
                WHERE id = ? OR request_id = ?
                ORDER BY timestamp DESC, updated_at DESC
                LIMIT 1
                """,
                (log_id, log_id),
            ).fetchone()
        return self._request_log_from_json(row["detail_json"]) if row else None

    def request_log_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM request_log_history").fetchone()
        return int(row["count"] or 0)

    def mark_interrupted_request_logs(self) -> int:
        placeholders = ",".join("?" for _ in _ACTIVE_REQUEST_LOG_STATUSES)
        interrupted_at = iso_now()
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, detail_json FROM request_log_history WHERE status IN ({placeholders})",
                _ACTIVE_REQUEST_LOG_STATUSES,
            ).fetchall()
            updates: list[tuple[str, str, str, str]] = []
            for row in rows:
                item = self._request_log_from_json(row["detail_json"])
                if item is None:
                    continue
                item["status"] = "interrupted"
                item["error"] = item.get("error") or "Gateway process stopped before this request completed."
                item["interrupted_at"] = interrupted_at
                updates.append(("interrupted", json_dumps(item), interrupted_at, row["id"]))
            if updates:
                conn.executemany(
                    """
                    UPDATE request_log_history
                    SET status = ?, detail_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    updates,
                )
        return len(updates)

    @staticmethod
    def _request_log_from_json(raw: str) -> Optional[dict[str, Any]]:
        try:
            item = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        return item if isinstance(item, dict) else None
