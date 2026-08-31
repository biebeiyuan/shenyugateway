from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.gateway_tools import GatewayToolService

from .fake_postgrest import apply_order, project_select


class FakeCalendarSupabase:
    def __init__(self):
        self.rows = []
        self.updated = []
        self.inserted = []

    async def query(self, table, params=None):
        if table != "calendar_pages":
            return []
        params = params or {}
        period_type = params.get("period_type")
        period_key = params.get("period_key")
        rows = [row for row in self.rows if row.get("period_type") == period_type[3:] and row.get("period_key") == period_key[3:]]
        rows = apply_order(rows, params)
        limit = int(params.get("limit") or len(rows) or 0)
        return project_select(rows[:limit], params)

    async def update(self, table, match, data):
        if table != "calendar_pages":
            return []
        self.updated.append((match, data))
        for row in self.rows:
            if all(str(row.get(key)) == str(value) for key, value in match.items()):
                row.update(data)
                return [dict(row)]
        return []

    async def insert(self, table, data):
        if table != "calendar_pages":
            return {}
        row = dict(data)
        row.setdefault("id", f"page-{len(self.inserted) + 1}")
        self.rows.append(row)
        self.inserted.append(row)
        return dict(row)


def test_add_calendar_updates_existing_day_page_instead_of_conflicting():
    supabase = FakeCalendarSupabase()
    supabase.rows.append(
        {
            "id": "page-1",
            "period_type": "day",
            "period_key": "2026-06-19",
            "period_start": "2026-06-19T00:00:00+00:00",
            "period_end": "2026-06-20T00:00:00+00:00",
            "version": 1,
            "is_latest": True,
            "title": "旧标题",
            "content": "旧内容",
            "summary": "",
            "digest": "旧内容",
            "author": "沈予",
            "source_model": "manual-calendar",
            "source_refs": "[]",
            "session_tags": "[]",
            "meta": "{}",
            "status": "final",
            "prompt_snapshot": "",
            "generated_by": "manual",
        }
    )
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=supabase, store=None)

    result = asyncio.run(
        service.add_calendar(
            content="新内容",
            period_key="2026-06-19",
            period_type="day",
            title="新标题",
        )
    )

    assert result["ok"] is True
    assert supabase.updated[0] == ({"id": "page-1"}, {"is_latest": False})
    assert len(supabase.inserted) == 1
    assert supabase.inserted[0]["content"] == "旧内容\n\n---\n\n新内容"
