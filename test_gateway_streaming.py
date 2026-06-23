from __future__ import annotations

import asyncio
import json
import tempfile
from collections import deque
from types import SimpleNamespace

import gateway
import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import Request
from starlette.types import Scope

from shenyu_gateway.chat_pipeline import ChatPipeline
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.request_logs import (
    _active_http_requests,
    _finalize_stale_tool_stream_log,
    _finalize_tool_stream_log,
    _finish_http_request_event,
    _http_request_diagnostics,
    _http_request_events,
    _mark_http_request_event,
    _mark_request_log_phase,
    _record_completion_finish_reason,
    _record_response_text,
    _start_http_request_event,
    _upstream_payload_summary,
)
from shenyu_gateway.schemas import ChatRequest
from shenyu_gateway.sessions import SessionManager
from shenyu_gateway.store import GatewayStore
from shenyu_gateway.streaming import (
    StreamReplayAccumulator,
    _apply_openai_stream_chunk,
    _completion_with_unstreamed_deltas,
    _new_stream_completion,
    _sse_response,
    _stream_content_event,
    _stream_final_event,
    _stream_keepalive_event,
    _stream_role_event,
    close_stream_reader,
    read_next_stream_chunk,
)
from shenyu_gateway.tool_loop import (
    InternalToolLoopContext,
    _execute_mixed_gateway_tool_calls,
    _extract_tool_calls,
    _tool_call_name,
    run_internal_tool_loop_stream,
)
from shenyu_gateway.upstream_adapter import (
    _anthropic_tool_index_override,
    _apply_openai_compatible_cache_control,
    _completion_to_stream_events,
    _openai_to_anthropic,
)


class _FakeStore:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def append_message(self, **kwargs):
        self.messages.append(kwargs)

    def touch_session(self, *args, **kwargs):
        return None


def _fake_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": raw_headers,
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }
    return Request(scope)


def _test_pipeline(*, prepare_messages, nonstream_chat=None) -> ChatPipeline:
    cfg = RuntimeConfig()
    cfg.enable_gateway_tools = False
    cfg.enable_upstream_tools = False
    cfg.model_mapping = {}
    store = _FakeStore()
    return ChatPipeline(
        cfg=cfg,
        store=store,
        prepare_messages=prepare_messages,
        build_upstream_request=lambda *args, **kwargs: None,
        run_internal_tool_loop=lambda *args, **kwargs: None,
        run_internal_tool_loop_stream=lambda *args, **kwargs: None,
        stream_chat=lambda *args, **kwargs: None,
        nonstream_chat=nonstream_chat or (lambda *args, **kwargs: None),
        upstream_for_hisense=lambda is_hisense=False: {
            "chat_url": "https://example.test/v1/chat/completions",
            "scope": "default",
            "protocol": "openai",
            "api_key": "test",
        },
        mapped_model_name=lambda model: model,
        private_capture_fallback_text=lambda *args, **kwargs: ("fallback", "generic"),
        private_capture_kinds=lambda *args, **kwargs: [],
        finalize_assistant_private_content=lambda message, **kwargs: (
            message.get("content") or "",
            "",
            [],
            [],
            {"applied": False},
        ),
        schedule_inline_memory_capture=lambda *args, **kwargs: None,
        store_heartbeat=lambda *args, **kwargs: None,
        mark_context_consumed=lambda *args, **kwargs: None,
        write_completion_context_snapshot=lambda *args, **kwargs: None,
    )


def test_require_session_store_raises_clear_runtime_error_when_uninitialized():
    old_store = gateway.session_store
    gateway.session_store = None
    try:
        with pytest.raises(RuntimeError, match="Gateway session store is not initialized"):
            gateway._require_session_store()
    finally:
        gateway.session_store = old_store


def test_chat_pipeline_logs_request_before_prepare_messages_fails(monkeypatch):
    from shenyu_gateway import chat_pipeline

    request_logs = deque(maxlen=30)
    monkeypatch.setattr(chat_pipeline, "_request_logs", request_logs)

    async def prepare_messages(_request, _body):
        raise RuntimeError("context store stalled")

    pipeline = _test_pipeline(prepare_messages=prepare_messages)
    body = ChatRequest(model="test-model", messages=[{"role": "user", "content": "hello"}])

    with pytest.raises(RuntimeError, match="context store stalled"):
        asyncio.run(pipeline.run(_fake_request({"X-Shenyu-Session-Tag": "new-test-thread"}), body))

    assert len(request_logs) == 1
    entry = request_logs[0]
    assert entry["status"] == "error"
    assert entry["stage"] == "prepare_messages"
    assert entry["session_tag"] == "new-test-thread"
    assert entry["original_messages_count"] == 1
    assert entry["error"] == "context store stalled"
    phases = [item["phase"] for item in entry["timeline"]]
    assert "pipeline.received" in phases
    assert "stage.prepare_messages" in phases


