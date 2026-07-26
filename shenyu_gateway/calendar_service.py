from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException

from .calendar import default_period_key, latest_page_by_key, month_grid


def _safe_json_loads(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


class CalendarService:
    """Read-side calendar APIs. Pages are handwritten by 沈予 via the add_calendar tool."""

    def __init__(self, *, supabase_client: Any):
        self.supabase_client = supabase_client

    def _require_supabase(self):
        if not self.supabase_client:
            raise HTTPException(status_code=400, detail="Supabase is not configured.")

    async def _safe_supabase_query(self, table: str, params: dict) -> list[dict]:
        try:
            return await self.supabase_client.query(table, params)
        except Exception:
            return []

    async def month_status(self, month_key: Optional[str]) -> dict[str, Any]:
        self._require_supabase()
        month_key = month_key or default_period_key("month")
        rows = await self._safe_supabase_query(
            "calendar_pages",
            {"select": "*", "limit": "500", "order": "period_start.asc,updated_at.desc"},
        )
        latest = latest_page_by_key(rows)
        pages = list(latest.values())
        days_by_key = {row["period_key"]: row for row in pages if row.get("period_type") == "day"}
        weeks_by_key = {row["period_key"]: row for row in pages if row.get("period_type") == "week"}
        months_by_key = {row["period_key"]: row for row in pages if row.get("period_type") == "month"}

        grid = month_grid(month_key)
        for item in grid:
            item["has_day"] = item["date"] in days_by_key
            item["has_week"] = item["week_key"] in weeks_by_key
            item["has_month"] = month_key in months_by_key
            if item["has_day"]:
                row = days_by_key[item["date"]]
                item["day_page"] = {
                    "id": row.get("id"),
                    "title": row.get("title") or "",
                    "summary": row.get("summary") or "",
                    "status": row.get("status") or "final",
                }
        return {
            "month_key": month_key,
            "grid": grid,
            "pages": {
                "day": [
                    {
                        "id": row.get("id"),
                        "period_key": row.get("period_key"),
                        "title": row.get("title") or "",
                        "summary": row.get("summary") or "",
                        "updated_at": row.get("updated_at") or row.get("created_at"),
                    }
                    for row in sorted(days_by_key.values(), key=lambda item: item.get("period_key", ""), reverse=True)
                    if (row.get("period_key") or "").startswith(month_key)
                ],
                "week": [
                    {
                        "id": row.get("id"),
                        "period_key": row.get("period_key"),
                        "title": row.get("title") or "",
                        "summary": row.get("summary") or "",
                        "updated_at": row.get("updated_at") or row.get("created_at"),
                    }
                    for row in sorted(weeks_by_key.values(), key=lambda item: item.get("period_key", ""), reverse=True)
                ],
                "month": [
                    {
                        "id": row.get("id"),
                        "period_key": row.get("period_key"),
                        "title": row.get("title") or "",
                        "summary": row.get("summary") or "",
                        "updated_at": row.get("updated_at") or row.get("created_at"),
                    }
                    for row in sorted(months_by_key.values(), key=lambda item: item.get("period_key", ""), reverse=True)
                ],
            },
        }

    async def page_detail(self, page_id: str) -> dict[str, Any]:
        self._require_supabase()
        rows = await self._safe_supabase_query("calendar_pages", {"id": f"eq.{page_id}", "select": "*", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="Calendar page not found.")
        row = rows[0]
        row["source_refs"] = _safe_json_loads(row.get("source_refs"), [])
        row["session_tags"] = _safe_json_loads(row.get("session_tags"), [])
        row["meta"] = _safe_json_loads(row.get("meta"), {})
        return row
