from __future__ import annotations

"""Admin routes for the chat archive reader and resident books.

The archive reader lists/browses verbatim messages by day, as one merged
timeline: the stored `thread` column is provenance only (one row per client
session epoch), never a browsing dimension. Rows repeated across sessions by
history handoff are folded away per (CST day, content_hash).
Origin-book routes serve the user-side workflow: clip frozen text from the
archive, edit title/epilogue/notes/status, never the original text.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .conflict_books import ConflictBookService
from .project_map import project_map_snapshot
from .resident_books import ResidentBooksService
from .runtime import LOCAL_DAY_TZ

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

    async def _query_all(client: Any, params: dict[str, Any], *, page_size: int = 1000, max_rows: int = 10000) -> list[dict]:
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

    def _cst_day(raw: str) -> str:
        if not raw:
            return ""
        try:
            return datetime.fromisoformat(raw).astimezone(LOCAL_DAY_TZ).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return raw[:10]

    def _fold_handoff_copies(rows: list[dict]) -> list[dict]:
        """Drop repeated copies of one message within a CST day.

        History handoff between session epochs used to re-archive the carried
        window under the new session_tag; those copies share content_hash and
        land on the same day. Keeps the first row in the given order.
        """
        seen: set[tuple[str, str]] = set()
        kept: list[dict] = []
        for row in rows:
            digest = row.get("content_hash")
            if digest:
                key = (_cst_day(row.get("event_at") or ""), digest)
                if key in seen:
                    continue
                seen.add(key)
            kept.append(row)
        return kept

    # Chronological replay order: event_at is the client-stamped moment,
    # archived_at replays the window order inside one inherited-time batch,
    # and id is the stable last resort. Role is deliberately not a cursor key:
    # it was only useful for legacy rows sharing one archived_at.
    # Composite cursor pagination using (event_at, archived_at, id) tuple.
    # Order must match cursor fields exactly to avoid skipped/duplicate rows.
    _ORDER_ASC = "event_at.asc,archived_at.asc,id.asc"
    _ORDER_DESC = "event_at.desc,archived_at.desc,id.desc"

    @router.get("/api/archive/days")
    async def archive_days(month: Optional[str] = None):
        """Days in a month that have archived messages, all sessions merged. month: YYYY-MM."""
        client = _supabase()
        params = {
            "select": "event_at,content_hash",
            "deleted_at": "is.null",
            "order": _ORDER_ASC,
        }
        if month:
            params["event_at"] = f"gte.{month}-01T00:00:00+08:00"
            year, _, mon = month.partition("-")
            try:
                next_month = f"{int(year) + 1}-01" if mon == "12" else f"{year}-{int(mon) + 1:02d}"
                params["and"] = f"(event_at.lt.{next_month}-01T00:00:00+08:00)"
            except ValueError:
                pass
        rows = _fold_handoff_copies(await _query_all(client, params))
        days: dict[str, int] = {}
        for row in rows:
            day = _cst_day(row.get("event_at") or "")
            if day:
                days[day] = days.get(day, 0) + 1
        return {"days": [{"date": day, "count": count} for day, count in sorted(days.items())]}

    @router.get("/api/archive/messages")
    async def archive_messages(
        date: Optional[str] = None,
        before: Optional[str] = None,
        after: Optional[str] = None,
        limit: int = 200,
        around_days: int = 0,
    ):
        """Messages for one day (date=YYYY-MM-DD), or paged by composite cursor. All sessions merged.

        `around_days` widens a `date` request symmetrically, so picking a day positions
        the reader instead of fencing it. A conversation that ran past midnight is one
        conversation; a hard one-day filter cut it in half, which truncated what could
        be clipped into an origin book. The reader scrolls to the chosen day and can
        still scroll out of it in both directions.

        `before`/`after` page by composite cursor "(event_at, archived_at, id)" — not just event_at,
        because same-turn user/assistant messages share one event_at (the assistant
        inherits the user's timestamp). Within one event_at, archived_at determines order.
        Single or two-column cursor would skip messages at page boundaries.
        Cursor format is opaque "event_at|archived_at|id" (pipe separator avoids : collision);
        both endpoints return ascending order so caller prepends/appends directly.
        """
        client = _supabase()
        params = {
            "select": "id,session_tag,role,content,content_hash,event_at,archived_at",
            "deleted_at": "is.null",
            "limit": str(max(1, min(int(limit or 200), 1000))),
        }
        reverse_after_fetch = False
        cursor_filter_in_python = None

        if date:
            from datetime import date as date_cls
            span = max(0, min(int(around_days or 0), 7))
            try:
                anchor = date_cls.fromisoformat(date)
                window_start = (anchor - timedelta(days=span)).isoformat()
                window_end = (anchor + timedelta(days=span + 1)).isoformat()
            except ValueError:
                window_start, window_end = date, date
            params["event_at"] = f"gte.{window_start}T00:00:00+08:00"
            params["and"] = f"(event_at.lt.{window_end}T00:00:00+08:00)"
            params["order"] = _ORDER_ASC
        elif after:
            # Composite cursor: oldest rows > (cursor_event_at, cursor_archived_at, cursor_id), ascending.
            # PostgREST doesn't support tuple comparison, so fetch event_at >= cursor
            # and filter precisely in Python.
            parts = after.split("|", 2)
            if len(parts) == 3:
                cursor_event_at, cursor_archived_at, cursor_id = parts
                if not cursor_event_at or not cursor_archived_at or not cursor_id:
                    raise HTTPException(status_code=400, detail="Invalid cursor format")
                params["event_at"] = f"gte.{cursor_event_at}"
                cursor_filter_in_python = ("after", cursor_event_at, cursor_archived_at, cursor_id)
            elif len(parts) == 2:
                # Legacy two-field cursor (backwards compat during transition).
                cursor_event_at, cursor_id = parts
                params["event_at"] = f"gte.{cursor_event_at}"
                cursor_filter_in_python = ("after", cursor_event_at, None, cursor_id)
            else:
                # Legacy single-field cursor (oldest format).
                cursor_event_at = after
                try:
                    datetime.fromisoformat(cursor_event_at)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid cursor event_at timestamp")
                params["event_at"] = f"gt.{cursor_event_at}"
            params["order"] = _ORDER_ASC
        elif before:
            # Composite cursor: newest rows < (cursor_event_at, cursor_archived_at, cursor_id), descending
            # then reversed. Fetch event_at <= cursor, filter in Python, return ascending.
            parts = before.split("|", 2)
            if len(parts) == 3:
                cursor_event_at, cursor_archived_at, cursor_id = parts
                if not cursor_event_at or not cursor_archived_at or not cursor_id:
                    raise HTTPException(status_code=400, detail="Invalid cursor format")
                params["event_at"] = f"lte.{cursor_event_at}"
                cursor_filter_in_python = ("before", cursor_event_at, cursor_archived_at, cursor_id)
            elif len(parts) == 2:
                # Legacy two-field cursor.
                cursor_event_at, cursor_id = parts
                params["event_at"] = f"lte.{cursor_event_at}"
                cursor_filter_in_python = ("before", cursor_event_at, None, cursor_id)
            else:
                # Legacy single-field cursor (oldest format).
                cursor_event_at = before
                try:
                    datetime.fromisoformat(cursor_event_at)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid cursor event_at timestamp")
                params["event_at"] = f"lt.{cursor_event_at}"
            params["order"] = _ORDER_DESC
            reverse_after_fetch = True
        else:
            params["order"] = _ORDER_DESC
            reverse_after_fetch = True

        rows = await client.query(ARCHIVE_TABLE, params=params)

        # Apply composite cursor filter in Python (tuple comparison).
        if cursor_filter_in_python:
            from datetime import timezone as tz
            direction, cursor_event_at, cursor_archived_at, cursor_id = cursor_filter_in_python

            # Parse cursor timestamps; fail fast if invalid.
            try:
                cursor_event_dt = datetime.fromisoformat(cursor_event_at)
                if cursor_event_dt.tzinfo is None:
                    cursor_event_dt = cursor_event_dt.replace(tzinfo=tz.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor event_at timestamp")

            cursor_archived_dt = None
            if cursor_archived_at:
                try:
                    cursor_archived_dt = datetime.fromisoformat(cursor_archived_at)
                    if cursor_archived_dt.tzinfo is None:
                        cursor_archived_dt = cursor_archived_dt.replace(tzinfo=tz.utc)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid cursor archived_at timestamp")

            filtered = []
            for row in rows or []:
                row_id = str(row.get("id") or "")
                row_event_at_str = row.get("event_at") or ""
                row_archived_at_str = row.get("archived_at") or ""

                try:
                    row_event_dt = datetime.fromisoformat(row_event_at_str)
                    if row_event_dt.tzinfo is None:
                        row_event_dt = row_event_dt.replace(tzinfo=tz.utc)
                    row_archived_dt = datetime.fromisoformat(row_archived_at_str)
                    if row_archived_dt.tzinfo is None:
                        row_archived_dt = row_archived_dt.replace(tzinfo=tz.utc)
                except ValueError:
                    # Can't parse row timestamp, skip it
                    continue

                # Three-key tuple comparison: (event_at, archived_at, id)
                if direction == "after":
                    # Want rows > cursor in ascending order.
                    if cursor_archived_dt is None:
                        # Legacy two-field cursor: compare (event_at, id) only
                        if row_event_dt > cursor_event_dt or (row_event_dt == cursor_event_dt and row_id > cursor_id):
                            filtered.append(row)
                    else:
                        # Full three-field cursor
                        if (row_event_dt > cursor_event_dt or
                            (row_event_dt == cursor_event_dt and row_archived_dt > cursor_archived_dt) or
                            (row_event_dt == cursor_event_dt and row_archived_dt == cursor_archived_dt and row_id > cursor_id)):
                            filtered.append(row)
                else:  # "before"
                    # Want rows < cursor in descending order.
                    if cursor_archived_dt is None:
                        # Legacy two-field cursor: compare (event_at, id) only
                        if row_event_dt < cursor_event_dt or (row_event_dt == cursor_event_dt and row_id < cursor_id):
                            filtered.append(row)
                    else:
                        # Full three-field cursor
                        if (row_event_dt < cursor_event_dt or
                            (row_event_dt == cursor_event_dt and row_archived_dt < cursor_archived_dt) or
                            (row_event_dt == cursor_event_dt and row_archived_dt == cursor_archived_dt and row_id < cursor_id)):
                            filtered.append(row)
            rows = filtered

        if reverse_after_fetch:
            rows = list(reversed(rows or []))
        messages = [
            {key: value for key, value in row.items() if key != "content_hash"}
            for row in _fold_handoff_copies(rows or [])
        ]
        return {"messages": messages, "count": len(messages)}

    def _cut_snippet(text: str, needle: str, context_chars: int = 30) -> dict[str, str]:
        """Cut text into before/match/after around the first case-insensitive match.

        Returns original-case match (not lowercased), so frontend highlighting
        stays byte-identical to what the user sees. Uses regex for case-insensitive
        matching to avoid casefold() length issues (e.g., 'ß' → 'ss' changes offsets).

        Pitfall avoided: Python counts Unicode code points, JS counts UTF-16 code units,
        Swift counts grapheme clusters — an emoji offset computed here would land wrong
        if sent as a number. Send the three strings instead; frontend renders them
        as three runs with no arithmetic.
        """
        import re
        # Use re.IGNORECASE to match without casefold's length-changing transform
        m = re.search(re.escape(needle), text, re.IGNORECASE)
        if not m:
            # Should not happen (caller already filtered), but guard anyway.
            return {"snippet_before": "", "snippet_match": text[:60], "snippet_after": ""}
        match_start = m.start()
        match_end = m.end()
        before_start = max(0, match_start - context_chars)
        after_end = min(len(text), match_end + context_chars)
        return {
            "snippet_before": text[before_start:match_start],
            "snippet_match": text[match_start:match_end],
            "snippet_after": text[match_end:after_end],
        }

    @router.get("/api/archive/search")
    async def archive_search(
        q: str = "",
        role: Optional[str] = None,
        limit: int = 60,
        cursor: Optional[str] = None,
    ):
        """Literal, case-insensitive substring search over the verbatim archive.

        Deliberately not semantic: someone looking for a phrase they remember
        saying needs the exact words they typed, not a neighbour — the same rule
        that keeps the window-newspaper basket literal (AGENTS.md § basket).
        The DB `ilike` narrows the fetch; the Python check is the authority, so
        wildcard characters in the phrase cannot widen the match.

        Returns snippet (before/match/after) instead of full content so frontend
        can highlight without offset arithmetic (which fails across Python/JS/Swift
        due to different string indexing — code points vs UTF-16 vs graphemes).

        Cursor is opaque "event_at|archived_at|id" (pipe separator to avoid :
        collision with ISO timestamps) for pagination; fetches one extra row to
        determine has_more without a separate count query.
        """
        from datetime import datetime, timezone as tz
        import re

        needle = (q or "").strip()
        if not needle:
            return {"results": [], "count": 0, "has_more": False, "query": "", "next_cursor": None}
        client = _supabase()

        # Escape ILIKE wildcards (%, _) and backslash, then wrap in quotes.
        # PostgREST quoted patterns use \" for literal quotes (not "").
        # Wrapping in quotes prevents comma/parens from being treated as separators.
        escaped = needle.replace('\\', '\\\\')  # Escape backslash first
        escaped = escaped.replace('%', '\\%')   # Escape ILIKE wildcards
        escaped = escaped.replace('_', '\\_')
        escaped = escaped.replace('*', '\\*')
        escaped = escaped.replace('"', '\\"')   # Escape quotes for PostgREST quoted pattern

        params = {
            "select": "id,session_tag,role,content,content_hash,event_at,archived_at",
            "deleted_at": "is.null",
            "content": f'ilike."*{escaped}*"',  # Quoted pattern with wildcards around needle
            "order": _ORDER_DESC,
        }
        if role in ("user", "assistant"):
            params["role"] = f"eq.{role}"

        # Cursor for pagination: "event_at|archived_at|id" format (opaque to client, pipe to avoid colon collision).
        # Parse and validate cursor before DB query.
        cursor_event_dt = None
        cursor_archived_dt = None
        cursor_id = None
        if cursor:
            parts = cursor.split("|", 2)
            if len(parts) == 3:
                cursor_event_at, cursor_archived_at, cursor_id = parts
                if not cursor_event_at or not cursor_archived_at or not cursor_id:
                    raise HTTPException(status_code=400, detail="Invalid cursor format")
            elif len(parts) == 2:
                # Legacy two-field cursor for backwards compat
                cursor_event_at, cursor_id = parts
                cursor_archived_at = None
            else:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="Invalid cursor format")

            # Parse cursor timestamps to validate them
            try:
                cursor_event_dt = datetime.fromisoformat(cursor_event_at)
                if cursor_event_dt.tzinfo is None:
                    cursor_event_dt = cursor_event_dt.replace(tzinfo=tz.utc)
            except ValueError:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="Invalid cursor event_at timestamp")

            if cursor_archived_at:
                try:
                    cursor_archived_dt = datetime.fromisoformat(cursor_archived_at)
                    if cursor_archived_dt.tzinfo is None:
                        cursor_archived_dt = cursor_archived_dt.replace(tzinfo=tz.utc)
                except ValueError:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=400, detail="Invalid cursor archived_at timestamp")

            # Use DB filter to narrow fetch (lte includes cursor row, will be filtered in Python)
            params["event_at"] = f"lte.{cursor_event_at}"

        # Fetch limit * 3 to account for: (1) handoff folding, (2) Python re.IGNORECASE filter,
        # (3) cursor filtering. This avoids pagination gaps while keeping fetch bounded.
        cap = max(1, min(int(limit), 200))
        fetch_limit = min(cap * 3, 600)
        params["limit"] = str(fetch_limit)

        rows = await client.query(ARCHIVE_TABLE, params=params)
        folded = _fold_handoff_copies(rows or [])

        # Python re.IGNORECASE is authoritative; filter after DB fetch.
        # This ensures the Python filter uses the same matching logic as snippet generation.
        hits = [row for row in folded if re.search(re.escape(needle), str(row.get("content") or ""), re.IGNORECASE)]

        # Apply cursor filtering in Python (complex tuple comparison).
        # IMPORTANT: filter BEFORE slicing, otherwise pagination breaks.
        if cursor_event_dt is not None and cursor_id is not None:
            filtered = []
            for row in hits:
                row_id = str(row.get("id") or "")
                row_event_at_str = row.get("event_at") or ""
                row_archived_at_str = row.get("archived_at") or ""

                try:
                    row_event_dt = datetime.fromisoformat(row_event_at_str)
                    if row_event_dt.tzinfo is None:
                        row_event_dt = row_event_dt.replace(tzinfo=tz.utc)
                    row_archived_dt = datetime.fromisoformat(row_archived_at_str)
                    if row_archived_dt.tzinfo is None:
                        row_archived_dt = row_archived_dt.replace(tzinfo=tz.utc)
                except ValueError:
                    continue

                # DESC order: want rows < cursor (earlier in three-key tuple)
                if cursor_archived_dt is None:
                    # Legacy two-field cursor: compare (event_at, id) only
                    if row_event_dt < cursor_event_dt or (row_event_dt == cursor_event_dt and row_id < cursor_id):
                        filtered.append(row)
                else:
                    # Full three-field cursor: compare (event_at, archived_at, id)
                    if (row_event_dt < cursor_event_dt or
                        (row_event_dt == cursor_event_dt and row_archived_dt < cursor_archived_dt) or
                        (row_event_dt == cursor_event_dt and row_archived_dt == cursor_archived_dt and row_id < cursor_id)):
                        filtered.append(row)
            hits = filtered

        # Fetch limit+1 to detect has_more without separate count query.
        page_hits = hits[: cap + 1]
        has_more = len(page_hits) > cap
        result_rows = page_hits[:cap]

        results = []
        for row in result_rows:
            snippet = _cut_snippet(str(row.get("content") or ""), needle, context_chars=30)
            results.append({
                "id": row.get("id"),
                "session_tag": row.get("session_tag"),
                "role": row.get("role"),
                "event_at": row.get("event_at"),
                "archived_at": row.get("archived_at"),
                **snippet,
            })

        next_cursor = None
        if has_more and result_rows:
            last = result_rows[-1]
            # Three-key cursor: event_at|archived_at|id
            event_at = last.get('event_at') or ''
            archived_at = last.get('archived_at') or ''
            next_cursor = f"{event_at}|{archived_at}|{last.get('id')}"

        return {
            "results": results,
            "count": len(results),
            "has_more": has_more,
            "query": needle,
            "next_cursor": next_cursor,
        }

    @router.delete("/api/archive/messages/{message_id}")
    async def archive_soft_delete(message_id: str):
        """Soft-delete one archived message (e.g. accidental capture).

        Same-day handoff copies of the message are folded away in the reader,
        so delete them too — otherwise a hidden twin would resurface.
        """
        from .runtime import iso_now

        client = _supabase()
        now = iso_now()
        rows = await client.update(
            ARCHIVE_TABLE,
            {"id": message_id, "deleted_at": "is.null"},
            {"deleted_at": now},
        )
        deleted = len(rows or [])
        target = (rows or [{}])[0]
        digest = target.get("content_hash")
        event_at = target.get("event_at") or ""
        day = _cst_day(event_at)
        if digest and day:
            twins = await client.query(
                ARCHIVE_TABLE,
                params={
                    "select": "id,event_at",
                    "content_hash": f"eq.{digest}",
                    "deleted_at": "is.null",
                    "limit": "50",
                },
            )
            twin_ids = [
                str(row.get("id"))
                for row in twins or []
                if row.get("id") and _cst_day(row.get("event_at") or "") == day
            ]
            if twin_ids:
                joined = ",".join(twin_ids)
                extra = await client.update(
                    ARCHIVE_TABLE,
                    {"id": f"in.({joined})", "deleted_at": "is.null"},
                    {"deleted_at": now},
                )
                deleted += len(extra or [])
        return {"ok": True, "deleted": deleted}

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
