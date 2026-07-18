from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.calendar import period_key_from_date
from shenyu_gateway.mem_notes import MEM_NOTE_MEMORY_KINDS, MEM_NOTE_PATCH_FIELDS, MEM_NOTE_TYPES
from shenyu_gateway.tool_schemas import (
    _gateway_core_tools,
    _gateway_list_mem_notes_tool,
    _gateway_mem0_management_tools,
    _gateway_notebook_and_recall_tools,
    _gateway_supabase_tools,
)
from shenyu_gateway.utils import coerce_json_object as _coerce_json_object

_logger = logging.getLogger(__name__)


MEM_NOTE_TYPE_ENUM = list(MEM_NOTE_TYPES)
MEM_NOTE_PATCH_KEYS = MEM_NOTE_PATCH_FIELDS
HIDDEN_COMPAT_TOOL_NAMES = {
    "shenyu_surface_passages",
}
DEPRECATED_COMPAT_TOOL_MESSAGES = {
    "shenyu_ask_memory": "Deprecated gateway tool: shenyu_ask_memory. Use shenyu_recall instead.",
    "shenyu_get_meta_summaries": "Deprecated gateway tool: shenyu_get_meta_summaries.",
    "shenyu_search_primary_texts": "Deprecated gateway tool: shenyu_search_primary_texts. Use shenyu_recall instead.",
}

DAILY_GATEWAY_TOOL_NAMES = {
    "shenyu_recall",
    "shenyu_recall_read",
    "shenyu_create_star",
    "shenyu_search_stars",
    "shenyu_star_review",
    "shenyu_star_feedback",
    "shenyu_connect_constellation",
    "shenyu_merge_stars",
    "shenyu_add_calendar",
    "shenyu_windowsill_write",
    "shenyu_windowsill_list",
    "shenyu_read_heartbeat",
    "shenyu_write_mem_note",
    "shenyu_search_mem_notes",
    "shenyu_notebook_write",
    "shenyu_notebook_list",
    "shenyu_conflict_list",
    "shenyu_conflict_read",
    "shenyu_conflict_annotate",
}

DAILY_CLIENT_TOOL_EXACT = {
    "gateway",
    "read_file",
    "visit_web",
    "package_proxy",
    "use_package",
    "room",
    "shenyu_room",
    "selection",
    "coread_selection",
    "coread_annotate",
}
DAILY_CLIENT_TOOL_PREFIXES = ("coread_",)
CLIENT_TOOL_SURFACES = {"all", "daily", "none"}

_BROKER_CATEGORIZED_DESCRIPTION = """\
记忆库总入口。tool=工具全名，params=参数对象（直接传对象，不要传 JSON 字符串）。
*=必填。查心跳/日历/便签等都有专用工具，不要用 supabase 系列代替。

星星
  create_star(content*, chord?, chords?[])
  search_stars(query*)
  star_review()  — 无参数
  star_feedback
    单条: feedback*(connected|positive|negative|should_surface|skipped|missed), candidate_id?, note?
    批量: items*=[{feedback, candidate_id?, ...}]  ← 不要把数组放进 feedback 字段
  connect_constellation(star_ids*[], name?)
  list_stars(status?: active|paused|archived|all, reviewed?: all|reviewed|unreviewed, limit?)
  mark_constant(star_id*, is_constant?: bool)
  archive_star(star_id*)
  merge_stars(source_ids*[], content*, chord?)

回忆
  recall(query*, mode?: auto|exact|fuzzy|mood|verbatim, source_types?[])
  recall_read(source_type*, source_id*)
  read_heartbeat(date?, limit?)
  last_seen()  — 无参数
  recall_main_thread(query?, since?, until?, limit?)

便签
  write_mem_note(content*, mem_type?, trigger_text?)
  list_mem_notes(status?: captured|active|paused|archived|all, query?, mem_type?, memory_kind?, limit?)
  update_mem_note(note_id*, content?, mem_type?, status?: captured|active|paused|archived)
  bulk_update_mem_notes(ids[] 或 updates[], status?, use_suggestions?: bool)
  delete_mem_note(note_id*)
  search_mem_notes(query 或 q, status?: captured|active|paused|archived|all, memory_kind?, limit?)

日记
  add_calendar(content*, date?: YYYY-MM-DD, period_type?: day|week|month, mode?: append|replace)

窗台
  windowsill_write(content*, title?, mood?)
  windowsill_list(mood?, limit?)

手边
  notebook_write(content*, scope?: shared|hisense|handoff)
  notebook_list(scope?: shared|hisense|handoff, limit?)
  notebook_update(id*, content?, status?)

矛盾书
  conflict_list()  — 先看书架和精确书名
  conflict_read(title* 或 book_id*)
  conflict_annotate(title* 或 book_id*, content*)

Supabase 直接操作看 supabase_guide。"""