def test_chat_pipeline_updates_single_early_log_on_success(monkeypatch):
    from shenyu_gateway import chat_pipeline

    request_logs = deque(maxlen=30)
    monkeypatch.setattr(chat_pipeline, "_request_logs", request_logs)

    session = {"id": "session-1", "session_tag": "new-test-thread", "message_count": 0}

    async def prepare_messages(_request, _body):
        return (
            [{"role": "user", "content": "hello"}],
            {
                "session": session,
                "is_first_turn": True,
                "client_message_window": {},
                "cache_layers": {},
                "is_hisense": False,
                "upstream": {
                    "chat_url": "https://example.test/v1/chat/completions",
                    "scope": "default",
                    "protocol": "openai",
                    "api_key": "test",
                },
            },
        )

    async def build_upstream_request(*_args, **_kwargs):
        return (
            {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
            {},
            "test-model",
            {"enabled": False, "protocol": "openai", "breakpoints": []},
            {
                "chat_url": "https://example.test/v1/chat/completions",
                "scope": "default",
                "protocol": "openai",
                "api_key": "test",
            },
        )

    async def nonstream_chat(*_args, **_kwargs):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    pipeline = _test_pipeline(prepare_messages=prepare_messages, nonstream_chat=nonstream_chat)
    pipeline.build_upstream_request = build_upstream_request
    body = ChatRequest(model="test-model", messages=[{"role": "user", "content": "hello"}])

    result = asyncio.run(pipeline.run(_fake_request({"X-Shenyu-Session-Tag": "new-test-thread"}), body))

    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(request_logs) == 1
    entry = request_logs[0]
    assert entry["status"] == "ok"
    assert entry["stage"] == "plain_upstream_path"
    assert entry["session_tag"] == "new-test-thread"
    assert entry["upstream_url"] == "https://example.test/v1/chat/completions"
    assert entry["response_preview"] == "ok"
    phases = [item["phase"] for item in entry["timeline"]]
    assert "pipeline.received" in phases
    assert "stage.plain_upstream_path" in phases
    assert entry["slow_phases"]


def test_chat_pipeline_writes_completion_context_snapshot_after_assistant_reply(monkeypatch):
    from shenyu_gateway import chat_pipeline

    request_logs = deque(maxlen=30)
    monkeypatch.setattr(chat_pipeline, "_request_logs", request_logs)
    snapshots: list[tuple[dict, str]] = []
    session = {"id": "session-1", "session_tag": "5.15", "message_count": 12}

    async def prepare_messages(_request, _body):
        return (
            [{"role": "user", "content": "最新一问"}],
            {
                "session": session,
                "is_first_turn": False,
                "snapshot_messages": [{"role": "user", "content": "最新一问"}],
                "snapshot_latest_user_text": "最新一问",
                "client_message_window": {},
                "cache_layers": {},
                "is_hisense": False,
                "upstream": {
                    "chat_url": "https://example.test/v1/chat/completions",
                    "scope": "default",
                    "protocol": "openai",
                    "api_key": "test",
                },
            },
        )

    async def build_upstream_request(*_args, **_kwargs):
        return (
            {"model": "test-model", "messages": [{"role": "user", "content": "最新一问"}]},
            {},
            "test-model",
            {"enabled": False, "protocol": "openai", "breakpoints": []},
            {
                "chat_url": "https://example.test/v1/chat/completions",
                "scope": "default",
                "protocol": "openai",
                "api_key": "test",
            },
        )

    async def nonstream_chat(*_args, **_kwargs):
        return {
            "choices": [{"message": {"role": "assistant", "content": "最新一答"}}],
            "usage": {},
        }

    pipeline = _test_pipeline(prepare_messages=prepare_messages, nonstream_chat=nonstream_chat)
    pipeline.build_upstream_request = build_upstream_request
    pipeline.write_completion_context_snapshot = lambda meta, content: snapshots.append((meta, content))
    body = ChatRequest(model="test-model", messages=[{"role": "user", "content": "最新一问"}])

    asyncio.run(pipeline.run(_fake_request({"X-Shenyu-Session-Tag": "5.15"}), body))

    assert len(snapshots) == 1
    meta, content = snapshots[0]
    assert meta["snapshot_messages"] == [{"role": "user", "content": "最新一问"}]
    assert content == "最新一答"


def test_http_request_diagnostics_track_active_and_recent_events():
    _active_http_requests.clear()
    _http_request_events.clear()

    _start_http_request_event(
        request_id="req-1",
        method="POST",
        path="/v1/chat/completions",
        client="127.0.0.1",
        session_tag="session-a",
        client_name="operit",
        now_iso="2026-06-17T00:00:00+00:00",
    )

    diagnostics = _http_request_diagnostics()
    assert diagnostics["active"][0]["request_id"] == "req-1"
    assert diagnostics["active"][0]["session_tag"] == "session-a"
    assert "Authorization" not in json.dumps(diagnostics)
    assert diagnostics["active"][0]["timeline"][0]["phase"] == "http.entry"

    _mark_http_request_event(
        "req-1",
        "handler.entered",
        now_iso="2026-06-17T00:00:00.500000+00:00",
        detail={"messages": 3036},
    )

    _finish_http_request_event(
        request_id="req-1",
        now_iso="2026-06-17T00:00:01+00:00",
        duration_ms=1000,
        http_status=200,
    )

    diagnostics = _http_request_diagnostics()
    assert diagnostics["active"] == []
    assert diagnostics["recent"][0]["status"] == "complete"
    assert diagnostics["recent"][0]["http_status"] == 200
    assert diagnostics["recent"][0]["duration_ms"] == 1000
    phases = [item["phase"] for item in diagnostics["recent"][0]["timeline"]]
    assert phases == ["http.entry", "handler.entered", "http.response_returned"]
    assert all(not key.startswith("_") for key in diagnostics["recent"][0])


def test_request_log_phase_tracks_tail_and_slow_phases():
    entry = {"id": "log-1"}

    _mark_request_log_phase(entry, "one", now_iso="2026-06-17T00:00:00+00:00")
    _mark_request_log_phase(entry, "two", now_iso="2026-06-17T00:00:01+00:00", detail={"rows": 3})

    assert [item["phase"] for item in entry["timeline"]] == ["one", "two"]
    assert entry["timeline_tail"][-1]["detail"] == {"rows": 3}
    assert entry["slow_phases"][0]["phase"] in {"one", "two"}


def test_runtime_config_does_not_cap_internal_tool_rounds_at_eight(monkeypatch):
    monkeypatch.setenv("MAX_INTERNAL_TOOL_ROUNDS", "12")

    cfg = RuntimeConfig()

    assert cfg.max_internal_tool_rounds == 12


def _data_payload(event: str) -> dict:
    line = next(line for line in event.splitlines() if line.startswith("data: "))
    return json.loads(line.removeprefix("data: "))


def test_internal_tool_keepalive_is_openai_compatible_empty_delta():
    payload = _data_payload(_stream_keepalive_event("test-model"))

    assert payload["object"] == "chat.completion.chunk"
    assert payload["model"] == "test-model"
    choice = payload["choices"][0]
    assert choice["delta"] == {"content": ""}
    assert choice["finish_reason"] is None


def test_stream_content_event_is_complete_openai_chunk():
    payload = _data_payload(
        _stream_content_event(
            "test-model",
            "hello",
            chunk_id="chatcmpl-fixed",
            created=123,
        )
    )

    assert payload["id"] == "chatcmpl-fixed"
    assert payload["object"] == "chat.completion.chunk"
    assert payload["created"] == 123
    assert payload["model"] == "test-model"
    assert payload["choices"] == [
        {"index": 0, "delta": {"content": "hello"}, "finish_reason": None}
    ]


def test_openai_compatible_tool_schema_defaults_are_type_safe():
    _, tools, _ = _apply_openai_compatible_cache_control(
        [{"role": "user", "content": "hello"}],
        [
            {
                "type": "function",
                "function": {
                    "name": "client_tool",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "flag": {"type": "boolean", "default": "false"},
                            "limit": {"type": "integer", "default": "20"},
                            "score": {"type": "number", "default": "0.5"},
                            "bad_expr": {"type": "integer", "default": "start_line + 99"},
                        },
                    },
                },
            }
        ],
    )

    props = tools[0]["function"]["parameters"]["properties"]
    assert props["flag"]["default"] is False
    assert props["limit"]["default"] == 20
    assert props["score"]["default"] == 0.5
    assert "default" not in props["bad_expr"]


