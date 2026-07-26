from __future__ import annotations
import json
import uuid
from collections import deque
from datetime import timedelta
from typing import Any, Optional
from ..runtime import dt_to_iso, iso_now, json_dumps, now, parse_ts


TOOL_ERROR_CONFIG_PHRASES = (
    "not configured",
    "未配置",
    "is not configured",
    "store is not configured",
    "embedding api is not configured",
    "not available",
)


class AdminMixin:
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
            window_event_count = conn.execute("SELECT COUNT(*) AS count FROM context_window_events").fetchone()
            heartbeat_count = conn.execute("SELECT COUNT(*) AS count FROM heartbeat_entries").fetchone()
            pending_count = conn.execute(
                "SELECT COUNT(*) AS count FROM pending_gateway_tool_turns WHERE consumed_at IS NULL"
            ).fetchone()
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
            "context_window_events": int(window_event_count["count"] or 0),
            "heartbeats": int(heartbeat_count["count"] or 0),
            "pending_gateway_tool_turns": int(pending_count["count"] or 0),
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
            "pending_gateway_tool_turns": 0,
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
                    AND active = 0
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
        deleted["pending_gateway_tool_turns"] = self.prune_pending_gateway_tool_turns(session_id)
        return deleted

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
            "context_window_events": self.list_context_window_events(limit=50000, session_tag=session_tag),
            "cold_start_snapshots": self.all_cold_start_snapshots(session_id),
            "pending_gateway_tool_turns": self.get_pending_gateway_tool_turns(session_id),
            "heartbeats": self.get_all_heartbeats(session_id),
        }

    def filter_unseen_archive_hashes(self, session_tag: str, content_hashes: list[str]) -> set[str]:
        """Return the subset of hashes not yet archived for this session_tag."""
        hashes = [item for item in dict.fromkeys(content_hashes or []) if item]
        if not hashes:
            return set()
        unseen = set(hashes)
        with self._connect() as conn:
            for start in range(0, len(hashes), 200):
                chunk = hashes[start : start + 200]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT content_hash FROM chat_archive_seen WHERE session_tag = ? AND content_hash IN ({placeholders})",
                    (session_tag, *chunk),
                ).fetchall()
                unseen -= {row["content_hash"] for row in rows}
        return unseen

    def mark_archive_hashes_seen(self, session_tag: str, content_hashes: list[str], keep_recent: int = 2000):
        hashes = [item for item in dict.fromkeys(content_hashes or []) if item]
        if not hashes:
            return
        timestamp = iso_now()
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO chat_archive_seen (session_tag, content_hash, created_at) VALUES (?, ?, ?)",
                [(session_tag, item, timestamp) for item in hashes],
            )
            conn.execute(
                """
                DELETE FROM chat_archive_seen
                WHERE session_tag = ? AND content_hash NOT IN (
                    SELECT content_hash FROM chat_archive_seen
                    WHERE session_tag = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                """,
                (session_tag, session_tag, max(int(keep_recent or 2000), 100)),
            )

    def save_config_overrides(self, updates: dict[str, str]) -> None:
        if not updates:
            return
        ts = iso_now()
        with self._connect() as conn:
            for key, value in updates.items():
                conn.execute(
                    """
                    INSERT INTO config_overrides (env_key, env_value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(env_key) DO UPDATE SET
                        env_value = excluded.env_value,
                        updated_at = excluded.updated_at
                    """,
                    (key, str(value) if value is not None else "", ts),
                )

    def load_config_overrides(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT env_key, env_value FROM config_overrides").fetchall()
            return {row["env_key"]: row["env_value"] for row in rows}

    def log_tool_error(
        self,
        session_id: str,
        session_tag: Optional[str],
        tool_name: str,
        target_tool: Optional[str],
        args: Optional[dict],
        error_text: str,
        error_source: str = "execute",
        error_kind: str = "unknown",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_error_log
                    (id, session_id, session_tag, tool_name, target_tool,
                     args_json, error_text, error_source, error_kind, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    session_id,
                    session_tag,
                    tool_name,
                    target_tool,
                    json_dumps(args) if args else None,
                    error_text[:4000],
                    error_source,
                    error_kind,
                    iso_now(),
                ),
            )

    def list_tool_errors(self, limit: int = 50, kind: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM tool_error_log WHERE error_kind = ? ORDER BY created_at DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
                return [dict(r) for r in rows]
            rows = conn.execute(
                "SELECT * FROM tool_error_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def heartbeat_echo(self) -> Optional[dict]:
        """Pick one random heartbeat from the furthest available time bucket.

        Buckets (checked from furthest first):
          very_old: 60+ days ago
          last_month: 28-60 days ago
          two_weeks: 14-28 days ago
          last_week: 7-14 days ago

        Returns dict with content, created_at, era label, or None.
        """
        import random
        buckets = [
            ("很早以前的", 60, None),
            ("上个月的", 28, 60),
            ("上上周的", 14, 28),
            ("上周的", 7, 14),
        ]
        _now = now()
        with self._connect() as conn:
            for era, min_days, max_days in buckets:
                from_ts = dt_to_iso(_now - timedelta(days=max_days)) if max_days else None
                to_ts = dt_to_iso(_now - timedelta(days=min_days))
                where = "created_at <= ?"
                params: list[Any] = [to_ts]
                if from_ts:
                    where += " AND created_at > ?"
                    params.append(from_ts)
                rows = conn.execute(
                    f"SELECT id, content, created_at FROM heartbeat_entries WHERE {where}",
                    params,
                ).fetchall()
                if rows:
                    row = random.choice(rows)
                    return {"content": row["content"], "created_at": row["created_at"], "era": era}
        return None