_BROKER_DAILY_DESCRIPTION = """\
记忆库日常入口。tool=工具全名，params=参数对象（直接传对象，不要传 JSON 字符串）。
这里放沈予日常会碰的东西；后台管理和数据库工具收起来了。

星星
  create_star(content*, chord?, chords?[])
  search_stars(query*)
  star_review()
  star_feedback(feedback* 或 items*[])
  connect_constellation(star_ids*[], name?)
  merge_stars(source_ids*[], content*, chord?)

回忆
  recall(query*, mode?: auto|exact|fuzzy|mood|verbatim, source_types?[])
  recall_read(source_type*, source_id*)
  read_heartbeat(date?, limit?)

便签
  write_mem_note(content*, mem_type?, trigger_text?)
  search_mem_notes(query 或 q, status?, limit?)

日记
  add_calendar(content*, date?: YYYY-MM-DD, period_type?: day|week|month, mode?: append|replace)

窗台
  windowsill_write(content*, title?, mood?)
  windowsill_list(mood?, limit?)

手边
  notebook_write(content*, scope?: shared|hisense|handoff)
  notebook_list(scope?: shared|hisense|handoff, limit?)

矛盾书
  conflict_list()  — 先看书架和精确书名
  conflict_read(title* 或 book_id*)
  conflict_annotate(title* 或 book_id*, content*)"""


def _upstream_tools_enabled(cfg: Any) -> bool:
    return bool(getattr(cfg, "enable_upstream_tools", True))


def _core_gateway_tools_enabled(cfg: Any) -> bool:
    return bool(getattr(cfg, "enable_gateway_tools", True))


def _mem0_management_tools_enabled(cfg: Any) -> bool:
    return bool(getattr(cfg, "enable_mem0_management_tools", False))


def _supabase_tools_enabled(cfg: Any) -> bool:
    return bool(getattr(cfg, "expose_supabase_tools", False))


def _gateway_tool_surface(cfg: Any) -> str:
    value = str(getattr(cfg, "gateway_tool_surface", "full") or "full").strip().lower()
    return value if value in {"full", "daily"} else "full"


def _client_tool_surface(cfg: Any) -> str:
    return normalize_client_tool_surface(getattr(cfg, "client_tool_surface", "all"))


def normalize_client_tool_surface(value: Any) -> str:
    value = str(value or "all").strip().lower()
    return value if value in CLIENT_TOOL_SURFACES else "all"


def _filter_gateway_tools_for_surface(tools: list[dict], cfg: Any) -> list[dict]:
    if _gateway_tool_surface(cfg) != "daily":
        return tools
    return [
        tool for tool in tools
        if tool.get("function", {}).get("name") in DAILY_GATEWAY_TOOL_NAMES
    ]


def _client_tool_name(tool: dict) -> str:
    if not isinstance(tool, dict):
        return ""
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def _is_daily_client_tool(name: str) -> bool:
    clean = (name or "").strip()
    lowered = clean.lower()
    if lowered in {item.lower() for item in DAILY_CLIENT_TOOL_EXACT}:
        return True
    return any(lowered.startswith(prefix) for prefix in DAILY_CLIENT_TOOL_PREFIXES)


def _filter_client_tools_for_surface(client_tools: Optional[list[dict]], cfg: Any) -> list[dict]:
    tools = list(client_tools or [])
    surface = _client_tool_surface(cfg)
    if surface == "all":
        return tools
    if surface == "none":
        return []
    return [tool for tool in tools if _is_daily_client_tool(_client_tool_name(tool))]






def _expanded_gateway_native_tools(cfg: Any) -> list[dict]:
    tools = []
    if _core_gateway_tools_enabled(cfg):
        tools.extend(_gateway_core_tools())
    if _mem0_management_tools_enabled(cfg):
        if not _core_gateway_tools_enabled(cfg):
            tools.append(_gateway_list_mem_notes_tool())
        tools.extend(_gateway_mem0_management_tools())
    if _supabase_tools_enabled(cfg):
        tools.extend(_gateway_supabase_tools())
    tools.extend(_gateway_notebook_and_recall_tools())
    return _filter_gateway_tools_for_surface(tools, cfg)