def test_openai_compatible_cache_control_uses_format_layer_as_fourth_breakpoint():
    messages = [
        {"role": "system", "content": "stable block"},
        {"role": "system", "content": "calendar block"},
        {"role": "system", "content": "mem block"},
        {"role": "system", "content": "heartbeat block"},
        {"role": "system", "content": "tool policy block"},
        {"role": "system", "content": "format block"},
        {"role": "assistant", "content": "previous reply"},
        {"role": "user", "content": "hello"},
    ]
    tools = [{"type": "function", "function": {"name": "client_tool", "parameters": {"type": "object"}}}]

    cached_messages, _cached_tools, cache_paths = _apply_openai_compatible_cache_control(
        messages,
        tools,
        cache_layers={"stable": "stable block", "slow": "calendar block", "format": "format block"},
    )

    assert cache_paths == ["tools[-1]", "messages[0].stable", "messages[1].slow", "messages[5].format"]
    assert cached_messages[0]["cache_control"] == {"type": "ephemeral"}
    assert cached_messages[1]["cache_control"] == {"type": "ephemeral"}
    assert cached_messages[5]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in cached_messages[6]


def test_anthropic_cache_control_marks_format_layer_after_reading_order_prefix():
    cache_paths: list[str] = []

    system, messages = _openai_to_anthropic(
        [
            {"role": "system", "content": "stable block"},
            {"role": "system", "content": "calendar block"},
            {"role": "system", "content": "mem block"},
            {"role": "system", "content": "heartbeat block"},
            {"role": "system", "content": "tool policy block"},
            {"role": "system", "content": "format block"},
            {"role": "user", "content": "hello"},
        ],
        cache_layers={"stable": "stable block", "slow": "calendar block", "format": "format block"},
        cache_paths=cache_paths,
    )

    assert cache_paths == ["system.stable", "system.slow", "system.format"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    assert system[5]["cache_control"] == {"type": "ephemeral"}
    assert [block["text"] for block in system] == [
        "stable block",
        "calendar block",
        "mem block",
        "heartbeat block",
        "tool policy block",
        "format block",
    ]
    assert messages == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]


