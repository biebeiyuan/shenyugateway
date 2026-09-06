from __future__ import annotations

import pytest

from shenyu_gateway.system_prefix_buffer import (
    buffer_seconds_from_ttl,
    resolve_system_prefix,
)


# ── TTL 解析 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ttl,expected",
    [("1h", 3600), ("5m", 300), ("1H", 3600), (" 5m ", 300), ("", 0), ("banana", 0), (None, 0)],
)
def test_buffer_seconds_parses_the_two_allowed_ttls_and_fails_open_to_zero(ttl, expected):
    assert buffer_seconds_from_ttl(ttl) == expected


# ── 闸判定 ────────────────────────────────────────────────────────────────

_T0 = "2026-09-01T10:00:00+00:00"


def _state(slow: str, heartbeat: str, refreshed_at: str = _T0) -> dict:
    return {"slow_text": slow, "heartbeat_text": heartbeat, "refreshed_at": refreshed_at}


def test_first_request_lands_a_snapshot_with_no_previous_state():
    slow, hb, state, decision = resolve_system_prefix(
        None, "日历A", "心跳1", buffer_seconds=3600, epoch_reset=False, now=_T0
    )
    assert (slow, hb) == ("日历A", "心跳1")
    assert decision == {"decision": "refreshed", "reason": "first_snapshot"}
    assert state["refreshed_at"] == _T0


def test_unchanged_content_is_held_without_touching_the_timestamp():
    prev = _state("日历A", "心跳1")
    slow, hb, state, decision = resolve_system_prefix(
        prev, "日历A", "心跳1", buffer_seconds=3600, epoch_reset=False, now="2026-09-01T10:30:00+00:00"
    )
    assert (slow, hb) == ("日历A", "心跳1")
    assert decision["decision"] == "held" and decision["reason"] == "unchanged"
    assert state["refreshed_at"] == _T0  # 不动


def test_added_heartbeat_before_the_ttl_is_buffered_and_reuses_the_old_text():
    prev = _state("日历A", "心跳1")
    # 半小时后又攒了一条心跳，没到 1h。
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1\n心跳2",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T10:30:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1")  # 沿用旧的，新心跳先憋着
    assert decision["reason"] == "buffered"
    assert state["refreshed_at"] == _T0


def test_added_heartbeat_after_the_ttl_is_refreshed():
    prev = _state("日历A", "心跳1")
    # 一小时零一分后。
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1\n心跳2",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T11:01:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1\n心跳2")
    assert decision["reason"] == "ttl_elapsed"
    assert state["refreshed_at"] == "2026-09-01T11:01:00+00:00"


def test_an_epoch_reset_rides_along_and_refreshes_even_before_the_ttl():
    prev = _state("日历A", "心跳1")
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1\n心跳2",
        buffer_seconds=3600,
        epoch_reset=True,
        now="2026-09-01T10:05:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1\n心跳2")
    assert decision["reason"] == "epoch_rebuild"


def test_removing_content_before_the_ttl_is_also_buffered():
    # 心跳内容变少（比如上一批滚出了窗口）还没到点：和「加东西」一视同仁，先憋着。
    # 早先这里有条 content_removed 强刷分支，把整批替换误判成撤销、短路掉时间闸；
    # 已删除——撤下来的旧内容最多多留一个 buffer 窗口，换前缀一小时内不抖。
    prev = _state("日历A", "心跳1\n心跳2")
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T10:10:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1\n心跳2")  # 沿用旧的，不因变少而强刷
    assert decision["reason"] == "buffered"
    assert state["refreshed_at"] == _T0


def test_removed_content_still_surfaces_once_the_ttl_elapses():
    # 憋着的「变少」不是永久钉死：到点照常换成新文本，撤下来的旧内容随之消失。
    prev = _state("日历A\n日历B", "心跳1")
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T11:01:00+00:00",
    )
    assert slow == "日历A"
    assert decision["reason"] == "ttl_elapsed"
    assert state["refreshed_at"] == "2026-09-01T11:01:00+00:00"


def test_heartbeat_batch_rollover_is_buffered_not_treated_as_a_removal():
    # 心跳是整批替换的滑动窗口：上一批 digest（心跳1..3）满了之后，
    # 这一轮换成全新的一批（心跳4..6），旧行一条都不在新文本里。
    # 这不是「沈予撤掉了东西」，是窗口往前滚——没到点、没裁剪，就该憋着。
    prev = _state("日历A", "心跳1\n心跳2\n心跳3")
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳4\n心跳5\n心跳6",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T10:20:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1\n心跳2\n心跳3")  # 沿用旧的，新批次先憋着
    assert decision["reason"] == "buffered"
    assert state["refreshed_at"] == _T0  # 时间戳不动，继续按原起点计时


def test_buffer_disabled_when_seconds_is_zero_refreshes_every_time():
    prev = _state("日历A", "心跳1")
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1\n心跳2",
        buffer_seconds=0,
        epoch_reset=False,
        now="2026-09-01T10:01:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1\n心跳2")
    assert decision["reason"] == "buffer_disabled"


