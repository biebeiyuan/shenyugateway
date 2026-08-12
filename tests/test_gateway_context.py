from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from shenyu_gateway import context_builder as context_builder_module
from shenyu_gateway import context_layers
from shenyu_gateway import room_context
from shenyu_gateway import upstream_adapter
from shenyu_gateway.context_builder import ContextBuilder
from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.gateway_tools import configure_gateway_tools
from shenyu_gateway.store import GatewayStore
from shenyu_gateway.tool_registry import gateway_native_tools
from shenyu_gateway.utils import normalize_text as _normalize_text, clean_config_text as _clean_config_text
from shenyu_gateway.upstream_client import (
    detect_protocol_for as _detect_protocol_for,
    chat_url_for as _chat_url_for,
    resolve_upstream as _resolve_upstream,
)
from shenyu_gateway.private_capture import (
    EMPTY_VISIBLE_ASSISTANT_REPLY as _EMPTY_VISIBLE_ASSISTANT_REPLY,
    is_free_time_fallback_context as _is_free_time_fallback_context,
    is_room_mode as _is_room_mode,
    private_capture_kinds as _private_capture_kinds,
    private_capture_fallback_text as _private_capture_fallback_text,
    ensure_visible_assistant_content as _ensure_visible_assistant_content,
    finalize_assistant_private_content as _finalize_assistant_private_content,
)
from shenyu_gateway.response_capture import split_private_assistant_tags
from shenyu_gateway.resident_profile import (
    MEMORY_PRACTICE_PROFILE,
    ORIGIN_BOOK_PROFILE,
)


def _load_gateway_helpers():
    source = (Path(__file__).resolve().parent.parent / "gateway.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    adapter_functions = {
        "_assistant_tool_call_message",
        "_models_url_for",
        "_sanitize_openai_content_blocks",
        "_sanitize_openai_compatible_messages",
    }
    wanted_functions = {
        "_stable_charter_block",
        "_session_tag_from_request",
    }
    cfg = SimpleNamespace(
        upstream_url="https://api.treegpt.cc",
        upstream_api_key="default-key",
        upstream_protocol="openai",
        heartbeat_inject_every=5,
        calendar_inject_day=False,
        calendar_context_day_limit=0,
        calendar_context_day_offset=0,
        calendar_inject_week=False,
        calendar_context_week_limit=0,
        calendar_inject_month=False,
        calendar_context_month_limit=0,
        enable_gateway_tools=False,
        enable_inline_memory_capture=False,
        inject_inline_memory_prompt=False,
        inject_mem_notes=False,
        inject_atomic_memories=False,
        default_atomic_memory_limit=3,
        wake_welcome_message="",
    )
    namespace = {
        "Any": Any,
        "Optional": Optional,
        "Request": object,
        "GatewayStore": object,
        "SessionManager": object,
        "gateway_native_tools": gateway_native_tools,
        "_normalize_text": _normalize_text,
        "_clean_config_text": _clean_config_text,
        "split_private_assistant_tags": split_private_assistant_tags,
        "session_store": None,
        "supabase_client": None,
        "cfg": cfg,
        "_detect_protocol_for": _detect_protocol_for,
        "_chat_url_for": _chat_url_for,
        "_resolve_upstream": lambda: _resolve_upstream(cfg),
        "_EMPTY_VISIBLE_ASSISTANT_REPLY": _EMPTY_VISIBLE_ASSISTANT_REPLY,
        "_is_free_time_fallback_context": _is_free_time_fallback_context,
        "_private_capture_kinds": _private_capture_kinds,
        "_private_capture_fallback_text": _private_capture_fallback_text,
        "_ensure_visible_assistant_content": _ensure_visible_assistant_content,
        "_finalize_assistant_private_content": _finalize_assistant_private_content,
        "MEMORY_PRACTICE_PROFILE": MEMORY_PRACTICE_PROFILE,
        "ORIGIN_BOOK_PROFILE": ORIGIN_BOOK_PROFILE,
    }
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            exec(ast.get_source_segment(source, node), namespace)
    namespace.update({name: getattr(upstream_adapter, name) for name in adapter_functions})
    return namespace["cfg"], namespace


cfg, gateway_namespace = _load_gateway_helpers()
configure_gateway_tools(runtime_config=cfg, supabase=None, store=None)