def _contains_cache_control(value):
    if isinstance(value, dict):
        return "cache_control" in value or any(_contains_cache_control(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_cache_control(item) for item in value)
    return False


def test_chat_request_does_not_default_or_cap_max_tokens():
    body = ChatRequest(model="test-model", messages=[{"role": "user", "content": "hello"}])
    large_body = ChatRequest(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=200000,
    )

    assert body.max_tokens is None
    assert large_body.max_tokens == 200000


@pytest.mark.parametrize(
    ("protocol", "url"),
    [
        ("openai", "https://example.com"),
    ],
)
def test_build_upstream_request_omits_max_tokens_when_not_requested(monkeypatch, protocol, url):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", protocol)
    monkeypatch.setenv("UPSTREAM_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert "max_tokens" not in payload


def test_build_upstream_request_uses_anthropic_default_max_tokens(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "anthropic")
    monkeypatch.setenv("UPSTREAM_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_DEFAULT_MAX_TOKENS", raising=False)
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert payload["max_tokens"] == 128000


@pytest.mark.parametrize(
    ("protocol", "url"),
    [
        ("openai", "https://example.com"),
        ("anthropic", "https://api.anthropic.com"),
    ],
)
def test_build_upstream_request_forwards_requested_max_tokens(monkeypatch, protocol, url):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", protocol)
    monkeypatch.setenv("UPSTREAM_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=200000,
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert payload["max_tokens"] == 200000


def test_build_upstream_request_omits_openai_cache_control_when_disabled(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "openai")
    monkeypatch.setenv("UPSTREAM_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_OPENAI_CACHE_CONTROL", "false")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "client_tool",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

        payload, _, _, cache_meta, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[
                    {"role": "system", "content": "stable"},
                    {"role": "user", "content": "hello"},
                ],
                meta={"cache_layers": {"stable": "stable"}},
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert cache_meta["enabled"] is False
    assert cache_meta["breakpoints"] == []
    assert _contains_cache_control(payload) is False


def test_build_upstream_request_omits_all_tools_when_upstream_tools_disabled(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "openai")
    monkeypatch.setenv("UPSTREAM_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_UPSTREAM_TOOLS", "false")
    monkeypatch.setenv("ENABLE_GATEWAY_TOOLS", "true")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "client_tool",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert "tools" not in payload


def test_build_upstream_request_includes_provider_string_for_openai(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "openai")
    monkeypatch.setenv("UPSTREAM_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", '["Amazon Bedrock", "OpenAI"]')
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert payload["provider"] == "Amazon Bedrock"


def test_build_upstream_request_includes_provider_order_object_for_openai(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "openai")
    monkeypatch.setenv("UPSTREAM_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPSTREAM_PROVIDER_FORMAT", "order_object")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", '["Amazon Bedrock", "OpenAI"]')
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert payload["provider"] == {"order": ["Amazon Bedrock", "OpenAI"]}


def test_build_upstream_request_omits_provider_order_for_anthropic(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "anthropic")
    monkeypatch.setenv("UPSTREAM_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", '["Amazon Bedrock"]')
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert "provider" not in payload


def test_build_upstream_request_forwards_anthropic_thinking_and_output_config(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "anthropic")
    monkeypatch.setenv("UPSTREAM_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.5,
            thinking={"type": "enabled", "budgetTokens": 2048},
            reasoning_effort="high",
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert payload["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2048,
        "display": "summarized",
    }
    assert payload["output_config"] == {"effort": "high"}
    assert "temperature" not in payload


def test_build_upstream_request_defaults_boolean_thinking_to_adaptive_summarized(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "anthropic")
    monkeypatch.setenv("UPSTREAM_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            thinking=True,
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert payload["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_build_upstream_request_auto_adds_anthropic_adaptive_thinking(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "anthropic")
    monkeypatch.setenv("UPSTREAM_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_ANTHROPIC_AUTO_THINKING", "true")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert payload["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_build_upstream_request_explicit_false_disables_auto_thinking(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROTOCOL", "anthropic")
    monkeypatch.setenv("UPSTREAM_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_ANTHROPIC_AUTO_THINKING", "true")
    old_cfg = gateway.cfg
    gateway.cfg = RuntimeConfig()
    try:
        body = ChatRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            thinking=False,
        )

        payload, _, _, _, _ = asyncio.run(
            gateway._build_upstream_request(
                None,
                body,
                messages_override=[{"role": "user", "content": "hello"}],
            )
        )
    finally:
        gateway.cfg = old_cfg

    assert "thinking" not in payload


def test_upstream_payload_summary_reports_thinking_shape():
    summary = _upstream_payload_summary(
        {
            "model": "test-model",
            "messages": [],
            "thinking": {"type": "adaptive", "display": "summarized", "signature": "hidden"},
        }
    )

    assert summary["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_sse_response_disables_proxy_buffering():
    async def generate():
        yield "data: [DONE]\n\n"

    response = _sse_response(generate())

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


def test_record_response_text_keeps_full_detail_when_payloads_retained():
    entry = {"request_payloads_retained": True}
    _record_response_text(entry, "x" * 250)

    assert entry["response_preview"].endswith("...")
    assert len(entry["response_preview"]) == 200
    assert entry["response_full"] == "x" * 250


def test_record_completion_finish_reason_updates_log_and_round():
    entry = {}
    round_log = {}
    completion = {"choices": [{"finish_reason": "length"}]}

    _record_completion_finish_reason(entry, completion, round_log=round_log)

    assert entry["finish_reason"] == "length"
    assert round_log["finish_reason"] == "length"


def test_finalize_tool_stream_log_closes_unfinished_streaming_status():
    entry = {"status": "streaming_tools", "error": None}

    _finalize_tool_stream_log(entry, 1234)

    assert entry["status"] == "client_disconnected"
    assert entry["duration_ms"] == 1234
    assert entry["error"] == "Client disconnected before native internal gateway tool stream completed."


def test_finalize_tool_stream_log_preserves_terminal_status():
    entry = {"status": "error", "error": "upstream failed"}

    _finalize_tool_stream_log(entry, 5678)

    assert entry["status"] == "error"
    assert entry["duration_ms"] == 5678
    assert entry["error"] == "upstream failed"


def test_finalize_stale_tool_stream_log_closes_inactive_stream():
    entry = {
        "status": "streaming_tools",
        "duration_ms": 0,
        "error": None,
        "_tool_stream_started_monotonic": 10.0,
        "_tool_stream_last_activity_monotonic": 20.0,
    }

    changed = _finalize_stale_tool_stream_log(entry, now_monotonic=30.0, stale_seconds=5.0)

    assert changed is True
    assert entry["status"] == "client_disconnected"
    assert entry["duration_ms"] == 20000
    assert "_tool_stream_started_monotonic" not in entry
    assert "_tool_stream_last_activity_monotonic" not in entry


def test_finalize_stale_tool_stream_log_keeps_recent_stream_active():
    entry = {
        "status": "streaming_tools",
        "duration_ms": 0,
        "error": None,
        "_tool_stream_started_monotonic": 10.0,
        "_tool_stream_last_activity_monotonic": 28.0,
    }

    changed = _finalize_stale_tool_stream_log(entry, now_monotonic=30.0, stale_seconds=5.0)

    assert changed is False
    assert entry["status"] == "streaming_tools"
    assert entry["_tool_stream_last_activity_monotonic"] == 28.0


def test_openai_stream_accumulator_collects_content_and_tool_arguments():
    completion = _new_stream_completion("test-model")

    _apply_openai_stream_chunk(
        completion,
        {"choices": [{"delta": {"content": "hello "}, "finish_reason": None}]},
    )
    _apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
    )
    _apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ":\"a.txt\"}"}}]},
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 3},
        },
    )

    message = completion["choices"][0]["message"]
    assert message["content"] == "hello "
    assert message["tool_calls"][0]["function"]["name"] == "read_file"
    assert message["tool_calls"][0]["function"]["arguments"] == "{\"path\":\"a.txt\"}"
    assert completion["choices"][0]["finish_reason"] == "tool_calls"
    assert completion["usage"] == {"prompt_tokens": 3}