def _gateway_tool_names(cfg: Any) -> list[str]:
    return [tool["function"]["name"] for tool in _expanded_gateway_native_tools(cfg)]


def _gateway_broker_tool(cfg: Any) -> dict:
    expanded_tools = _expanded_gateway_native_tools(cfg)
    names = [tool["function"]["name"] for tool in expanded_tools]
    description = (
        _BROKER_DAILY_DESCRIPTION
        if _gateway_tool_surface(cfg) == "daily"
        else _BROKER_CATEGORIZED_DESCRIPTION
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
                    "params": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "选中工具的参数对象。",
                    },
                },
                "required": ["tool"],
            },
        },
    }


def gateway_native_tools(cfg: Any) -> list[dict]:
    if not _upstream_tools_enabled(cfg):
        return []
    tools_enabled = bool(
        _core_gateway_tools_enabled(cfg)
        or _mem0_management_tools_enabled(cfg)
        or _supabase_tools_enabled(cfg)
    )
    if not tools_enabled:
        return []
    if getattr(cfg, "gateway_tool_mode", "full") == "broker":
        return [_gateway_broker_tool(cfg)]
    return _expanded_gateway_native_tools(cfg)


def merge_tools(client_tools: Optional[list[dict]], cfg: Any, *, meta: Optional[dict] = None) -> list[dict]:
    if not _upstream_tools_enabled(cfg):
        return []
    filtered_client_tools = _filter_client_tools_for_surface(client_tools, cfg)

    # Room mode: keep client tools + direct room tools, drop normal gateway tools
    if meta and meta.get("is_room"):
        package = meta.get("package") or {}
        room_tools = package.get("room_tools") or []
        merged = list(filtered_client_tools)
        if room_tools:
            existing = {tool.get("function", {}).get("name") for tool in merged if isinstance(tool, dict)}
            for rt in room_tools:
                name = rt.get("function", {}).get("name", "")
                if name not in existing:
                    merged.append(rt)
        return merged

    merged = list(filtered_client_tools)
    if not (
        _core_gateway_tools_enabled(cfg)
        or _mem0_management_tools_enabled(cfg)
        or _supabase_tools_enabled(cfg)
    ):
        return merged
    existing = {tool.get("function", {}).get("name") for tool in merged if isinstance(tool, dict)}
    for tool in gateway_native_tools(cfg):
        name = tool["function"]["name"]
        if name not in existing:
            merged.append(tool)
    return merged


def is_gateway_native_tool(name: str) -> bool:
    return name.startswith("shenyu_") or name.startswith("supabase_") or name.startswith("room_")


def _int_arg(arguments: dict, key: str, default: int) -> int:
    try:
        return int(arguments.get(key, default))
    except (TypeError, ValueError):
        return default


def _bool_arg(arguments: dict, key: str, default: bool) -> bool:
    value = arguments.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _query_arg(arguments: dict) -> str:
    return arguments.get("query") or arguments.get("q") or ""


def _first_nonempty_arg(arguments: dict, *keys: str) -> Any:
    for key in keys:
        value = arguments.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _coerce_broker_arguments(value: Any) -> Optional[dict]:
    target_args = _coerce_json_object(value)
    if target_args is None:
        return None
    if set(target_args) in ({"arguments"}, {"params"}):
        nested_args = _coerce_json_object(target_args.get("arguments", target_args.get("params")))
        if nested_args is not None:
            return nested_args
    return target_args


def _broker_target_name(arguments: dict, cfg: Any) -> str:
    target_name = str(arguments.get("tool") or arguments.get("name") or "").strip()
    if not target_name and arguments.get("action"):
        target_name = str(arguments.get("action") or "").strip()
    if target_name and not (target_name.startswith("shenyu_") or target_name.startswith("supabase_")):
        prefixed_name = f"shenyu_{target_name}"
        if prefixed_name in set(_gateway_tool_names(cfg)) | HIDDEN_COMPAT_TOOL_NAMES:
            return prefixed_name
    return target_name


def _mem_note_id_arg(arguments: dict) -> str:
    for key in ("note_id", "id", "noteId"):
        value = arguments.get(key)
        if value:
            return str(value)
    return ""


def _mem_note_patch_args(arguments: dict) -> dict:
    id_keys = {"note_id", "id", "noteId"}
    return {key: value for key, value in arguments.items() if key not in id_keys}


