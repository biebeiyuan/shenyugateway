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

    async def list_mem_notes(
        self,
        status: str = "captured",
        limit: int = 30,
        session_tag: str = None,
        q: str = "",
        mem_type=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_list_mem_notes",
                "q": q,
                "session_tag": session_tag,
                "limit": limit,
                "status": status,
                "mem_type": mem_type,
            }
        )
        return {"ok": True, "q": q, "status": status, "limit": limit}

    async def search_primary_texts(self, query: str, categories=None, session_tag=None, limit: int = 5):
        self.calls.append(
            {
                "tool": "shenyu_search_primary_texts",
                "query": query,
                "categories": categories,
                "session_tag": session_tag,
                "limit": limit,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

    async def recall(
        self,
        query: str,
        source_types=None,
        session_tag=None,
        date_from=None,
        date_to=None,
        include_undated: bool = True,
        limit: int = 8,
        auto_sync: bool = True,
    ):
        self.calls.append(
            {
                "tool": "shenyu_recall",
                "query": query,
                "source_types": source_types,
                "session_tag": session_tag,
                "date_from": date_from,
                "date_to": date_to,
                "include_undated": include_undated,
                "limit": limit,
                "auto_sync": auto_sync,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

    async def ask_memory(
        self,
        query: str,
        session_tag: str,
        limit: int = 8,
        date=None,
        date_from=None,
        date_to=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_ask_memory",
                "query": query,
                "session_tag": session_tag,
                "limit": limit,
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

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

    async def bulk_update_mem_notes(self, ids=None, patch=None, updates=None, use_suggestions=False):
        self.calls.append(
            {
                "tool": "shenyu_bulk_update_mem_notes",
                "ids": ids,
                "patch": patch,
                "updates": updates,
                "use_suggestions": use_suggestions,
            }
        )
        return {"ok": True, "updated_count": len(ids or []) + len(updates or [])}

    async def delete_mem_note(self, note_id: str):
        self.calls.append(
            {
                "tool": "shenyu_delete_mem_note",
                "note_id": note_id,
            }
        )
        return {"ok": True, "note_id": note_id}

    async def notebook_list(self, type_filter=None, status="active", limit: int = 10, tag=None, scope=None):
        self.calls.append(
            {
                "tool": "shenyu_notebook_list",
                "type_filter": type_filter,
                "status": status,
                "limit": limit,
                "tag": tag,
                "scope": scope,
            }
        )
        return {"ok": True, "limit": limit}

    async def notebook_write(self, type_=None, content="", tags=None, metadata=None, session_tag=None, scope=None):
        self.calls.append(
            {
                "tool": "shenyu_notebook_write",
                "type": type_,
                "content": content,
                "tags": tags,
                "metadata": metadata,
                "session_tag": session_tag,
                "scope": scope,
            }
        )
        return {"ok": True, "content": content}


def _cfg(enable_mem0_management_tools: bool = False):
    return SimpleNamespace(
        enable_gateway_tools=True,
        enable_mem0_management_tools=enable_mem0_management_tools,
        expose_supabase_tools=False,
        gateway_tool_mode="broker",
        default_surface_limit=3,
        mem_note_limit=3,
        enable_recall_auto_sync=False,
    )


def test_execute_gateway_tool_reuses_service_for_broker_target():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_list_mem_notes", "arguments": {"q": "home", "status": "all", "limit": 2}},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "q": "home", "status": "all", "limit": 2}
    assert service.calls == [
        {
            "tool": "shenyu_list_mem_notes",
            "q": "home",
            "session_tag": "default",
            "limit": 2,
            "status": "all",
            "mem_type": None,
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


def test_execute_gateway_tool_routes_hidden_search_mem_notes_for_compat():
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


def test_execute_gateway_tool_accepts_broker_json_string_arguments():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_recall",
                "arguments": "{\"query\":\"长隆海洋馆 海獭 企鹅\",\"limit\":2}",
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "长隆海洋馆 海獭 企鹅", "limit": 2}
    assert service.calls == [
        {
            "tool": "shenyu_recall",
            "query": "长隆海洋馆 海獭 企鹅",
            "source_types": None,
            "session_tag": "default",
            "date_from": None,
            "date_to": None,
            "include_undated": True,
            "limit": 2,
            "auto_sync": False,
        }
    ]


def test_execute_gateway_tool_routes_shenyu_recall():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_recall",
                "arguments": {
                    "query": "长隆 海獭",
                    "source_types": ["memory", "journal"],
                    "include_undated": False,
                    "limit": 6,
                },
            },
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "长隆 海獭", "limit": 6}
    assert service.calls == [
        {
            "tool": "shenyu_recall",
            "query": "长隆 海獭",
            "source_types": ["memory", "journal"],
            "session_tag": "5.15",
            "date_from": None,
            "date_to": None,
            "include_undated": False,
            "limit": 6,
            "auto_sync": False,
        }
    ]


def test_execute_gateway_tool_unwraps_nested_broker_arguments_object():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_recall",
                "arguments": "{\"arguments\":{\"query\":\"claudeai 长隆\",\"limit\":3}}",
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "claudeai 长隆", "limit": 3}
    assert service.calls[0]["query"] == "claudeai 长隆"
    assert service.calls[0]["limit"] == 3


def test_execute_gateway_tool_accepts_q_alias_for_hidden_primary_text_search_compat():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_search_primary_texts",
            {"q": "海獭", "limit": 5},
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "海獭", "limit": 5}
    assert service.calls == [
        {
            "tool": "shenyu_search_primary_texts",
            "query": "海獭",
            "categories": None,
            "session_tag": "5.15",
            "limit": 5,
        }
    ]


def test_execute_gateway_tool_accepts_q_alias_for_surface_passages():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_surface_passages",
            {"q": "海獭", "limit": 2},
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "limit": 2, "session_tag": "5.15"}
    assert service.calls == [
        {
            "tool": "shenyu_surface_passages",
            "query": "海獭",
            "session_tag": "5.15",
            "limit": 2,
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


def test_execute_gateway_tool_routes_bulk_mem_note_update():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_bulk_update_mem_notes",
            {
                "ids": ["note-1", "note-2"],
                "status": "active",
                "use_suggestions": True,
            },
            session_tag="default",
            cfg=_cfg(enable_mem0_management_tools=True),
            service=service,
        )
    )

    assert result == {"ok": True, "updated_count": 2}
    assert service.calls == [
        {
            "tool": "shenyu_bulk_update_mem_notes",
            "ids": ["note-1", "note-2"],
            "patch": {"status": "active"},
            "updates": [],
            "use_suggestions": True,
        }
    ]


def test_execute_gateway_tool_routes_notebook_scope_arguments():
    service = FakeToolService()

    write_result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_notebook_write",
                "arguments": {
                    "content": "给海信那边留一条交接。",
                    "scope": "handoff",
                    "tags": ["release"],
                },
            },
            session_tag="5.29",
            cfg=_cfg(),
            service=service,
        )
    )
    list_result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_notebook_list",
                "arguments": {"scope": "hisense", "limit": 4},
            },
            session_tag="5.29",
            cfg=_cfg(),
            service=service,
        )
    )

    assert write_result == {"ok": True, "content": "给海信那边留一条交接。"}
    assert list_result == {"ok": True, "limit": 4}
    assert service.calls[-2:] == [
        {
            "tool": "shenyu_notebook_write",
            "type": None,
            "content": "给海信那边留一条交接。",
            "tags": ["release"],
            "metadata": None,
            "session_tag": "5.29",
            "scope": "handoff",
        },
        {
            "tool": "shenyu_notebook_list",
            "type_filter": None,
            "status": "active",
            "limit": 4,
            "tag": None,
            "scope": "hisense",
        },
    ]


