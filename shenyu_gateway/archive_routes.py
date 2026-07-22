from __future__ import annotations

"""Admin routes for the chat archive reader and resident books.

The archive reader lists/browses verbatim messages by day and thread.
Origin-book routes serve the user-side workflow: clip frozen text from the
archive, edit title/epilogue/notes/status, never the original text.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .conflict_books import ConflictBookService
from .project_map import project_map_snapshot
from .resident_books import ResidentBooksService

ARCHIVE_TABLE = "shenyu_chat_archive"
_CST = timezone(timedelta(hours=8))


class ConflictBookCreate(BaseModel):
    title: str
    original_text: str
    thread: Optional[str] = None
    span_start: Optional[str] = None
    span_end: Optional[str] = None
    message_refs: list[Any] = Field(default_factory=list)
    user_notes: Optional[str] = None
    epilogue: Optional[str] = None


class ConflictBookPatch(BaseModel):
    title: Optional[str] = None
    thread: Optional[str] = None
    epilogue: Optional[str] = None
    user_notes: Optional[str] = None
    status: Optional[str] = None


class ResidentBookWrite(BaseModel):
    content: str
    mode: str = "replace"
    expected_revision: Optional[int] = None
    summary: str = ""


class ResidentBookAnnotation(BaseModel):
    content: str
    target_revision: Optional[int] = None


@dataclass(frozen=True)
class ArchiveRouteDeps:
    get_supabase_client: Callable[[], Any]


def build_archive_router(deps: ArchiveRouteDeps) -> APIRouter:
    router = APIRouter()

    def _supabase() -> Any:
        client = deps.get_supabase_client()
        if client is None:
            raise HTTPException(status_code=503, detail="Supabase is not configured.")
        return client

    async def _query_all(client: Any, params: dict[str, Any], *, page_size: int = 1000, max_rows: int = 50000) -> list[dict]:
        rows: list[dict] = []
        page_size = max(1, min(int(page_size or 1000), 1000))
        max_rows = max(page_size, int(max_rows or page_size))
        for start in range(0, max_rows, page_size):
            page_params = dict(params)
            page_params["limit"] = str(page_size)
            page_params["offset"] = str(start)
            page = await client.query(ARCHIVE_TABLE, params=page_params)
            rows.extend(page or [])
            if len(page or []) < page_size:
                break
        return rows

    @router.get("/api/archive/threads")
    async def archive_threads():
        client = _supabase()
        rows = await _query_all(
            client,
            {"select": "thread", "deleted_at": "is.null", "order": "thread.asc"},
        )
        threads: dict[str, int] = {}
        for row in rows or []:
            key = row.get("thread") or "main"
            threads[key] = threads.get(key, 0) + 1
        return {"threads": [{"thread": key, "count": count} for key, count in sorted(threads.items())]}

    @router.get("/api/archive/days")
    async def archive_days(thread: str = "main", month: Optional[str] = None):
        """Days in a month that have archived messages. month: YYYY-MM."""
        client = _supabase()
        params = {
            "select": "event_at",
            "thread": f"eq.{thread}",
            "deleted_at": "is.null",
            "order": "event_at.asc,archived_at.asc,role.desc",
        }
        if month:
            params["event_at"] = f"gte.{month}-01T00:00:00+08:00"
            year, _, mon = month.partition("-")
            try:
                next_month = f"{int(year) + 1}-01" if mon == "12" else f"{year}-{int(mon) + 1:02d}"
                params["and"] = f"(event_at.lt.{next_month}-01T00:00:00+08:00)"
            except ValueError:
                pass
        rows = await _query_all(client, params)
        days: dict[str, int] = {}
        for row in rows or []:
            raw = row.get("event_at") or ""
            if raw:
                try:
                    day = datetime.fromisoformat(raw).astimezone(_CST).strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    day = raw[:10]
            else:
                day = ""
            if day:
                days[day] = days.get(day, 0) + 1
        return {"days": [{"date": day, "count": count} for day, count in sorted(days.items())]}

    @router.get("/api/archive/messages")
    async def archive_messages(
        thread: str = "main",
        date: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 200,
    ):
        """Messages for one day (date=YYYY-MM-DD), or paged backwards via before."""
        client = _supabase()
        params = {
            "select": "id,session_tag,role,content,event_at,archived_at",
            "thread": f"eq.{thread}",
            "deleted_at": "is.null",
            "limit": str(max(1, min(int(limit or 200), 500))),
        }
        if date:
            from datetime import date as date_cls
            params["event_at"] = f"gte.{date}T00:00:00+08:00"
            try:
                next_day = (date_cls.fromisoformat(date) + timedelta(days=1)).isoformat()
            except ValueError:
                next_day = date
            params["and"] = f"(event_at.lt.{next_day}T00:00:00+08:00)"
            params["order"] = "event_at.asc,archived_at.asc,role.desc"
        elif before:
            params["event_at"] = f"lt.{before}"
            params["order"] = "event_at.desc,archived_at.desc,role.asc"
        else:
            params["order"] = "event_at.desc,archived_at.desc,role.asc"
        rows = await client.query(ARCHIVE_TABLE, params=params)
        if not date:
            rows = list(reversed(rows or []))
        return {"messages": rows or [], "count": len(rows or [])}

    @router.delete("/api/archive/messages/{message_id}")
    async def archive_soft_delete(message_id: str):
        """Soft-delete one archived message (e.g. accidental capture)."""
        from .runtime import iso_now

        client = _supabase()
        rows = await client.update(
            ARCHIVE_TABLE,
            {"id": message_id, "deleted_at": "is.null"},
            {"deleted_at": iso_now()},
        )
        return {"ok": True, "deleted": len(rows or [])}

    # ---- conflict books (admin side) ----

    def _books() -> ConflictBookService:
        return ConflictBookService(_supabase())

    def _resident_books() -> ResidentBooksService:
        return ResidentBooksService(deps.get_supabase_client())

    @router.get("/api/books")
    async def resident_books_overview():
        return await _resident_books().overview()

    @router.get("/api/project-map")
    async def project_map_read():
        """Owner-only live map; deliberately separate from resident books."""
        return project_map_snapshot()

    @router.get("/api/books/{book}")
    async def resident_book_read(book: str, view: str = "current"):
        return await _resident_books().read(book=book, view=view)

    @router.patch("/api/books/{book}")
    async def resident_book_write(book: str, body: ResidentBookWrite):
        return await _resident_books().write(
            book=book,
            content=body.content,
            mode=body.mode,
            expected_revision=body.expected_revision,
            summary=body.summary,
            actor="圆圆",
        )

    @router.post("/api/books/{book}/annotations")
    async def resident_book_annotate(book: str, body: ResidentBookAnnotation):
        return await _resident_books().annotate(
            book=book,
            content=body.content,
            target_revision=body.target_revision,
            actor="圆圆",
        )

    @router.get("/api/conflict-books")
    async def conflict_books_list(include_text: bool = False):
        return await _books().admin_list_books(include_text=include_text)

    @router.get("/api/conflict-books/{book_id}")
    async def conflict_books_get(book_id: str):
        return await _books().admin_get_book(book_id)

    @router.post("/api/conflict-books")
    async def conflict_books_create(body: ConflictBookCreate):
        return await _books().create_book(
            title=body.title,
            original_text=body.original_text,
            thread=body.thread,
            span_start=body.span_start,
            span_end=body.span_end,
            message_refs=body.message_refs,
            user_notes=body.user_notes,
            epilogue=body.epilogue,
        )

    @router.patch("/api/conflict-books/{book_id}")
    async def conflict_books_patch(book_id: str, body: ConflictBookPatch):
        return await _books().update_book(book_id, body.model_dump(exclude_none=True))

    @router.delete("/api/conflict-books/{book_id}")
    async def conflict_books_delete(book_id: str):
        return await _books().delete_book(book_id)

    return router
