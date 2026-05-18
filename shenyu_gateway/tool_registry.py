from __future__ import annotations

from typing import Any, Optional

from shenyu_gateway.gateway_tools import GatewayToolService


def _gateway_core_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_surface_passages",
                "description": "Surface relevant room / message_board passages. This does not search diary, letters, or paper notes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What you want surfaced."},
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
                "description": "Show the common Supabase tables, fields, categories, and writing conventions for home data.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_ask_memory",
                "description": "Recall event memories from the core memories table. Returns only title, date, summary, facts, and emotional_context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Words to look for. Use * or leave broad when listing by date."},
                        "date": {"type": "string", "description": "One exact memory date, e.g. 2026-04-05."},
                        "date_from": {"type": "string", "description": "Start date for a memory date range."},
                        "date_to": {"type": "string", "description": "End date for a memory date range."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                        "session_tag": {"type": "string", "description": "Optional advanced filter. Usually omit this because core memories are shared across sessions."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_search_atomic_memory",
                "description": "Search small atomic memory notes for durable preferences, states, commitments, and relationship continuity.",
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
                "description": "Search diary, letters, paper notes, room text, or message board explicitly by category.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What you want to find in primary texts."},
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
                "description": "Write a manual calendar memory page into calendar_pages. Multiple pages for the same day can coexist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The full manually written calendar page content."},
                        "period_key": {"type": "string", "description": "Date or period key. Defaults to today for day pages, e.g. 2026-05-11."},
                        "period_type": {"type": "string", "enum": ["day", "week", "month"], "default": "day"},
                        "title": {"type": "string"},
                        "summary": {"type": "string", "description": "Short listing summary. Defaults to a shortened content excerpt."},
                        "digest": {"type": "string", "description": "Injected calendar memory digest. Defaults to summary/content excerpt."},
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
                "description": "Browse your own mem notes. Default is inline active notes; add date, query, status, or tags only when you want to narrow it down.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Words to look for. Leave empty to just list notes."},
                        "date": {"type": "string", "description": "One local day, e.g. 2026-05-11."},
                        "date_from": {"type": "string", "description": "Start local day/date-time for a range."},
                        "date_to": {"type": "string", "description": "End local day/date-time for a range. Same as date_from means that whole local day."},
                        "status": {"type": "string", "enum": ["active", "proposed", "deprecated", "superseded", "all"], "default": "active"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Require all tags.",
                        },
                        "source": {"type": "string", "enum": ["inline", "manual", "auto", "captured", "all"], "default": "inline", "description": "Usually leave this as inline. Use all/manual/auto only while tidying."},
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
                "description": "Read stored heartbeat notes. To see one day, pass date like 2026-05-11. scope=auto reads the current session's pool; use scope=normal for the default/global pool or scope=hisense for the Hisense pool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "One local day, e.g. 2026-05-11."},
                        "date_from": {"type": "string", "description": "Start local day/date-time for a range."},
                        "date_to": {"type": "string", "description": "End local day/date-time for a range."},
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
                "description": "Load active context summaries from Supabase.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_last_seen",
                "description": "Load the latest heartbeat / interaction summary.",
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
                "description": "Browse your own mem0 atomic memories for review. Use this when you feel like tidying proposed or active notes.",
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
                "description": "Edit one mem0 atomic memory's text or classification before/after review.",
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
                "description": "Approve, requeue, or mark old one mem0 atomic memory without touching database details.",
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
                "description": "Delete one mem0 atomic memory when it is noise or no longer wanted.",
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
                "description": "查看圆儿那边最近的聊天记录。不会自动出现在上下文里，需要你主动查。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "since": {"type": "string", "description": "起始时间 ISO 格式，如 2026-05-10T00:00:00Z"},
                        "until": {"type": "string", "description": "截止时间 ISO 格式（可选）"},
                        "query": {"type": "string", "description": "关键词搜索，匹配聊天内容"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_list",
                "description": "列出笔记本里的条目（想法、待办、笔记、观察、问题）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "按类型筛选：thought/task/note/observation/question"},
                        "status": {"type": "string", "default": "active", "description": "状态筛选：active/done/archived"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_write",
                "description": "往笔记本里写一条新的。想法、待办、随手记都行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "default": "note", "description": "类型：thought/task/note/observation/question"},
                        "content": {"type": "string", "description": "正文内容"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（可选）"},
                        "metadata": {"type": "object", "description": "附加信息（可选）"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_update",
                "description": "修改笔记本里已有的条目（改内容、改状态、加标签、置顶等）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "条目 ID"},
                        "content": {"type": "string"},
                        "status": {"type": "string", "description": "active/done/archived"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "type": {"type": "string"},
                        "pinned": {"type": "boolean", "description": "置顶，启动时优先展示"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id"],
                },
            },
        },
    ]


def gateway_native_tools(cfg: Any) -> list[dict]:
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
                        "description": "Query any Supabase table directly. Use filters for equality shorthand and operators for ranges, in lists, ilike, and null checks.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "table": {"type": "string"},
                                "filters": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "Equality shorthand, e.g. {\"status\":\"active\"}. Legacy PostgREST strings like \"gte.2026-01-01\" also work.",
                                },
                                "operators": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "Either short form on created_at, e.g. {\"gte\":\"2026-05-01\",\"lte\":\"2026-05-12\"}, or per-column form, e.g. {\"content\":{\"ilike\":\"%xx%\"},\"id\":{\"in\":[\"a\",\"b\"]}}.",
                                },
                                "column": {"type": "string", "description": "Optional column for short-form operators. Defaults to created_at."},
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
                        "description": "Insert a row into any Supabase table. Returns the inserted row.",
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
                        "description": "Update rows in any Supabase table. Use match for equality shorthand and operators for ranges, in lists, ilike, and null checks. Returns updated rows.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "table": {"type": "string"},
                                "match": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "Equality shorthand, e.g. {\"id\":\"...\"}.",
                                },
                                "operators": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "Short form defaults to created_at, e.g. {\"gte\":\"2026-05-01\"}; per-column form also works.",
                                },
                                "column": {"type": "string", "description": "Optional column for short-form operators. Defaults to created_at."},
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
                        "description": "Delete rows in any Supabase table. Defaults to soft delete when an is_deleted field exists.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "table": {"type": "string"},
                                "match": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "Equality shorthand, e.g. {\"id\":\"...\"}.",
                                },
                                "operators": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "Short form defaults to created_at, e.g. {\"gte\":\"2026-05-01\"}; per-column form also works.",
                                },
                                "column": {"type": "string", "description": "Optional column for short-form operators. Defaults to created_at."},
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