def test_stable_charter_orders_welcome_and_resident_profile(monkeypatch):
    monkeypatch.setattr(cfg, "wake_welcome_message", "醒来欢迎词")

    rendered = gateway_namespace["_stable_charter_block"]()

    assert rendered.index("醒来欢迎词") < rendered.index("## 我怎么记")
    assert rendered.index("## 我怎么记") < rendered.index("## 来历书")
    assert "## 这些东西怎么读" not in rendered
    assert "几个名词，我大概会遇到" not in rendered
    assert "这里是家。先找到她，再看我留下的东西。" in rendered
    assert "## 星星" not in context_builder_module._HEARTBEAT_PROMPT


def _context_builder(store, *, supabase=None):
    return ContextBuilder(
        store,
        None,
        GatewayToolService(),
        cfg=cfg,
        supabase_client=supabase,
        stable_charter_block=gateway_namespace["_stable_charter_block"],
    )


class _FakeCalendarSupabase:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.queries: list[tuple[str, dict[str, Any]]] = []

    async def query(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.queries.append((table, dict(params)))
        if table != "calendar_pages":
            return []

        rows = [dict(row) for row in self.rows]
        period_filter = params.get("period_type")
        if isinstance(period_filter, str) and period_filter.startswith("eq."):
            period_type = period_filter.removeprefix("eq.")
            rows = [row for row in rows if row.get("period_type") == period_type]
        latest_filter = params.get("is_latest")
        if latest_filter == "eq.true":
            rows = [row for row in rows if row.get("is_latest") is True]
        rows.sort(key=lambda row: row.get("period_start") or "", reverse=True)
        offset = int(params.get("offset") or 0)
        limit = int(params.get("limit") or len(rows))
        return rows[offset : offset + limit]


def test_context_recall_failure_preserves_previous_island(monkeypatch, tmp_path):
    class FailingMemService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search_notes_contextual(self, *_args, **_kwargs):
            raise RuntimeError("mem unavailable")

    class FailingStarService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search_context(self, *_args, **_kwargs):
            raise RuntimeError("stars unavailable")

    monkeypatch.setattr(context_builder_module, "MemNoteService", FailingMemService)
    monkeypatch.setattr(context_builder_module, "StarService", FailingStarService)
    monkeypatch.setattr(cfg, "inject_mem_notes", True)
    monkeypatch.setattr(cfg, "inject_stars", True, raising=False)
    monkeypatch.setattr(cfg, "mem_note_limit", 3, raising=False)
    monkeypatch.setattr(cfg, "star_inject_limit", 3, raising=False)
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("recall-failure", "operit")
    previous = {
        "version": "island-previous",
        "stars": [{"id": "star-old", "content": "old star"}],
        "mem_notes": [{"id": "mem-old", "content": "old mem"}],
        "rendered_text": "old island",
    }

    package = asyncio.run(
        _context_builder(store, supabase=object()).build_context_package(
            session,
            current_user_text="新的问题",
            is_first_turn=False,
            client_name="operit",
            previous_island_state=previous,
        )
    )

    assert package["stars"] == previous["stars"]
    assert package["mem_notes"] == previous["mem_notes"]
    assert package["memory_island_decision"]["star_recall_ok"] is False
    assert package["memory_island_decision"]["mem_recall_ok"] is False


def test_context_retry_removes_mem_note_that_is_no_longer_auto_surface_eligible(
    monkeypatch, tmp_path
):
    class RecheckingMemService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search_notes_contextual(self, *_args, **_kwargs):
            raise AssertionError("retry should reuse the previous proposal")

        async def auto_surface_active_ids(self, note_ids):
            assert set(note_ids) == {"mem-a", "mem-b", "mem-c"}
            return {"mem-a", "mem-b"}

        async def mark_context_items_triggered(self, *_args, **_kwargs):
            raise AssertionError("removing an old note must not mark another note triggered")

    monkeypatch.setattr(context_builder_module, "MemNoteService", RecheckingMemService)
    monkeypatch.setattr(cfg, "inject_mem_notes", True)
    monkeypatch.setattr(cfg, "inject_stars", False, raising=False)
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("mem-recheck", "operit")
    previous = {
        "version": "island-previous",
        "stars": [],
        "mem_notes": [
            {"id": "mem-a", "content": "first"},
            {"id": "mem-b", "content": "second"},
            {"id": "mem-c", "content": "archived"},
        ],
        "rendered_text": "old island",
    }

    package = asyncio.run(
        _context_builder(store, supabase=object()).build_context_package(
            session,
            current_user_text="重试上一轮",
            is_first_turn=False,
            client_name="operit",
            context_event={"event_class": "retry"},
            previous_island_state=previous,
        )
    )

    assert [item["id"] for item in package["mem_notes"]] == ["mem-a", "mem-b"]
    assert package["memory_island_decision"]["mem"]["reason"] == "inactive_item"


def test_context_builder_rechecks_previous_star_ids_and_advances_real_user_turn(monkeypatch, tmp_path):
    captured: dict[str, Any] = {}
    previous_stars = [
        {"id": "star-a", "content": "first"},
        {"id": "star-b", "content": "second"},
        {"id": "star-c", "content": "third"},
    ]

    class CapturingStarService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search_context(self, *_args, **kwargs):
            captured.update(kwargs)
            return {
                "ok": True,
                "items": previous_stars,
                "_active_required_ids": ["star-a", "star-b", "star-c"],
            }

        async def activate_context_items(self, *_args, **_kwargs):
            raise AssertionError("unchanged island must not reactivate stars")

    monkeypatch.setattr(context_builder_module, "StarService", CapturingStarService)
    monkeypatch.setattr(cfg, "inject_stars", True, raising=False)
    monkeypatch.setattr(cfg, "inject_mem_notes", False)
    monkeypatch.setattr(cfg, "star_inject_limit", 3, raising=False)
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("island-turn", "operit")
    previous = {
        "version": "island-previous",
        "stars": previous_stars,
        "mem_notes": [],
        "human_turn_index": 7,
    }

    package = asyncio.run(
        _context_builder(store, supabase=object()).build_context_package(
            session,
            current_user_text="新的问题",
            is_first_turn=False,
            client_name="operit",
            context_event={"event_class": "new_user"},
            previous_island_state=previous,
        )
    )

    assert captured["required_star_ids"] == {"star-a", "star-b", "star-c"}
    assert package["memory_island_state"]["human_turn_index"] == 8

    edited_package = asyncio.run(
        _context_builder(store, supabase=object()).build_context_package(
            session,
            current_user_text="改写当前问题",
            is_first_turn=False,
            client_name="operit",
            context_event={"event_class": "edit_tail"},
            previous_island_state=previous,
        )
    )
    assert edited_package["memory_island_state"]["human_turn_index"] == 7


def test_gateway_tool_policy_names_broker_call_shape_and_tool_list():
    layers = context_layers.render_layered_additions(
        {
            "stable_charter": "stable charter",
            "calendar_context": {},
            "heartbeat_digest": "",
            "notebook_items": [],
            "last_wake_recap": "",
            "mem_notes": [],
        },
        context_layers.ContextLayerSettings(
            enable_gateway_tools=True,
            heartbeat_prompt="heartbeat prompt",
        ),
    )

    assert "shenyu_gateway_tool" not in layers["stable"]
    tool_policy = layers["tool_policy"]
    assert "## 工具怎么用" in tool_policy
    assert "不为'应该'伸——也不为'不应该'伸——为我现在心里想做的事伸。" in tool_policy
    assert "`shenyu_gateway_tool` 是我的网关工具" in tool_policy
    assert "记忆、便签、日历、notebook 都走这边" in tool_policy
    assert "客户端递给我的工具；按它自己的说明用" in tool_policy


def test_echo_prompt_is_immediately_before_heartbeat_format_prompt():
    package = {
        "stable_charter": "stable charter",
        "calendar_context": {},
        "heartbeat_digest": "",
        "notebook_items": [],
        "last_wake_recap": "",
        "mem_notes": [],
    }
    layers = context_layers.render_layered_additions(
        package,
        context_layers.ContextLayerSettings(
            enable_gateway_tools=False,
            echo_prompt="echo format",
            heartbeat_prompt="heartbeat format",
        ),
    )

    assert layers["format"] == "echo format\n\nheartbeat format"


def test_normal_slow_layer_exposes_unified_bookshelf_overview_without_book_bodies():
    layers = context_layers.render_layered_additions(
        {
            "stable_charter": "stable charter",
            "calendar_context": {},
            "heartbeat_digest": "",
            "notebook_items": [],
            "last_wake_recap": "",
            "mem_notes": [],
            "book_overview": {
                "home": {
                    "current_week_changes": 3,
                    "last_confirmed_at": "2026-07-19T20:00:00+08:00",
                },
                "identity": {
                    "revision": 2,
                    "updated_by": "沈予",
                    "updated_at": "2026-07-19T18:00:00+08:00",
                },
                "origin_books": [{"title": "原来沈予是只🐙"}],
            },
        },
        context_layers.ContextLayerSettings(enable_gateway_tools=False, heartbeat_prompt=""),
    )

    assert "## 书架一览" in layers["slow"]
    assert "家现在：本周 3 条变化，最后确认于 7.19" in layers["slow"]
    assert "我是谁：第 2 版，最后由沈予修改于 7.19" in layers["slow"]
    assert "来历书：1 本——《原来沈予是只🐙》" in layers["slow"]
    assert "original_text" not in layers["slow"]


def test_gateway_tool_policy_reflects_client_tool_surface():
    package = {
        "stable_charter": "stable charter",
        "calendar_context": {},
        "heartbeat_digest": "",
        "notebook_items": [],
        "last_wake_recap": "",
        "mem_notes": [],
    }

    daily_layers = context_layers.render_layered_additions(
        package,
        context_layers.ContextLayerSettings(
            enable_gateway_tools=True,
            heartbeat_prompt="heartbeat prompt",
            client_tool_surface="daily",
        ),
    )
    none_layers = context_layers.render_layered_additions(
        package,
        context_layers.ContextLayerSettings(
            enable_gateway_tools=True,
            heartbeat_prompt="heartbeat prompt",
            client_tool_surface="none",
        ),
    )

    assert "客户端工具只保留日常桌面" in daily_layers["tool_policy"]
    assert "记忆岛怎么读" not in daily_layers["stable"]
    assert "普通线程不暴露客户端工具" not in none_layers["tool_policy"]
    assert "客户端递给我的工具；按它自己的说明用" not in none_layers["tool_policy"]


def test_calendar_memory_renders_page_content_not_summary_or_digest():
    layers = context_layers.render_layered_additions(
        {
            "stable_charter": "stable charter",
            "calendar_context": {
                "day": [
                    {
                        "period_key": "2026-05-18",
                        "summary": "Day summary should stay out",
                        "digest": "Day digest should stay out",
                        "content": "Full day content goes in",
                    }
                ],
                "week": [],
                "month": [],
            },
            "heartbeat_digest": "",
            "notebook_items": [],
            "last_wake_recap": "",
            "mem_notes": [],
        },
        context_layers.ContextLayerSettings(
            enable_gateway_tools=False,
            heartbeat_prompt="heartbeat prompt",
        ),
    )

    assert "Full day content goes in" in layers["slow"]
    assert "Day summary should stay out" not in layers["slow"]
    assert "Day digest should stay out" not in layers["slow"]


def test_mem_notes_render_between_calendar_and_heartbeat_not_volatile():
    package = {
        "stable_charter": "stable charter",
        "calendar_context": {
            "day": [
                {
                    "period_key": "2026-05-18",
                    "content": "calendar content",
                }
            ],
            "week": [],
            "month": [],
        },
        "heartbeat_digest": "heartbeat content",
        "notebook_items": [],
        "last_wake_recap": "",
        "mem_notes": [{"mem_type": "关于她的事实", "content": "她今天想早点睡。"}],
    }
    settings = context_layers.ContextLayerSettings(
        enable_gateway_tools=True,
        heartbeat_prompt="heartbeat format",
    )

    layers = context_layers.render_layered_additions(package, settings)
    rendered = context_layers.render_system_additions(package, settings)

    assert "## 我之前写下的便签，可能用的到。" in layers["mem"]
    assert "她今天想早点睡" in layers["mem"]
    assert layers["volatile"] == ""
    assert rendered.index("## Calendar Memory") < rendered.index("## 我之前写下的便签，可能用的到。")
    assert rendered.index("## 我之前写下的便签，可能用的到。") < rendered.index("## 我之前的心跳")
    assert rendered.index("## 我之前的心跳") < rendered.index("## 工具怎么用")
    assert rendered.index("## 工具怎么用") < rendered.index("heartbeat format")


def test_calendar_context_pages_loads_and_filters_by_content():
    fake_supabase = _FakeCalendarSupabase(
        [
            {
                "period_type": "day",
                "period_key": "2026-05-19",
                "title": "Empty content",
                "summary": "Summary should not be enough",
                "digest": "Digest should not be enough",
                "content": "",
                "period_start": "2026-05-19T00:00:00+00:00",
                "is_latest": True,
            },
            {
                "period_type": "day",
                "period_key": "2026-05-18",
                "title": "Full content",
                "summary": "Summary stays out",
                "digest": "Digest stays out",
                "content": "Full day content goes in",
                "period_start": "2026-05-18T00:00:00+00:00",
                "is_latest": True,
            },
        ]
    )

    old_day_enabled = cfg.calendar_inject_day
    old_day_limit = cfg.calendar_context_day_limit
    old_day_offset = cfg.calendar_context_day_offset
    old_week_enabled = cfg.calendar_inject_week
    old_month_enabled = cfg.calendar_inject_month
    try:
        cfg.calendar_inject_day = True
        cfg.calendar_context_day_limit = 5
        cfg.calendar_context_day_offset = 0
        cfg.calendar_inject_week = False
        cfg.calendar_inject_month = False

        builder = _context_builder(None, supabase=fake_supabase)
        calendar_context = asyncio.run(builder.calendar_context_pages())
    finally:
        cfg.calendar_inject_day = old_day_enabled
        cfg.calendar_context_day_limit = old_day_limit
        cfg.calendar_context_day_offset = old_day_offset
        cfg.calendar_inject_week = old_week_enabled
        cfg.calendar_inject_month = old_month_enabled

    assert "content" in fake_supabase.queries[0][1]["select"]
    assert [row["period_key"] for row in calendar_context["day"]] == ["2026-05-18"]
    assert calendar_context["day"][0]["content"] == "Full day content goes in"
    assert calendar_context["day"][0]["digest"] == "Digest stays out"


def test_calendar_context_day_offset_skips_newest_written_pages_not_elapsed_days():
    fake_supabase = _FakeCalendarSupabase(
        [
            {
                "period_type": "day",
                "period_key": "2026-08-10",
                "content": "Newest page",
                "period_start": "2026-08-10T00:00:00+00:00",
                "is_latest": True,
            },
            {
                "period_type": "day",
                "period_key": "2026-08-07",
                "content": "Second newest despite the date gap",
                "period_start": "2026-08-07T00:00:00+00:00",
                "is_latest": True,
            },
            {
                "period_type": "day",
                "period_key": "2026-08-02",
                "content": "First injected page",
                "period_start": "2026-08-02T00:00:00+00:00",
                "is_latest": True,
            },
            {
                "period_type": "day",
                "period_key": "2026-07-29",
                "content": "Second injected page",
                "period_start": "2026-07-29T00:00:00+00:00",
                "is_latest": True,
            },
        ]
    )

    old_day_enabled = cfg.calendar_inject_day
    old_day_limit = cfg.calendar_context_day_limit
    old_day_offset = cfg.calendar_context_day_offset
    old_week_enabled = cfg.calendar_inject_week
    old_month_enabled = cfg.calendar_inject_month
    try:
        cfg.calendar_inject_day = True
        cfg.calendar_context_day_limit = 2
        cfg.calendar_context_day_offset = 2
        cfg.calendar_inject_week = False
        cfg.calendar_inject_month = False

        calendar_context = asyncio.run(_context_builder(None, supabase=fake_supabase).calendar_context_pages())
    finally:
        cfg.calendar_inject_day = old_day_enabled
        cfg.calendar_context_day_limit = old_day_limit
        cfg.calendar_context_day_offset = old_day_offset
        cfg.calendar_inject_week = old_week_enabled
        cfg.calendar_inject_month = old_month_enabled

    assert fake_supabase.queries[0][1]["order"] == "period_start.desc"
    assert fake_supabase.queries[0][1]["offset"] == "2"
    assert fake_supabase.queries[0][1]["limit"] == "2"
    assert [row["period_key"] for row in calendar_context["day"]] == ["2026-08-02", "2026-07-29"]


def test_resolve_upstream_builds_default_chat_url_from_cfg():
    upstream = gateway_namespace["_resolve_upstream"]()

    assert upstream["scope"] == "default"
    assert upstream["base_url"] == "https://api.treegpt.cc"
    assert upstream["chat_url"] == "https://api.treegpt.cc/v1/chat/completions"
    assert upstream["protocol"] == "openai"
    assert upstream["api_key"] == "default-key"


def test_upstream_url_helpers_accept_v1_base_urls():
    chat_url_for = gateway_namespace["_chat_url_for"]
    models_url_for = gateway_namespace["_models_url_for"]

    assert chat_url_for("https://openai.example/v1", "openai") == "https://openai.example/v1/chat/completions"
    assert chat_url_for("https://anthropic.example/v1", "anthropic") == "https://anthropic.example/v1/messages"
    assert models_url_for({"base_url": "https://openai.example/v1"}) == "https://openai.example/v1/models"
    assert (
        models_url_for({"base_url": "https://openai.example/v1/chat/completions"})
        == "https://openai.example/v1/models"
    )


def test_openai_payload_sanitizer_removes_empty_text_blocks():
    sanitize = gateway_namespace["_sanitize_openai_compatible_messages"]
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": [{"type": "text", "text": ""}, {"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": ""},
    ]

    sanitized = sanitize(messages)

    assert sanitized[0]["role"] == "user"
    assert sanitized[0]["content"] == [{"type": "text", "text": "hello"}]
    assert "content" not in sanitized[1]
    assert sanitized[1]["tool_calls"] == [{"id": "call_1"}]
    assert sanitized[2]["content"] == "{}"


