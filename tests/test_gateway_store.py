from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shenyu_gateway.context_snapshots import write_completion_context_snapshot
from shenyu_gateway.gateway_admin_routes import GatewayAdminRouteDeps, build_gateway_admin_router
from shenyu_gateway.prepare_messages import maybe_prepare_cold_start_snapshot
from shenyu_gateway.store import GatewayStore, NEXT_REQUEST_COLD_START_TAG


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

    assert maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=False,
        current_message_count=5,
        cfg=cfg,
        store=store,
    ) is None
    assert store.latest_active_cold_start_snapshot(target["id"]) is not None

    snapshot = maybe_prepare_cold_start_snapshot(
        target,
        is_first_turn=False,
        current_message_count=2,
        cfg=cfg,
        store=store,
    )

    assert [msg["content"] for source in snapshot["sources"] for msg in source["messages"]] == [
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
        max_injections=1,
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