def _mem_note_ids_arg(arguments: dict) -> list[str]:
    value = arguments.get("ids") or arguments.get("note_ids") or arguments.get("noteIds") or []
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _mem_note_bulk_patch_arg(arguments: dict) -> dict:
    patch: dict[str, Any] = {}
    nested = arguments.get("patch")
    if isinstance(nested, dict):
        patch.update({key: value for key, value in nested.items() if key in MEM_NOTE_PATCH_KEYS})
    patch.update({key: value for key, value in arguments.items() if key in MEM_NOTE_PATCH_KEYS})
    return patch


def _star_id_arg(arguments: dict) -> str:
    for key in ("star_id", "id", "starId"):
        value = arguments.get(key)
        if value:
            return str(value)
    return ""


@dataclass(frozen=True)
class ToolContext:
    arguments: dict
    session_tag: Optional[str]
    resolved_session_tag: Optional[str]
    cfg: Any
    service: GatewayToolService


_TOOL_HANDLERS: dict[str, Callable[[ToolContext], Awaitable[dict]]] = {}


def _tool_handler(name: str) -> Callable[[Callable[[ToolContext], Awaitable[dict]]], Callable[[ToolContext], Awaitable[dict]]]:
    def decorator(fn: Callable[[ToolContext], Awaitable[dict]]) -> Callable[[ToolContext], Awaitable[dict]]:
        _TOOL_HANDLERS[name] = fn
        return fn

    return decorator


@_tool_handler("shenyu_recall")
async def _handle_recall(ctx: ToolContext) -> dict:
    return await ctx.service.recall(
        query=_query_arg(ctx.arguments),
        source_types=ctx.arguments.get("source_types") or ctx.arguments.get("sources"),
        mode=ctx.arguments.get("mode", "auto"),
        session_tag=ctx.arguments.get("session_tag") or ctx.session_tag,
        date_from=ctx.arguments.get("date_from") or ctx.arguments.get("since"),
        date_to=ctx.arguments.get("date_to") or ctx.arguments.get("until"),
        include_undated=_bool_arg(ctx.arguments, "include_undated", True),
        limit=_int_arg(ctx.arguments, "limit", 4),
        auto_sync=bool(getattr(ctx.cfg, "enable_recall_auto_sync", False)),
    )


@_tool_handler("shenyu_recall_read")
async def _handle_recall_read(ctx: ToolContext) -> dict:
    return await ctx.service.recall_read(
        source_type=ctx.arguments.get("source_type") or ctx.arguments.get("type", ""),
        source_id=ctx.arguments.get("source_id") or ctx.arguments.get("id", ""),
        session_tag=ctx.session_tag,
    )


@_tool_handler("shenyu_create_star")
async def _handle_create_star(ctx: ToolContext) -> dict:
    return await ctx.service.create_star(
        content=ctx.arguments.get("content", ""),
        chord=ctx.arguments.get("chord", ""),
        chords=ctx.arguments.get("chords") if isinstance(ctx.arguments.get("chords"), list) else None,
        session_tag=ctx.arguments.get("session_tag") or ctx.session_tag,
        status=ctx.arguments.get("status", "active"),
        is_constant=_bool_arg(ctx.arguments, "is_constant", False),
        metadata=ctx.arguments.get("metadata") if isinstance(ctx.arguments.get("metadata"), dict) else None,
    )


@_tool_handler("shenyu_list_stars")
async def _handle_list_stars(ctx: ToolContext) -> dict:
    return await ctx.service.list_stars(
        status=ctx.arguments.get("status", "active"),
        limit=_int_arg(ctx.arguments, "limit", 50),
        session_tag=ctx.arguments.get("session_tag") or ctx.session_tag,
        q=ctx.arguments.get("q") or ctx.arguments.get("query", ""),
        reviewed=ctx.arguments.get("reviewed", "all"),
    )


@_tool_handler("shenyu_search_stars")
async def _handle_search_stars(ctx: ToolContext) -> dict:
    return await ctx.service.search_stars(
        query=_query_arg(ctx.arguments),
        session_tag=ctx.arguments.get("session_tag") or ctx.session_tag,
        limit=_int_arg(ctx.arguments, "limit", 10),
        log_run=_bool_arg(ctx.arguments, "log_run", False),
    )


