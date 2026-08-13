from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import gateway
from shenyu_gateway import mcp_registry as mcp_registry_module
from shenyu_gateway.context_layers import trim_mcp_tool_results
from shenyu_gateway.mcp_registry import (
    McpToolRegistry,
    _normalize_call_result,
    validate_mcp_servers,
)
from shenyu_gateway.tool_registry import merge_tools


def _cfg(**overrides):
    base = {
        "enable_upstream_tools": True,
        "enable_mcp_tools": True,
        "mcp_servers": [],
        "mcp_call_timeout_seconds": 60,
        "mcp_list_timeout_seconds": 10,
        "mcp_tools_cache_seconds": 300,
        "enable_gateway_tools": False,
        "enable_mem0_management_tools": False,
        "expose_supabase_tools": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _server(name="calc", url="http://mcp.local/mcp", **overrides):
    base = {"name": name, "url": url, "transport": "auto", "headers": {}, "enabled": True}
    base.update(overrides)
    return base


class FakeClient:
    """Stands in for mcp.Client: async context manager with list/call."""

    def __init__(self, tools=None, call_result=None, list_error=None, call_error=None):
        self._tools = tools or []
        self._call_result = call_result
        self._list_error = list_error
        self._call_error = call_error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def list_tools(self):
        if self._list_error is not None:
            raise self._list_error
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self._call_error is not None:
            raise self._call_error
        return self._call_result


def _remote_tool(name, description="", input_schema=None):
    return SimpleNamespace(
        name=name,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {}},
    )


def _text_result(text, *, is_error=False, structured=None):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        is_error=is_error,
        structured_content=structured,
    )


def _patch_client(monkeypatch, client_factory):
    monkeypatch.setattr(mcp_registry_module, "_build_client", client_factory)


# ---------------------------------------------------------------------------
# validate_mcp_servers
# ---------------------------------------------------------------------------


def test_validate_accepts_json_string_and_normalizes():
    raw = json.dumps(
        [
            {
                "name": "Calc",
                "url": " http://mcp.local/mcp ".strip(),
                "headers": {"Authorization": "Bearer abc"},
            }
        ]
    )
    servers = validate_mcp_servers(raw)
    assert servers == [
        {
            "name": "calc",
            "url": "http://mcp.local/mcp",
            "transport": "auto",
            "headers": {"Authorization": "Bearer abc"},
            "enabled": True,
        }
    ]


def test_validate_empty_inputs_return_empty_list():
    assert validate_mcp_servers(None) == []
    assert validate_mcp_servers("") == []
    assert validate_mcp_servers([]) == []


@pytest.mark.parametrize(
    "item",
    [
        {"name": "bad name!", "url": "http://x/"},
        {"name": "", "url": "http://x/"},
        {"name": "a" * 25, "url": "http://x/"},
        {"name": "ok", "url": "ftp://x/"},
        {"name": "ok", "url": ""},
        {"name": "ok", "url": "http://x/", "transport": "websocket"},
        {"name": "ok", "url": "http://x/", "headers": ["not-a-dict"]},
        "not-a-dict",
    ],
)
def test_validate_rejects_bad_entries(item):
    with pytest.raises(ValueError):
        validate_mcp_servers([item])


def test_validate_rejects_duplicate_names():
    with pytest.raises(ValueError, match="重复"):
        validate_mcp_servers([_server("dup"), _server("dup", url="http://other/")])


def test_validate_rejects_non_list_json():
    with pytest.raises(ValueError):
        validate_mcp_servers("{\"name\": \"x\"}")
    with pytest.raises(ValueError):
        validate_mcp_servers("not json")


# ---------------------------------------------------------------------------
# registry refresh / snapshot
# ---------------------------------------------------------------------------


def test_refresh_builds_prefixed_tools_and_per_server_status(monkeypatch):
    def factory(server, *, read_timeout_seconds):
        if server["name"] == "calc":
            return FakeClient(tools=[_remote_tool("add", "加法"), _remote_tool("Sub Tool")])
        return FakeClient(list_error=ConnectionError("boom"))

    _patch_client(monkeypatch, factory)
    registry = McpToolRegistry()
    cfg = _cfg(mcp_servers=[_server("calc"), _server("news", url="http://news.local/mcp")])

    status = asyncio.run(registry.refresh(cfg))

    by_name = {item["name"]: item for item in status}
    assert by_name["calc"]["ok"] is True
    assert by_name["calc"]["tool_count"] == 2
    assert by_name["news"]["ok"] is False
    assert "ConnectionError" in by_name["news"]["error"]

    exposed = {tool["function"]["name"] for tool in registry.tools_for_merge(cfg)}
    assert exposed == {"mcp_calc_add", "mcp_calc_sub_tool"}
    summaries = {item["name"]: item for item in registry.tool_summaries()}
    assert summaries["mcp_calc_add"]["remote_name"] == "add"
    assert summaries["mcp_calc_add"]["server"] == "calc"


