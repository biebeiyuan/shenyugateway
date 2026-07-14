from __future__ import annotations
import json
import uuid
from typing import Any, Optional
from ..runtime import iso_now, json_dumps


class RoomMixin:
    @staticmethod
    def _decode_json(value: Any, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

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

    def _room_newspaper_issue(self, conn: Any, issue_id: str) -> Optional[dict]:
        row = conn.execute(
            "SELECT * FROM room_newspaper_issues WHERE id = ?",
            (issue_id,),
        ).fetchone()
        if not row:
            return None
        issue = dict(row)
        issue["source_status"] = self._decode_json(issue.pop("source_status_json", "[]"), [])
        issue["qa_detail"] = self._decode_json(issue.pop("qa_detail_json", "{}"), {})
        item_rows = conn.execute(
            "SELECT * FROM room_newspaper_items WHERE issue_id = ? ORDER BY position ASC",
            (issue_id,),
        ).fetchall()
        issue["items"] = [dict(item) for item in item_rows]
        return issue

    def create_room_newspaper_issue(
        self,
        items: list[dict[str, Any]],
        *,
        source_status: Optional[list[dict[str, Any]]] = None,
        qa_detail: Optional[dict[str, Any]] = None,
    ) -> dict:
        if not items:
            raise ValueError("A newspaper issue needs at least one item.")
        issue_id = f"rmppr_{uuid.uuid4().hex[:12]}"
        created_at = iso_now()
        interest_count = sum(1 for item in items if item.get("bucket") == "interest")
        random_count = sum(1 for item in items if item.get("bucket") == "random")
        with self._connect() as conn:
            conn.execute("UPDATE room_newspaper_issues SET status = 'discarded' WHERE status = 'draft'")
            conn.execute(
                """
                INSERT INTO room_newspaper_issues (
                    id, status, item_count, interest_count, random_count,
                    source_status_json, qa_detail_json, created_at
                ) VALUES (?, 'draft', ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    len(items),
                    interest_count,
                    random_count,
                    json_dumps(source_status or []),
                    json_dumps(qa_detail or {}),
                    created_at,
                ),
            )
            for position, item in enumerate(items, start=1):
                conn.execute(
                    """
                    INSERT INTO room_newspaper_items (
                        id, issue_id, position, source_id, source_name, bucket,
                        title, summary, url, guid, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"rmpit_{uuid.uuid4().hex[:12]}",
                        issue_id,
                        position,
                        str(item.get("source_id") or ""),
                        str(item.get("source_name") or ""),
                        str(item.get("bucket") or "interest"),
                        str(item.get("title") or "").strip(),
                        str(item.get("summary") or "").strip(),
                        str(item.get("url") or "").strip(),
                        str(item.get("guid") or "").strip(),
                        str(item.get("published_at") or "").strip() or None,
                    ),
                )
            issue = self._room_newspaper_issue(conn, issue_id)
        if not issue:
            raise RuntimeError("Newspaper issue was not stored.")
        return issue

    def get_room_newspaper_issue(self, issue_id: str) -> Optional[dict]:
        with self._connect() as conn:
            return self._room_newspaper_issue(conn, issue_id)

    def list_room_newspaper_issues(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM room_newspaper_issues ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 50)),),
            ).fetchall()
            return [issue for row in rows if (issue := self._room_newspaper_issue(conn, row["id"]))]

    def latest_published_room_newspaper(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM room_newspaper_issues WHERE status = 'published' "
                "ORDER BY published_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
            return self._room_newspaper_issue(conn, row["id"]) if row else None

    def publish_room_newspaper_issue(self, issue_id: str) -> Optional[dict]:
        published_at = iso_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM room_newspaper_issues WHERE id = ?",
                (issue_id,),
            ).fetchone()
            if not row or row["status"] not in {"draft", "published"}:
                return None
            conn.execute(
                "UPDATE room_newspaper_issues SET status = 'archived' WHERE status = 'published' AND id != ?",
                (issue_id,),
            )
            conn.execute(
                "UPDATE room_newspaper_issues SET status = 'published', published_at = ?, delivered_at = NULL "
                "WHERE id = ?",
                (published_at, issue_id),
            )
            return self._room_newspaper_issue(conn, issue_id)

    def discard_room_newspaper_issue(self, issue_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE room_newspaper_issues SET status = 'discarded' WHERE id = ? AND status = 'draft'",
                (issue_id,),
            )
            return cursor.rowcount > 0

    def mark_room_newspaper_delivered(self, issue_id: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE room_newspaper_issues SET delivered_at = COALESCE(delivered_at, ?) "
                "WHERE id = ? AND status = 'published'",
                (iso_now(), issue_id),
            )
            return self._room_newspaper_issue(conn, issue_id)

    def has_undelivered_room_newspaper(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM room_newspaper_issues "
                "WHERE status = 'published' AND delivered_at IS NULL LIMIT 1"
            ).fetchone()
            return bool(row)

    def used_room_newspaper_urls(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT url FROM room_newspaper_items").fetchall()
            return {str(row["url"]) for row in rows if row["url"]}
