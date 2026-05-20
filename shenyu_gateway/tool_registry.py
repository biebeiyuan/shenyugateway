from __future__ import annotations

from typing import Any, Optional

from shenyu_gateway.gateway_tools import GatewayToolService


def _gateway_core_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_surface_passages",
                "description": "Pools: room, message_board. Surface a few relevant living-space passages.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3},
                        "session_tag": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_supabase_guide",
                "description": "Guide: common Supabase tables and writing conventions.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_ask_memory",
                "description": "Table: memories. Recall summarized event memories.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "date": {"type": "string"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                        "session_tag": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_search_atomic_memory",
                "description": "Table: atomic_memories. Search active durable facts, states, preferences, and commitments.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3},
                        "session_tag": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_search_primary_texts",
                "description": "Tables: journal, room, message_board. Search primary texts by category.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "categories": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["diary", "letter", "paper", "lock", "annotation", "life_tick", "room", "message_board", "journal", "all"],
                            },
                            "default": ["diary", "letter", "paper"],
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                        "session_tag": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_add_calendar",
                "description": "Table: calendar_pages. Write a manual day/week/month calendar memory page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "period_key": {"type": "string"},
                        "period_type": {"type": "string", "enum": ["day", "week", "month"], "default": "day"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "digest": {"type": "string"},
                        "author": {"type": "string", "default": "沈予"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_list_self_memories",
                "description": "Table: atomic_memories. Browse assistant-owned mem notes; default is inline active notes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "date": {"type": "string"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "status": {"type": "string", "enum": ["active", "proposed", "deprecated", "superseded", "all"], "default": "active"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "source": {"type": "string", "enum": ["inline", "manual", "auto", "captured", "all"], "default": "inline"},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_read_heartbeat",
                "description": "SQLite pools: heartbeat_entries, hisense_heartbeat. Read heartbeat notes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "session_tag": {"type": "string"},
                        "scope": {"type": "string", "enum": ["auto", "normal", "hisense"], "default": "auto"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                        "state": {"type": "string", "enum": ["all", "pending", "injected"], "default": "all"},
                        "order": {"type": "string", "enum": ["desc", "asc"], "default": "desc"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_get_meta_summaries",
                "description": "RPC: get_meta_summaries. Load active context summaries.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_last_seen",
                "description": "RPC: last_seen. Load the latest interaction summary.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


def _gateway_mem0_management_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_list_atomic_memories",
                "description": "Table: atomic_memories. Browse mem0 rows for review.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["proposed", "active", "deprecated", "all"], "default": "proposed"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                        "session_tag": {"type": "string"},
                        "query": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_update_atomic_memory",
                "description": "Table: atomic_memories. Edit one mem0 row.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "content_surface": {"type": "string"},
                        "subject": {"type": "string", "enum": ["圆圆", "沈予", "我们"]},
                        "memory_type": {"type": "string", "enum": ["emotion", "commitment", "fact", "relation", "preference", "boundary"]},
                        "tier": {"type": "integer", "minimum": 1, "maximum": 4},
                        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                        "quote": {"type": "string"},
                        "time_hint": {"type": "string"},
                    },
                    "required": ["memory_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_review_atomic_memory",
                "description": "Table: atomic_memories. Approve, requeue, deprecate, or supersede one mem0 row.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "action": {"type": "string", "enum": ["approve", "requeue", "deprecate", "supersede"]},
                    },
                    "required": ["memory_id", "action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_delete_atomic_memory",
                "description": "Table: atomic_memories. Delete one mem0 row.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                    },
                    "required": ["memory_id"],
                },
            },
        },
    ]


def _gateway_notebook_and_recall_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_recall_main_thread",
                "description": "SQLite: gateway_messages. Recall recent main-thread dialogue.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "since": {"type": "string"},
                        "until": {"type": "string"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_list",
                "description": "Table: shenyu_notebook. List notebook entries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "status": {"type": "string", "default": "active"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_write",
                "description": "Table: shenyu_notebook. Write a notebook entry.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "default": "note"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_update",
                "description": "Table: shenyu_notebook. Update a notebook entry.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "type": {"type": "string"},
                        "pinned": {"type": "boolean"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id"],
                },
            },
        },
    ]