def test_a_broken_refreshed_at_is_treated_as_elapsed_rather_than_pinning_forever():
    prev = _state("日历A", "心跳1", refreshed_at="not-a-timestamp")
    slow, hb, state, decision = resolve_system_prefix(
        prev, "日历A", "心跳1\n心跳2", buffer_seconds=3600, epoch_reset=False, now=_T0
    )
    assert (slow, hb) == ("日历A", "心跳1\n心跳2")
    assert decision["reason"] == "ttl_elapsed"


# ── 端到端：憋着时系统前缀逐字节不变，断点能命中；换版时才变 ────────────────

from shenyu_gateway.context_layers import assemble_layered_messages


def _system_prefix(layers: dict) -> list[str]:
    """走真实装配，取出系统前缀那几条的文本——就是 system.end 断点覆盖的内容。"""
    messages, _ = assemble_layered_messages(
        [{"role": "user", "content": "在吗"}], layers
    )
    return [m["content"] for m in messages if m.get("role") == "system"]


def _layers(slow: str, heartbeat: str) -> dict:
    return {"stable": "charter", "slow": slow, "heartbeat": heartbeat, "mem": "", "island_bumps": ""}


def test_end_to_end_buffered_request_keeps_the_system_prefix_byte_identical():
    # 第一次：落一版。
    slow1, hb1, state1, _ = resolve_system_prefix(
        None, "日历A", "## 我之前的心跳\n心跳1", buffer_seconds=3600, epoch_reset=False, now=_T0
    )
    prefix1 = _system_prefix(_layers(slow1, hb1))

    # 半小时后攒了新心跳，没到点：憋着，系统前缀应逐字节不变。
    slow2, hb2, state2, decision2 = resolve_system_prefix(
        state1,
        "日历A",
        "## 我之前的心跳\n心跳1\n心跳2",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T10:30:00+00:00",
    )
    prefix2 = _system_prefix(_layers(slow2, hb2))
    assert decision2["reason"] == "buffered"
    assert prefix2 == prefix1  # 断点能命中的前提

    # 过了一小时：换版，系统前缀这时才变。
    slow3, hb3, state3, decision3 = resolve_system_prefix(
        state2,
        "日历A",
        "## 我之前的心跳\n心跳1\n心跳2",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T11:31:00+00:00",
    )
    prefix3 = _system_prefix(_layers(slow3, hb3))
    assert decision3["reason"] == "ttl_elapsed"
    assert prefix3 != prefix1
    assert "心跳2" in "\n".join(prefix3)


def test_end_to_end_state_survives_a_store_round_trip(tmp_path):
    from shenyu_gateway.store import GatewayStore

    store = GatewayStore(str(tmp_path / "g.db"))
    sid = store.get_or_create_session(session_tag="buf", client_name="pwa")["id"]

    _, _, state1, _ = resolve_system_prefix(
        None, "日历A", "心跳1", buffer_seconds=3600, epoch_reset=False, now=_T0
    )
    store.upsert_context_window_state(sid, {"epoch_id": "e1", "system_prefix_state": state1})

    reloaded = store.get_context_window_state(sid)["system_prefix_state"]
    # 从库里读回旧快照后，加了新心跳仍在缓冲期内 → 沿用旧文本。
    slow, hb, _, decision = resolve_system_prefix(
        reloaded,
        "日历A",
        "心跳1\n心跳2",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T10:20:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1")
    assert decision["reason"] == "buffered"


def test_store_window_handoff_reaches_the_buffer_gate_as_held(tmp_path):
    from shenyu_gateway.context_window import select_chunked_window
    from shenyu_gateway.store import GatewayStore

    store = GatewayStore(str(tmp_path / "g.db"))
    sid = store.get_or_create_session(session_tag="seam", client_name="pwa")["id"]
    _, first_state, _ = select_chunked_window(
        [{"role": "user", "content": "one"}],
        limit=168,
        previous_state=None,
        event_class="initial",
    )
    _, _, prefix_state, _ = resolve_system_prefix(
        None, "日历A", "心跳1", buffer_seconds=3600, epoch_reset=False, now=_T0
    )
    first_state["system_prefix_state"] = prefix_state
    store.upsert_context_window_state(sid, first_state)

    previous = store.get_context_window_state(sid)
    _, next_state, _ = select_chunked_window(
        [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}],
        limit=168,
        previous_state=previous,
        event_class="new_user",
    )
    _, _, _, decision = resolve_system_prefix(
        next_state.get("system_prefix_state"),
        "日历A",
        "心跳1\n心跳2",
        buffer_seconds=3600,
        epoch_reset=bool(next_state.get("epoch_reset")),
        now="2026-09-01T10:20:00+00:00",
    )
    assert decision == {"decision": "held", "reason": "buffered"}