@_tool_handler("shenyu_star_review")
async def _handle_star_review(ctx: ToolContext) -> dict:
    feedback_result = None
    if ctx.arguments.get("expected_star_id"):
        feedback_result = await ctx.service.star_feedback(
            feedback="missed",
            run_id=ctx.arguments.get("run_id"),
            expected_star_id=ctx.arguments.get("expected_star_id"),
            scored_by=ctx.arguments.get("scored_by", "沈予"),
            note=ctx.arguments.get("note", ""),
            metadata=ctx.arguments.get("metadata") if isinstance(ctx.arguments.get("metadata"), dict) else None,
        )
    review_result = await ctx.service.star_review(
        limit_new=ctx.arguments.get("limit_new"),
        candidates_per_star=ctx.arguments.get("candidates_per_star"),
        total_candidate_limit=ctx.arguments.get("total_candidate_limit"),
        session_tag=ctx.arguments.get("session_tag") or ctx.session_tag,
    )
    if feedback_result is not None:
        review_result["feedback"] = feedback_result
    return review_result


@_tool_handler("shenyu_star_feedback")
async def _handle_star_feedback(ctx: ToolContext) -> dict:
    feedback = _first_nonempty_arg(ctx.arguments, "feedback", "label", "action", "value")
    note = _first_nonempty_arg(ctx.arguments, "note", "reason", "comment")
    items = ctx.arguments.get("items")
    return await ctx.service.star_feedback(
        feedback=feedback if feedback is not None else "",
        run_id=ctx.arguments.get("run_id"),
        candidate_id=ctx.arguments.get("candidate_id"),
        candidate_star_id=_first_nonempty_arg(
            ctx.arguments,
            "candidate_star_id",
            "candidate_node_id",
            "star_id",
        ),
        expected_star_id=ctx.arguments.get("expected_star_id"),
        scored_by=ctx.arguments.get("scored_by", "沈予"),
        note=str(note or ""),
        metadata=ctx.arguments.get("metadata") if isinstance(ctx.arguments.get("metadata"), dict) else None,
        items=items if isinstance(items, (dict, list)) else None,
    )


@_tool_handler("shenyu_connect_constellation")
async def _handle_connect_constellation(ctx: ToolContext) -> dict:
    return await ctx.service.connect_constellation(
        star_ids=ctx.arguments.get("star_ids") or ctx.arguments.get("ids"),
        name=ctx.arguments.get("name", ""),
        relation_type=ctx.arguments.get("relation_type", "constellation"),
        scored_by=ctx.arguments.get("scored_by", "沈予"),
        note=ctx.arguments.get("note", ""),
    )


@_tool_handler("shenyu_mark_constant")
async def _handle_mark_constant(ctx: ToolContext) -> dict:
    return await ctx.service.mark_constant_star(
        _star_id_arg(ctx.arguments),
        is_constant=_bool_arg(ctx.arguments, "is_constant", True),
    )


@_tool_handler("shenyu_archive_star")
async def _handle_archive_star(ctx: ToolContext) -> dict:
    return await ctx.service.archive_star(_star_id_arg(ctx.arguments))


@_tool_handler("shenyu_merge_stars")
async def _handle_merge_stars(ctx: ToolContext) -> dict:
    return await ctx.service.merge_stars(
        source_ids=ctx.arguments.get("source_ids") or [],
        content=ctx.arguments.get("content", ""),
        chord=ctx.arguments.get("chord", ""),
        is_constant=_bool_arg(ctx.arguments, "is_constant", False),
        metadata=ctx.arguments.get("metadata") if isinstance(ctx.arguments.get("metadata"), dict) else None,
    )


@_tool_handler("shenyu_surface_passages")
async def _handle_surface_passages(ctx: ToolContext) -> dict:
    return await ctx.service.surface_passages(
        query=_query_arg(ctx.arguments),
        session_tag=ctx.resolved_session_tag,
        limit=_int_arg(ctx.arguments, "limit", ctx.cfg.default_surface_limit),
    )


@_tool_handler("shenyu_add_calendar")
async def _handle_add_calendar(ctx: ToolContext) -> dict:
    period_type = ctx.arguments.get("period_type", "day")
    period_key = ctx.arguments.get("period_key")
    natural_date = ctx.arguments.get("date") or ctx.arguments.get("anchor_date")
    if not period_key and natural_date:
        try:
            period_key = period_key_from_date(str(period_type or "day").strip().lower(), str(natural_date))
        except ValueError:
            return {"ok": False, "error": "date must be YYYY-MM-DD.", "error_kind": "validation"}
    return await ctx.service.add_calendar(
        content=ctx.arguments.get("content", ""),
        period_key=period_key,
        period_type=period_type,
        title=ctx.arguments.get("title", ""),
        author=ctx.arguments.get("author", "沈予"),
        mode=ctx.arguments.get("mode", "append"),
    )


