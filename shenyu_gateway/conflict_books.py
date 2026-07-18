from __future__ import annotations

"""Conflict books ("矛盾书").

Frozen verbatim excerpts of arguments, clipped and curated by the user in the
admin UI, readable and annotatable by Shenyu through gateway tools.

Hard rules, enforced here because no other layer may bypass them:
  * original_text is written once at creation and is never updatable —
    update paths explicitly drop it.
  * Shenyu's annotations are append-only: no update/delete methods exist.
  * Every shenyu_conflict_read call appends a read-log row; the count is
    visible on the shelf ("翻过几次").
  * Books are never auto-injected as content. The shelf block (titles and
    status only) is the only passive surface.
"""

from typing import Any, Optional

from .runtime import iso_now

BOOKS_TABLE = "shenyu_conflict_books"
ANNOTATIONS_TABLE = "shenyu_conflict_annotations"
READS_TABLE = "shenyu_conflict_reads"

# Fields the user may edit after creation. original_text is intentionally absent.
USER_EDITABLE_FIELDS = {"title", "epilogue", "user_notes", "status", "thread"}


class ConflictBookService:
    def __init__(self, supabase: Any):
        self.supabase = supabase

    def _ready(self) -> Optional[dict]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        return None

    # ---- user-side (admin UI) ----

    async def create_book(
        self,
        *,
        title: str,
        original_text: str,
        thread: Optional[str] = None,
        span_start: Optional[str] = None,
        span_end: Optional[str] = None,
        message_refs: Optional[list] = None,
        user_notes: Optional[str] = None,
        epilogue: Optional[str] = None,
    ) -> dict:
        if error := self._ready():
            return error
        title = (title or "").strip()
        original_text = (original_text or "").strip()
        if not title:
            return {"ok": False, "error": "title is required"}
        if not original_text:
            return {"ok": False, "error": "original_text is required"}
        data = {
            "title": title,
            "original_text": original_text,
            "thread": (thread or "").strip() or None,
            "span_start": span_start,
            "span_end": span_end,
            "message_refs": message_refs or [],
            "user_notes": (user_notes or "").strip() or None,
            "epilogue": (epilogue or "").strip() or None,
            "status": "open",
        }
        try:
            row = await self.supabase.insert(BOOKS_TABLE, data)
            return {"ok": True, "book": row}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def update_book(self, book_id: str, patch: dict) -> dict:
        """Update user-editable fields only. original_text can never change."""
        if error := self._ready():
            return error
        if not book_id:
            return {"ok": False, "error": "book_id is required"}
        clean = {key: value for key, value in (patch or {}).items() if key in USER_EDITABLE_FIELDS}
        if "status" in clean and clean["status"] not in {"open", "settled"}:
            return {"ok": False, "error": "status must be open or settled"}
        if not clean:
            return {"ok": False, "error": "nothing editable in patch (original_text is frozen)"}
        clean["updated_at"] = iso_now()
        try:
            rows = await self.supabase.update(BOOKS_TABLE, {"id": book_id, "deleted_at": "is.null"}, clean)
            return {"ok": True, "book": rows[0] if rows else None}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def delete_book(self, book_id: str) -> dict:
        """Soft delete only; the frozen text is never physically erased."""
        if error := self._ready():
            return error
        if not book_id:
            return {"ok": False, "error": "book_id is required"}
        try:
            rows = await self.supabase.update(
                BOOKS_TABLE, {"id": book_id, "deleted_at": "is.null"}, {"deleted_at": iso_now()}
            )
            return {"ok": True, "deleted": len(rows or [])}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def admin_list_books(self, include_text: bool = False, limit: int = 100) -> dict:
        if error := self._ready():
            return error
        select = "id,title,thread,span_start,span_end,status,read_count,last_read_at,created_at,updated_at"
        if include_text:
            select += ",original_text,epilogue,user_notes,message_refs"
        try:
            rows = await self.supabase.query(
                BOOKS_TABLE,
                params={
                    "select": select,
                    "deleted_at": "is.null",
                    "order": "created_at.desc",
                    "limit": str(max(1, min(int(limit or 100), 500))),
                },
            )
            return {"ok": True, "count": len(rows or []), "books": rows or []}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def admin_get_book(self, book_id: str) -> dict:
        return await self._read_book(book_id, log_read=False)

    # ---- Shenyu-side (gateway tools) ----

    async def list_books(self) -> dict:
        """Shelf view: titles, status, read stats. Never the text."""
        if error := self._ready():
            return error
        try:
            rows = await self.supabase.query(
                BOOKS_TABLE,
                params={
                    "select": "title,thread,span_start,span_end,status,read_count,last_read_at,created_at",
                    "deleted_at": "is.null",
                    "order": "created_at.desc",
                    "limit": "100",
                },
            )
            return {"ok": True, "count": len(rows or []), "books": rows or []}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def read_book(self, book_id: str = "", *, title: str = "") -> dict:
        """Full read: frozen text + user's notes + all annotations. Logs the read."""
        return await self._read_book(book_id, title=title, log_read=True)

    async def annotate_book(self, book_id: str = "", content: str = "", *, title: str = "") -> dict:
        """Append one annotation. There is no way to edit or remove it later."""
        if error := self._ready():
            return error
        book_id = (book_id or "").strip()
        title = (title or "").strip()
        if not book_id and not title:
            return {"ok": False, "error": "book_id or title is required"}
        content = (content or "").strip()
        if not content:
            return {"ok": False, "error": "content is required"}
        try:
            book = await self._get_alive_book(book_id, select="id", title=title)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if book is None:
            return {"ok": False, "error": "book not found"}
        book_id = str(book.get("id") or book_id)
        try:
            row = await self.supabase.insert(ANNOTATIONS_TABLE, {"book_id": book_id, "content": content})
            return {"ok": True, "annotation": row, "note": "已落笔。批注不可改、不可删，和原文待在一起了。"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- internals ----

    async def _get_alive_book(self, book_id: str, select: str, *, title: str = "") -> Optional[dict]:
        book_id = (book_id or "").strip()
        title = (title or "").strip()
        if not book_id and not title:
            return None
        key, value = ("id", book_id) if book_id else ("title", title)
        rows = await self.supabase.query(
            BOOKS_TABLE,
            params={"select": select, key: f"eq.{value}", "deleted_at": "is.null", "limit": "2"},
        )
        if len(rows or []) > 1:
            raise ValueError("title is ambiguous; use a unique title or book_id")
        return rows[0] if rows else None

    async def _read_book(self, book_id: str = "", *, title: str = "", log_read: bool) -> dict:
        if error := self._ready():
            return error
        book_id = (book_id or "").strip()
        title = (title or "").strip()
        if not book_id and not title:
            return {"ok": False, "error": "book_id or title is required"}
        try:
            book = await self._get_alive_book(
                book_id,
                title=title,
                select=(
                    "id,title,thread,span_start,span_end,status,original_text,"
                    "epilogue,user_notes,read_count,last_read_at,created_at,updated_at"
                ),
            )
            if book is None:
                return {"ok": False, "error": "book not found"}
            book_id = str(book.get("id") or book_id)
            annotations = await self.supabase.query(
                ANNOTATIONS_TABLE,
                params={
                    "select": "id,content,created_at",
                    "book_id": f"eq.{book_id}",
                    "order": "created_at.asc",
                    "limit": "500",
                },
            )
            if log_read:
                await self.supabase.insert(READS_TABLE, {"book_id": book_id})
                new_count = int(book.get("read_count") or 0) + 1
                await self.supabase.update(
                    BOOKS_TABLE,
                    {"id": book_id},
                    {"read_count": new_count, "last_read_at": iso_now()},
                )
                book["read_count"] = new_count
            book["annotations"] = annotations or []
            return {"ok": True, "book": book}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def render_conflict_shelf(books: list[dict]) -> str:
    """Render the passive shelf block for the slow context layer.

    Titles and status only — the text stays in the book until Shenyu opens it.
    """
    if not books:
        return ""
    lines = ["## 矛盾书", "圆圆整理的、我们掰扯过的事的原文。想回去看哪一本，用 shenyu_conflict_read。"]
    for book in books:
        status = "已落地" if book.get("status") == "settled" else "还开着"
        read_count = int(book.get("read_count") or 0)
        read_part = f" · 翻过 {read_count} 次" if read_count else " · 还没翻过"
        date_part = ""
        span_start = str(book.get("span_start") or "")[:10]
        if span_start:
            date_part = f"[{span_start}] "
        lines.append(f"- {date_part}《{book.get('title') or ''}》 {status}{read_part}")
    return "\n".join(lines)
