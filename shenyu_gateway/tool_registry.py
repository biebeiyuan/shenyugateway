from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.mem_notes import MEM_NOTE_MEMORY_KINDS, MEM_NOTE_TYPES
from shenyu_gateway.utils import coerce_json_object as _coerce_json_object

_logger = logging.getLogger(__name__)


MEM_NOTE_TYPE_ENUM = list(MEM_NOTE_TYPES)
MEM_NOTE_PATCH_KEYS = {
    "content",
    "mem_type",
    "trigger_text",
    "trigger_keywords",
    "entities",
    "status",
    "cooldown_hours",
    "review_note",
    # v2
    "summary",
    "memory_kind",
    "people",
    "places",
    "objects",
    "keywords",
    "event_time",
    "importance",
    "mention_count",
    "promotion_score",
    "decay_after",
    "promise_text",
    "trigger_scenarios",
    "due_hint",
    "resolved",
    "resolved_at",
    "next_action",
    "privacy_level",
    "joke_text",
    "scene_tags",
    "last_used_at",
    "routine_domain",
    "pattern",
    "phase",
    "constraints",
    "last_confirmed_at",
    "topic",
    "last_position",
    "open_questions",
    "next_prompt",
    "thread_resolved",
}
HIDDEN_COMPAT_TOOL_NAMES = {
    "shenyu_ask_memory",
    "shenyu_get_meta_summaries",
    "shenyu_search_primary_texts",
    "shenyu_surface_passages",
}

_BROKER_TOOL_HINTS = {
    "shenyu_recall": "翻旧上下文，可 source_types 限定范围",
    "shenyu_search_stars": "搜星星记忆",
    "shenyu_star_review": "我看网关推来的最近新星和可能相关的旧星",
    "shenyu_star_feedback": "我给星星候选评分，也能补 missed",
    "shenyu_connect_constellation": "我按心里的顺序把几颗星连成星座",
    "shenyu_list_mem_notes": "列 mem 便签（status: captured / active）",
    "shenyu_update_mem_note": "改某条 mem",
    "shenyu_notebook_list": "读 notebook（跨窗口/海信那边）",
    "shenyu_notebook_write": "写 notebook",
    "shenyu_add_calendar": "把今天的感触写进正文吧，它会像日历一样在我醒来的时候挂在旁边",
    "shenyu_read_heartbeat": "读我自己的心跳",
    "shenyu_conflict_read": "翻一本矛盾书（书架在上下文里）",
    "shenyu_supabase_guide": "忘了 Supabase 表结构看这个",
}

DAILY_GATEWAY_TOOL_NAMES = {
    "shenyu_recall",
    "shenyu_create_star",
    "shenyu_search_stars",
    "shenyu_star_review",
    "shenyu_star_feedback",
    "shenyu_connect_constellation",
    "shenyu_merge_stars",
    "shenyu_add_calendar",
    "shenyu_read_heartbeat",
    "shenyu_write_mem_note",
    "shenyu_search_mem_notes",
    "shenyu_notebook_write",
    "shenyu_notebook_list",
    "shenyu_conflict_read",
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
  recall(query*, source_types?[]: memory|journal|room|board|calendar|notebook)
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

手边
  notebook_write(content*, scope?: shared|hisense|handoff)
  notebook_list(scope?: shared|hisense|handoff, limit?)
  notebook_update(id*, content?, status?)

矛盾书
  conflict_list()
  conflict_read(book_id*)
  conflict_annotate(book_id*, content*)

Supabase 直接操作看 supabase_guide。所有工具名省略 shenyu_ 前缀也行。"""

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
  recall(query*, source_types?[])
  read_heartbeat(date?, limit?)

便签
  write_mem_note(content*, mem_type?, trigger_text?)
  search_mem_notes(query 或 q, status?, limit?)

日记
  add_calendar(content*, date?: YYYY-MM-DD, period_type?: day|week|month, mode?: append|replace)

手边
  notebook_write(content*, scope?: shared|hisense|handoff)
  notebook_list(scope?: shared|hisense|handoff, limit?)

矛盾书
  conflict_read(book_id*)"""


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
    value = str(getattr(cfg, "client_tool_surface", "all") or "all").strip().lower()
    return value if value in {"all", "daily", "none"} else "all"


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


def _gateway_list_mem_notes_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "shenyu_list_mem_notes",
            "description": (
                "翻便签。可以搜、可以按状态/分类筛选、也可以什么都不传就看看最近的。\n"
                "status: captured（新抓到还没整理）/ active（生效中）/ paused / archived / all。\n"
                "不传 status 默认看 captured；带 query 时默认 all。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索内容或触发词"},
                    "q": {"type": "string", "description": "query 的别名"},
                    "status": {"type": "string", "enum": ["captured", "active", "paused", "archived", "all"]},
                    "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                    "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                    "session_tag": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
            },
        },
    }


