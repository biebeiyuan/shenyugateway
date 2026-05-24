from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.tool_registry import execute_gateway_tool, gateway_native_tools


class FakeToolService:
    def __init__(self):
        self.calls = []

    async def surface_passages(self, query: str, session_tag: str, limit: int):
        self.calls.append(
            {
                "tool": "shenyu_surface_passages",
                "query": query,
                "session_tag": session_tag,
                "limit": limit,
            }
        )
        return {"ok": True, "limit": limit, "session_tag": session_tag}

    async def search_mem_notes(
        self,
        query: str,
        session_tag: str,
        limit: int,
        status: str = "all",
        mem_type=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_search_mem_notes",
                "query": query,
                "session_tag": session_tag,
                "limit": limit,
                "status": status,
                "mem_type": mem_type,
            }
        )
        return {"ok": True, "query": query, "status": status, "limit": limit}

    async def write_mem_note(
        self,
        content: str,
        session_tag: str,
        mem_type=None,
        trigger_text="",
        trigger_keywords=None,
        status="active",
        cooldown_hours=None,
        review_note="",
    ):
        self.calls.append(
            {
                "tool": "shenyu_write_mem_note",
                "content": content,
                "session_tag": session_tag,
                "mem_type": mem_type,
                "trigger_text": trigger_text,
                "trigger_keywords": trigger_keywords,
                "status": status,
                "cooldown_hours": cooldown_hours,
                "review_note": review_note,
            }
        )
        return {"ok": True, "content": content, "status": status, "session_tag": session_tag}

    async def update_mem_note(self, note_id: str, patch: dict):
        self.calls.append(
            {
                "tool": "shenyu_update_mem_note",
                "note_id": note_id,
                "patch": patch,
            }
        )
        return {"ok": True, "note_id": note_id, "patch": patch}

    async def delete_mem_note(self, note_id: str):
        self.calls.append(
            {
                "tool": "shenyu_delete_mem_note",
                "note_id": note_id,
            }
        )
        return {"ok": True, "note_id": note_id}


def _cfg(enable_mem0_management_tools: bool = False):
    return SimpleNamespace(
        enable_gateway_tools=True,
        enable_mem0_management_tools=enable_mem0_management_tools,
        expose_supabase_tools=False,
        gateway_tool_mode="broker",
        default_surface_limit=3,
        mem_note_limit=3,
    )


def test_execute_gateway_tool_reuses_service_for_broker_target():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_surface_passages", "arguments": {"query": "home", "limit": 2}},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "limit": 2, "session_tag": "default"}
    assert service.calls == [
        {
            "tool": "shenyu_surface_passages",
            "query": "home",
            "session_tag": "default",
            "limit": 2,
        }
    ]


def test_execute_gateway_tool_uses_default_for_invalid_integer_arg():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_surface_passages",
            {"query": "home", "limit": "not-a-number"},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result["limit"] == 3
    assert service.calls[0]["limit"] == 3


def test_execute_gateway_tool_routes_write_mem_note():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_write_mem_note",
                "arguments": {
                    "content": "圆圆今天帮我把上游预设修回气泡。",
                },
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {
        "ok": True,
        "content": "圆圆今天帮我把上游预设修回气泡。",
        "status": "active",
        "session_tag": "default",
    }
    assert service.calls == [
        {
            "tool": "shenyu_write_mem_note",
            "content": "圆圆今天帮我把上游预设修回气泡。",
            "session_tag": "default",
            "mem_type": None,
            "trigger_text": "",
            "trigger_keywords": None,
            "status": "active",
            "cooldown_hours": None,
            "review_note": "",
        }
    ]


def test_execute_gateway_tool_routes_search_mem_notes_as_browse():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_search_mem_notes",
            {"q": "北海道", "status": "all", "limit": 60},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "北海道", "status": "all", "limit": 60}
    assert service.calls == [
        {
            "tool": "shenyu_search_mem_notes",
            "query": "北海道",
            "session_tag": "default",
            "limit": 60,
            "status": "all",
            "mem_type": None,
        }
    ]


def test_execute_gateway_tool_accepts_mem_note_id_alias_for_update():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_update_mem_note",
            {
                "id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
                "status": "active",
                "trigger_text": "整理 mem",
            },
            session_tag="default",
            cfg=_cfg(enable_mem0_management_tools=True),
            service=service,
        )
    )

    assert result == {
        "ok": True,
        "note_id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
        "patch": {"status": "active", "trigger_text": "整理 mem"},
    }
    assert service.calls == [
        {
            "tool": "shenyu_update_mem_note",
            "note_id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
            "patch": {"status": "active", "trigger_text": "整理 mem"},
        }
    ]


def test_gateway_tools_do_not_expose_legacy_atomic_memories():
    cfg = _cfg(enable_mem0_management_tools=True)

    broker_tool = gateway_native_tools(cfg)[0]
    assert "shenyu_legacy_atomic_memories" not in broker_tool["function"]["parameters"]["properties"]["tool"]["enum"]

    cfg.gateway_tool_mode = "full"
    names = [tool["function"]["name"] for tool in gateway_native_tools(cfg)]
    assert "shenyu_legacy_atomic_memories" not in names