@_tool_handler("shenyu_supabase_guide")
async def _handle_supabase_guide(ctx: ToolContext) -> dict:
    return await ctx.service.supabase_guide()


@_tool_handler("shenyu_search_mem_notes")
async def _handle_search_mem_notes(ctx: ToolContext) -> dict:
    kwargs = {
        "query": _query_arg(ctx.arguments),
        "session_tag": ctx.arguments.get("session_tag"),
        "limit": _int_arg(ctx.arguments, "limit", 20),
        "status": ctx.arguments.get("status", "all"),
        "mem_type": ctx.arguments.get("mem_type"),
    }
    if ctx.arguments.get("memory_kind"):
        kwargs["memory_kind"] = ctx.arguments.get("memory_kind")
    return await ctx.service.search_mem_notes(**kwargs)


@_tool_handler("shenyu_list_mem_notes")
async def _handle_list_mem_notes(ctx: ToolContext) -> dict:
    query = ctx.arguments.get("query") or ctx.arguments.get("q", "")
    default_status = "all" if query else "captured"
    kwargs = {
        "status": ctx.arguments.get("status", default_status),
        "limit": _int_arg(ctx.arguments, "limit", 20),
        "session_tag": ctx.arguments.get("session_tag"),
        "q": query,
        "mem_type": ctx.arguments.get("mem_type"),
    }
    if ctx.arguments.get("memory_kind"):
        kwargs["memory_kind"] = ctx.arguments.get("memory_kind")
    return await ctx.service.list_mem_notes(**kwargs)


@_tool_handler("shenyu_write_mem_note")
async def _handle_write_mem_note(ctx: ToolContext) -> dict:
    return await ctx.service.write_mem_note(
        content=ctx.arguments.get("content", ""),
        session_tag=ctx.resolved_session_tag,
        mem_type=ctx.arguments.get("mem_type"),
        trigger_text=ctx.arguments.get("trigger_text", ""),
        trigger_keywords=ctx.arguments.get("trigger_keywords"),
        entities=ctx.arguments.get("entities"),
        status=ctx.arguments.get("status", "active"),
        cooldown_hours=ctx.arguments.get("cooldown_hours"),
        review_note=ctx.arguments.get("review_note", ""),
        replaces=ctx.arguments.get("replaces"),
        # v2 fields
        summary=ctx.arguments.get("summary"),
        memory_kind=ctx.arguments.get("memory_kind"),
        people=ctx.arguments.get("people"),
        places=ctx.arguments.get("places"),
        objects=ctx.arguments.get("objects"),
        keywords=ctx.arguments.get("keywords"),
        event_time=ctx.arguments.get("event_time"),
        importance=ctx.arguments.get("importance"),
        promise_text=ctx.arguments.get("promise_text"),
        trigger_scenarios=ctx.arguments.get("trigger_scenarios"),
        due_hint=ctx.arguments.get("due_hint"),
        resolved=ctx.arguments.get("resolved"),
        next_action=ctx.arguments.get("next_action"),
        privacy_level=ctx.arguments.get("privacy_level"),
        joke_text=ctx.arguments.get("joke_text"),
        scene_tags=ctx.arguments.get("scene_tags"),
        routine_domain=ctx.arguments.get("routine_domain"),
        pattern=ctx.arguments.get("pattern"),
        phase=ctx.arguments.get("phase"),
        constraints=ctx.arguments.get("constraints"),
        topic=ctx.arguments.get("topic"),
        last_position=ctx.arguments.get("last_position"),
        open_questions=ctx.arguments.get("open_questions"),
        next_prompt=ctx.arguments.get("next_prompt"),
    )


@_tool_handler("shenyu_read_heartbeat")
async def _handle_read_heartbeat(ctx: ToolContext) -> dict:
    return await ctx.service.read_heartbeat(
        session_tag=ctx.resolved_session_tag,
        limit=_int_arg(ctx.arguments, "limit", 10),
        state=ctx.arguments.get("state", "all"),
        order=ctx.arguments.get("order", "desc"),
        scope=ctx.arguments.get("scope", "auto"),
        date=ctx.arguments.get("date"),
        date_from=ctx.arguments.get("date_from"),
        date_to=ctx.arguments.get("date_to"),
        created_from=ctx.arguments.get("created_from"),
        created_to=ctx.arguments.get("created_to"),
    )


def _conflict_book_id_arg(arguments: dict) -> str:
    for key in ("book_id", "id", "bookId"):
        value = arguments.get(key)
        if value:
            return str(value)
    return ""