def _expanded_gateway_native_tools(cfg: Any) -> list[dict]:
    tools = []
    if cfg.enable_gateway_tools:
        tools.extend(_gateway_core_tools())
    if cfg.enable_mem0_management_tools:
        tools.extend(_gateway_mem0_management_tools())
    if cfg.expose_supabase_tools:
        tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "supabase_query",
                        "description": "Supabase fallback. Query a table directly.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "table": {"type": "string"},
                                "filters": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "operators": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "column": {"type": "string"},
                                "select": {"type": "string"},
                                "order": {"type": "string"},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                            },
                            "required": ["table"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "supabase_insert",
                        "description": "Supabase fallback. Insert one row.",
                        "parameters": {
                            "type": "object",
                            "properties": {"table": {"type": "string"}, "data": {"type": "object", "additionalProperties": True}},
                            "required": ["table", "data"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "supabase_update",
                        "description": "Supabase fallback. Update matched rows.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "table": {"type": "string"},
                                "match": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "operators": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "column": {"type": "string"},
                                "data": {"type": "object", "additionalProperties": True},
                            },
                            "required": ["table", "data"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "supabase_delete",
                        "description": "Supabase fallback. Delete matched rows.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "table": {"type": "string"},
                                "match": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "operators": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "column": {"type": "string"},
                                "hard": {"type": "boolean", "default": False},
                            },
                            "required": ["table"],
                        },
                    },
                },
            ]
        )
    tools.extend(_gateway_notebook_and_recall_tools())
    return tools


def _gateway_tool_names(cfg: Any) -> list[str]:
    return [tool["function"]["name"] for tool in _expanded_gateway_native_tools(cfg)]


def _gateway_broker_tool(cfg: Any) -> dict:
    names = _gateway_tool_names(cfg)
    description = (
        "Compact gateway tool broker. Use it when gateway memory, heartbeat, notebook, "
        "calendar, primary-text search, or Supabase access is needed. Set `tool` to one "
        "available tool name and put that tool's normal arguments in `arguments`. "
        "Available tools: " + ", ".join(names)
    )
    return {
        "type": "function",
        "function": {
            "name": "shenyu_gateway_tool",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": names},
                    "arguments": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Arguments for the selected gateway tool.",
                    },
                },
                "required": ["tool", "arguments"],
            },
        },
    }


def gateway_native_tools(cfg: Any) -> list[dict]:
    tools_enabled = bool(cfg.enable_gateway_tools or cfg.enable_mem0_management_tools or cfg.expose_supabase_tools)
    if not tools_enabled:
        return []
    if getattr(cfg, "gateway_tool_mode", "full") == "broker":
        return [_gateway_broker_tool(cfg)]
    return _expanded_gateway_native_tools(cfg)


def merge_tools(client_tools: Optional[list[dict]], cfg: Any) -> list[dict]:
    merged = list(client_tools or [])
    if not cfg.enable_gateway_tools and not cfg.enable_mem0_management_tools and not cfg.expose_supabase_tools:
        return merged
    existing = {tool.get("function", {}).get("name") for tool in merged if isinstance(tool, dict)}
    for tool in gateway_native_tools(cfg):
        name = tool["function"]["name"]
        if name not in existing:
            merged.append(tool)
    return merged


def is_gateway_native_tool(name: str) -> bool:
    return name.startswith("shenyu_") or name.startswith("supabase_")


