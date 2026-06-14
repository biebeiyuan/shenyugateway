from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Optional

from .calendar import period_bounds
from .utils import normalize_text as _normalize_text
from .utils import shorten as _shorten


def _safe_json_loads(value: Any, fallback: Any):
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


class CalendarSourceCollector:
    """Collects source material for day/week/month calendar generation."""

    def __init__(
        self,
        *,
        session_store: Any,
        calendar_page_query: Callable[[dict[str, str]], Awaitable[list[dict[str, Any]]]],
        surface_passages: Callable[[str, Optional[str], int], Awaitable[dict[str, Any]]],
        default_surface_limit: int,
    ):
        self.session_store = session_store
        self.calendar_page_query = calendar_page_query
        self.surface_passages = surface_passages
        self.default_surface_limit = default_surface_limit

    async def collect_sources(
        self,
        period_type: str,
        period_key: str,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        start, end = period_bounds(period_type, period_key)
        if period_type == "day":
            return await self._collect_day_sources(period_key, start, end, session_tag=session_tag)
        if period_type == "week":
            return await self._collect_week_sources(period_key, start, end, session_tag=session_tag)
        return await self._collect_month_sources(period_key, start, end, session_tag=session_tag)

    def context_snapshots(
        self,
        limit: int = 5,
        session_tag: Optional[str] = None,
        message_limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        if self.session_store is None:
            return []
        snapshots = self.session_store.latest_request_context_snapshots(limit=limit, session_tag=session_tag)
        for item in snapshots:
            item["messages"] = self._clean_snapshot_messages(item.get("messages") or [], limit=message_limit)
            item["latest_user_text"] = _shorten(item.get("latest_user_text") or "", 300)
        return snapshots

    def _clean_snapshot_messages(self, messages: list[dict], limit: Optional[int] = None) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = _normalize_text(msg.get("content")).strip()
            if not content:
                continue
            cleaned.append({"role": role, "content": _shorten(content, 1200)})
        return cleaned[-limit:] if limit else cleaned

    async def _recent_calendar_pages(
        self,
        period_type: str,
        limit: int,
        before_key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        params = {
            "select": "*",
            "period_type": f"eq.{period_type}",
            "is_latest": "eq.true",
            "order": "period_start.desc",
            "limit": str(max(1, min(limit + 5, 50))),
        }
        rows = await self.calendar_page_query(params)
        if before_key:
            rows = [row for row in rows if (row.get("period_key") or "") != before_key]
        return rows[:limit]

    def _recent_heartbeats(self, limit: int) -> list[dict[str, Any]]:
        if self.session_store is None:
            return []
        rows = self.session_store.read_heartbeats(
            session_id=None,
            state="all",
            limit=max(1, int(limit or 1)),
            order="desc",
            hisense=False,
        )
        for row in rows:
            row["state"] = "injected" if row.get("injected_at") else "pending"
            row["content"] = _shorten(_normalize_text(row.get("content") or ""), 500)
        return rows

    async def _surface_rows_for_snapshots(
        self,
        snapshots: list[dict[str, Any]],
        session_tag: Optional[str],
    ) -> list[dict[str, Any]]:
        if not snapshots:
            return []
        trigger_parts = [item.get("latest_user_text") or "" for item in snapshots[:3]]
        trigger = "\n".join(part for part in trigger_parts if part).strip() or "calendar preview"
        surfaced = await self.surface_passages(trigger, session_tag, self.default_surface_limit)
        return (surfaced.get("passages") or [])[:4]

    def _calendar_source_refs(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "source_table": "calendar_pages",
                "source_id": row.get("id"),
                "title": row.get("title") or row.get("period_key") or "",
                "period_type": row.get("period_type"),
                "period_key": row.get("period_key"),
            }
            for row in rows
        ]

    def _heartbeat_source_refs(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "source_table": "heartbeat_entries",
                "source_id": row.get("id"),
                "title": "heartbeat",
                "created_at": row.get("created_at"),
                "state": row.get("state") or ("injected" if row.get("injected_at") else "pending"),
            }
            for row in rows
        ]

    async def _collect_day_sources(
        self,
        period_key: str,
        start: datetime,
        end: datetime,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        snapshots = self.context_snapshots(limit=10, session_tag=session_tag)
        recent_days = await self._recent_calendar_pages("day", 3, before_key=period_key)
        recent_weeks = await self._recent_calendar_pages("week", 1)
        recent_months = await self._recent_calendar_pages("month", 1)
        recent_heartbeats = self._recent_heartbeats(8)
        surface_rows = await self._surface_rows_for_snapshots(snapshots, session_tag=session_tag)
        calendar_rows = recent_days + recent_weeks + recent_months
        session_tags = sorted({item.get("session_tag") for item in snapshots if item.get("session_tag")})
        source_refs = self._calendar_source_refs(calendar_rows) + self._heartbeat_source_refs(recent_heartbeats)
        return {
            "period_type": "day",
            "period_key": period_key,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "context_snapshots": snapshots,
            "surface_rows": surface_rows,
            "recent_days": recent_days,
            "recent_weeks": recent_weeks,
            "recent_months": recent_months,
            "recent_heartbeats": recent_heartbeats,
            "source_refs": source_refs,
            "session_tags": session_tags,
        }

    async def _collect_week_sources(
        self,
        period_key: str,
        start: datetime,
        end: datetime,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        snapshots = self.context_snapshots(limit=8, session_tag=session_tag, message_limit=20)
        recent_days = await self._recent_calendar_pages("day", 7)
        recent_weeks = await self._recent_calendar_pages("week", 2, before_key=period_key)
        recent_months = await self._recent_calendar_pages("month", 1)
        recent_heartbeats = self._recent_heartbeats(5)
        calendar_rows = recent_days + recent_weeks + recent_months
        session_tags = sorted({item.get("session_tag") for item in snapshots if item.get("session_tag")})
        return {
            "period_type": "week",
            "period_key": period_key,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "context_snapshots": snapshots,
            "recent_days": recent_days,
            "recent_weeks": recent_weeks,
            "recent_months": recent_months,
            "recent_heartbeats": recent_heartbeats,
            "source_refs": self._calendar_source_refs(calendar_rows) + self._heartbeat_source_refs(recent_heartbeats),
            "session_tags": session_tags,
        }

    async def _collect_month_sources(
        self,
        period_key: str,
        start: datetime,
        end: datetime,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        snapshots = self.context_snapshots(limit=6, session_tag=session_tag, message_limit=20)
        recent_days = await self._recent_calendar_pages("day", 7)
        recent_weeks = await self._recent_calendar_pages("week", 4)
        recent_months = await self._recent_calendar_pages("month", 1, before_key=period_key)
        recent_heartbeats = self._recent_heartbeats(5)
        calendar_rows = recent_days + recent_weeks + recent_months
        session_tags = sorted(
            {
                *{item.get("session_tag") for item in snapshots if item.get("session_tag")},
                *{tag for row in calendar_rows for tag in _safe_json_loads(row.get("session_tags"), []) if tag},
            }
        )
        return {
            "period_type": "month",
            "period_key": period_key,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "context_snapshots": snapshots,
            "recent_days": recent_days,
            "recent_weeks": recent_weeks,
            "recent_months": recent_months,
            "recent_heartbeats": recent_heartbeats,
            "source_refs": self._calendar_source_refs(calendar_rows) + self._heartbeat_source_refs(recent_heartbeats),
            "session_tags": session_tags,
        }

    @staticmethod
    def render_source_block(period_type: str, sources: dict[str, Any]) -> str:
        lines = [f"Period: {period_type} / {sources.get('period_key')}"]
        snapshots = sources.get("context_snapshots") or []
        if snapshots:
            lines.append("\n[Current Client Context Snapshots]")
            for snapshot in snapshots:
                lines.append(
                    f"\n- session_tag: {snapshot.get('session_tag') or ''}"
                    f" / client: {snapshot.get('client_name') or ''}"
                    f" / snapshot_at: {snapshot.get('created_at') or ''}"
                )
                for msg in snapshot.get("messages") or []:
                    lines.append(f"  - {msg.get('role')}: {_shorten(msg.get('content') or '', 520)}")

        if sources.get("surface_rows"):
            lines.append("\n[Soft Surfaced Primary Texts]")
            for row in sources["surface_rows"][:4]:
                lines.append(f"- {row.get('source_table')} / {row.get('title')} / {_shorten(row.get('excerpt') or '', 180)}")

        if sources.get("recent_heartbeats"):
            lines.append("\n[Recent Heartbeats]")
            for row in sources["recent_heartbeats"][:10]:
                marker = f"{row.get('created_at') or ''} / {row.get('state') or ''}".strip(" /")
                lines.append(f"- {marker}: {_shorten(row.get('content') or '', 260)}")

        def add_calendar_rows(label: str, rows: list[dict[str, Any]], limit: int):
            if not rows:
                return
            lines.append(f"\n[{label}]")
            for row in rows[:limit]:
                text = row.get("digest") or row.get("summary") or row.get("content") or ""
                lines.append(f"- {row.get('period_key')} / {row.get('title') or ''} / {_shorten(text, 260)}")

        add_calendar_rows("Recent Day Pages", sources.get("recent_days") or [], 10)
        add_calendar_rows("Recent Week Pages", sources.get("recent_weeks") or [], 6)
        add_calendar_rows("Recent Month Pages", sources.get("recent_months") or [], 3)
        return "\n".join(lines)

    @staticmethod
    def source_counts(sources: dict[str, Any]) -> dict[str, int]:
        return {
            "context_snapshots": len(sources.get("context_snapshots") or []),
            "surface_rows": len(sources.get("surface_rows") or []),
            "recent_days": len(sources.get("recent_days") or []),
            "recent_weeks": len(sources.get("recent_weeks") or []),
            "recent_months": len(sources.get("recent_months") or []),
            "recent_heartbeats": len(sources.get("recent_heartbeats") or []),
            "context_messages": sum(len(item.get("messages") or []) for item in sources.get("context_snapshots") or []),
        }