def test_gateway_tools_do_not_expose_legacy_atomic_memories():
    cfg = _cfg(enable_mem0_management_tools=True)

    broker_tool = gateway_native_tools(cfg)[0]
    assert "shenyu_legacy_atomic_memories" not in broker_tool["function"]["parameters"]["properties"]["tool"]["enum"]

    cfg.gateway_tool_mode = "full"
    names = [tool["function"]["name"] for tool in gateway_native_tools(cfg)]
    assert "shenyu_legacy_atomic_memories" not in names


def test_gateway_tools_expose_all_registered_query_tools():
    cfg = _cfg()
    registered = {
        "shenyu_surface_passages",
        "shenyu_search_primary_texts",
        "shenyu_ask_memory",
        "shenyu_search_mem_notes",
    }

    broker_tool = gateway_native_tools(cfg)[0]
    broker_names = set(broker_tool["function"]["parameters"]["properties"]["tool"]["enum"])
    assert registered.issubset(broker_names)
    assert "shenyu_recall" in broker_names
    assert "shenyu_list_mem_notes" in broker_names

    cfg.gateway_tool_mode = "full"
    full_names = {tool["function"]["name"] for tool in gateway_native_tools(cfg)}
    assert registered.issubset(full_names)
    assert "shenyu_recall" in full_names
    assert "shenyu_list_mem_notes" in full_names


def test_shenyu_recall_source_types_are_public_set_only():
    cfg = _cfg()

    broker_tool = gateway_native_tools(cfg)[0]
    assert "shenyu_recall" in broker_tool["function"]["parameters"]["properties"]["tool"]["enum"]

    cfg.gateway_tool_mode = "full"
    recall_tool = next(tool for tool in gateway_native_tools(cfg) if tool["function"]["name"] == "shenyu_recall")
    source_types = recall_tool["function"]["parameters"]["properties"]["source_types"]["items"]["enum"]
    include_undated = recall_tool["function"]["parameters"]["properties"]["include_undated"]

    assert source_types == ["all", "memory", "journal", "room", "board", "calendar", "notebook"]
    assert include_undated["default"] is True
    assert "mem_note" not in source_types
    assert "note" not in source_types
    assert "atomic" not in source_types
    assert "meta" not in source_types