def test_refresh_disambiguates_colliding_tool_names(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(
            tools=[_remote_tool("run tool"), _remote_tool("run-tool")]
        ),
    )
    registry = McpToolRegistry()
    cfg = _cfg(mcp_servers=[_server("calc")])

    asyncio.run(registry.refresh(cfg))

    exposed = {tool["function"]["name"] for tool in registry.tools_for_merge(cfg)}
    assert exposed == {"mcp_calc_run_tool", "mcp_calc_run_tool_2"}


def test_tools_for_merge_respects_toggles_and_disabled_servers(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(tools=[_remote_tool("add")]),
    )
    registry = McpToolRegistry()
    cfg = _cfg(mcp_servers=[_server("calc")])
    asyncio.run(registry.refresh(cfg))

    assert registry.tools_for_merge(cfg)
    assert registry.tools_for_merge(_cfg(mcp_servers=[_server("calc")], enable_mcp_tools=False)) == []
    assert registry.tools_for_merge(_cfg(mcp_servers=[_server("calc")], enable_upstream_tools=False)) == []
    disabled = _cfg(mcp_servers=[_server("calc", enabled=False)])
    assert registry.tools_for_merge(disabled) == []


def test_ensure_fresh_skips_refresh_within_ttl(monkeypatch):
    registry = McpToolRegistry()
    calls = []

    async def fake_refresh(cfg):
        calls.append(cfg)

    monkeypatch.setattr(registry, "refresh", fake_refresh)
    cfg = _cfg(mcp_servers=[_server("calc")])

    asyncio.run(registry.ensure_fresh(cfg))
    assert len(calls) == 1

    import time

    registry._refreshed_at = time.monotonic()
    asyncio.run(registry.ensure_fresh(cfg))
    assert len(calls) == 1


def test_ensure_fresh_noop_without_servers(monkeypatch):
    registry = McpToolRegistry()

    async def fail_refresh(cfg):
        raise AssertionError("should not refresh")

    monkeypatch.setattr(registry, "refresh", fail_refresh)
    asyncio.run(registry.ensure_fresh(_cfg(mcp_servers=[])))
    asyncio.run(registry.ensure_fresh(_cfg(mcp_servers=[_server()], enable_mcp_tools=False)))


# ---------------------------------------------------------------------------
# registry execute
# ---------------------------------------------------------------------------


def _seeded_registry(monkeypatch, *, call_result=None, call_error=None):
    client = FakeClient(
        tools=[_remote_tool("add")],
        call_result=call_result,
        call_error=call_error,
    )
    _patch_client(monkeypatch, lambda server, *, read_timeout_seconds: client)
    registry = McpToolRegistry()
    cfg = _cfg(mcp_servers=[_server("calc")])
    asyncio.run(registry.refresh(cfg))
    return registry, cfg, client


def test_execute_success_returns_text_result(monkeypatch):
    registry, cfg, client = _seeded_registry(monkeypatch, call_result=_text_result("42"))

    result = asyncio.run(registry.execute("mcp_calc_add", {"a": 1, "b": 41}, cfg=cfg))

    assert result == {"ok": True, "result": "42"}
    assert client.calls == [("add", {"a": 1, "b": 41})]


def test_execute_prefers_structured_content(monkeypatch):
    structured = {"sum": 42}
    registry, cfg, _ = _seeded_registry(
        monkeypatch, call_result=_text_result("ignored", structured=structured)
    )

    result = asyncio.run(registry.execute("mcp_calc_add", {}, cfg=cfg))

    assert result["ok"] is True
    assert result["result"] == structured
    assert result["text"] == "ignored"


def test_execute_surfaces_remote_tool_error(monkeypatch):
    registry, cfg, _ = _seeded_registry(
        monkeypatch, call_result=_text_result("bad input", is_error=True)
    )

    result = asyncio.run(registry.execute("mcp_calc_add", {}, cfg=cfg))

    assert result == {"ok": False, "error": "bad input", "error_kind": "mcp_tool_error"}


def test_execute_degrades_on_connection_failure(monkeypatch):
    registry, cfg, _ = _seeded_registry(monkeypatch, call_error=ConnectionError("down"))

    result = asyncio.run(registry.execute("mcp_calc_add", {}, cfg=cfg))

    assert result["ok"] is False
    assert result["error_kind"] == "mcp_connection"
    assert "calc" in result["error"]


