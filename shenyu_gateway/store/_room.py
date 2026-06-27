from __future__ import annotations
import json
import uuid
from typing import Any, Optional
from ..runtime import iso_now, json_dumps


class RoomMixin:
    def add_room_trace(
        self,
        session_id: str,
        action: str,
        detail: Optional[dict] = None,
        scribble: Optional[str] = None,
    ) -> str:
        trace_id = f"rmtrc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO room_trace (id, session_id, action, detail_json, scribble, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (trace_id, session_id, action, json_dumps(detail) if detail else None, scribble, iso_now()),
            )
        return trace_id

    def recent_room_traces(self, limit: int = 5) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM room_trace ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def last_room_visit_at(self) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM room_trace ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return row["created_at"] if row else None

    def save_window_scene(self, session_id: str, scene_tag: str) -> str:
        return self.add_room_trace(session_id, "window", detail={"tag": scene_tag})

    def last_window_scene(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT detail_json, created_at FROM room_trace "
                "WHERE action = 'window' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row or not row["detail_json"]:
                return None
            import json as _json
            try:
                detail = _json.loads(row["detail_json"])
                return {"tag": detail.get("tag", ""), "created_at": row["created_at"]}
            except Exception:
                return None

    def add_room_scribble(self, content: str) -> str:
        scribble_id = f"rmscr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO room_scribbles (id, content, created_at) VALUES (?, ?, ?)",
                (scribble_id, content, iso_now()),
            )
        return scribble_id

    def recent_room_scribbles(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM room_scribbles ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_room_pin(self, content: str) -> str:
        pin_id = f"rmpin_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO room_pins (id, content, done, created_at) VALUES (?, ?, 0, ?)",
                (pin_id, content, iso_now()),
            )
        return pin_id

    def list_room_pins(self, include_done: bool = False) -> list[dict]:
        with self._connect() as conn:
            if include_done:
                rows = conn.execute("SELECT * FROM room_pins ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM room_pins WHERE done = 0 ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def complete_room_pin(self, pin_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE room_pins SET done = 1, done_at = ? WHERE id = ? AND done = 0",
                (iso_now(), pin_id),
            )
            return cursor.rowcount > 0

    def add_locked_drawer_note(self, content: str) -> str:
        note_id = f"rmlck_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO room_locked_drawer (id, content, created_at) VALUES (?, ?, ?)",
                (note_id, content, iso_now()),
            )
        return note_id

    def list_locked_drawer_notes(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM room_locked_drawer ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def room_pin_count_undone(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM room_pins WHERE done = 0").fetchone()
            return row["cnt"] if row else 0

    def room_message_count_since(self, since_iso: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM gateway_messages WHERE created_at > ?",
                (since_iso,),
            ).fetchone()
            return row["cnt"] if row else 0

    def add_drawer_note(self, content: str) -> str:
        note_id = f"rmdnr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO room_drawer_notes (id, content, created_at) VALUES (?, ?, ?)",
                (note_id, content, iso_now()),
            )
        return note_id

    def list_drawer_notes(self, limit: int = 10, unread_only: bool = False) -> list[dict]:
        with self._connect() as conn:
            if unread_only:
                rows = conn.execute(
                    "SELECT * FROM room_drawer_notes WHERE read_at IS NULL ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM room_drawer_notes ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def drawer_note_count_unread(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM room_drawer_notes WHERE read_at IS NULL"
            ).fetchone()
            return row["cnt"] if row else 0

    def mark_drawer_notes_read(self, note_ids: list[str]) -> int:
        if not note_ids:
            return 0
        with self._connect() as conn:
            ts = iso_now()
            placeholders = ",".join("?" for _ in note_ids)
            cursor = conn.execute(
                f"UPDATE room_drawer_notes SET read_at = ? WHERE id IN ({placeholders}) AND read_at IS NULL",
                [ts] + note_ids,
            )
            return cursor.rowcount

    def random_drawer_note(self) -> Optional[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM room_drawer_notes").fetchall()
            if not rows:
                return None
            import random
            return dict(random.choice(rows))
