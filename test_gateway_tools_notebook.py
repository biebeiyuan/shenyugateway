from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.gateway_tools import GatewayToolService


class FakeSupabase:
    def __init__(self):
        self.inserts = []
        self.queries = []

    async def insert(self, table, data):
        self.inserts.append((table, data))
        return {"id": "nb_1", **data}

    async def query(self, table, params):
        self.queries.append((table, params))
        return []


def test_notebook_write_marks_handoff_for_hisense():
    supabase = FakeSupabase()
    service = GatewayToolService(
        runtime_config=SimpleNamespace(),
        supabase=supabase,
        store=None,
    )

    result = asyncio.run(
        service.notebook_write(
            type_=None,
            content="给海信那边留一条交接。",
            tags=["release"],
            metadata={"source": "test"},
            session_tag="5.29",
            scope="handoff",
        )
    )

    assert result["ok"] is True
    assert supabase.inserts == [
        (
            "shenyu_notebook",
            {
                "type": "handoff",
                "content": "给海信那边留一条交接。",
                "status": "active",
                "tags": ["release", "handoff", "hisense"],
                "metadata": {"source": "test", "scope": "handoff"},
                "session_tag": "5.29",
            },
        )
    ]


def test_notebook_list_filters_hisense_scope_by_tag():
    supabase = FakeSupabase()
    service = GatewayToolService(
        runtime_config=SimpleNamespace(),
        supabase=supabase,
        store=None,
    )

    result = asyncio.run(
        service.notebook_list(
            type_filter=None,
            status="active",
            limit=4,
            scope="hisense",
        )
    )

    assert result == {"ok": True, "count": 0, "data": []}
    assert supabase.queries == [
        (
            "shenyu_notebook",
            {
                "order": "pinned.desc,updated_at.desc",
                "limit": "4",
                "select": "id,type,content,tags,status,pinned,metadata,created_at,updated_at",
                "status": "eq.active",
                "tags": "cs.{hisense}",
            },
        )
    ]


def test_add_calendar_does_not_derive_summary_from_content():
    supabase = FakeSupabase()
    service = GatewayToolService(
        runtime_config=SimpleNamespace(),
        supabase=supabase,
        store=None,
    )

    result = asyncio.run(
        service.add_calendar(
            content="这是一段手写日历正文，应该只进入正文和 digest 兜底，不应该被截成 summary。",
            period_key="2026-05-18",
            period_type="day",
        )
    )

    assert result["ok"] is True
    assert supabase.inserts[0][0] == "calendar_pages"
    payload = supabase.inserts[0][1]
    assert payload["content"].startswith("这是一段手写日历正文")
    assert payload["summary"] == ""
    assert payload["digest"]