def test_execute_degrades_on_timeout(monkeypatch):
    registry, cfg, _ = _seeded_registry(monkeypatch, call_error=TimeoutError())

    result = asyncio.run(registry.execute("mcp_calc_add", {}, cfg=cfg))

    assert result["ok"] is False
    assert result["error_kind"] == "timeout"


def test_execute_unknown_tool_returns_validation_error(monkeypatch):
    registry, cfg, _ = _seeded_registry(monkeypatch, call_result=_text_result("42"))

    result = asyncio.run(registry.execute("mcp_calc_missing", {}, cfg=cfg))

    assert result["ok"] is False
    assert result["error_kind"] == "validation"
    assert "mcp_calc_add" in result["available_tools"]


def test_execute_rejects_disabled_mcp(monkeypatch):
    registry, cfg, _ = _seeded_registry(monkeypatch, call_result=_text_result("42"))
    cfg.enable_mcp_tools = False

    result = asyncio.run(registry.execute("mcp_calc_add", {}, cfg=cfg))

    assert result == {"ok": False, "error": "MCP tools are disabled.", "error_kind": "validation"}


def test_execute_rejects_server_removed_from_config(monkeypatch):
    registry, cfg, _ = _seeded_registry(monkeypatch, call_result=_text_result("42"))
    cfg.mcp_servers = [_server("calc", enabled=False)]

    result = asyncio.run(registry.execute("mcp_calc_add", {}, cfg=cfg))

    assert result["ok"] is False
    assert result["error_kind"] == "validation"


def test_normalize_call_result_counts_non_text_blocks():
    res = SimpleNamespace(
        content=[SimpleNamespace(text="hi"), SimpleNamespace(data=b"img")],
        is_error=False,
        structured_content=None,
    )
    assert _normalize_call_result(res) == {"ok": True, "result": "hi", "non_text_blocks": 1}


def test_test_server_probe(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(tools=[_remote_tool("add")]),
    )
    registry = McpToolRegistry()

    result = asyncio.run(registry.test_server(_server("calc"), cfg=_cfg()))

    assert result == {"ok": True, "tool_count": 1, "tools": ["add"]}
    assert registry.tool_summaries() == []


def test_test_server_probe_failure(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(list_error=ConnectionError("nope")),
    )
    registry = McpToolRegistry()

    result = asyncio.run(registry.test_server(_server("calc"), cfg=_cfg()))

    assert result["ok"] is False
    assert "ConnectionError" in result["error"]


# ---------------------------------------------------------------------------
# merge_tools integration
# ---------------------------------------------------------------------------


def test_merge_tools_appends_mcp_tools(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(tools=[_remote_tool("add")]),
    )
    registry = McpToolRegistry()
    cfg = _cfg(mcp_servers=[_server("calc")])
    asyncio.run(registry.refresh(cfg))
    monkeypatch.setattr("shenyu_gateway.mcp_registry.registry", registry)

    merged = merge_tools([], cfg)

    assert "mcp_calc_add" in {tool["function"]["name"] for tool in merged}


def test_merge_tools_skips_mcp_when_disabled(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(tools=[_remote_tool("add")]),
    )
    registry = McpToolRegistry()
    cfg = _cfg(mcp_servers=[_server("calc")])
    asyncio.run(registry.refresh(cfg))
    monkeypatch.setattr("shenyu_gateway.mcp_registry.registry", registry)

    cfg.enable_mcp_tools = False
    merged = merge_tools([], cfg)

    assert all(not tool["function"]["name"].startswith("mcp_") for tool in merged)


# ---------------------------------------------------------------------------
# context trimming
# ---------------------------------------------------------------------------


def _mcp_round(call_id, tool_name, content):
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": call_id, "function": {"name": tool_name, "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": content},
    ]


def test_trim_mcp_tool_results_compresses_old_large_results():
    large = "x" * 700
    messages = []
    for idx in range(4):
        messages.extend(_mcp_round(f"call_{idx}", "mcp_calc_add", large))

    trimmed, meta = trim_mcp_tool_results(messages, keep_recent=2)

    tool_msgs = [m for m in trimmed if m.get("role") == "tool"]
    assert "已省略" in tool_msgs[0]["content"]
    assert "mcp_calc_add" in tool_msgs[0]["content"]
    assert "已省略" in tool_msgs[1]["content"]
    assert tool_msgs[2]["content"] == large
    assert tool_msgs[3]["content"] == large
    assert meta == {"mcp_tool_results_seen": 4, "mcp_tool_results_compressed": 2}


def test_trim_mcp_tool_results_ignores_small_and_non_mcp_results():
    messages = _mcp_round("c1", "mcp_calc_add", "small") + _mcp_round(
        "c2", "shenyu_recall", "y" * 700
    )

    trimmed, meta = trim_mcp_tool_results(messages, keep_recent=0)

    assert trimmed == messages
    assert meta["mcp_tool_results_compressed"] == 0


