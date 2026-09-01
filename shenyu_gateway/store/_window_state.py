from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from ..runtime import iso_now, json_dumps


class WindowStateMixin:
    def get_context_window_state(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM context_window_states WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        state = dict(row)
        state["island_state"] = json.loads(state.get("island_state_json") or "{}")
        state["system_prefix_state"] = json.loads(state.get("system_prefix_state_json") or "{}")
        state["epoch_reset"] = False
        return state

    def upsert_context_window_state(self, session_id: str, state: dict[str, Any]) -> dict[str, Any]:
        now_text = iso_now()
        payload = {
            "session_id": session_id,
            "epoch_id": str(state.get("epoch_id") or ""),
            "base_limit": state.get("base_limit"),
            "overflow_messages": int(state.get("overflow_messages") or 0),
            "high_water": state.get("high_water"),
            "window_start_index": int(state.get("window_start_index") or 0),
            "island_anchor_offset": int(state.get("island_anchor_offset") or 0),
            "raw_protected_turns": int(state.get("raw_protected_turns") or 0),
            "island_state_json": json_dumps(state.get("island_state") or {}),
            "system_prefix_state_json": json_dumps(state.get("system_prefix_state") or {}),
            "last_event_class": str(state.get("last_event_class") or ""),
            "reset_reason": str(state.get("reset_reason") or ""),
            "updated_at": now_text,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO context_window_states (
                    session_id, epoch_id, base_limit, overflow_messages, high_water,
                    window_start_index, island_anchor_offset, raw_protected_turns,
                    island_state_json, system_prefix_state_json, last_event_class,
                    reset_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    epoch_id = excluded.epoch_id,
                    base_limit = excluded.base_limit,
                    overflow_messages = excluded.overflow_messages,
                    high_water = excluded.high_water,
                    window_start_index = excluded.window_start_index,
                    island_anchor_offset = excluded.island_anchor_offset,
                    raw_protected_turns = excluded.raw_protected_turns,
                    island_state_json = excluded.island_state_json,
                    system_prefix_state_json = excluded.system_prefix_state_json,
                    last_event_class = excluded.last_event_class,
                    reset_reason = excluded.reset_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["session_id"], payload["epoch_id"], payload["base_limit"],
                    payload["overflow_messages"], payload["high_water"],
                    payload["window_start_index"], payload["island_anchor_offset"],
                    payload["raw_protected_turns"], payload["island_state_json"],
                    payload["system_prefix_state_json"], payload["last_event_class"],
                    payload["reset_reason"], now_text, now_text,
                ),
            )
        return {
            **state,
            **payload,
            "island_state": state.get("island_state") or {},
            "system_prefix_state": state.get("system_prefix_state") or {},
        }

    def log_context_window_event(
        self,
        *,
        session_id: str,
        session_tag: str,
        event_class: str,
        epoch_id: str,
        detail: dict[str, Any],
        keep_recent: int = 10000,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO context_window_events (
                    id, session_id, session_tag, event_class, epoch_id, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"cwe_{uuid.uuid4().hex[:12]}",
                    session_id,
                    session_tag,
                    event_class,
                    epoch_id,
                    json_dumps(detail),
                    iso_now(),
                ),
            )
            conn.execute(
                """
                DELETE FROM context_window_events
                WHERE session_id = ? AND id NOT IN (
                    SELECT id FROM context_window_events
                    WHERE session_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                )
                """,
                (session_id, session_id, max(100, int(keep_recent or 10000))),
            )

    def list_context_window_events(
        self,
        *,
        limit: int = 1000,
        session_tag: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 1000), 50000))
        with self._connect() as conn:
            if session_tag:
                rows = conn.execute(
                    """
                    SELECT * FROM context_window_events
                    WHERE session_tag = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (session_tag, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM context_window_events
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item.get("detail_json") or "{}")
            events.append(item)
        return events