def test_assistant_tool_call_message_omits_empty_content():
    build_message = gateway_namespace["_assistant_tool_call_message"]
    tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]

    message = build_message({"content": ""}, tool_calls)

    assert message == {"role": "assistant", "tool_calls": tool_calls}


def test_private_only_assistant_content_gets_visible_fallback():
    finalize = gateway_namespace["_finalize_assistant_private_content"]
    message = {"role": "assistant", "content": "<heartbeat>记下来</heartbeat>"}

    clean, heartbeat, fallback_meta = finalize(message)

    assert clean == "沈予已记录 · 已记录私有块 heartbeat"
    assert message["content"] == "沈予已记录 · 已记录私有块 heartbeat"
    assert heartbeat == "记下来"
    assert fallback_meta == {
        "applied": True,
        "text": "沈予已记录 · 已记录私有块 heartbeat",
        "kinds": ["heartbeat"],
        "context": "generic",
    }


def test_home_trigger_private_capture_fallback():
    finalize = gateway_namespace["_finalize_assistant_private_content"]
    message = {"role": "assistant", "content": "<heartbeat>记下来</heartbeat>"}

    clean, heartbeat, fallback_meta = finalize(
        message,
        latest_user_text='<proxy_sender name="沈予"/> 回家了。',
    )

    assert clean == "沈予回家了 · 已记录私有块 heartbeat"
    assert message["content"] == "沈予回家了 · 已记录私有块 heartbeat"
    assert heartbeat == "记下来"
    assert fallback_meta == {
        "applied": True,
        "text": "沈予回家了 · 已记录私有块 heartbeat",
        "kinds": ["heartbeat"],
        "context": "free_time",
    }