# ---------------------------------------------------------------------------
# /api/mcp/* routes
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_client(monkeypatch):
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(gateway.cfg, "gateway_key", "")
    monkeypatch.setattr(gateway, "_persist_env", lambda updates, **kwargs: persisted.append(dict(updates)))
    monkeypatch.setattr(
        gateway.cfg,
        "mcp_servers",
        [_server("calc", headers={"Authorization": "Bearer secret-token-value"})],
    )
    fresh = McpToolRegistry()
    monkeypatch.setattr(mcp_registry_module, "registry", fresh)
    monkeypatch.setattr("shenyu_gateway.mcp_routes.registry", fresh)
    return TestClient(gateway.app), persisted, fresh


def test_get_servers_masks_headers(mcp_client):
    client, _, _ = mcp_client

    resp = client.get("/api/mcp/servers")

    assert resp.status_code == 200
    payload = resp.json()
    header_value = payload["servers"][0]["headers"]["Authorization"]
    assert "secret-token-value" not in header_value
    assert header_value.endswith("****")
    assert payload["status"] == []
    assert payload["tools"] == []


def test_post_servers_persists_and_restores_masked_headers(mcp_client):
    client, persisted, _ = mcp_client

    resp = client.post(
        "/api/mcp/servers",
        json=[
            {
                "name": "calc",
                "url": "http://mcp.local/mcp",
                "headers": {"Authorization": "Bearer s****"},
            },
            {"name": "news", "url": "http://news.local/mcp"},
        ],
    )

    assert resp.status_code == 200
    assert gateway.cfg.mcp_servers[0]["headers"]["Authorization"] == "Bearer secret-token-value"
    assert persisted, "MCP_SERVERS should be persisted"
    stored = json.loads(persisted[-1]["MCP_SERVERS"])
    assert stored[0]["headers"]["Authorization"] == "Bearer secret-token-value"
    assert stored[1] == {
        "name": "news",
        "url": "http://news.local/mcp",
        "transport": "auto",
        "headers": {},
        "enabled": True,
    }
    body = resp.json()
    assert "secret-token-value" not in json.dumps(body)


def test_post_servers_keeps_new_plaintext_header(mcp_client):
    client, persisted, _ = mcp_client

    resp = client.post(
        "/api/mcp/servers",
        json=[
            {
                "name": "calc",
                "url": "http://mcp.local/mcp",
                "headers": {"Authorization": "Bearer brand-new-token"},
            }
        ],
    )

    assert resp.status_code == 200
    assert gateway.cfg.mcp_servers[0]["headers"]["Authorization"] == "Bearer brand-new-token"


def test_post_servers_rejects_invalid_payload(mcp_client):
    client, persisted, _ = mcp_client

    resp = client.post(
        "/api/mcp/servers",
        json=[{"name": "bad name", "url": "http://x/"}],
    )

    assert resp.status_code == 400
    assert persisted == []


def test_post_test_probes_without_touching_snapshot(mcp_client, monkeypatch):
    client, _, fresh = mcp_client
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(tools=[_remote_tool("add")]),
    )

    resp = client.post(
        "/api/mcp/test",
        json={"name": "probe", "url": "http://probe.local/mcp"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "tool_count": 1, "tools": ["add"]}
    assert fresh.tool_summaries() == []


def test_post_test_restores_masked_headers_from_config(mcp_client, monkeypatch):
    client, _, _ = mcp_client
    seen_headers = {}

    def factory(server, *, read_timeout_seconds):
        seen_headers.update(server.get("headers") or {})
        return FakeClient(tools=[_remote_tool("add")])

    _patch_client(monkeypatch, factory)

    resp = client.post(
        "/api/mcp/test",
        json={
            "name": "calc",
            "url": "http://mcp.local/mcp",
            "headers": {"Authorization": "Bearer s****"},
        },
    )

    assert resp.status_code == 200
    assert seen_headers["Authorization"] == "Bearer secret-token-value"


def test_post_test_rejects_invalid_server(mcp_client):
    client, _, _ = mcp_client

    resp = client.post("/api/mcp/test", json={"name": "x", "url": "not-a-url"})

    assert resp.status_code == 400


def test_post_refresh_reloads_tools(mcp_client, monkeypatch):
    client, _, fresh = mcp_client
    _patch_client(
        monkeypatch,
        lambda server, *, read_timeout_seconds: FakeClient(tools=[_remote_tool("add")]),
    )

    resp = client.post("/api/mcp/refresh")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["status"][0]["ok"] is True
    assert payload["tools"][0]["name"] == "mcp_calc_add"
