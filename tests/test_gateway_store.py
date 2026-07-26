from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shenyu_gateway.context_snapshots import write_completion_context_snapshot
from shenyu_gateway.gateway_admin_routes import (
    GatewayAdminRouteDeps,
    _public_log_detail,
    build_gateway_admin_router,
)
from shenyu_gateway.prepare_messages import maybe_prepare_cold_start_snapshot, pwa_history_ready_for_cold_start
from shenyu_gateway.store import GatewayStore, NEXT_REQUEST_COLD_START_TAG


def test_public_log_detail_recursively_redacts_credentials_without_hiding_messages():
    source = {
        "upstream_payload": {
            "messages": [{"role": "user", "content": "keep this private conversation visible to admin"}],
            "provider": {
                "api_key": "provider-secret",
                "routing": "preferred",
            },
            "callback_url": "https://example.test/callback?token=url-secret&mode=debug",
        },
        "tool_args": {
            "authorization": "Bearer tool-secret",
            "openai_api_key": "nested-api-secret",
            "webhook_secret": "nested-webhook-secret",
            "token_count": 123,
            "max_tokens": 4096,
            "query": "ordinary tool input",
        },
        "_started_monotonic": 123.0,
    }

    detail = _public_log_detail(source)

    assert detail["upstream_payload"]["provider"]["api_key"] == "<redacted>"
    assert detail["upstream_payload"]["provider"]["routing"] == "preferred"
    assert detail["upstream_payload"]["callback_url"] == (
        "https://example.test/callback?token=%3Credacted%3E&mode=debug"
    )
    assert detail["tool_args"]["authorization"] == "<redacted>"
    assert detail["tool_args"]["openai_api_key"] == "<redacted>"
    assert detail["tool_args"]["webhook_secret"] == "<redacted>"
    assert detail["tool_args"]["token_count"] == 123
    assert detail["tool_args"]["max_tokens"] == 4096
    assert detail["tool_args"]["query"] == "ordinary tool input"
    assert detail["upstream_payload"]["messages"][0]["content"].startswith("keep this")
    assert "_started_monotonic" not in detail
    assert source["upstream_payload"]["provider"]["api_key"] == "provider-secret"