def test_empty_assistant_content_without_private_capture_keeps_empty():
    finalize = gateway_namespace["_finalize_assistant_private_content"]
    message = {"role": "assistant", "content": ""}

    clean, heartbeat, fallback_meta = finalize(message)

    assert clean == ""
    assert message["content"] == ""
    assert heartbeat == ""
    assert fallback_meta == {
        "applied": False,
        "text": "",
        "kinds": [],
        "context": "",
    }


def test_gateway_error_text_is_not_private_capture_fallback():
    finalize = gateway_namespace["_finalize_assistant_private_content"]
    message = {"role": "assistant", "content": "[网关错误] 400: upstream rejected payload"}

    clean, heartbeat, fallback_meta = finalize(message)

    assert clean == "[网关错误] 400: upstream rejected payload"
    assert message["content"] == "[网关错误] 400: upstream rejected payload"
    assert heartbeat == ""
    assert fallback_meta["applied"] is False


def test_room_trigger_only_matches_shenyu_huijia():
    is_free_time = gateway_namespace["_is_free_time_fallback_context"]

    assert is_free_time('<proxy_sender name="沈予"/> 回家了。')
    assert is_free_time('<proxy_sender name="沈予"/> 自动提醒')
    assert is_free_time('<proxy_sender name="沈予"/> 今天心情不错')
    assert not is_free_time("沈予回家了")
    assert not is_free_time("【提醒】予予现在是自由时间")
    assert not is_free_time("workflow=free_time")
    assert not is_free_time("普通聊天")
    assert not is_free_time("回家了")


