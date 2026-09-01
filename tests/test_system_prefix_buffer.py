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


def test_deleting_an_injected_heartbeat_refreshes_immediately_despite_the_buffer():
    prev = _state("日历A", "心跳1\n心跳2")
    # 删掉了心跳2，还没到 1h——撤东西不能憋。
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T10:10:00+00:00",
    )
    assert (slow, hb) == ("日历A", "心跳1")
    assert decision["reason"] == "content_removed"
    assert state["refreshed_at"] == "2026-09-01T10:10:00+00:00"


def test_clearing_a_calendar_page_also_forces_a_refresh():
    prev = _state("日历A\n日历B", "心跳1")
    slow, hb, state, decision = resolve_system_prefix(
        prev,
        "日历A",
        "心跳1",
        buffer_seconds=3600,
        epoch_reset=False,
        now="2026-09-01T10:10:00+00:00",
    )
    assert slow == "日历A"
    assert decision["reason"] == "content_removed"


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