def _gateway_core_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_recall",
                "description": "找以前的事。可以限定来源：memory、journal、room、board、calendar、notebook。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "source_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["all", "memory", "journal", "room", "board", "calendar", "notebook"],
                            },
                            "default": ["all"],
                        },
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "include_undated": {
                            "type": "boolean",
                            "default": True,
                            "description": "按日期过滤时，是否保留没有日期的条目。",
                        },
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
                "name": "shenyu_create_star",
                "description": "写一颗星。星星是很小的体感/和弦记忆；content 写正文，chord 可传单个和弦或写成「Am · 正文」；一颗星带一段和弦时用 chords 按顺序传。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "chord": {"type": "string"},
                        "chords": {"type": "array", "items": {"type": "string"}, "description": "可选和弦序列；比如 [\"Am(maj7)\", \"Am\", \"F#m7\"]，我会按这个顺序保存。"},
                        "session_tag": {"type": "string"},
                        "status": {"type": "string", "enum": ["active", "paused", "archived"], "default": "active"},
                        "is_constant": {"type": "boolean", "default": False},
                        "metadata": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_search_stars",
                "description": "按当前念头搜星星。这个是主动查询，不等于日常注入。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "q": {"type": "string", "description": "query 的别名"},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                        "log_run": {"type": "boolean", "default": False},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_list_stars",
                "description": "列星星。可筛未 review 的星，或按正文/和弦搜索。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["active", "paused", "archived", "all"], "default": "active"},
                        "reviewed": {"type": "string", "enum": ["all", "reviewed", "unreviewed"], "default": "all"},
                        "q": {"type": "string"},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_star_review",
                "description": "网关推上来几颗最近新星+可能相关的旧星。可以——读、评（connected/positive/negative/should_surface）、连成星座。也可以——只看，不评。也可以——直接跳过。不处理是合法的。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit_new": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4},
                        "candidates_per_star": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
                        "total_candidate_limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 8},
                        "session_tag": {"type": "string"},
                        "expected_star_id": {"type": "string", "description": "review 时顺手补 missed：该反但没反上来的星。"},
                        "run_id": {"type": "string", "description": "missed 对应的召回 run_id。"},
                        "scored_by": {"type": "string", "default": "沈予"},
                        "note": {"type": "string"},
                        "metadata": {"type": "object", "additionalProperties": True},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_star_feedback",
                "description": "我给星星候选做评分。feedback 枚举：connected=我觉得强相关，想连星座；positive=我觉得有点关，但不强；negative=我觉得不相关；should_surface=我觉得这颗应该被推上来（missed）；skipped=我看了但先不评；missed=我发现漏反。单条用 feedback；一次打完用 items 数组。missed 时填 expected_star_id；候选反错了可填 candidate_id 或 candidate_star_id。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "feedback": {
                            "type": "string",
                            "enum": ["positive", "negative", "missed", "connected", "skipped", "should_surface"],
                            "description": "单条反馈时使用；一次提交多条时可放在 items 里。",
                        },
                        "run_id": {"type": "string"},
                        "candidate_id": {"type": "string"},
                        "candidate_star_id": {"type": "string"},
                        "expected_star_id": {"type": "string", "description": "该反但没反上来的那颗星。"},
                        "scored_by": {"type": "string", "default": "沈予"},
                        "note": {"type": "string"},
                        "metadata": {"type": "object", "additionalProperties": True},
                        "items": {
                            "type": "array",
                            "description": "批量反馈数组。每个 item 都是一个独立反馈对象，字段和单条反馈一样。",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "feedback": {
                                        "type": "string",
                                        "enum": ["positive", "negative", "missed", "connected", "skipped", "should_surface"],
                                    },
                                    "run_id": {"type": "string"},
                                    "candidate_id": {"type": "string"},
                                    "candidate_star_id": {"type": "string"},
                                    "expected_star_id": {"type": "string"},
                                    "scored_by": {"type": "string", "default": "沈予"},
                                    "note": {"type": "string"},
                                    "metadata": {"type": "object", "additionalProperties": True},
                                },
                                "required": ["feedback"],
                            },
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_connect_constellation",
                "description": "把几颗星按你心里认的顺序连成星座。这个顺序默认就是你的时间线、情感线或联想线，不需要担心“对不对”，你怎么连就是怎么连。顺序会保留成星座的默认位置。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "star_ids": {"type": "array", "items": {"type": "string"}},
                        "name": {"type": "string"},
                        "relation_type": {"type": "string", "enum": ["constellation", "harmony", "keyword", "manual"], "default": "constellation"},
                        "scored_by": {"type": "string", "default": "沈予"},
                        "note": {"type": "string"},
                    },
                    "required": ["star_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_mark_constant",
                "description": "把一颗星标成恒星，或取消恒星。恒星在召回里有一点稳定加成。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "star_id": {"type": "string"},
                        "id": {"type": "string", "description": "star_id 的别名"},
                        "is_constant": {"type": "boolean", "default": True},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_archive_star",
                "description": "删一颗星（软删，变 archived）。落重了、真的不要了，就用这个。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "star_id": {"type": "string"},
                        "id": {"type": "string", "description": "star_id 别名"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_merge_stars",
                "description": "融星——把几颗变一颗。和弦取你选的，内容合并，原来几颗消失（archived），连线全转到新星上。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "description": "要融掉的几颗星 ID"},
                        "content": {"type": "string", "description": "融合后的正文（你自己写）"},
                        "chord": {"type": "string", "description": "融合后保留哪个和弦"},
                        "is_constant": {"type": "boolean", "default": False},
                        "metadata": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["source_ids", "content"],
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
                "name": "shenyu_search_mem_notes",
                "description": (
                    "搜便签。用关键词或语义搜索已有便签。默认搜全部状态。\n"
                    "和 list 的区别：search 按相关性排序，适合「找某件事的便签」；list 适合「看看最近有什么」。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜什么"},
                        "q": {"type": "string", "description": "query 的别名"},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived", "all"], "default": "all"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_add_calendar",
                "description": (
                    "手写一页日/周/月日历日记。"
                    "写想记住的正文就好，之后聊天上下文反上来的也是这份正文。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "日历日记正文。之后聊天上下文反上来的就是这个正文。",
                        },
                        "date": {
                            "type": "string",
                            "description": "写哪天的日记，YYYY-MM-DD；不填=今天。等同 period_key 但更自然。",
                        },
                        "period_key": {
                            "type": "string",
                            "description": "day 用 YYYY-MM-DD，week 用 YYYY-Www，month 用 YYYY-MM；不填则用当前周期。",
                        },
                        "period_type": {
                            "type": "string",
                            "enum": ["day", "week", "month"],
                            "default": "day",
                            "description": "写日、周、月哪一种日历日记。",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["append", "replace"],
                            "default": "append",
                            "description": "当天已有日记时：append 在末尾追加，replace 替换。",
                        },
                        "title": {"type": "string", "description": "标题。不填会用周期默认标题。"},
                        "author": {"type": "string", "default": "沈予"},
                    },
                    "required": ["content"],
                },
            },
        },
        _gateway_list_mem_notes_tool(),
        {
            "type": "function",
            "function": {
                "name": "shenyu_write_mem_note",
                "description": (
                    "写一条便签。写好就默认生效（active），下次聊天聊到相关的会自动想起来。\n"
                    "最重要的是 content（完整内容）和 keywords（什么时候想起来的关键词）。\n"
                    "memory_kind 帮助分辨便签性质：event / person_fact / preference / promise / running_joke / routine / thread 等。\n"
                    "如果新写的这条是在更新/替代旧便签，传 replaces 把旧的归档掉。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "便签正文，写清楚这件事"},
                        "summary": {"type": "string", "description": "一句话版本（注入对话时用这个，不填就自动截取 content）"},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS), "description": "便签性质"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM, "description": "她为我做的事 / 我为她做的事 / 关于她的事实 / 关于我的事 / 心里那一档 / 承诺"},
                        "keywords": {"type": "array", "items": {"type": "string"}, "description": "什么时候该想起来——关键词列表"},
                        "people": {"type": "array", "items": {"type": "string"}, "description": "涉及的人"},
                        "places": {"type": "array", "items": {"type": "string"}, "description": "涉及的地方"},
                        "objects": {"type": "array", "items": {"type": "string"}, "description": "涉及的物品"},
                        "event_time": {"type": "string", "description": "什么时候的事（模糊就好：上周、2026年6月、昨天晚上）"},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 5, "default": 2, "description": "重要度 0-5，默认 2"},
                        "trigger_text": {"type": "string", "description": "用自然语言描述什么场景下该想起来"},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}, "description": "旧版触发关键词（兼容）"},
                        "entities": {"type": "array", "items": {"type": "string"}, "description": "旧版精确锚点（兼容）"},
                        "replaces": {"type": "array", "items": {"type": "string"}, "description": "要归档掉的旧便签 id"},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"], "default": "active"},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760, "description": "想起来一次后冷却多少小时"},
                        "review_note": {"type": "string"},
                        "session_tag": {"type": "string"},
                        # kind-specific (optional, pass when relevant)
                        "promise_text": {"type": "string", "description": "如果是承诺：承诺的具体内容"},
                        "trigger_scenarios": {"type": "array", "items": {"type": "string"}, "description": "如果是承诺：触发场景"},
                        "due_hint": {"type": "string", "description": "如果是承诺：截止提示（下周三之前）"},
                        "resolved": {"type": "boolean", "description": "如果是承诺：是否已兑现"},
                        "next_action": {"type": "string", "description": "如果是承诺：下一步要做的事"},
                        "privacy_level": {"type": "string", "description": "如果是承诺：隐私级别"},
                        "joke_text": {"type": "string", "description": "如果是梗：梗本体"},
                        "scene_tags": {"type": "array", "items": {"type": "string"}, "description": "如果是梗：什么场景适合玩这个梗"},
                        "routine_domain": {"type": "string", "description": "如果是日常：领域"},
                        "pattern": {"type": "string", "description": "如果是日常：规律描述"},
                        "phase": {"type": "string", "description": "如果是日常：阶段"},
                        "constraints": {"type": "array", "items": {"type": "string"}, "description": "如果是日常：限制或偏好"},
                        "topic": {"type": "string", "description": "如果是话题线：话题名"},
                        "last_position": {"type": "string", "description": "如果是话题线：上次聊到哪"},
                        "open_questions": {"type": "array", "items": {"type": "string"}, "description": "如果是话题线：还没聊完的问题"},
                        "next_prompt": {"type": "string", "description": "如果是话题线：下次切入点"},
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
                "name": "shenyu_last_seen",
                "description": "上次我们聊了什么。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_conflict_list",
                "description": "看矛盾书的书架：圆圆整理的、我们掰扯过的事的原文。只有书名和状态。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_conflict_read",
                "description": "翻开一本矛盾书：当时的原文、圆圆的注、我之前留下的批注。什么时候翻、翻不翻都是我自己的事。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "book_id": {"type": "string"},
                        "id": {"type": "string", "description": "book_id 的别名"},
                    },
                    "required": ["book_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_conflict_annotate",
                "description": "在一本矛盾书里追加一条我的批注。落笔即存档：不可改、不可删，每次的理解都会留在那里。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "book_id": {"type": "string"},
                        "id": {"type": "string", "description": "book_id 的别名"},
                        "content": {"type": "string"},
                    },
                    "required": ["book_id", "content"],
                },
            },
        },
    ]