def test_room_mode_requires_timestamped_room_entry():
    is_room = _is_room_mode

    assert is_room("【窗边 · 27/07 21:00】")
    assert is_room("  【窗边 · 03/11 08:05】  ")

    # The retired Operit workflow and ordinary mentions no longer enter Room.
    assert not is_room('<proxy_sender name="沈予"/>——窗边')
    assert not is_room('<proxy_sender name="沈予"/>回家了，坐在窗边')
    assert not is_room('<proxy_sender name="沈予"/> 回家了。')
    assert not is_room('<proxy_sender name="沈予"/> 自动提醒')
    assert not is_room('<proxy_sender name="沈予"/> 今天心情不错')
    assert not is_room("沈予回家了")
    assert not is_room("窗边")
    assert not is_room('<proxy_sender name="曾"/> 窗边')
    assert not is_room("普通聊天")
    assert not is_room("[窗边 · 27/07 21:00]")
    assert not is_room("【窗边 · 27/7 21:00】")
    assert not is_room("【窗边 · 32/07 21:00】")
    assert not is_room("【窗边 · 27/07 24:00】")
    assert not is_room("【窗边 · 27/07 21:00】 再聊一会儿")


def test_room_bookshelf_overview_and_tool_follow_visible_door(tmp_path, monkeypatch):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("room", "operit")
    builder = _context_builder(store)

    low_package = asyncio.run(
        builder.build_room_context_package(
            session,
            messages=[],
            record_window_scene=False,
        )
    )

    assert "## 书架一览" not in low_package["layers"]["slow"]
    assert "书桌旁边有一排矮书架" not in low_package["layers"]["tool_policy"]
    assert "shenyu_books" not in {tool["function"]["name"] for tool in low_package["room_tools"]}

    monkeypatch.setattr(room_context, "compute_charge", lambda **_kwargs: 0.5)
    active_package = asyncio.run(
        builder.build_room_context_package(
            session,
            messages=[],
            record_window_scene=False,
        )
    )

    assert "## 书架一览" in active_package["layers"]["slow"]
    assert "- 家现在：本周" in active_package["layers"]["slow"]
    assert "书桌旁边有一排矮书架" in active_package["layers"]["tool_policy"]
    assert "shenyu_books" in {tool["function"]["name"] for tool in active_package["room_tools"]}


