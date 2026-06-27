from __future__ import annotations

import json
import uuid
from collections import deque
from typing import Any, Optional

from ..runtime import iso_now, json_dumps


class SnapshotsMixin:
    # -- context snapshot reads ----------------------------------------

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

    # -- context snapshot write ----------------------------------------

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

    # -- cross-session context queries ---------------------------------

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
                    ORDER BY r.created_at DESC, r.rowid DESC
                    LIMIT ?
                    """,
                    (session_tag, limit),
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
                    ORDER BY r.created_at DESC, r.rowid DESC
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

    def latest_context_source_session(
        self,
        exclude_session_id: Optional[str] = None,
        since: Optional[str] = None,
    ) -> Optional[dict]:
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
                SELECT
                    r.session_id,
                    s.session_tag,
                    s.client_name,
                    r.created_at AS snapshot_at,
                    r.latest_user_text
                FROM request_context_snapshots r
                JOIN gateway_sessions s ON s.id = r.session_id
                {where_sql}
                ORDER BY r.created_at DESC, r.rowid DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        return dict(row) if row else None

    def latest_session_context(
        self,
        session_tag: str,
        limit_messages: int,
        since: Optional[str] = None,
    ) -> list[dict]:
        session_tag = (session_tag or "").strip()
        if not session_tag:
            return []
        limit_messages = max(1, min(int(limit_messages or 1), 500))
        where = ["r.session_tag = ?"]
        params: list[Any] = [session_tag]
        if since:
            where.append("r.created_at > ?")
            params.append(since)
        where_sql = "WHERE " + " AND ".join(where)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT r.*, s.session_tag AS resolved_session_tag, s.client_name AS resolved_client_name
                FROM request_context_snapshots r
                JOIN gateway_sessions s ON s.id = r.session_id
                {where_sql}
                ORDER BY r.created_at DESC, r.rowid DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        if not row:
            return []

        newest = dict(row)
        raw_messages = json.loads(newest.get("messages_json") or "[]")
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
                "session_id": newest.get("session_id"),
                "session_tag": newest.get("resolved_session_tag") or newest.get("session_tag"),
                "client_name": newest.get("resolved_client_name") or newest.get("client_name"),
                "snapshot_at": newest.get("created_at"),
                "latest_user_text": newest.get("latest_user_text"),
                "messages": selected,
            }
        ]

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
                ORDER BY r.created_at DESC, r.rowid DESC
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
        fetch_limit = max(20, min(limit_messages * 3, 500))
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
            rows = conn.execute(
                f"""
                SELECT r.*, s.session_tag AS resolved_session_tag, s.client_name AS resolved_client_name
                FROM request_context_snapshots r
                JOIN gateway_sessions s ON s.id = r.session_id
                {where_sql}
                ORDER BY r.created_at DESC, r.rowid DESC
                LIMIT ?
                """,
                (*params, fetch_limit),
            ).fetchall()
        if not rows:
            return []

        selected_reversed: deque[dict[str, Any]] = deque()
        seen_messages: set[tuple[str, str]] = set()
        remaining = limit_messages

        for row in rows:
            item = dict(row)
            raw_messages = json.loads(item.get("messages_json") or "[]")
            source_messages = []
            for msg in reversed(raw_messages):
                role = msg.get("role")
                content = msg.get("content")
                if role not in {"user", "assistant"} or not content:
                    continue
                key = (str(role), str(content))
                if key in seen_messages:
                    continue
                seen_messages.add(key)
                source_messages.append({"role": role, "content": content})
                remaining -= 1
                if remaining <= 0:
                    break

            if source_messages:
                selected_reversed.append(
                    {
                        "session_id": item.get("session_id"),
                        "session_tag": item.get("resolved_session_tag") or item.get("session_tag"),
                        "client_name": item.get("resolved_client_name") or item.get("client_name"),
                        "snapshot_at": item.get("created_at"),
                        "latest_user_text": item.get("latest_user_text"),
                        "messages": list(reversed(source_messages)),
                    }
                )
            if remaining <= 0:
                break

        sources = list(reversed(selected_reversed))
        return sources

    # -- raw request window methods ------------------------------------

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