def test_openai_stream_accumulator_treats_null_arguments_as_empty_delta():
    completion = _new_stream_completion("test-model")

    _apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": None},
                            }
                        ]
                    }
                }
            ]
        },
    )
    _apply_openai_stream_chunk(
        completion,
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"path\":\"a.txt\"}"}}]}}]},
    )

    arguments = completion["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert arguments == "{\"path\":\"a.txt\"}"


def test_openai_stream_accumulator_drops_empty_sparse_tool_placeholders():
    completion = _new_stream_completion("test-model")

    _apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {
                        "content": ".",
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "tooluse_1",
                                "type": "function",
                                "function": {
                                    "name": "shenyu_gateway_tool",
                                    "arguments": "{\"tool\":\"shenyu_list_mem_notes\"}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    )

    tool_calls = completion["choices"][0]["message"]["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "tooluse_1"
    assert tool_calls[0]["function"]["name"] == "shenyu_gateway_tool"
    assert _extract_tool_calls(completion) == tool_calls


def test_openai_stream_accumulator_drops_only_empty_tool_calls():
    completion = _new_stream_completion("test-model")

    _apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_empty",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    )

    message = completion["choices"][0]["message"]
    assert "tool_calls" not in message
    assert completion["choices"][0]["finish_reason"] == "stop"
    assert _extract_tool_calls(completion) == []


def test_openai_stream_accumulator_clears_tool_finish_without_tool_calls():
    completion = _new_stream_completion("test-model")

    _apply_openai_stream_chunk(
        completion,
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )

    assert "tool_calls" not in completion["choices"][0]["message"]
    assert completion["choices"][0]["finish_reason"] == "stop"
    assert _extract_tool_calls(completion) == []


def test_extract_tool_calls_preserves_real_client_tools_after_empty_placeholder():
    completion = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "I will read it.",
                    "tool_calls": [
                        {"id": "empty", "type": "function", "function": {"name": "", "arguments": ""}},
                        {
                            "id": "call_client",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                        },
                    ],
                },
            }
        ]
    }

    tool_calls = _extract_tool_calls(completion)

    assert [_tool_call_name(call) for call in tool_calls] == ["read_file"]
    assert completion["choices"][0]["message"]["tool_calls"] == tool_calls
    assert completion["choices"][0]["finish_reason"] == "tool_calls"


def test_extract_tool_calls_ignores_malformed_function_payloads():
    completion = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": "bad_none", "type": "function", "function": None},
                        {"id": "bad_text", "type": "function", "function": "read_file"},
                    ],
                },
            }
        ]
    }

    assert _extract_tool_calls(completion) == []
    assert "tool_calls" not in completion["choices"][0]["message"]
    assert completion["choices"][0]["finish_reason"] == "stop"


def test_extract_tool_calls_clears_non_list_tool_calls():
    completion = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": {"id": "bad", "function": {"name": "read_file"}},
                },
            }
        ]
    }

    assert _extract_tool_calls(completion) == []
    assert "tool_calls" not in completion["choices"][0]["message"]
    assert completion["choices"][0]["finish_reason"] == "stop"


def test_stream_role_and_final_events_are_openai_compatible():
    role_payload = _data_payload(_stream_role_event("test-model", chunk_id="chatcmpl-fixed", created=123))
    final_payload = _data_payload(
        _stream_final_event("test-model", "tool_calls", chunk_id="chatcmpl-fixed", created=123)
    )

    assert role_payload["id"] == final_payload["id"] == "chatcmpl-fixed"
    assert role_payload["created"] == final_payload["created"] == 123
    assert role_payload["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert role_payload["choices"][0]["finish_reason"] is None
    assert final_payload["choices"][0]["delta"] == {}
    assert final_payload["choices"][0]["finish_reason"] == "tool_calls"


def test_anthropic_tool_block_indexes_are_compacted_for_openai():
    state: dict[int, int] = {}

    text_start = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    tool_start = {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use"}}
    tool_delta = {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta"}}
    second_tool = {"type": "content_block_start", "index": 3, "content_block": {"type": "tool_use"}}

    assert _anthropic_tool_index_override(text_start, state) is None
    assert _anthropic_tool_index_override(tool_start, state) == 0
    assert _anthropic_tool_index_override(tool_delta, state) == 0
    assert _anthropic_tool_index_override(second_tool, state) == 1


def test_completion_replay_skips_already_streamed_text_for_mixed_tools():
    completion = {
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "I will check.\n\n第一段正文。\n\n第二段正文。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                }
            }
        ],
    }

    replay = _completion_with_unstreamed_deltas(
        completion,
        streamed_content="I will check.",
    )

    message = replay["choices"][0]["message"]
    assert message["content"] == "\n\n第一段正文。\n\n第二段正文。"
    assert completion["choices"][0]["message"]["content"].startswith("I will check.")


def test_stream_replay_accumulator_replays_only_unstreamed_deltas():
    accumulator = StreamReplayAccumulator()

    assert accumulator.record_reasoning("thinking ") == "thinking "
    assert accumulator.record_content("I will check.") == "I will check."
    assert accumulator.visible_output_sent is True
    accumulator.mark_tool_call_seen()

    completion = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "reasoning_content": "thinking more",
                    "content": "I will check.\n\nFinal text.",
                }
            }
        ],
    }

    replay = accumulator.replay_completion(completion)

    assert accumulator.should_skip_visible_delta() is True
    assert replay["choices"][0]["message"]["reasoning_content"] == "more"
    assert replay["choices"][0]["message"]["content"] == "\n\nFinal text."


