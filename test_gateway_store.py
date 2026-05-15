from __future__ import annotations

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
