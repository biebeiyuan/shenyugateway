from __future__ import annotations

from types import SimpleNamespace

from shenyu_gateway.prepare_messages import maybe_prepare_cold_start_snapshot
from shenyu_gateway.store import GatewayStore


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