class _DisconnectProbe:
    def __init__(self, disconnected: bool = False):
        self.disconnected = disconnected

    async def is_disconnected(self):
        return self.disconnected


class _ClosableAsyncIterator:
    def __init__(self, values):
        self._values = list(values)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._values:
            raise StopAsyncIteration
        value = self._values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def aclose(self):
        self.closed = True


def test_read_next_stream_chunk_returns_chunk_when_upstream_task_finishes():
    async def run_case():
        upstream = _ClosableAsyncIterator([{"choices": [{"delta": {"content": "hello"}}]}])
        next_chunk = asyncio.create_task(anext(upstream))

        result = await read_next_stream_chunk(
            upstream_chunks=upstream,
            next_chunk=next_chunk,
            request=_DisconnectProbe(),
            timeout=0.1,
        )

        assert result.kind == "chunk"
        assert result.data == {"choices": [{"delta": {"content": "hello"}}]}
        assert upstream.closed is False

    asyncio.run(run_case())


def test_read_next_stream_chunk_returns_keepalive_while_upstream_is_pending():
    async def pending_forever():
        await asyncio.sleep(3600)

    async def run_case():
        upstream = _ClosableAsyncIterator([])
        next_chunk = asyncio.create_task(pending_forever())
        try:
            result = await read_next_stream_chunk(
                upstream_chunks=upstream,
                next_chunk=next_chunk,
                request=_DisconnectProbe(),
                timeout=0.001,
            )

            assert result.kind == "keepalive"
            assert next_chunk.cancelled() is False
            assert upstream.closed is False
        finally:
            next_chunk.cancel()

    asyncio.run(run_case())


def test_read_next_stream_chunk_closes_upstream_when_client_disconnects():
    async def pending_forever():
        await asyncio.sleep(3600)

    async def run_case():
        upstream = _ClosableAsyncIterator([])
        next_chunk = asyncio.create_task(pending_forever())

        result = await read_next_stream_chunk(
            upstream_chunks=upstream,
            next_chunk=next_chunk,
            request=_DisconnectProbe(disconnected=True),
            timeout=0.001,
        )

        assert result.kind == "disconnected"
        assert next_chunk.cancelled() is True
        assert upstream.closed is True

    asyncio.run(run_case())


def test_close_stream_reader_cancels_pending_task_and_closes_upstream():
    async def pending_forever():
        await asyncio.sleep(3600)

    async def run_case():
        upstream = _ClosableAsyncIterator([])
        next_chunk = asyncio.create_task(pending_forever())

        await close_stream_reader(upstream_chunks=upstream, next_chunk=next_chunk)

        assert next_chunk.cancelled() is True
        assert upstream.closed is True

    asyncio.run(run_case())


