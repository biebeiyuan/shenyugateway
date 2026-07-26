from __future__ import annotations

from typing import Optional

from shenyu_gateway.calendar import default_period_key, period_bounds
from shenyu_gateway.runtime import iso_now as _iso_now, json_dumps as _json_dumps
from shenyu_gateway.utils import shorten as _shorten

from ._helpers import _safe_json_loads


class CalendarToolsMixin:
    async def add_calendar(
        self,
        content: str,
        period_key: Optional[str] = None,
        period_type: str = "day",
        title: str = "",
        summary: str = "",
        digest: str = "",
        author: str = "沈予",
        mode: str = "append",
    ) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        body = (content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required."}

        period_type = (period_type or "day").strip().lower()
        if period_type not in {"day", "week", "month"}:
            return {"ok": False, "error": "Unsupported period_type."}
        period_key = (period_key or default_period_key(period_type)).strip()
        start, end = period_bounds(period_type, period_key)
        author = (author or "沈予").strip() or "沈予"
        title = (title or "").strip() or f"{period_key} 手写日历"
        summary = (summary or "").strip()
        digest = (digest or "").strip() or summary or _shorten(body, 180)
        mode = (mode or "append").strip().lower()
        if mode not in {"append", "replace"}:
            mode = "append"

        rows = await self._safe_query(
            "calendar_pages",
            {
                "select": "*",
                "period_type": f"eq.{period_type}",
                "period_key": f"eq.{period_key}",
                "order": "version.desc",
                "limit": "1",
            },
        )
        current = rows[0] if rows else None

        if current:
            old_content = (current.get("content") or "").strip()
            if mode == "append" and old_content:
                merged = old_content + "\n\n---\n\n" + body
            else:
                merged = body
            meta = _safe_json_loads(current.get("meta"), {})
            meta["manual_calendar_writes"] = int(meta.get("manual_calendar_writes") or 0) + 1
            meta["latest_manual_write_at"] = _iso_now()
            page_payload = {
                "period_type": period_type,
                "period_key": period_key,
                "period_start": current.get("period_start") or start.isoformat(),
                "period_end": current.get("period_end") or end.isoformat(),
                "version": int(current.get("version") or 1) + 1,
                "is_latest": True,
                "title": title,
                "content": merged,
                "summary": summary,
                "digest": digest,
                "author": author,
                "source_model": "manual-calendar",
                "source_refs": current.get("source_refs") or "[]",
                "session_tags": current.get("session_tags") or "[]",
                "meta": _json_dumps(meta),
                "status": current.get("status") or "final",
                "prompt_snapshot": current.get("prompt_snapshot") or "",
                "generated_by": "manual",
            }
        else:
            page_payload = {
                "period_type": period_type,
                "period_key": period_key,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "version": 1,
                "is_latest": True,
                "title": title,
                "content": body,
                "summary": summary,
                "digest": digest,
                "author": author,
                "source_model": "manual-calendar",
                "source_refs": "[]",
                "session_tags": "[]",
                "meta": _json_dumps({"manual_calendar_writes": 1, "latest_manual_write_at": _iso_now()}),
                "status": "final",
                "prompt_snapshot": "",
                "generated_by": "manual",
            }

        if current and current.get("id"):
            await self.supabase.update("calendar_pages", {"id": current.get("id")}, {"is_latest": False})

        page = await self.supabase.insert("calendar_pages", page_payload)
        return {
            "ok": True,
            "period_type": period_type,
            "period_key": period_key,
            "mode": mode if current else "new",
            "page": page,
            "digest": digest,
        }