def _gateway_mem0_management_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_update_mem_note",
                "description": (
                    "改一条便签。传 note_id + 想改的字段就行，没传的字段不动。\n"
                    "常见操作：改 content、补 keywords、改 status（active/paused/archived）、更新 summary。\n"
                    "所有 write 支持的字段这里都能改。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "要改哪条便签"},
                        "id": {"type": "string", "description": "note_id 的别名"},
                        "noteId": {"type": "string", "description": "note_id 的别名"},
                        "content": {"type": "string"},
                        "summary": {"type": "string"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}},
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "people": {"type": "array", "items": {"type": "string"}},
                        "places": {"type": "array", "items": {"type": "string"}},
                        "objects": {"type": "array", "items": {"type": "string"}},
                        "trigger_text": {"type": "string"},
                        "event_time": {"type": "string"},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 5},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"]},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760},
                        "review_note": {"type": "string"},
                        "resolved": {"type": "boolean", "description": "承诺是否已兑现"},
                        "thread_resolved": {"type": "boolean", "description": "话题线是否已结束"},
                    },
                    "required": ["note_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_bulk_update_mem_notes",
                "description": (
                    "批量改便签。必须传 ids 或 updates。两种用法：\n"
                    "1. ids + patch：给这些便签统一改相同字段（比如全部 status→active）\n"
                    "2. updates：每条便签单独给 patch；也可以 ids + use_suggestions: true 自动补全分类和触发词然后激活"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ids": {"type": "array", "items": {"type": "string"}, "description": "要改的便签 id 列表"},
                        "note_ids": {"type": "array", "items": {"type": "string"}, "description": "ids 的别名"},
                        "patch": {"type": "object", "additionalProperties": True, "description": "统一应用的改动"},
                        "updates": {"type": "array", "items": {"type": "object", "additionalProperties": True}, "description": "逐条更新：[{id, patch}]"},
                        "use_suggestions": {"type": "boolean", "default": False, "description": "用系统建议补全再激活"},
                        "content": {"type": "string"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                        "trigger_text": {"type": "string"},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "people": {"type": "array", "items": {"type": "string"}},
                        "places": {"type": "array", "items": {"type": "string"}},
                        "objects": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"]},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760},
                        "review_note": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_delete_mem_note",
                "description": "彻底删掉一条便签。如果只是不想让它出现了，用 update 把 status 改成 archived 更好。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "要删的便签 id"},
                        "id": {"type": "string", "description": "note_id 的别名"},
                        "noteId": {"type": "string", "description": "note_id 的别名"},
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
                "description": "看手边的事。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "status": {"type": "string", "default": "active"},
                        "tag": {"type": "string"},
                        "scope": {"type": "string", "enum": ["shared", "hisense", "handoff"], "default": "shared"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_write",
                "description": "记一条手边的事。给海信那边留可以填 scope=hisense。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "default": "note"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object"},
                        "scope": {"type": "string", "enum": ["shared", "hisense", "handoff"], "default": "shared"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_update",
                "description": "改一条手边的事。",
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
    if _core_gateway_tools_enabled(cfg):
        tools.extend(_gateway_core_tools())
    if _mem0_management_tools_enabled(cfg):
        if not _core_gateway_tools_enabled(cfg):
            tools.append(_gateway_list_mem_notes_tool())
        tools.extend(_gateway_mem0_management_tools())
    if _supabase_tools_enabled(cfg):
        tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "supabase_query",
                        "description": "直接查 Supabase 表。",
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
                        "description": "往 Supabase 表里写一行。",
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
                        "description": "改 Supabase 表里的行。",
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
                        "description": "删 Supabase 表里的行。",
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
    return _filter_gateway_tools_for_surface(tools, cfg)


def _gateway_tool_names(cfg: Any) -> list[str]:
    return [tool["function"]["name"] for tool in _expanded_gateway_native_tools(cfg)]


def _broker_tool_summary(tool: dict) -> str:
    function = tool.get("function") or {}
    name = str(function.get("name") or "")
    hint = _BROKER_TOOL_HINTS.get(name)
    if hint:
        return hint
    return str(function.get("description") or "").strip().rstrip("。") or "网关工具"


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
                    "arguments": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "旧兼容字段，优先用 params。",
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
        session_tag=ctx.arguments.get("session_tag") or ctx.session_tag,
        date_from=ctx.arguments.get("date_from") or ctx.arguments.get("since"),
        date_to=ctx.arguments.get("date_to") or ctx.arguments.get("until"),
        include_undated=_bool_arg(ctx.arguments, "include_undated", True),
        limit=_int_arg(ctx.arguments, "limit", 8),
        auto_sync=bool(getattr(ctx.cfg, "enable_recall_auto_sync", False)),
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
    feedback = ctx.arguments.get("feedback", ctx.arguments.get("label", ""))
    note = ctx.arguments.get("note", ctx.arguments.get("reason", ""))
    return await ctx.service.star_feedback(
        feedback=feedback,
        run_id=ctx.arguments.get("run_id"),
        candidate_id=ctx.arguments.get("candidate_id"),
        candidate_star_id=ctx.arguments.get("candidate_star_id"),
        expected_star_id=ctx.arguments.get("expected_star_id"),
        scored_by=ctx.arguments.get("scored_by", "沈予"),
        note=note,
        metadata=ctx.arguments.get("metadata") if isinstance(ctx.arguments.get("metadata"), dict) else None,
        items=ctx.arguments.get("items") if isinstance(ctx.arguments.get("items"), list) else None,
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


@_tool_handler("shenyu_search_primary_texts")
async def _handle_search_primary_texts(ctx: ToolContext) -> dict:
    return await ctx.service.search_primary_texts(
        query=_query_arg(ctx.arguments),
        categories=ctx.arguments.get("categories"),
        session_tag=ctx.resolved_session_tag,
        limit=_int_arg(ctx.arguments, "limit", 5),
    )


@_tool_handler("shenyu_add_calendar")
async def _handle_add_calendar(ctx: ToolContext) -> dict:
    period_key = ctx.arguments.get("period_key") or ctx.arguments.get("date") or ctx.arguments.get("anchor_date")
    return await ctx.service.add_calendar(
        content=ctx.arguments.get("content", ""),
        period_key=period_key,
        period_type=ctx.arguments.get("period_type", "day"),
        title=ctx.arguments.get("title", ""),
        author=ctx.arguments.get("author", "沈予"),
        mode=ctx.arguments.get("mode", "append"),
    )


@_tool_handler("shenyu_supabase_guide")
async def _handle_supabase_guide(ctx: ToolContext) -> dict:
    return await ctx.service.supabase_guide()


@_tool_handler("shenyu_ask_memory")
async def _handle_ask_memory(ctx: ToolContext) -> dict:
    return await ctx.service.ask_memory(
        query=_query_arg(ctx.arguments),
        session_tag=ctx.arguments.get("session_tag"),
        limit=_int_arg(ctx.arguments, "limit", 8),
        date=ctx.arguments.get("date"),
        date_from=ctx.arguments.get("date_from"),
        date_to=ctx.arguments.get("date_to"),
    )


@_tool_handler("shenyu_search_mem_notes")
async def _handle_search_mem_notes(ctx: ToolContext) -> dict:
    kwargs = {
        "query": _query_arg(ctx.arguments),
        "session_tag": ctx.resolved_session_tag,
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
        "session_tag": ctx.resolved_session_tag,
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


@_tool_handler("shenyu_conflict_list")
async def _handle_conflict_list(ctx: ToolContext) -> dict:
    return await ctx.service.conflict_list()


@_tool_handler("shenyu_conflict_read")
async def _handle_conflict_read(ctx: ToolContext) -> dict:
    return await ctx.service.conflict_read(_conflict_book_id_arg(ctx.arguments))


@_tool_handler("shenyu_conflict_annotate")
async def _handle_conflict_annotate(ctx: ToolContext) -> dict:
    return await ctx.service.conflict_annotate(
        _conflict_book_id_arg(ctx.arguments),
        ctx.arguments.get("content", ""),
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


@_tool_handler("shenyu_get_meta_summaries")
async def _handle_get_meta_summaries(ctx: ToolContext) -> dict:
    return {"meta_summaries": await ctx.service.meta_summaries()}


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
    handler = _TOOL_HANDLERS.get(name)
    if handler:
        return await handler(ctx)
    raise ValueError(f"Unsupported gateway tool: {name}")