def test_internal_stream_loop_ignores_sparse_empty_placeholder_and_runs_gateway_tool():
    async def run_case():
        class Body:
            model = "test-model"

        class Cfg:
            max_internal_tool_rounds = 3

        executed_tools: list[tuple[str, dict]] = []
        payload_messages_counts: list[int] = []

        async def build_upstream_request(request, body, messages_override=None, meta=None):
            payload_messages_counts.append(len(messages_override or []))
            return (
                {"model": body.model, "messages": messages_override or [], "tools": []},
                {},
                "",
                {},
                {"chat_url": "https://upstream.test/v1/chat/completions", "protocol": "openai"},
            )

        async def stream_upstream_openai_chunks(request, payload, headers, model, upstream):
            if len(payload_messages_counts) == 1:
                yield {
                    "choices": [
                        {
                            "delta": {
                                "content": ".",
                                "tool_calls": [
                                    {
                                        "index": 1,
                                        "id": "tooluse_1",
                                        "type": "function",
                                        "function": {
                                            "name": "shenyu_gateway_tool",
                                            "arguments": "{\"tool\":\"shenyu_list_mem_notes\",\"arguments\":{}}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            else:
                yield {"choices": [{"delta": {"content": "done"}, "finish_reason": None}]}
                yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

        async def execute_gateway_tool(name, args, session_tag=None, cfg=None):
            executed_tools.append((name, args))
            return {"ok": True, "items": []}

        class Sessions:
            def log_tool_result(self, *args, **kwargs):
                pass

            def log_assistant_output(self, *args, **kwargs):
                pass

        ctx = InternalToolLoopContext(
            request=_DisconnectProbe(),
            body=Body(),
            prepared_messages=[{"role": "user", "content": "list mem"}],
            meta={"session": {"id": "session-1", "session_tag": "5.15"}},
            log_entry={},
            cfg=Cfg(),
            store=None,
            sessions=Sessions(),
            build_upstream_request=build_upstream_request,
            call_upstream_json=None,
            stream_upstream_openai_chunks=stream_upstream_openai_chunks,
            execute_gateway_tool=execute_gateway_tool,
            record_upstream_payload=lambda log_entry, payload: None,
            aggregate_cache_usage=lambda usages: {},
            finalize_assistant_private_content=lambda assistant_message, **kwargs: (
                assistant_message.get("content", ""),
                "",
                [],
                [],
                {"applied": False},
            ),
            store_heartbeat=lambda *args, **kwargs: None,
            schedule_inline_memory_capture=lambda *args, **kwargs: None,
            mark_context_consumed=lambda meta: None,
            write_completion_context_snapshot=lambda *args, **kwargs: None,
            record_response_text=lambda log_entry, text: log_entry.__setitem__("response_text", text),
        )

        events = [
            event
            async for event in run_internal_tool_loop_stream(ctx)
            if isinstance(event, str) and event.startswith("data: ")
        ]

        assert executed_tools == [
            ("shenyu_gateway_tool", {"tool": "shenyu_list_mem_notes", "arguments": {}})
        ]
        assert len(payload_messages_counts) == 2
        assert ctx.log_entry["response_text"] == "done"
        assert any('"content": "done"' in event for event in events)
        assert not any('"function": {"name": ""' in event for event in events)

    asyncio.run(run_case())


def test_read_next_stream_chunk_returns_exhausted_at_end_of_stream():
    async def run_case():
        upstream = _ClosableAsyncIterator([])
        next_chunk = asyncio.create_task(anext(upstream))

        result = await read_next_stream_chunk(
            upstream_chunks=upstream,
            next_chunk=next_chunk,
            request=_DisconnectProbe(),
            timeout=0.1,
        )

        assert result.kind == "exhausted"
        assert upstream.closed is False

    asyncio.run(run_case())


def test_pending_gateway_tool_turn_store_round_trip_consume_and_prune():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        pending = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_client"],
            original_assistant_message={"role": "assistant", "tool_calls": [{"id": "call_client"}]},
            gateway_tool_messages=[{"role": "tool", "tool_call_id": "call_gateway", "content": "{\"ok\":true}"}],
        )

        found = store.find_pending_gateway_tool_turn(session["id"], ["call_client"])

        assert found is not None
        assert found["id"] == pending["id"]
        assert found["client_tool_call_ids"] == ["call_client"]
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_other"]) is None
        assert store.mark_pending_gateway_tool_turns_consumed([pending["id"]]) == 1
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"]) is None
        assert store.prune_pending_gateway_tool_turns(session["id"]) == 1

        expired = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_expired"],
            original_assistant_message={"role": "assistant", "tool_calls": [{"id": "call_expired"}]},
            gateway_tool_messages=[],
            ttl_minutes=-1,
        )
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_expired"]) is None
        assert store.prune_pending_gateway_tool_turns(session["id"]) >= 1
        assert expired["id"]


def test_pending_gateway_tool_turn_lookup_uses_canonical_tool_ids():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        target = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_b", "call_a"],
            original_assistant_message={"role": "assistant", "tool_calls": []},
            gateway_tool_messages=[],
        )
        for index in range(30):
            store.create_pending_gateway_tool_turn(
                session_id=session["id"],
                session_tag=session["session_tag"],
                client_tool_call_ids=[f"call_other_{index}"],
                original_assistant_message={"role": "assistant", "tool_calls": []},
                gateway_tool_messages=[],
            )

        found = store.find_pending_gateway_tool_turn(session["id"], ["call_a", "call_b"])

        assert target["client_tool_call_ids"] == ["call_a", "call_b"]
        assert found is not None
        assert found["id"] == target["id"]


def test_pending_gateway_tool_turn_rebuilds_mixed_transcript_before_upstream():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        original_assistant = {
            "role": "assistant",
            "content": "I will check both.",
            "tool_calls": [
                {
                    "id": "call_gateway",
                    "type": "function",
                    "function": {"name": "shenyu_recall", "arguments": "{}"},
                },
                {
                    "id": "call_client",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                },
            ],
        }
        gateway_result = {
            "role": "tool",
            "tool_call_id": "call_gateway",
            "name": "shenyu_recall",
            "content": "{\"ok\":true}",
        }
        pending = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_client"],
            original_assistant_message=original_assistant,
            gateway_tool_messages=[gateway_result],
        )
        client_messages = [
            {"role": "user", "content": "check"},
            {
                "role": "assistant",
                "content": "I will check both.",
                "tool_calls": [original_assistant["tool_calls"][1]],
            },
            {"role": "tool", "tool_call_id": "call_client", "name": "read_file", "content": "file body"},
        ]

        rebuilt, meta = gateway._inject_pending_gateway_tool_turns(
            client_messages,
            store,
            session["id"],
        )

        assert meta["pending_gateway_tool_turns_injected"] == 1
        assert meta["pending_gateway_tool_turn_ids"] == [pending["id"]]
        assert rebuilt == [
            client_messages[0],
            original_assistant,
            gateway_result,
            client_messages[2],
        ]
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"]) is not None
        assert store.mark_pending_gateway_tool_turns_consumed(meta["pending_gateway_tool_turn_ids"]) == 1
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"]) is None


def test_pending_gateway_tool_turn_is_not_injected_without_complete_client_result():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        original_assistant = {
            "role": "assistant",
            "content": "I will check both.",
            "tool_calls": [
                {
                    "id": "call_gateway",
                    "type": "function",
                    "function": {"name": "shenyu_recall", "arguments": "{}"},
                },
                {
                    "id": "call_client",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                },
            ],
        }
        pending = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_client"],
            original_assistant_message=original_assistant,
            gateway_tool_messages=[
                {
                    "role": "tool",
                    "tool_call_id": "call_gateway",
                    "name": "shenyu_recall",
                    "content": "{\"ok\":true}",
                }
            ],
        )
        client_messages = [
            {"role": "user", "content": "check"},
            {
                "role": "assistant",
                "content": "I will check both.",
                "tool_calls": [original_assistant["tool_calls"][1]],
            },
        ]

        rebuilt, meta = gateway._inject_pending_gateway_tool_turns(
            client_messages,
            store,
            session["id"],
        )

        assert rebuilt == client_messages
        assert meta == {
            "pending_gateway_tool_turns_injected": 0,
            "pending_gateway_tool_turn_ids": [],
            "pending_gateway_tool_messages": 0,
        }
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"])["id"] == pending["id"]


def test_pending_gateway_tool_turn_is_not_injected_for_mismatched_client_result_id():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        original_assistant = {
            "role": "assistant",
            "content": "I will check both.",
            "tool_calls": [
                {
                    "id": "call_gateway",
                    "type": "function",
                    "function": {"name": "shenyu_recall", "arguments": "{}"},
                },
                {
                    "id": "call_client",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                },
            ],
        }
        pending = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_client"],
            original_assistant_message=original_assistant,
            gateway_tool_messages=[
                {
                    "role": "tool",
                    "tool_call_id": "call_gateway",
                    "name": "shenyu_recall",
                    "content": "{\"ok\":true}",
                }
            ],
        )
        client_messages = [
            {"role": "user", "content": "check"},
            {
                "role": "assistant",
                "content": "I will check both.",
                "tool_calls": [original_assistant["tool_calls"][1]],
            },
            {"role": "tool", "tool_call_id": "call_other", "name": "read_file", "content": "file body"},
        ]

        rebuilt, meta = gateway._inject_pending_gateway_tool_turns(
            client_messages,
            store,
            session["id"],
        )

        assert rebuilt == client_messages
        assert meta == {
            "pending_gateway_tool_turns_injected": 0,
            "pending_gateway_tool_turn_ids": [],
            "pending_gateway_tool_messages": 0,
        }
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"])["id"] == pending["id"]


def test_execute_mixed_gateway_tool_calls_stores_hidden_result_and_returns_only_client_calls():
    async def run_case():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(f"{tmp}/gateway.db")
            session = store.get_or_create_session("test-session", "test-client")
            sessions = SessionManager(store, gateway.cfg)
            old_store = gateway.session_store
            old_execute = gateway.execute_gateway_tool

            async def fake_execute(name, args, session_tag=None, cfg=None):
                return {"ok": True, "items": [{"content": "hidden gateway result", "source_table": "journal"}]}

            gateway.session_store = store
            gateway.execute_gateway_tool = fake_execute
            try:
                completion = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 123,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "I will check.",
                                "tool_calls": [
                                    {
                                        "id": "call_gateway",
                                        "type": "function",
                                        "function": {"name": "shenyu_recall", "arguments": "{\"q\":\"x\"}"},
                                    },
                                    {
                                        "id": "call_client",
                                        "type": "function",
                                        "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                                    },
                                ],
                            },
                        }
                    ],
                }

                ctx = gateway._make_internal_tool_loop_context(
                    request=None,
                    body=None,
                    prepared_messages=[],
                    meta={"session": {"id": session["id"], "session_tag": session["session_tag"]}},
                    sessions=sessions,
                )
                result, gateway_calls, client_calls = await _execute_mixed_gateway_tool_calls(
                    ctx,
                    completion,
                    completion["choices"][0]["message"]["tool_calls"],
                )
            finally:
                gateway.session_store = old_store
                gateway.execute_gateway_tool = old_execute

            message = result["choices"][0]["message"]
            pending = store.find_pending_gateway_tool_turn(session["id"], ["call_client"])
            replay_events = list(
                _completion_to_stream_events(
                    result,
                    include_role=False,
                    content_chunk_chars=1200,
                    chunk_id="chatcmpl-fixed",
                )
            )
            response_text = json.dumps(result, ensure_ascii=False) + "\n".join(replay_events)

            assert [_tool_call_name(call) for call in gateway_calls] == ["shenyu_recall"]
            assert [_tool_call_name(call) for call in client_calls] == ["read_file"]
            assert [_tool_call_name(call) for call in message["tool_calls"]] == ["read_file"]
            assert message["content"] == "I will check."
            assert pending is not None
            assert "hidden gateway result" in pending["gateway_tool_messages"][0]["content"]
            assert "hidden gateway result" not in response_text
            assert "<gateway_tool_results>" not in response_text

    asyncio.run(run_case())