@pytest.mark.parametrize("protocol,ttl_seconds", [("anthropic", 3600), ("openai", 300)])
@pytest.mark.parametrize("release", ["ttl", "trim"])
def test_prepare_rounds_hold_then_consume_two_heartbeat_batches_in_order(
    tmp_path, monkeypatch, protocol, ttl_seconds, release
):
    import asyncio
    import json
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from starlette.requests import Request
    from shenyu_gateway import prepare_messages as preparation
    from shenyu_gateway import system_prefix_buffer
    from shenyu_gateway.private_capture import mark_context_consumed
    from shenyu_gateway.schemas import ChatRequest
    from shenyu_gateway.store import GatewayStore
    from tests.test_gateway_context import _context_builder, cfg as builder_cfg

    store = GatewayStore(str(tmp_path / "pipeline.db"))
    builder = _context_builder(store)
    monkeypatch.setattr(builder_cfg, "heartbeat_inject_every", 2)
    # Keep the real heartbeat picker, renderer, window/store and consumer;
    # calendar and memory retrieval are external inputs to this test.
    slow = ["calendar before"]

    async def package(session, **kwargs):
        heartbeat, ids = builder._normal_heartbeat_context(session["id"])
        return {"stable_charter": "charter", "heartbeat_digest": heartbeat,
                "heartbeat_pending_ids": ids, "calendar_context": {}}

    original_render = builder.render_layered_additions

    def render(package, **kwargs):
        layers = original_render(package, **kwargs)
        layers["slow"] = slow[0]
        return layers

    monkeypatch.setattr(builder, "build_context_package", package)
    monkeypatch.setattr(builder, "render_layered_additions", render)
    monkeypatch.setattr(preparation._mcp_registry, "ensure_fresh", AsyncMock())
    config = SimpleNamespace(
        max_client_messages=4, epoch_reset_on_cold_cache=False,
        enable_room_mode=False, client_tool_surface="none",
        anthropic_cache_ttl="1h", openai_cache_ttl="5m",
    )
    deps = preparation.PrepareMessagesDeps(
        cfg=config, store=store, supabase_client=None,
        context_builder_factory=lambda *args: builder,
        client_name_from_request=lambda request: "operit",
        session_tag_from_request=lambda *args, **kwargs: "pipeline",
        resolve_upstream=lambda: {"protocol": protocol},
        maybe_prepare_cold_start_snapshot=lambda *args: None,
        prune_runtime_state=lambda *args: {},
    )
    moment = [datetime.fromisoformat(_T0)]
    monkeypatch.setattr(system_prefix_buffer, "iso_now", lambda: moment[0].isoformat())
    history = [{"role": "user", "content": "start"}]

    def turn():
        request = Request({"type": "http", "headers": []})
        messages, meta = asyncio.run(preparation.prepare_messages(
            request, ChatRequest(model="test", messages=history), deps
        ))
        with store._connect() as conn:
            row = conn.execute(
                "SELECT detail_json FROM context_window_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        decision = json.loads(row[0])["system_prefix_decision"]
        mark_context_consumed(meta, store=store)
        return messages, meta, decision

    first_messages, first, decision = turn()
    assert decision["reason"] == "first_snapshot"
    sid = first["session"]["id"]
    ids = [store.append_heartbeat(sid, f"batch heartbeat {i}")["id"] for i in range(4)]
    slow[0] = "calendar after"
    history.extend([{"role": "assistant", "content": "answer"}, {"role": "user", "content": "next"}])
    moment[0] += timedelta(seconds=1)
    held_messages, held, decision = turn()
    assert decision == {"decision": "held", "reason": "buffered"}
    assert held["package"]["heartbeat_pending_ids"] == []
    assert [m for m in held_messages if m["role"] == "system"] == [m for m in first_messages if m["role"] == "system"]
    assert [hb["id"] for hb in store.get_pending_heartbeats()] == ids
    assert store.get_latest_heartbeat_digest() == ""

    def advance():
        if release == "ttl":
            moment[0] += timedelta(seconds=ttl_seconds)
        else:
            # Real high-water trim, keeping complete user/answer pairs.
            for i in range(14):
                history.extend([
                    {"role": "assistant", "content": f"answer {len(history)}"},
                    {"role": "user", "content": f"question {len(history)}"},
                ])

    for batch in range(2):
        advance()
        _, applied, decision = turn()
        assert decision["reason"] == ("ttl_elapsed" if release == "ttl" else "epoch_rebuild")
        assert applied["package"]["heartbeat_pending_ids"] == ids[batch * 2 : batch * 2 + 2]
        text = applied["cache_layers"]["heartbeat"]
        assert text.index(f"batch heartbeat {batch * 2}") < text.index(f"batch heartbeat {batch * 2 + 1}")
        assert applied["cache_layers"]["slow"] == "calendar after"
        assert [hb["id"] for hb in store.get_pending_heartbeats()] == ids[batch * 2 + 2 :]
        if batch == 0:
            _, held, decision = turn()
            assert decision == {"decision": "held", "reason": "buffered"}
            assert held["package"]["heartbeat_pending_ids"] == []
            assert [hb["id"] for hb in store.get_pending_heartbeats()] == ids[2:]