def test_request_log_history_survives_reopen_prunes_and_excludes_full_payloads(tmp_path):
    db_path = tmp_path / "gateway.db"
    store = GatewayStore(str(db_path))

    for index in range(1, 4):
        store.upsert_request_log(
            {
                "id": f"log-{index}",
                "request_id": f"req-{index}",
                "timestamp": f"2026-07-14T00:0{index}:00+00:00",
                "session_tag": "persist-test",
                "status": "ok",
                "response_preview": f"preview-{index}",
                "response_full": f"full response {index}",
                "prepared_messages": [{"role": "user", "content": "full user message"}],
                "upstream_payload": {"messages": [{"role": "user", "content": "full payload"}]},
                "system_additions_full": "full system text",
                "upstream_payload_summary": {
                    "thinking": {"type": "adaptive", "display": "summarized"},
                },
                "diagnostics": {
                    "new_counter": index,
                    "messages": 9,
                    "api_key": "must-not-persist",
                    "thinking": "raw thinking must not persist",
                    "signature": "opaque-signature",
                },
                "internal_tool_rounds": [
                    {
                        "round": 1,
                        "response_full": "full round response",
                        "response_preview": "round preview",
                        "args_preview": '{"api_key":"preview-secret","query":"safe"}',
                        "result_preview": '{"token":"truncated-secret",',
                        "messages": [{"role": "user", "content": "round message"}],
                        "upstream_payload": {"messages": []},
                        "prompt_cache": {
                            "enabled": True,
                            "protocol": "anthropic",
                            "ttl": "5m",
                            "breakpoints": ["system.end", "messages[4].content[0]"],
                            "prefix_fingerprints": [
                                {"path": "system.end", "sha256": "system-prefix"},
                                {"path": "messages[4].content[0]", "sha256": "message-prefix"},
                            ],
                            "cache_control_marker_count": 2,
                        },
                        "anthropic_thinking": {
                            "preserved": True,
                            "signature_present": True,
                        },
                    }
                ],
            },
            retention=2,
        )

    reopened = GatewayStore(str(db_path))
    logs = reopened.list_request_logs(limit=10)
    assert [item["id"] for item in logs] == ["log-3", "log-2"]
    assert reopened.request_log_count() == 2

    detail = reopened.get_request_log("req-3")
    assert detail is not None
    assert detail["persisted"] is True
    assert detail["persistence_schema_version"] == 2
    assert detail["request_payloads_retained"] is False
    assert detail["response_preview"] == "preview-3"
    assert detail["response_full"] is None
    assert detail["prepared_messages"] is None
    assert detail["upstream_payload"] is None
    assert detail["system_additions_full"] is None
    assert detail["diagnostics"]["new_counter"] == 3
    assert detail["diagnostics"]["messages"] == 9
    assert detail["diagnostics"]["api_key"] == "<redacted>"
    assert "thinking" not in detail["diagnostics"]
    assert "signature" not in detail["diagnostics"]
    assert detail["upstream_payload_summary"]["thinking"]["type"] == "adaptive"
    round_log = detail["internal_tool_rounds"][0]
    assert round_log["response_preview"] == "round preview"
    assert '"api_key": "<redacted>"' in round_log["args_preview"]
    assert round_log["result_preview"] == "<omitted:truncated-json-preview>"
    assert round_log["anthropic_thinking"]["signature_present"] is True
    assert round_log["prompt_cache"]["breakpoints"] == ["system.end", "messages[4].content[0]"]
    assert round_log["prompt_cache"]["cache_control_marker_count"] == 2
    assert "response_full" not in round_log
    assert "messages" not in round_log
    assert "upstream_payload" not in round_log