def _conflict_title_arg(arguments: dict) -> str:
    return str(arguments.get("title") or "").strip()


@_tool_handler("shenyu_conflict_list")
async def _handle_conflict_list(ctx: ToolContext) -> dict:
    return await ctx.service.conflict_list()


@_tool_handler("shenyu_conflict_read")
async def _handle_conflict_read(ctx: ToolContext) -> dict:
    return await ctx.service.conflict_read(
        _conflict_book_id_arg(ctx.arguments),
        title=_conflict_title_arg(ctx.arguments),
    )


@_tool_handler("shenyu_conflict_annotate")
async def _handle_conflict_annotate(ctx: ToolContext) -> dict:
    return await ctx.service.conflict_annotate(
        _conflict_book_id_arg(ctx.arguments),
        ctx.arguments.get("content", ""),
        title=_conflict_title_arg(ctx.arguments),
    )


@_tool_handler("shenyu_update_mem_note")
async def _handle_update_mem_note(ctx: ToolContext) -> dict:
    return await ctx.service.update_mem_note(
        _mem_note_id_arg(ctx.arguments),
        _mem_note_patch_args(ctx.arguments),
    )


@_tool_handler("shenyu_bulk_update_mem_notes")
async def _handle_bulk_update_mem_notes(ctx: ToolContext) -> dict:
    return await ctx.service.bulk_update_mem_notes(
        ids=_mem_note_ids_arg(ctx.arguments),
        patch=_mem_note_bulk_patch_arg(ctx.arguments),
        updates=ctx.arguments.get("updates") if isinstance(ctx.arguments.get("updates"), list) else [],
        use_suggestions=_bool_arg(ctx.arguments, "use_suggestions", False),
    )


@_tool_handler("shenyu_delete_mem_note")
async def _handle_delete_mem_note(ctx: ToolContext) -> dict:
    return await ctx.service.delete_mem_note(_mem_note_id_arg(ctx.arguments))


@_tool_handler("shenyu_last_seen")
async def _handle_last_seen(ctx: ToolContext) -> dict:
    return {"last_seen": await ctx.service.last_seen()}


@_tool_handler("supabase_query")
async def _handle_supabase_query(ctx: ToolContext) -> dict:
    return await ctx.service.supabase_query(
        table=ctx.arguments.get("table", ""),
        filters=ctx.arguments.get("filters"),
        operators=ctx.arguments.get("operators"),
        column=ctx.arguments.get("column"),
        select=ctx.arguments.get("select"),
        order=ctx.arguments.get("order"),
        limit=_int_arg(ctx.arguments, "limit", 20),
    )


@_tool_handler("supabase_insert")
async def _handle_supabase_insert(ctx: ToolContext) -> dict:
    return await ctx.service.supabase_insert(
        table=ctx.arguments.get("table", ""),
        data=ctx.arguments.get("data") or {},
    )


@_tool_handler("supabase_update")
async def _handle_supabase_update(ctx: ToolContext) -> dict:
    return await ctx.service.supabase_update(
        table=ctx.arguments.get("table", ""),
        match=ctx.arguments.get("match") or {},
        data=ctx.arguments.get("data") or {},
        operators=ctx.arguments.get("operators"),
        column=ctx.arguments.get("column"),
    )


@_tool_handler("supabase_delete")
async def _handle_supabase_delete(ctx: ToolContext) -> dict:
    return await ctx.service.supabase_delete(
        table=ctx.arguments.get("table", ""),
        match=ctx.arguments.get("match") or {},
        hard=bool(ctx.arguments.get("hard", False)),
        operators=ctx.arguments.get("operators"),
        column=ctx.arguments.get("column"),
    )


@_tool_handler("shenyu_recall_main_thread")
async def _handle_recall_main_thread(ctx: ToolContext) -> dict:
    return await ctx.service.recall_main_thread(
        since=ctx.arguments.get("since"),
        until=ctx.arguments.get("until"),
        query=_query_arg(ctx.arguments),
        limit=_int_arg(ctx.arguments, "limit", 10),
    )


@_tool_handler("shenyu_notebook_list")
async def _handle_notebook_list(ctx: ToolContext) -> dict:
    return await ctx.service.notebook_list(
        type_filter=ctx.arguments.get("type"),
        status=ctx.arguments.get("status", "active"),
        limit=_int_arg(ctx.arguments, "limit", 10),
        tag=ctx.arguments.get("tag"),
        scope=ctx.arguments.get("scope"),
    )


