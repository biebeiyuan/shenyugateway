from __future__ import annotations

"""Admin routes for the chat archive reader and conflict books.

The archive reader lists/browses verbatim messages by day and thread.
Conflict book routes serve the user-side workflow: clip frozen text from the
archive, edit title/epilogue/notes/status, never the original text.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .conflict_books import ConflictBookService

ARCHIVE_TABLE = "shenyu_chat_archive"


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
            {"select": "thread", "deleted_at": "is.null", "order": "thread.asc,archived_at.asc"},
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
            "order": "event_at.asc",
        }
        if month:
            params["event_at"] = f"gte.{month}-01"
            year, _, mon = month.partition("-")
            try:
                next_month = f"{int(year) + 1}-01" if mon == "12" else f"{year}-{int(mon) + 1:02d}"
                params["and"] = f"(event_at.lt.{next_month}-01)"
            except ValueError:
                pass
        rows = await _query_all(client, params)
        days: dict[str, int] = {}
        for row in rows or []:
            day = str(row.get("event_at") or "")[:10]
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
            params["event_at"] = f"gte.{date}T00:00:00+00:00"
            params["and"] = f"(event_at.lt.{date}T23:59:59.999+00:00)"
            params["order"] = "event_at.asc"
        elif before:
            params["event_at"] = f"lt.{before}"
            params["order"] = "event_at.desc"
        else:
            params["order"] = "event_at.desc"
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