def test_request_log_history_marks_only_active_rows_interrupted(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    store.upsert_request_log(
        {
            "id": "active-log",
            "timestamp": "2026-07-14T00:01:00+00:00",
            "status": "streaming",
            "error": None,
        }
    )
    store.upsert_request_log(
        {
            "id": "complete-log",
            "timestamp": "2026-07-14T00:02:00+00:00",
            "status": "ok",
            "error": None,
        }
    )

    assert store.mark_interrupted_request_logs() == 1
    assert store.get_request_log("active-log")["status"] == "interrupted"
    assert "stopped before" in store.get_request_log("active-log")["error"]
    assert store.get_request_log("complete-log")["status"] == "ok"


def test_gateway_logs_api_reads_persisted_history_after_memory_is_empty(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    store.upsert_request_log(
        {
            "id": "persisted-log",
            "request_id": "persisted-request",
            "timestamp": "2026-07-14T00:01:00+00:00",
            "last_activity_at": "2026-07-14T00:01:02+00:00",
            "stage": "plain_upstream_path",
            "model": "test-model",
            "client_model": "test-model",
            "upstream_model": "test-model",
            "model_mapped": False,
            "stream": False,
            "session_tag": "persist-test",
            "is_first_turn": False,
            "original_messages_count": 1,
            "prepared_messages_count": 1,
            "client_message_window": {},
            "memory_island": {},
            "cold_start": {"injected": False},
            "system_additions_preview": "",
            "system_additions_chars": 0,
            "tools_count": 0,
            "tool_names": [],
            "has_internal_tools": False,
            "upstream_url": "https://example.test/v1/chat/completions",
            "upstream_scope": "default",
            "prompt_cache": {"enabled": False},
            "usage": {},
            "cache_usage": {},
            "internal_tool_rounds": [
                {
                    "round": 1,
                    "messages_count": 1,
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                    "cache_usage": {
                        "total_input_tokens": 1010,
                        "total_input_reported": True,
                    },
                    "prompt_cache": {
                        "enabled": True,
                        "protocol": "anthropic",
                        "ttl": "5m",
                        "breakpoints": ["system.end"],
                        "prefix_fingerprints": [{"path": "system.end", "sha256": "safe-prefix"}],
                        "cache_control_marker_count": 1,
                    },
                    "tools": [],
                }
            ],
            "status": "ok",
            "duration_ms": 2000,
            "error": None,
            "response_preview": "persisted answer",
            "response_full": "full answer must stay ephemeral",
            "diagnostics": {"new_counter": 7},
        }
    )

    app = FastAPI()
    app.include_router(
        build_gateway_admin_router(
            GatewayAdminRouteDeps(
                cfg=SimpleNamespace(gateway_request_log_retention=200),
                get_supabase_client=lambda: None,
                get_session_store=lambda: store,
                require_session_store=lambda: store,
                context_builder=lambda *_args, **_kwargs: None,
                upstream_for_hisense=lambda _is_hisense: {},
                prune_runtime_state=lambda **_kwargs: {},
                cold_start_idle_minutes=lambda _session: 0,
                is_hisense_session=lambda _session: False,
                now=lambda: None,
                request_logs=[],
            )
        )
    )

    with TestClient(app) as client:
        listing = client.get("/api/gateway/logs?limit=30")
        detail = client.get("/api/gateway/logs/persisted-request")

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["logs"]] == ["persisted-log"]
    assert listing.json()["logs"][0]["response_preview"] == "persisted answer"
    assert listing.json()["logs"][0]["internal_tool_rounds"][0]["cache_usage"]["total_input_tokens"] == 1010
    assert listing.json()["logs"][0]["internal_tool_rounds"][0]["prompt_cache"]["breakpoints"] == [
        "system.end"
    ]
    assert detail.status_code == 200
    assert detail.json()["diagnostics"]["new_counter"] == 7
    assert detail.json()["response_full"] is None


def test_hisense_heartbeats_are_stored_separately(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("main", "operit")
    hisense_session = store.get_or_create_session("hisense", "hisense")

    normal_hb = store.append_heartbeat(normal_session["id"], "normal hb")
    hisense_hb = store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)

    assert normal_hb["id"].startswith("hb_")
    assert hisense_hb["id"].startswith("hhb_")
    assert [item["content"] for item in store.read_heartbeats(None, order="asc")] == ["normal hb"]
    assert [item["content"] for item in store.read_heartbeats(None, order="asc", hisense=True)] == ["hisense hb"]


def test_hisense_heartbeat_injection_state_does_not_touch_normal_pool(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("main", "operit")
    hisense_session = store.get_or_create_session("hisense", "hisense")

    normal_hb = store.append_heartbeat(normal_session["id"], "normal hb")
    hisense_hb = store.append_heartbeat(hisense_session["id"], "hisense hb", hisense=True)

    store.mark_heartbeats_injected(heartbeat_ids=[hisense_hb["id"]], hisense=True)

    assert [item["id"] for item in store.get_pending_heartbeats()] == [normal_hb["id"]]
    assert store.get_latest_heartbeat_digest() == ""
    assert store.get_latest_heartbeat_digest(hisense=True) == "hisense hb"


def test_get_or_create_session_refreshes_client_name(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))

    first = store.get_or_create_session("shared", "debug")
    second = store.get_or_create_session("shared", "hisense")

    assert second["id"] == first["id"]
    assert second["client_name"] == "hisense"
    assert store.get_session_by_tag("shared")["client_name"] == "hisense"


def test_tool_error_log_records_error_kind_and_filters(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("main", "operit")

    store.log_tool_error(
        session_id=session["id"],
        session_tag=session["session_tag"],
        tool_name="shenyu_gateway_tool",
        target_tool="shenyu_write_mem_note",
        args={"tool": "shenyu_write_mem_note", "params": {}},
        error_text="content is required",
        error_source="result",
        error_kind="validation",
    )
    store.log_tool_error(
        session_id=session["id"],
        session_tag=session["session_tag"],
        tool_name="shenyu_gateway_tool",
        target_tool="shenyu_recall",
        args={"tool": "shenyu_recall", "params": {}},
        error_text="Store not available",
        error_source="result",
        error_kind="config",
    )

    all_errors = store.list_tool_errors(limit=10)
    validation_errors = store.list_tool_errors(limit=10, kind="validation")

    assert {item["error_kind"] for item in all_errors} == {"validation", "config"}
    assert len(validation_errors) == 1
    assert validation_errors[0]["target_tool"] == "shenyu_write_mem_note"


def test_delete_session_removes_all_session_scoped_sqlite_diagnostics(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("delete-me", "operit")
    store.append_message(session["id"], "user", "sensitive message")
    store.log_tool_error(
        session_id=session["id"],
        session_tag=session["session_tag"],
        tool_name="shenyu_gateway_tool",
        target_tool="shenyu_recall",
        args={"query": "sensitive tool args"},
        error_text="sensitive tool error",
    )
    store.add_room_trace(
        session["id"],
        "window",
        detail={"private": "sensitive room detail"},
        scribble="sensitive scribble",
    )

    deleted = store.delete_session(session["id"])

    assert deleted["gateway_sessions"] == 1
    assert deleted["gateway_messages"] == 1
    assert deleted["tool_error_log"] == 1
    assert deleted["room_trace"] == 1
    assert store.get_session_by_tag("delete-me") is None
    assert store.list_tool_errors(limit=10) == []
    assert store.recent_room_traces(limit=10) == []

    with sqlite3.connect(store.db_path) as connection:
        session_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
            if "session_id" in {
                column[1] for column in connection.execute(f"PRAGMA table_info({row[0]})")
            }
        }
    assert session_tables <= set(deleted)


def test_latest_cross_session_context_accumulates_multiple_snapshots(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("main", "operit")

    store.write_request_context_snapshot(
        session_id=session["id"],
        session_tag=session["session_tag"],
        client_name=session["client_name"],
        latest_user_text="old u3",
        messages=[
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "old u1"},
            {"role": "assistant", "content": "old a1"},
            {"role": "user", "content": "old u2"},
            {"role": "assistant", "content": "old a2"},
            {"role": "user", "content": "old u3"},
        ],
    )
    store.write_request_context_snapshot(
        session_id=session["id"],
        session_tag=session["session_tag"],
        client_name=session["client_name"],
        latest_user_text="new u1",
        messages=[
            {"role": "user", "content": "old u3"},
            {"role": "assistant", "content": "new a1"},
            {"role": "user", "content": "new u1"},
        ],
    )

    sources = store.latest_cross_session_context(
        exclude_session_id=None,
        since=None,
        limit_messages=6,
    )
    messages = [msg for source in sources for msg in source["messages"]]

    assert [msg["content"] for msg in messages] == [
        "old a1",
        "old u2",
        "old a2",
        "old u3",
        "new a1",
        "new u1",
    ]


def test_latest_session_context_stays_on_selected_thread(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    main = store.get_or_create_session("main", "operit")
    smoke = store.get_or_create_session("codex-smoke", "codex")

    store.write_request_context_snapshot(
        session_id=main["id"],
        session_tag=main["session_tag"],
        client_name=main["client_name"],
        latest_user_text="main latest",
        messages=[
            {"role": "user", "content": "main u1"},
            {"role": "assistant", "content": "main a1"},
            {"role": "user", "content": "main latest"},
        ],
    )
    store.write_request_context_snapshot(
        session_id=smoke["id"],
        session_tag=smoke["session_tag"],
        client_name=smoke["client_name"],
        latest_user_text="smoke latest",
        messages=[
            {"role": "user", "content": "smoke u1"},
            {"role": "assistant", "content": "smoke a1"},
        ],
    )

    sources = store.latest_session_context("main", limit_messages=10)

    assert [source["session_tag"] for source in sources] == ["main"]
    assert [msg["content"] for msg in sources[0]["messages"]] == [
        "main u1",
        "main a1",
        "main latest",
    ]


def test_latest_session_context_uses_latest_snapshot_tail_without_splicing_old_windows(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("5.15", "operit")

    store.write_request_context_snapshot(
        session_id=session["id"],
        session_tag=session["session_tag"],
        client_name=session["client_name"],
        latest_user_text="old tail",
        messages=[
            {"role": "user", "content": "old u1"},
            {"role": "assistant", "content": "old a1"},
            {"role": "user", "content": "old tail"},
        ],
    )
    store.write_request_context_snapshot(
        session_id=session["id"],
        session_tag=session["session_tag"],
        client_name=session["client_name"],
        latest_user_text="new tail",
        messages=[
            {"role": "user", "content": "new u1"},
            {"role": "assistant", "content": "new a1"},
            {"role": "user", "content": "new u2"},
            {"role": "assistant", "content": "new a2"},
            {"role": "user", "content": "new tail"},
        ],
    )

    sources = store.latest_session_context("5.15", limit_messages=8)

    assert len(sources) == 1
    assert sources[0]["latest_user_text"] == "new tail"
    assert [msg["content"] for msg in sources[0]["messages"]] == [
        "new u1",
        "new a1",
        "new u2",
        "new a2",
        "new tail",
    ]


def test_completion_context_snapshot_appends_latest_assistant_reply(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("5.15", "operit")
    meta = {
        "session": session,
        "snapshot_messages": [
            {"role": "user", "content": "最新一问"},
        ],
        "snapshot_latest_user_text": "最新一问",
    }

    write_completion_context_snapshot(store, meta, "最新一答")
    sources = store.latest_session_context("5.15", limit_messages=10)

    assert [msg["content"] for msg in sources[0]["messages"]] == ["最新一问", "最新一答"]
    assert sources[0]["latest_user_text"] == "最新一问"


def test_cold_start_uses_active_preview_snapshot_before_auto_source(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    target = store.get_or_create_session("default", "operit")
    chosen = store.get_or_create_session("main", "operit")
    newer = store.get_or_create_session("codex-smoke", "codex")
    cfg = SimpleNamespace(
        enable_cold_start=True,
        cold_start_message_limit=5,
        max_client_messages=5,
        cold_start_idle_minutes=120,
    )

    store.write_request_context_snapshot(
        session_id=chosen["id"],
        session_tag=chosen["session_tag"],
        client_name=chosen["client_name"],
        latest_user_text="main latest",
        messages=[
            {"role": "user", "content": "main u1"},
            {"role": "assistant", "content": "main a1"},
            {"role": "user", "content": "main latest"},
        ],
    )
    preview_sources = store.latest_session_context("main", limit_messages=5)
    store.write_cold_start_snapshot(
        session_id=target["id"],
        session_tag=target["session_tag"],
        reason="manual_preview:new_window",
        sources=preview_sources,
        trigger_last_active_at=target.get("last_active_at"),
        max_injections=5,
    )
    store.write_request_context_snapshot(
        session_id=newer["id"],
        session_tag=newer["session_tag"],
        client_name=newer["client_name"],
        latest_user_text="smoke latest",
        messages=[
            {"role": "user", "content": "smoke u1"},
            {"role": "assistant", "content": "smoke a1"},
        ],
    )

    snapshot = maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=True,
        current_message_count=1,
        cfg=cfg,
        store=store,
    )

    assert snapshot["reason"] == "manual_preview:new_window"
    assert snapshot["source_session_tags"] == ["main"]
    assert [msg["content"] for source in snapshot["sources"] for msg in source["messages"]] == [
        "main u1",
        "main a1",
        "main latest",
    ]


def test_pwa_history_ready_disables_cold_start_at_client_window(tmp_path):
    cfg = SimpleNamespace(max_client_messages=168, cold_start_message_limit=75)

    assert not pwa_history_ready_for_cold_start("shenyu-pwa", 167, cfg)
    assert pwa_history_ready_for_cold_start("shenyu-pwa", 168, cfg)
    assert pwa_history_ready_for_cold_start("pwa", 200, cfg)
    assert not pwa_history_ready_for_cold_start("operit", 200, cfg)


def test_new_session_automatically_uses_latest_context_source(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    source = store.get_or_create_session("7.11", "operit")
    target = store.get_or_create_session("7.12", "operit")
    cfg = SimpleNamespace(enable_cold_start=True, cold_start_message_limit=None, max_client_messages=5)
    store.write_request_context_snapshot(
        session_id=source["id"],
        session_tag=source["session_tag"],
        client_name=source["client_name"],
        latest_user_text="继续",
        messages=[
            {"role": "user", "content": "上一问"},
            {"role": "assistant", "content": "上一答"},
        ],
    )

    snapshot = maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=True,
        current_message_count=1,
        cfg=cfg,
        store=store,
    )

    assert snapshot["reason"] == "new_window"
    assert snapshot["source_session_tags"] == ["7.11"]


def test_existing_session_never_auto_cold_starts(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    source = store.get_or_create_session("7.11", "operit")
    target = store.get_or_create_session("7.12", "operit")
    cfg = SimpleNamespace(enable_cold_start=True, cold_start_message_limit=None, max_client_messages=5)
    store.write_request_context_snapshot(
        session_id=source["id"],
        session_tag=source["session_tag"],
        client_name=source["client_name"],
        latest_user_text="不应注入",
        messages=[{"role": "user", "content": "别的线程"}],
    )

    snapshot = maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=False,
        current_message_count=1,
        cfg=cfg,
        store=store,
    )

    assert snapshot is None


def test_cold_start_snapshot_stays_active_until_window_retires_bridge(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    target = store.get_or_create_session("7.12", "operit")
    snapshot = store.write_cold_start_snapshot(
        session_id=target["id"],
        session_tag=target["session_tag"],
        reason="manual_preview:new_window",
        sources=[{"session_tag": "7.11", "messages": [{"role": "user", "content": "接续"}]}],
        trigger_last_active_at=target.get("last_active_at"),
        max_injections=1,
    )

    store.mark_cold_start_injected(snapshot["id"])

    active = store.latest_active_cold_start_snapshot(target["id"])
    assert active is not None
    assert active["injected_count"] == 1

    store.complete_cold_start_snapshot(snapshot["id"])

    assert store.latest_active_cold_start_snapshot(target["id"]) is None


def test_active_cold_start_snapshot_survives_one_full_window(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    target = store.get_or_create_session("6.20", "operit")
    cfg = SimpleNamespace(
        enable_cold_start=True,
        cold_start_message_limit=5,
        max_client_messages=5,
        cold_start_idle_minutes=120,
    )
    store.write_cold_start_snapshot(
        session_id=target["id"],
        session_tag=target["session_tag"],
        reason="manual_preview:new_window",
        sources=[
            {
                "session_id": "source",
                "session_tag": "5.15",
                "client_name": "operit",
                "snapshot_at": "now",
                "latest_user_text": "source 4",
                "messages": [
                    {"role": "user", "content": f"source {index}"}
                    for index in range(5)
                ],
            }
        ],
        trigger_last_active_at=target.get("last_active_at"),
        max_injections=5,
    )

    full_window_snapshot = maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=False,
        current_message_count=5,
        cfg=cfg,
        store=store,
    )
    assert [msg["content"] for source in full_window_snapshot["sources"] for msg in source["messages"]] == [
        "source 0",
        "source 1",
        "source 2",
        "source 3",
        "source 4",
    ]
    assert store.latest_active_cold_start_snapshot(target["id"]) is not None

    snapshot = maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=False,
        current_message_count=2,
        cfg=cfg,
        store=store,
    )

    assert [msg["content"] for source in snapshot["sources"] for msg in source["messages"]] == [
        "source 0",
        "source 1",
        "source 2",
        "source 3",
        "source 4",
    ]


def test_active_cold_start_snapshot_survives_store_restart_after_old_max_count(tmp_path):
    db_path = tmp_path / "gateway.db"
    store = GatewayStore(str(db_path))
    target = store.get_or_create_session("6.20", "operit")
    snapshot = store.write_cold_start_snapshot(
        session_id=target["id"],
        session_tag=target["session_tag"],
        reason="manual_preview:new_window",
        sources=[
            {
                "session_id": "source",
                "session_tag": "5.15",
                "client_name": "operit",
                "snapshot_at": "now",
                "latest_user_text": "source",
                "messages": [{"role": "user", "content": "source"}],
            }
        ],
        trigger_last_active_at=target.get("last_active_at"),
        max_injections=5,
    )
    store.mark_cold_start_injected(snapshot["id"])

    reopened = GatewayStore(str(db_path))

    assert reopened.latest_active_cold_start_snapshot(target["id"]) is not None


def test_next_request_cold_start_binds_to_actual_session_header(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    pending = store.get_or_create_session(NEXT_REQUEST_COLD_START_TAG, "cold-start-next-request")
    source = store.get_or_create_session("5.15", "operit")
    target = store.get_or_create_session("6.20", "operit")
    cfg = SimpleNamespace(
        enable_cold_start=True,
        cold_start_message_limit=5,
        max_client_messages=5,
        cold_start_idle_minutes=120,
    )
    store.write_request_context_snapshot(
        session_id=source["id"],
        session_tag=source["session_tag"],
        client_name=source["client_name"],
        latest_user_text="source 5",
        messages=[
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"source {index}"}
            for index in range(6)
        ],
    )
    store.write_cold_start_snapshot(
        session_id=pending["id"],
        session_tag=pending["session_tag"],
        reason="manual_preview:next_request",
        sources=store.latest_session_context("5.15", limit_messages=5),
        trigger_last_active_at=pending.get("last_active_at"),
        max_injections=5,
    )

    snapshot = maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=True,
        current_message_count=2,
        cfg=cfg,
        store=store,
    )

    assert snapshot["session_tag"] == "6.20"
    assert snapshot["reason"] == "manual_preview:next_request"
    assert [msg["content"] for source in snapshot["sources"] for msg in source["messages"]] == [
        "source 3",
        "source 4",
        "source 5",
    ]
    assert store.latest_next_request_cold_start_snapshot() is None
    assert store.latest_active_cold_start_snapshot(target["id"]) is not None


def test_cold_start_preview_auto_source_uses_latest_old_thread_and_full_source_tail(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    target = store.get_or_create_session("default", "operit")
    older = store.get_or_create_session("5.15", "operit")

    store.write_request_context_snapshot(
        session_id=target["id"],
        session_tag=target["session_tag"],
        client_name=target["client_name"],
        latest_user_text="target latest",
        messages=[
            {"role": "user", "content": "target u1"},
            {"role": "assistant", "content": "target a1"},
        ],
    )
    source_messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"source {index}"}
        for index in range(70)
    ]
    store.write_request_context_snapshot(
        session_id=older["id"],
        session_tag=older["session_tag"],
        client_name=older["client_name"],
        latest_user_text="source 69",
        messages=source_messages,
    )

    app = FastAPI()
    cfg = SimpleNamespace(
        enable_cold_start=True,
        cold_start_message_limit=108,
        max_client_messages=108,
        cold_start_idle_minutes=120,
        gateway_message_retention=2000,
        gateway_context_snapshot_retention=3,
        gateway_cold_start_retention=20,
    )
    app.include_router(
        build_gateway_admin_router(
            GatewayAdminRouteDeps(
                cfg=cfg,
                get_supabase_client=lambda: None,
                get_session_store=lambda: store,
                require_session_store=lambda: store,
                context_builder=lambda *_args, **_kwargs: None,
                upstream_for_hisense=lambda _is_hisense: {
                    "scope": "default",
                    "chat_url": "",
                    "protocol": "openai",
                    "api_key": "",
                },
                prune_runtime_state=lambda **_kwargs: {},
                cold_start_idle_minutes=lambda _session: 0,
                is_hisense_session=lambda _session: False,
                now=lambda: None,
                request_logs=[],
            )
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/gateway/cold-start/preview",
            json={
                "target_session_tag": "default",
                "current_message_count": 50,
                "persist": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_mode"] == "auto_latest"
    assert payload["target_session_tag"] == "default"
    assert payload["source_session_tag"] == "5.15"
    assert payload["config"]["preview_fill_count"] == 58
    assert payload["config"]["current_message_count"] == 50
    assert payload["config"]["source_snapshot_limit"] == 108
    assert payload["snapshot"]["source_message_count"] == 70
    assert [source["session_tag"] for source in payload["sources"]] == ["5.15"]
    assert [msg["content"] for msg in payload["sources"][0]["messages"]][:2] == ["source 0", "source 1"]


def test_config_overrides_round_trip(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    assert store.load_config_overrides() == {}

    store.save_config_overrides({"WAKE_WELCOME_MESSAGE": "hello", "UPSTREAM_URL": "https://example.com"})
    result = store.load_config_overrides()
    assert result == {"WAKE_WELCOME_MESSAGE": "hello", "UPSTREAM_URL": "https://example.com"}

    store.save_config_overrides({"WAKE_WELCOME_MESSAGE": "updated"})
    result = store.load_config_overrides()
    assert result["WAKE_WELCOME_MESSAGE"] == "updated"
    assert result["UPSTREAM_URL"] == "https://example.com"


def test_context_window_state_round_trip(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("window-state", "operit")
    stored = store.upsert_context_window_state(
        session["id"],
        {
            "epoch_id": "epoch_1",
            "base_limit": 168,
            "overflow_messages": 32,
            "high_water": 200,
            "window_start_index": 12,
            "island_anchor_offset": 136,
            "raw_protected_turns": 18,
            "island_state": {"rendered_text": "island"},
            "last_event_class": "new_user",
            "reset_reason": "",
        },
    )

    assert stored["epoch_id"] == "epoch_1"
    restored = store.get_context_window_state(session["id"])
    assert restored["window_start_index"] == 12
    assert restored["island_anchor_offset"] == 136
    assert restored["island_state"] == {"rendered_text": "island"}

    store.log_context_window_event(
        session_id=session["id"],
        session_tag=session["session_tag"],
        event_class="new_user",
        epoch_id="epoch_1",
        detail={"client_non_system_retained": 170, "context_epoch_reset": False},
    )
    events = store.list_context_window_events(session_tag="window-state")
    assert len(events) == 1
    assert events[0]["event_class"] == "new_user"
    assert events[0]["detail"]["client_non_system_retained"] == 170


def test_runtime_prune_keeps_active_pending_tool_turns_and_removes_terminal_ones(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("pending-prune", "operit")

    active = store.create_pending_gateway_tool_turn(
        session_id=session["id"],
        session_tag=session["session_tag"],
        client_tool_call_ids=["call_active"],
        original_assistant_message={"role": "assistant", "tool_calls": []},
        gateway_tool_messages=[],
    )
    consumed = store.create_pending_gateway_tool_turn(
        session_id=session["id"],
        session_tag=session["session_tag"],
        client_tool_call_ids=["call_consumed"],
        original_assistant_message={"role": "assistant", "tool_calls": []},
        gateway_tool_messages=[],
    )
    expired = store.create_pending_gateway_tool_turn(
        session_id=session["id"],
        session_tag=session["session_tag"],
        client_tool_call_ids=["call_expired"],
        original_assistant_message={"role": "assistant", "tool_calls": []},
        gateway_tool_messages=[],
        ttl_minutes=-1,
    )
    store.mark_pending_gateway_tool_turns_consumed([consumed["id"]])

    deleted = store.prune_runtime_state(session_id=session["id"], message_retention=1)

    remaining_ids = {
        item["id"]
        for item in store.get_pending_gateway_tool_turns(session["id"])
    }
    assert deleted["pending_gateway_tool_turns"] == 2
    assert remaining_ids == {active["id"]}
    assert consumed["id"] not in remaining_ids
    assert expired["id"] not in remaining_ids
