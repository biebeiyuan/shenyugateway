from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from shenyu_gateway import context_layers
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
    upstream_for_hisense as _upstream_for_hisense,
)
from shenyu_gateway.private_capture import (
    EMPTY_VISIBLE_ASSISTANT_REPLY as _EMPTY_VISIBLE_ASSISTANT_REPLY,
    is_free_time_fallback_context as _is_free_time_fallback_context,
    private_capture_kinds as _private_capture_kinds,
    private_capture_fallback_text as _private_capture_fallback_text,
    ensure_visible_assistant_content as _ensure_visible_assistant_content,
    finalize_assistant_private_content as _finalize_assistant_private_content,
)
from shenyu_gateway.response_capture import split_private_assistant_tags


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
        "_is_hisense_client",
        "_is_hisense_session",
    }
    cfg = SimpleNamespace(
        hisense_client_name="hisense",
        hisense_upstream_url="",
        hisense_api_key="",
        hisense_protocol="",
        upstream_url="https://api.treegpt.cc",
        upstream_api_key="default-key",
        upstream_protocol="openai",
        heartbeat_inject_every=5,
        hisense_heartbeat_limit=3,
        calendar_inject_day=False,
        calendar_context_day_limit=0,
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
        hisense_notebook_limit=5,
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
        "_upstream_for_hisense": lambda is_hisense=False: _upstream_for_hisense(cfg, is_hisense),
        "_EMPTY_VISIBLE_ASSISTANT_REPLY": _EMPTY_VISIBLE_ASSISTANT_REPLY,
        "_is_free_time_fallback_context": _is_free_time_fallback_context,
        "_private_capture_kinds": _private_capture_kinds,
        "_private_capture_fallback_text": _private_capture_fallback_text,
        "_ensure_visible_assistant_content": _ensure_visible_assistant_content,
        "_finalize_assistant_private_content": _finalize_assistant_private_content,
    }
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            exec(ast.get_source_segment(source, node), namespace)
    namespace.update({name: getattr(upstream_adapter, name) for name in adapter_functions})
    return namespace["cfg"], namespace


cfg, gateway_namespace = _load_gateway_helpers()
configure_gateway_tools(runtime_config=cfg, supabase=None, store=None)