@_tool_handler("shenyu_windowsill_write")
async def _handle_windowsill_write(ctx: ToolContext) -> dict:
    return await ctx.service.windowsill_write(
        content=ctx.arguments.get("content", ""),
        title=ctx.arguments.get("title", ""),
        mood=ctx.arguments.get("mood", ""),
    )


@_tool_handler("shenyu_windowsill_list")
async def _handle_windowsill_list(ctx: ToolContext) -> dict:
    return await ctx.service.windowsill_list(
        mood=ctx.arguments.get("mood", ""),
        limit=_int_arg(ctx.arguments, "limit", 10),
    )


@_tool_handler("shenyu_notebook_write")
async def _handle_notebook_write(ctx: ToolContext) -> dict:
    return await ctx.service.notebook_write(
        type_=ctx.arguments.get("type"),
        content=ctx.arguments.get("content", ""),
        tags=ctx.arguments.get("tags"),
        metadata=ctx.arguments.get("metadata"),
        session_tag=ctx.arguments.get("session_tag") or ctx.session_tag,
        scope=ctx.arguments.get("scope"),
    )


@_tool_handler("shenyu_notebook_update")
async def _handle_notebook_update(ctx: ToolContext) -> dict:
    return await ctx.service.notebook_update(
        id_=ctx.arguments.get("id", ""),
        content=ctx.arguments.get("content"),
        status=ctx.arguments.get("status"),
        tags=ctx.arguments.get("tags"),
        type_=ctx.arguments.get("type"),
        pinned=ctx.arguments.get("pinned"),
        metadata=ctx.arguments.get("metadata"),
    )


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
        target_name = _broker_target_name(arguments, cfg)
        raw_target_args = arguments.get("params")
        if raw_target_args is None:
            raw_target_args = arguments.get("arguments")
        if raw_target_args is None:
            raw_target_args = {
                key: value
                for key, value in arguments.items()
                if key not in {"tool", "name", "action", "params", "arguments"}
            }
        exposed = set(_gateway_tool_names(cfg))
        from .room_tools import ROOM_TOOL_NAMES as _ROOM_TOOL_NAMES
        allowed = exposed | HIDDEN_COMPAT_TOOL_NAMES | _ROOM_TOOL_NAMES
        if target_name in DEPRECATED_COMPAT_TOOL_MESSAGES:
            return {
                "ok": False,
                "error": DEPRECATED_COMPAT_TOOL_MESSAGES[target_name],
                "error_kind": "validation",
            }
        if target_name not in allowed:
            return {
                "ok": False,
                "error": (
                    f"Unsupported gateway broker target: {target_name}. "
                    "Use `tool` with the full shenyu_ / supabase_ name, and put arguments in `params`."
                ),
                "available_tools": sorted(exposed),
            }
        target_args = _coerce_broker_arguments(raw_target_args)
        if target_args is None:
            return {
                "ok": False,
                "error": "`params`/`arguments` must be an object or a JSON object string.",
            }
        return await execute_gateway_tool(
            target_name,
            target_args,
            session_tag=session_tag,
            cfg=cfg,
            service=service,
        )

    if name.startswith("room_"):
        from .room_tools import execute_room_tool
        from .gateway_tools import _runtime
        store = _runtime.session_store
        _session = store.get_session_by_tag(session_tag) if session_tag else None
        _session_id = _session["id"] if _session else ""
        _logger.info("[Room] tool=%s session_tag=%s", name, session_tag or "")
        result = await execute_room_tool(
            name,
            arguments,
            store=store,
            cfg=cfg,
            supabase_client=_runtime.supabase_client,
            session_id=_session_id,
            session_tag=session_tag,
        )
        # Auto-trace: record which door was opened (skip sit — it records internally)
        if result.get("ok") and name != "room_sit_by_window" and _session_id:
            action = name.removeprefix("room_")
            try:
                store.add_room_trace(_session_id, action)
            except Exception:
                pass
        return result

    ctx = ToolContext(
        arguments=arguments,
        session_tag=session_tag,
        resolved_session_tag=arguments.get("session_tag") or session_tag,
        cfg=cfg,
        service=service,
    )
    if name in DEPRECATED_COMPAT_TOOL_MESSAGES:
        return {"ok": False, "error": DEPRECATED_COMPAT_TOOL_MESSAGES[name], "error_kind": "validation"}
    handler = _TOOL_HANDLERS.get(name)
    if handler:
        return await handler(ctx)
    raise ValueError(f"Unsupported gateway tool: {name}")
