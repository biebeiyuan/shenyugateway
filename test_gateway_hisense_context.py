from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from shenyu_gateway.store import GatewayStore


def _load_gateway_classes():
    source = Path(__file__).with_name("gateway.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    wanted_functions = {
        "_date_range_bounds",
        "_shorten",
        "_relative_time_label",
        "_stable_charter_block",
        "_is_hisense_client",
        "_is_hisense_session",
    }
    wanted_constants = {"_HEARTBEAT_PROMPT", "_INLINE_MEM_PROMPT"}
    namespace = {
        "Any": Any,
        "Optional": Optional,
        "GatewayStore": object,
        "SessionManager": object,
        "GatewayToolService": object,
        "asyncio": asyncio,
        "logger": logging.getLogger("test"),
        "session_store": None,
        "supabase_client": None,
        "cfg": SimpleNamespace(
            hisense_client_name="hisense",
            heartbeat_inject_every=5,
            hisense_heartbeat_limit=3,
            calendar_inject_day=False,
            calendar_context_day_limit=0,
            calendar_inject_week=False,
            calendar_context_week_limit=0,
            calendar_inject_month=False,
            calendar_context_month_limit=0,
            enable_gateway_tools=False,
            inject_inline_memory_prompt=False,
            inject_meta_summaries=False,
            inject_atomic_memories=False,
            default_atomic_memory_limit=3,
            hisense_notebook_limit=5,
        ),
    }
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in wanted_constants
        ):
            exec(ast.get_source_segment(source, node), namespace)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            exec(ast.get_source_segment(source, node), namespace)
        elif isinstance(node, ast.ClassDef) and node.name in {"GatewayToolService", "ContextBuilder"}:
            exec(ast.get_source_segment(source, node), namespace)
    return namespace["ContextBuilder"], namespace["GatewayToolService"], namespace["cfg"], namespace


ContextBuilder, GatewayToolService, cfg, gateway_namespace = _load_gateway_classes()


def test_hisense_context_can_see_both_heartbeat_pools(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("main", "operit")
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    store.append_heartbeat(normal_session["id"], "normal hb")
    store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)

    builder = ContextBuilder(store, None, SimpleNamespace())
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

    assert "normal hb" in layers["slow"]
    assert "hisense hb" in layers["slow"]


def test_normal_context_does_not_see_hisense_heartbeat_pool(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("main", "operit")
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    store.append_heartbeat(normal_session["id"], "normal hb")
    store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)

    builder = ContextBuilder(store, None, SimpleNamespace())
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

    assert "normal hb" in layers["slow"]
    assert "hisense hb" not in layers["slow"]


def test_hisense_context_marks_three_pending_heartbeats_injected(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    heartbeat_limit = int(cfg.hisense_heartbeat_limit)
    for index in range(heartbeat_limit):
        store.append_heartbeat(hisense_session["id"], f"hisense pending {index + 1}", hisense=True)

    builder = ContextBuilder(store, None, SimpleNamespace())
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

    assert "hisense pending 1" in layers["slow"]
    assert "hisense pending 2" in layers["slow"]
    assert f"hisense pending {heartbeat_limit}" in layers["slow"]
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

    builder = ContextBuilder(store, None, SimpleNamespace())
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

    assert "hisense injected" in layers["slow"]
    assert "hisense pending 1" not in layers["slow"]
    assert f"hisense pending {heartbeat_limit - 1}" not in layers["slow"]
    assert len(store.read_heartbeats(None, state="pending", hisense=True)) == heartbeat_limit - 1


def test_read_heartbeat_scope_can_override_hisense_default(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("default", "operit")
    hisense_session = store.get_or_create_session("hisense", cfg.hisense_client_name)
    store.append_heartbeat(normal_session["id"], "normal hb")
    store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)
    gateway_namespace["session_store"] = store

    service = GatewayToolService()
    auto_result = asyncio.run(service.read_heartbeat(session_tag="hisense"))
    normal_result = asyncio.run(service.read_heartbeat(session_tag="hisense", scope="normal"))

    assert auto_result["scope"] == "hisense"
    assert [item["content"] for item in auto_result["items"]] == ["hisense hb"]
    assert normal_result["scope"] == "normal"
    assert [item["content"] for item in normal_result["items"]] == ["normal hb"]