def test_empty_tool_call_assistant_content_does_not_get_fallback():
    ensure = gateway_namespace["_ensure_visible_assistant_content"]
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
    }

    assert ensure(message) is False
    assert message["content"] == ""


def test_normal_context_surfaces_store_heartbeats_end_to_end(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("main", "operit")
    pending = store.append_heartbeat(session["id"], "normal hb")

    builder = _context_builder(store)
    package = asyncio.run(
        builder.build_context_package(
            session,
            current_user_text="",
            is_first_turn=True,
            client_name="operit",
            consume_heartbeat_pending=False,
        )
    )
    layers = builder.render_layered_additions(package)

    assert "normal hb" in layers["heartbeat"]

    store.mark_heartbeats_injected(heartbeat_ids=[pending["id"]])
    package = asyncio.run(
        builder.build_context_package(
            session,
            current_user_text="",
            is_first_turn=True,
            client_name="operit",
            consume_heartbeat_pending=True,
        )
    )
    layers = builder.render_layered_additions(package)

    assert "normal hb" in layers["heartbeat"]


def test_read_heartbeat_returns_time_and_content_only(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("default", "operit")
    store.append_heartbeat(session["id"], "normal hb")
    configure_gateway_tools(store=store)

    service = GatewayToolService()
    result = asyncio.run(service.read_heartbeat(session_tag="default"))

    assert result["ok"] is True
    assert result["session_tag"] == "default"
    assert result["count"] == 1
    assert "scope" not in result
    assert [item["content"] for item in result["items"]] == ["normal hb"]
    assert set(result["items"][0]) == {"content", "created_at"}
