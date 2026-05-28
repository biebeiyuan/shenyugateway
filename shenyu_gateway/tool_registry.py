from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.mem_notes import MEM_NOTE_TYPES


MEM_NOTE_TYPE_ENUM = list(MEM_NOTE_TYPES)


def _gateway_core_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_recall",
                "description": "统一召回入口：按语义/关键词查 memories、journal、room、calendar、mem、notebook 等索引，不需要猜 Supabase 表。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "source_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["all", "memory", "journal", "room", "board", "calendar", "note", "atomic", "notebook", "meta"],
                            },
                            "default": ["all"],
                        },
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 8},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_surface_passages",
                "description": "从 room 和留言板里捞几段相关原文，适合先找手边的感觉。",
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
                "description": "不知道该查哪个 Supabase 表时，先看这个。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_ask_memory",
                "description": "ClaudeAI 时期的旧记忆库；查以前整理过的事件、关系脉络或某天发生过什么。",
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
                "name": "shenyu_search_mem_notes",
                "description": "查看我写过的 mem 便签，可按关键词筛选。默认查所有状态；当前聊天相关的 active mem 会由网关自动命中，不需要用这个工具反复召回。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "description": "关键词过滤 content/type/trigger/review_note。"},
                        "query": {"type": "string", "description": "Alias of q."},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived", "all"], "default": "all"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_search_primary_texts",
                "description": "查日记、信、纸条、room、留言板这些原文。",
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
                "description": "手动写一页 day / week / month 日历记忆。",
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
                "name": "shenyu_list_mem_notes",
                "description": "看 mem 便签列表。整理时通常先看 status=captured。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived", "all"], "default": "captured"},
                        "q": {"type": "string"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_write_mem_note",
                "description": "我主动写一条新的 mem 便签。默认 active 直接放行；没填 trigger 时用正文当 trigger，没填 type 时先归到“心里那一档”。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "trigger_text": {"type": "string"},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"], "default": "active"},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760},
                        "review_note": {"type": "string"},
                        "session_tag": {"type": "string"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_read_heartbeat",
                "description": "读我以前留给自己的心跳。",
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
                "description": "读取当前启用的元摘要。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_last_seen",
                "description": "读取最近一次互动摘要。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


def _gateway_mem0_management_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_update_mem_note",
                "description": "补或修改一条 mem 便签的 type、trigger、触发词、状态和冷却时间。设为 active 前必须补 type 和 trigger。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "Use the id returned by shenyu_list_mem_notes."},
                        "id": {"type": "string", "description": "Alias of note_id."},
                        "noteId": {"type": "string", "description": "Alias of note_id."},
                        "content": {"type": "string"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "trigger_text": {"type": "string"},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"]},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760},
                        "review_note": {"type": "string"},
                    },
                    "required": ["note_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_delete_mem_note",
                "description": "删除一条 mem 便签。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "Use the id returned by shenyu_list_mem_notes."},
                        "id": {"type": "string", "description": "Alias of note_id."},
                        "noteId": {"type": "string", "description": "Alias of note_id."},
                    },
                    "required": ["note_id"],
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
                "description": "查最近主线程对话。",
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
                "description": "看 notebook 里留过的条目。",
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
                "description": "写一条 notebook，适合跨窗口或海信那边留事。",
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
                "description": "修改一条 notebook。",
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
        "这是网关工具箱。想查旧记忆、mem 便签、心跳、日记、room、notebook 或 Supabase 时，"
        "用 `tool` 选择名字，把参数放进 `arguments`。可用工具：" + ", ".join(names)
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


def _int_arg(arguments: dict, key: str, default: int) -> int:
    try:
        return int(arguments.get(key, default))
    except (TypeError, ValueError):
        return default


def _coerce_json_object(value: Any) -> Optional[dict]:
    current = value
    for _ in range(2):
        if not isinstance(current, str):
            break
        text = current.strip()
        if not text:
            return {}
        try:
            current = json.loads(text)
        except json.JSONDecodeError:
            return None
    return current if isinstance(current, dict) else None


def _coerce_broker_arguments(value: Any) -> Optional[dict]:
    target_args = _coerce_json_object(value)
    if target_args is None:
        return None
    if set(target_args) == {"arguments"}:
        nested_args = _coerce_json_object(target_args.get("arguments"))
        if nested_args is not None:
            return nested_args
    return target_args


def _mem_note_id_arg(arguments: dict) -> str:
    for key in ("note_id", "id", "noteId"):
        value = arguments.get(key)
        if value:
            return str(value)
    return ""


def _mem_note_patch_args(arguments: dict) -> dict:
    id_keys = {"note_id", "id", "noteId"}
    return {key: value for key, value in arguments.items() if key not in id_keys}


async def _wrapped_service_result(key: str, awaitable: Awaitable[Any]) -> dict:
    return {key: await awaitable}


async def execute_gateway_tool(
    name: str,
    arguments: dict,
    session_tag: Optional[str],
    cfg: Any,
    service: Optional[GatewayToolService] = None,
) -> dict:
    arguments = arguments if isinstance(arguments, dict) else {}
    service = service or GatewayToolService(runtime_config=cfg)
    if name == "shenyu_gateway_tool":
        target_name = str(arguments.get("tool") or arguments.get("name") or "").strip()
        raw_target_args = arguments.get("arguments")
        if raw_target_args is None:
            raw_target_args = {key: value for key, value in arguments.items() if key not in {"tool", "name"}}
        target_args = _coerce_broker_arguments(raw_target_args)
        if target_args is None:
            return {"ok": False, "error": "`arguments` must be an object or a JSON object string."}
        allowed = set(_gateway_tool_names(cfg))
        if target_name not in allowed:
            return {
                "ok": False,
                "error": f"Unsupported gateway broker target: {target_name}",
                "available_tools": sorted(allowed),
            }
        return await execute_gateway_tool(
            target_name,
            target_args,
            session_tag=session_tag,
            cfg=cfg,
            service=service,
        )

    resolved_session_tag = arguments.get("session_tag") or session_tag
    handlers: dict[str, Callable[[], Awaitable[dict]]] = {
        "shenyu_recall": lambda: service.recall(
            query=arguments.get("query") or arguments.get("q") or "",
            source_types=arguments.get("source_types") or arguments.get("sources"),
            session_tag=arguments.get("session_tag") or session_tag,
            date_from=arguments.get("date_from") or arguments.get("since"),
            date_to=arguments.get("date_to") or arguments.get("until"),
            limit=_int_arg(arguments, "limit", 8),
            auto_sync=bool(getattr(cfg, "enable_recall_auto_sync", False)),
        ),
        "shenyu_surface_passages": lambda: service.surface_passages(
            query=arguments.get("query", ""),
            session_tag=resolved_session_tag,
            limit=_int_arg(arguments, "limit", cfg.default_surface_limit),
        ),
        "shenyu_search_primary_texts": lambda: service.search_primary_texts(
            query=arguments.get("query") or arguments.get("q") or "",
            categories=arguments.get("categories"),
            session_tag=resolved_session_tag,
            limit=_int_arg(arguments, "limit", 5),
        ),
        "shenyu_add_calendar": lambda: service.add_calendar(
            content=arguments.get("content", ""),
            period_key=arguments.get("period_key"),
            period_type=arguments.get("period_type", "day"),
            title=arguments.get("title", ""),
            summary=arguments.get("summary", ""),
            digest=arguments.get("digest", ""),
            author=arguments.get("author", "沈予"),
        ),
        "shenyu_supabase_guide": lambda: service.supabase_guide(),
        "shenyu_ask_memory": lambda: service.ask_memory(
            query=arguments.get("query") or arguments.get("q") or "",
            session_tag=arguments.get("session_tag"),
            limit=_int_arg(arguments, "limit", 8),
            date=arguments.get("date"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
        ),
        "shenyu_search_mem_notes": lambda: service.search_mem_notes(
            query=arguments.get("q") or arguments.get("query", ""),
            session_tag=resolved_session_tag,
            limit=_int_arg(arguments, "limit", 30),
            status=arguments.get("status", "all"),
            mem_type=arguments.get("mem_type"),
        ),
        "shenyu_list_mem_notes": lambda: service.list_mem_notes(
            status=arguments.get("status", "captured"),
            limit=_int_arg(arguments, "limit", 30),
            session_tag=resolved_session_tag,
            q=arguments.get("q") or arguments.get("query", ""),
            mem_type=arguments.get("mem_type"),
        ),
        "shenyu_write_mem_note": lambda: service.write_mem_note(
            content=arguments.get("content", ""),
            session_tag=resolved_session_tag,
            mem_type=arguments.get("mem_type"),
            trigger_text=arguments.get("trigger_text", ""),
            trigger_keywords=arguments.get("trigger_keywords"),
            status=arguments.get("status", "active"),
            cooldown_hours=arguments.get("cooldown_hours"),
            review_note=arguments.get("review_note", ""),
        ),
        "shenyu_read_heartbeat": lambda: service.read_heartbeat(
            session_tag=resolved_session_tag,
            limit=_int_arg(arguments, "limit", 10),
            state=arguments.get("state", "all"),
            order=arguments.get("order", "desc"),
            scope=arguments.get("scope", "auto"),
            date=arguments.get("date"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            created_from=arguments.get("created_from"),
            created_to=arguments.get("created_to"),
        ),
        "shenyu_update_mem_note": lambda: service.update_mem_note(
            _mem_note_id_arg(arguments),
            _mem_note_patch_args(arguments),
        ),
        "shenyu_delete_mem_note": lambda: service.delete_mem_note(_mem_note_id_arg(arguments)),
        "shenyu_get_meta_summaries": lambda: _wrapped_service_result("meta_summaries", service.meta_summaries()),
        "shenyu_last_seen": lambda: _wrapped_service_result("last_seen", service.last_seen()),
        "supabase_query": lambda: service.supabase_query(
            table=arguments.get("table", ""),
            filters=arguments.get("filters"),
            operators=arguments.get("operators"),
            column=arguments.get("column"),
            select=arguments.get("select"),
            order=arguments.get("order"),
            limit=_int_arg(arguments, "limit", 20),
        ),
        "supabase_insert": lambda: service.supabase_insert(
            table=arguments.get("table", ""),
            data=arguments.get("data") or {},
        ),
        "supabase_update": lambda: service.supabase_update(
            table=arguments.get("table", ""),
            match=arguments.get("match") or {},
            data=arguments.get("data") or {},
            operators=arguments.get("operators"),
            column=arguments.get("column"),
        ),
        "supabase_delete": lambda: service.supabase_delete(
            table=arguments.get("table", ""),
            match=arguments.get("match") or {},
            hard=bool(arguments.get("hard", False)),
            operators=arguments.get("operators"),
            column=arguments.get("column"),
        ),
        "shenyu_recall_main_thread": lambda: service.recall_main_thread(
            since=arguments.get("since"),
            until=arguments.get("until"),
            query=arguments.get("query"),
            limit=_int_arg(arguments, "limit", 10),
        ),
        "shenyu_notebook_list": lambda: service.notebook_list(
            type_filter=arguments.get("type"),
            status=arguments.get("status", "active"),
            limit=_int_arg(arguments, "limit", 10),
        ),
        "shenyu_notebook_write": lambda: service.notebook_write(
            type_=arguments.get("type", "note"),
            content=arguments.get("content", ""),
            tags=arguments.get("tags"),
            metadata=arguments.get("metadata"),
            session_tag=session_tag,
        ),
        "shenyu_notebook_update": lambda: service.notebook_update(
            id_=arguments.get("id", ""),
            content=arguments.get("content"),
            status=arguments.get("status"),
            tags=arguments.get("tags"),
            type_=arguments.get("type"),
            pinned=arguments.get("pinned"),
            metadata=arguments.get("metadata"),
        ),
    }
    handler = handlers.get(name)
    if handler:
        return await handler()
    raise ValueError(f"Unsupported gateway tool: {name}")
