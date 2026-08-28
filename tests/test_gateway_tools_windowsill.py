from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.gateway_tools import GatewayToolService

from .fake_postgrest import project_select


class FakeSupabase:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserts = []
        self.queries = []

    async def insert(self, table, data):
        self.inserts.append((table, data))
        return {
            "id": "windowsill-1",
            **data,
            "created_at": "2026-07-10T08:00:00+00:00",
        }

    async def query(self, table, params):
        self.queries.append((table, params))
        return project_select(self.rows, params)


def _service(supabase):
    return GatewayToolService(
        runtime_config=SimpleNamespace(),
        supabase=supabase,
        store=None,
    )


def test_windowsill_write_leaves_created_at_to_database():
    supabase = FakeSupabase()

    result = asyncio.run(
        _service(supabase).windowsill_write(
            content="风吹进来一点，我就不想急着解释了。",
            title="晚一点",
            mood="松下来",
        )
    )

    assert result["ok"] is True
    assert result["data"]["created_at"] == "2026-07-10T08:00:00+00:00"
    assert supabase.inserts == [
        (
            "windowsill",
            {
                "content": "风吹进来一点，我就不想急着解释了。",
                "title": "晚一点",
                "mood": "松下来",
            },
        )
    ]
    assert "created_at" not in supabase.inserts[0][1]


def test_windowsill_write_rejects_blank_content():
    result = asyncio.run(_service(FakeSupabase()).windowsill_write(content="  "))

    assert result == {
        "ok": False,
        "error": "content is required.",
        "error_kind": "validation",
    }


def test_windowsill_list_filters_mood_and_orders_recent_first():
    rows = [
        {
            "id": "windowsill-1",
            "content": "一小段。",
            "title": "",
            "mood": "安静",
            "created_at": "2026-07-10T08:00:00+00:00",
        }
    ]
    supabase = FakeSupabase(rows)

    result = asyncio.run(_service(supabase).windowsill_list(mood=" 安静 ", limit=4))

    assert result == {"ok": True, "count": 1, "data": rows}
    assert supabase.queries == [
        (
            "windowsill",
            {
                "select": "id,content,title,mood,origin,created_at",
                "order": "created_at.desc",
                "limit": "4",
                "mood": "eq.安静",
            },
        )
    ]