def test_execute_mixed_gateway_tool_calls_stores_clean_pending_assistant_copy():
    async def run_case():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(f"{tmp}/gateway.db")
            session = store.get_or_create_session("test-session", "test-client")
            sessions = SessionManager(store, gateway.cfg)
            old_store = gateway.session_store
            old_execute = gateway.execute_gateway_tool

            async def fake_execute(name, args, session_tag=None, cfg=None):
                return {"ok": True}

            gateway.session_store = store
            gateway.execute_gateway_tool = fake_execute
            try:
                completion = {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Visible [mem]private note[/mem]",
                                "tool_calls": [
                                    {
                                        "id": "call_gateway",
                                        "type": "function",
                                        "function": {"name": "shenyu_recall", "arguments": "{}"},
                                    },
                                    {
                                        "id": "call_client",
                                        "type": "function",
                                        "function": {"name": "read_file", "arguments": "{}"},
                                    },
                                ],
                            }
                        }
                    ]
                }

                ctx = gateway._make_internal_tool_loop_context(
                    request=None,
                    body=None,
                    prepared_messages=[],
                    meta={"session": {"id": session["id"], "session_tag": session["session_tag"]}},
                    sessions=sessions,
                )
                result, _, _ = await _execute_mixed_gateway_tool_calls(
                    ctx,
                    completion,
                    completion["choices"][0]["message"]["tool_calls"],
                )
            finally:
                gateway.session_store = old_store
                gateway.execute_gateway_tool = old_execute

            pending = store.find_pending_gateway_tool_turn(session["id"], ["call_client"])

            assert pending is not None
            assert pending["original_assistant_message"].get("content", "").strip() == "Visible"
            assert "[mem]" not in pending["original_assistant_message"].get("content", "")
            assert result["choices"][0]["message"]["content"] == "Visible [mem]private note[/mem]"

    asyncio.run(run_case())