def _context_builder(store, *, supabase=None):
    return ContextBuilder(
        store,
        None,
        GatewayToolService(),
        cfg=cfg,
        supabase_client=supabase,
        stable_charter_block=gateway_namespace["_stable_charter_block"],
        is_hisense_client=gateway_namespace["_is_hisense_client"],
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
        limit = int(params.get("limit") or len(rows))
        return rows[:limit]


def test_hisense_context_can_see_both_heartbeat_pools(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("main", "operit")
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    store.append_heartbeat(normal_session["id"], "normal hb")
    store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)

    builder = _context_builder(store)
    package = asyncio.run(
        builder.build_context_package(
            hisense_session,
            current_user_text="",
            is_first_turn=True,
            client_name=cfg.hisense_client_name,
            consume_heartbeat_pending=False,
        )
    )
    layers = builder.render_layered_additions(package)

    assert "normal hb" in layers["heartbeat"]
    assert "hisense hb" in layers["heartbeat"]


def test_gateway_tool_policy_names_broker_call_shape_and_tool_list():
    layers = context_layers.render_layered_additions(
        {
            "stable_charter": "stable charter",
            "calendar_context": {},
            "heartbeat_digest": "",
            "hisense_heartbeat_digest": "",
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


def test_gateway_tool_policy_reflects_client_tool_surface():
    package = {
        "stable_charter": "stable charter",
        "calendar_context": {},
        "heartbeat_digest": "",
        "hisense_heartbeat_digest": "",
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
    assert "普通线程不暴露客户端工具" in none_layers["tool_policy"]
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
            "hisense_heartbeat_digest": "",
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
        "hisense_heartbeat_digest": "",
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
    old_week_enabled = cfg.calendar_inject_week
    old_month_enabled = cfg.calendar_inject_month
    try:
        cfg.calendar_inject_day = True
        cfg.calendar_context_day_limit = 5
        cfg.calendar_inject_week = False
        cfg.calendar_inject_month = False

        builder = _context_builder(None, supabase=fake_supabase)
        calendar_context = asyncio.run(builder.calendar_context_pages())
    finally:
        cfg.calendar_inject_day = old_day_enabled
        cfg.calendar_context_day_limit = old_day_limit
        cfg.calendar_inject_week = old_week_enabled
        cfg.calendar_inject_month = old_month_enabled

    assert "content" in fake_supabase.queries[0][1]["select"]
    assert [row["period_key"] for row in calendar_context["day"]] == ["2026-05-18"]
    assert calendar_context["day"][0]["content"] == "Full day content goes in"
    assert calendar_context["day"][0]["digest"] == "Digest stays out"


def test_hisense_client_defaults_to_isolated_session_tag():
    request = SimpleNamespace(headers={})

    session_tag = gateway_namespace["_session_tag_from_request"](
        request,
        client_name=cfg.hisense_client_name,
    )

    assert session_tag == "hisense"


def test_hisense_client_detection_tolerates_case_and_chinese_alias():
    assert gateway_namespace["_is_hisense_client"]("Hisense")
    assert gateway_namespace["_is_hisense_client"]("海信")


def test_hisense_upstream_can_use_dedicated_url():
    cfg.upstream_url = "https://default.example"
    cfg.upstream_api_key = "default-key"
    cfg.upstream_protocol = "openai"
    cfg.hisense_upstream_url = "https://hisense.example"
    cfg.hisense_api_key = "hisense-key"
    cfg.hisense_protocol = "openai"

    upstream = gateway_namespace["_upstream_for_hisense"](True)
    default_upstream = gateway_namespace["_upstream_for_hisense"](False)

    assert upstream["scope"] == "hisense"
    assert upstream["chat_url"] == "https://hisense.example/v1/chat/completions"
    assert upstream["api_key"] == "hisense-key"
    assert default_upstream["chat_url"] == "https://default.example/v1/chat/completions"

    cfg.upstream_url = "https://api.treegpt.cc"
    cfg.upstream_api_key = "default-key"
    cfg.upstream_protocol = "openai"
    cfg.hisense_upstream_url = ""
    cfg.hisense_api_key = ""
    cfg.hisense_protocol = ""


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


def test_empty_tool_call_assistant_content_does_not_get_fallback():
    ensure = gateway_namespace["_ensure_visible_assistant_content"]
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
    }

    assert ensure(message) is False
    assert message["content"] == ""


def test_normal_context_does_not_see_hisense_heartbeat_pool(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("main", "operit")
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    store.append_heartbeat(normal_session["id"], "normal hb")
    store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)

    builder = _context_builder(store)
    package = asyncio.run(
        builder.build_context_package(
            normal_session,
            current_user_text="",
            is_first_turn=True,
            client_name="operit",
            consume_heartbeat_pending=False,
        )
    )
    layers = builder.render_layered_additions(package)

    assert "normal hb" in layers["heartbeat"]
    assert "hisense hb" not in layers["heartbeat"]


def test_hisense_context_returns_three_pending_heartbeat_ids_for_deferred_marking(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    heartbeat_limit = int(cfg.hisense_heartbeat_limit)
    for index in range(heartbeat_limit):
        store.append_heartbeat(hisense_session["id"], f"hisense pending {index + 1}", hisense=True)

    builder = _context_builder(store)
    package = asyncio.run(
        builder.build_context_package(
            hisense_session,
            current_user_text="",
            is_first_turn=True,
            client_name=cfg.hisense_client_name,
            consume_heartbeat_pending=True,
        )
    )
    layers = builder.render_layered_additions(package)

    assert "hisense pending 1" in layers["heartbeat"]
    assert "hisense pending 2" in layers["heartbeat"]
    assert f"hisense pending {heartbeat_limit}" in layers["heartbeat"]
    assert len(package["hisense_heartbeat_pending_ids"]) == heartbeat_limit
    assert len(store.read_heartbeats(None, state="pending", hisense=True)) == heartbeat_limit

    store.mark_heartbeats_injected(heartbeat_ids=package["hisense_heartbeat_pending_ids"], hisense=True)

    assert store.read_heartbeats(None, state="pending", hisense=True) == []
    assert len(store.read_heartbeats(None, state="injected", hisense=True)) == heartbeat_limit


def test_hisense_context_waits_for_three_pending_heartbeats(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    injected = store.append_heartbeat(hisense_session["id"], "hisense injected", hisense=True)
    store.mark_heartbeats_injected(heartbeat_ids=[injected["id"]], hisense=True)
    heartbeat_limit = int(cfg.hisense_heartbeat_limit)
    for index in range(heartbeat_limit - 1):
        store.append_heartbeat(hisense_session["id"], f"hisense pending {index + 1}", hisense=True)

    builder = _context_builder(store)
    package = asyncio.run(
        builder.build_context_package(
            hisense_session,
            current_user_text="",
            is_first_turn=True,
            client_name=cfg.hisense_client_name,
            consume_heartbeat_pending=True,
        )
    )
    layers = builder.render_layered_additions(package)

    assert "hisense injected" in layers["heartbeat"]
    assert "hisense pending 1" not in layers["heartbeat"]
    assert f"hisense pending {heartbeat_limit - 1}" not in layers["heartbeat"]
    assert len(store.read_heartbeats(None, state="pending", hisense=True)) == heartbeat_limit - 1


def test_read_heartbeat_scope_can_override_hisense_default(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("default", "operit")
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    store.append_heartbeat(normal_session["id"], "normal hb")
    store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)
    gateway_namespace["session_store"] = store
    configure_gateway_tools(store=store)

    service = GatewayToolService()
    auto_result = asyncio.run(service.read_heartbeat(session_tag="hisense"))
    normal_result = asyncio.run(service.read_heartbeat(session_tag="hisense", scope="normal"))

    assert auto_result["scope"] == "hisense"
    assert [item["content"] for item in auto_result["items"]] == ["hisense hb"]
    assert normal_result["scope"] == "normal"
    assert [item["content"] for item in normal_result["items"]] == ["normal hb"]