async def execute_gateway_tool(name: str, arguments: dict, session_tag: Optional[str], cfg: Any) -> dict:
    service = GatewayToolService()
    if name == "shenyu_gateway_tool":
        target_name = str(arguments.get("tool") or arguments.get("name") or "").strip()
        target_args = arguments.get("arguments") or {}
        if not isinstance(target_args, dict):
            return {"ok": False, "error": "`arguments` must be an object."}
        allowed = set(_gateway_tool_names(cfg))
        if target_name not in allowed:
            return {
                "ok": False,
                "error": f"Unsupported gateway broker target: {target_name}",
                "available_tools": sorted(allowed),
            }
        return await execute_gateway_tool(target_name, target_args, session_tag=session_tag, cfg=cfg)
    if name == "shenyu_surface_passages":
        return await service.surface_passages(
            query=arguments.get("query", ""),
            session_tag=arguments.get("session_tag") or session_tag,
            limit=int(arguments.get("limit", cfg.default_surface_limit)),
        )
    if name == "shenyu_search_primary_texts":
        return await service.search_primary_texts(
            query=arguments.get("query", ""),
            categories=arguments.get("categories"),
            session_tag=arguments.get("session_tag") or session_tag,
            limit=int(arguments.get("limit", 5)),
        )
    if name == "shenyu_add_calendar":
        return await service.add_calendar(
            content=arguments.get("content", ""),
            period_key=arguments.get("period_key"),
            period_type=arguments.get("period_type", "day"),
            title=arguments.get("title", ""),
            summary=arguments.get("summary", ""),
            digest=arguments.get("digest", ""),
            author=arguments.get("author", "沈予"),
        )
    if name == "shenyu_supabase_guide":
        return await service.supabase_guide()
    if name == "shenyu_ask_memory":
        return await service.ask_memory(
            query=arguments.get("query", ""),
            session_tag=arguments.get("session_tag"),
            limit=int(arguments.get("limit", 8)),
            date=arguments.get("date"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
        )
    if name == "shenyu_search_atomic_memory":
        return await service.search_atomic_memories(
            query=arguments.get("query", ""),
            session_tag=arguments.get("session_tag") or session_tag,
            limit=int(arguments.get("limit", cfg.default_atomic_memory_limit)),
        )
    if name == "shenyu_list_self_memories":
        return await service.list_self_memories(
            query=arguments.get("query", ""),
            status=arguments.get("status", "active"),
            source=arguments.get("source", "inline"),
            date=arguments.get("date"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            created_from=arguments.get("created_from"),
            created_to=arguments.get("created_to"),
            tags=arguments.get("tags"),
            session_tag=arguments.get("session_tag") or session_tag,
            limit=int(arguments.get("limit", 20)),
        )
    if name == "shenyu_read_heartbeat":
        return await service.read_heartbeat(
            session_tag=arguments.get("session_tag") or session_tag,
            limit=int(arguments.get("limit", 10)),
            state=arguments.get("state", "all"),
            order=arguments.get("order", "desc"),
            scope=arguments.get("scope", "auto"),
            date=arguments.get("date"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            created_from=arguments.get("created_from"),
            created_to=arguments.get("created_to"),
        )
    if name == "shenyu_list_atomic_memories":
        return await service.list_atomic_memories_for_review(
            status=arguments.get("status", "proposed"),
            limit=int(arguments.get("limit", 20)),
            session_tag=arguments.get("session_tag") or session_tag,
            query=arguments.get("query", ""),
        )
    if name == "shenyu_update_atomic_memory":
        payload = {key: value for key, value in arguments.items() if key != "memory_id"}
        return await service.update_atomic_memory_for_review(arguments.get("memory_id", ""), payload)
    if name == "shenyu_review_atomic_memory":
        return await service.review_atomic_memory_action(
            arguments.get("memory_id", ""),
            arguments.get("action", ""),
        )
    if name == "shenyu_delete_atomic_memory":
        return await service.delete_atomic_memory_for_review(arguments.get("memory_id", ""))
    if name == "shenyu_get_meta_summaries":
        return {"meta_summaries": await service.meta_summaries()}
    if name == "shenyu_last_seen":
        return {"last_seen": await service.last_seen()}
    if name == "supabase_query":
        return await service.supabase_query(
            table=arguments.get("table", ""),
            filters=arguments.get("filters"),
            operators=arguments.get("operators"),
            column=arguments.get("column"),
            select=arguments.get("select"),
            order=arguments.get("order"),
            limit=int(arguments.get("limit", 20)),
        )
    if name == "supabase_insert":
        return await service.supabase_insert(
            table=arguments.get("table", ""),
            data=arguments.get("data") or {},
        )
    if name == "supabase_update":
        return await service.supabase_update(
            table=arguments.get("table", ""),
            match=arguments.get("match") or {},
            data=arguments.get("data") or {},
            operators=arguments.get("operators"),
            column=arguments.get("column"),
        )
    if name == "supabase_delete":
        return await service.supabase_delete(
            table=arguments.get("table", ""),
            match=arguments.get("match") or {},
            hard=bool(arguments.get("hard", False)),
            operators=arguments.get("operators"),
            column=arguments.get("column"),
        )
    if name == "shenyu_recall_main_thread":
        return await service.recall_main_thread(
            since=arguments.get("since"),
            until=arguments.get("until"),
            query=arguments.get("query"),
            limit=int(arguments.get("limit", 10)),
        )
    if name == "shenyu_notebook_list":
        return await service.notebook_list(
            type_filter=arguments.get("type"),
            status=arguments.get("status", "active"),
            limit=int(arguments.get("limit", 10)),
        )
    if name == "shenyu_notebook_write":
        return await service.notebook_write(
            type_=arguments.get("type", "note"),
            content=arguments.get("content", ""),
            tags=arguments.get("tags"),
            metadata=arguments.get("metadata"),
            session_tag=session_tag,
        )
    if name == "shenyu_notebook_update":
        return await service.notebook_update(
            id_=arguments.get("id", ""),
            content=arguments.get("content"),
            status=arguments.get("status"),
            tags=arguments.get("tags"),
            type_=arguments.get("type"),
            pinned=arguments.get("pinned"),
            metadata=arguments.get("metadata"),
        )
    raise ValueError(f"Unsupported gateway tool: {name}")
