from __future__ import annotations

import json
import sqlite3

import pytest

from shenyu_gateway import context_layers
from shenyu_gateway.context_window import MEMORY_ISLAND_BUMP_KEY, MEMORY_ISLAND_LAYER
from shenyu_gateway.island_bumps import (
    BUMP_HEADING,
    bump_lines_from_tool_rows,
    render_island_bumps,
)
from shenyu_gateway.runtime import local_waking_day, local_waking_day_start
from shenyu_gateway.upstream_adapter import (
    _openai_to_anthropic,
    _sanitize_openai_compatible_messages,
)


def _tool_row(tool_name: str, result: dict) -> dict:
    return {"role": "tool", "tool_name": tool_name, "content": json.dumps(result, ensure_ascii=False)}


def _star_row(content: str = "她说想养一只橘猫", chord: str = "Cmaj7") -> dict:
    return _tool_row(
        "shenyu_create_star",
        {"ok": True, "star_id": "st-1", "star": {"content": content, "chord": chord}},
    )


# ── the waking day rolls over at 02:00, not midnight ──────────────────────


@pytest.mark.parametrize(
    "moment,expected",
    [
        ("2026-08-29T17:30:00+00:00", "2026-08-29"),  # 01:30 local — still last night
        ("2026-08-29T17:59:59+00:00", "2026-08-29"),  # 01:59 local — still last night
        ("2026-08-29T18:00:00+00:00", "2026-08-30"),  # 02:00 local — new day opens
        ("2026-08-29T04:00:00+00:00", "2026-08-29"),  # noon local
    ],
)
def test_waking_day_treats_the_small_hours_as_the_previous_day(moment, expected):
    assert local_waking_day(moment).isoformat() == expected


def test_waking_day_start_is_returned_in_utc_so_text_comparison_is_valid():
    # Stored timestamps come from iso_now() (UTC). A +08:00 boundary would sort
    # wrong against them lexically, which is how this silently picks a bad window.
    boundary = local_waking_day_start("2026-08-29T17:30:00+00:00")
    assert boundary.isoformat() == "2026-08-28T18:00:00+00:00"
    assert boundary.isoformat() < "2026-08-29T17:30:00+00:00"


# ── which writes become a bump line ───────────────────────────────────────


def test_star_bump_reuses_the_chord_and_body_wording_from_the_island():
    lines = bump_lines_from_tool_rows([_star_row()])
    assert lines == ["星星 Cmaj7 · 她说想养一只橘猫"]


def test_mem_note_bump_prefers_the_one_line_summary_and_names_its_reminder_day():
    row = _tool_row(
        "shenyu_write_mem_note",
        {
            "ok": True,
            "note": {
                "summary": "周五帮她看简历",
                "content": "她说周五要投简历，让我帮她看一遍",
                "mem_type": "承诺",
                "remind_on": "2026-09-04",
            },
        },
    )
    assert bump_lines_from_tool_rows([row]) == ["便签 承诺：周五帮她看简历（记的是 2026-09-04）"]


def test_mem_note_bump_says_when_the_write_was_absorbed_by_the_daily_dedupe():
    # create_note returns ok with duplicate_of when a same-day twin exists and
    # nothing was written. Staying silent would read as a fresh note.
    row = _tool_row(
        "shenyu_write_mem_note",
        {
            "ok": True,
            "note_id": "mn-1",
            "duplicate_of": "mn-1",
            "note": {"summary": "周五帮她看简历", "mem_type": "承诺"},
        },
    )
    assert bump_lines_from_tool_rows([row]) == [
        "便签 承诺：周五帮她看简历（本来就有一张，没有重复写）"
    ]


@pytest.mark.parametrize(
    "mode,word",
    [("new", "新建"), ("append", "续写"), ("replace", "覆盖")],
)
def test_calendar_bump_states_whether_the_page_was_new_appended_or_overwritten(mode, word):
    row = _tool_row(
        "shenyu_add_calendar",
        {"ok": True, "period_key": "2026-08-29", "mode": mode, "digest": "今天她提到换工作的事"},
    )
    assert bump_lines_from_tool_rows([row]) == [f"日历 2026-08-29 {word}：今天她提到换工作的事"]


def _orchard_row(action: str, fruit: dict, *, broker: bool = False) -> dict:
    row = _tool_row("shenyu_orchard", {"ok": True, "data": {"fruit": fruit, "garden": "平常天气"}})
    # full 模式 action 在顶层；broker 模式（默认）真参数裹在 params 里。
    if broker:
        row["tool_args_json"] = json.dumps(
            {"tool": "shenyu_orchard", "params": {"action": action, "name": fruit.get("name")}},
            ensure_ascii=False,
        )
    else:
        row["tool_args_json"] = json.dumps({"action": action, "name": fruit.get("name")}, ensure_ascii=False)
    return row


def test_planting_a_fruit_becomes_a_one_line_bump_in_the_orchard_s_own_voice():
    row = _orchard_row("plant", {"name": "蒜冒尖", "due_on": None})
    assert bump_lines_from_tool_rows([row]) == ["盼圃 种下：蒜冒尖"]


def test_a_planted_fruit_with_a_due_day_names_that_day():
    row = _orchard_row("plant", {"name": "9月1号抽血", "due_on": "2026-09-01"})
    assert bump_lines_from_tool_rows([row]) == ["盼圃 种下：9月1号抽血（预计 2026-09-01）"]


def test_plant_is_read_from_the_broker_nested_params_not_just_the_top_level():
    # Broker mode is the default: the real action rides inside params, so reading
    # only the top level would never see a plant.
    row = _orchard_row("plant", {"name": "蒜冒尖", "due_on": None}, broker=True)
    assert bump_lines_from_tool_rows([row]) == ["盼圃 种下：蒜冒尖"]


@pytest.mark.parametrize("action", ["note", "pick", "look"])
def test_only_planting_bumps_the_other_orchard_actions_stay_on_the_wall(action):
    # note: 一天本来就想贴好几张；pick: 条件更新挡着摘不了第二次；look: 读操作。
    row = _orchard_row(action, {"name": "蒜冒尖", "due_on": None})
    assert bump_lines_from_tool_rows([row]) == []


def test_failed_writes_never_become_a_bump():
    row = _tool_row("shenyu_create_star", {"ok": False, "error": "Supabase is not configured."})
    assert bump_lines_from_tool_rows([row]) == []


def test_read_only_and_bookkeeping_tools_stay_out_of_the_bumps():
    rows = [
        _tool_row("shenyu_search_stars", {"ok": True, "items": [{"content": "x"}]}),
        _tool_row("shenyu_star_feedback", {"ok": True, "count": 1}),
        _tool_row("shenyu_delete_mem_note", {"ok": True, "deleted": {"content": "别复述这个"}}),
        _tool_row("supabase_insert", {"ok": True, "table": "whatever", "row": {"id": 1}}),
        _tool_row("room_locked_drawer", {"ok": True, "note": "锁好了。"}),
    ]
    assert bump_lines_from_tool_rows(rows) == []


def test_a_tool_row_whose_json_will_not_parse_is_skipped_not_guessed_at():
    rows = [{"role": "tool", "tool_name": "shenyu_create_star", "content": "{broken"}, _star_row()]
    assert bump_lines_from_tool_rows(rows) == ["星星 Cmaj7 · 她说想养一只橘猫"]


def test_the_store_reader_returns_only_this_session_s_tool_rows_since_the_boundary(tmp_path):
    from shenyu_gateway.store import GatewayStore

    store = GatewayStore(str(tmp_path / "gateway.db"))
    mine = store.get_or_create_session(session_tag="mine", client_name="pwa")["id"]
    theirs = store.get_or_create_session(session_tag="theirs", client_name="pwa")["id"]

    def add(session_id: str, role: str, created_at: str, tool_name: str = "") -> None:
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO gateway_messages (id, session_id, role, content, tool_name, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (f"gm-{role}-{created_at}-{session_id[:4]}", session_id, role, "{}", tool_name, created_at),
            )

    add(mine, "tool", "2026-08-28T17:00:00+00:00", "shenyu_create_star")  # before boundary
    add(mine, "tool", "2026-08-28T19:00:00+00:00", "shenyu_create_star")  # after
    add(mine, "user", "2026-08-28T20:00:00+00:00")  # not a tool row
    add(mine, "tool", "2026-08-28T21:00:00+00:00", "shenyu_add_calendar")
    add(theirs, "tool", "2026-08-28T22:00:00+00:00", "shenyu_create_star")  # other session

    rows = store.get_tool_messages_since(mine, "2026-08-28T18:00:00+00:00")

    assert [row["tool_name"] for row in rows] == ["shenyu_create_star", "shenyu_add_calendar"]
    assert [row["created_at"] for row in rows] == sorted(row["created_at"] for row in rows)


def test_broker_mode_records_the_real_action_name_on_the_tool_row():
    from shenyu_gateway.tool_loop import _logged_tool_name

    # Broker mode is the default, so storing the wire name verbatim recorded
    # "shenyu_gateway_tool" for every write and made them indistinguishable.
    assert _logged_tool_name("shenyu_gateway_tool", {"tool": "shenyu_create_star"}) == "shenyu_create_star"
    assert _logged_tool_name("shenyu_gateway_tool", {"action": "shenyu_add_calendar"}) == "shenyu_add_calendar"
    assert _logged_tool_name("shenyu_create_star", {}) == "shenyu_create_star"
    # Unresolvable broker args fall back to the wire name rather than an empty one.
    assert _logged_tool_name("shenyu_gateway_tool", {}) == "shenyu_gateway_tool"


def test_a_replayed_duplicate_call_does_not_produce_a_second_line():
    # tool_loop replays a cached result for a repeated call in the same round;
    # nothing was written the second time.
    cached = _tool_row(
        "shenyu_create_star",
        {
            "ok": True,
            "cached_duplicate": True,
            "result": {"ok": True, "star": {"content": "她说想养一只橘猫", "chord": "Cmaj7"}},
        },
    )
    assert bump_lines_from_tool_rows([_star_row(), cached]) == ["星星 Cmaj7 · 她说想养一只橘猫"]


def test_the_limit_keeps_the_most_recent_writes():
    rows = [_star_row(content=f"第 {index} 件事") for index in range(6)]
    lines = bump_lines_from_tool_rows(rows, limit=2)
    assert lines == ["星星 Cmaj7 · 第 4 件事", "星星 Cmaj7 · 第 5 件事"]


@pytest.fixture
def logged_star_write(tmp_path):
    """A store holding one session that already landed a star this waking day."""
    from shenyu_gateway.store import GatewayStore

    store = GatewayStore(str(tmp_path / "gateway.db"))
    session_id = store.get_or_create_session(session_tag="bumps", client_name="pwa")["id"]
    store.append_message(
        session_id=session_id,
        role="tool",
        content=json.dumps(
            {"ok": True, "star": {"content": "她说想养一只橘猫", "chord": "Cmaj7"}},
            ensure_ascii=False,
        ),
        tool_name="shenyu_create_star",
    )
    return store, session_id


def test_the_builder_reads_today_s_writes_back_out_of_the_message_log(logged_star_write):
    from tests.test_gateway_context import _context_builder

    store, session_id = logged_star_write

    assert _context_builder(store)._island_bump_lines(session_id) == [
        "星星 Cmaj7 · 她说想养一只橘猫"
    ]


def test_turning_the_bumps_off_stops_the_read_entirely(logged_star_write, monkeypatch):
    from tests.test_gateway_context import _context_builder, cfg

    store, session_id = logged_star_write
    monkeypatch.setattr(cfg, "inject_island_bumps", False, raising=False)

    assert _context_builder(store)._island_bump_lines(session_id) == []


def test_a_broken_message_log_costs_the_bumps_and_nothing_else(tmp_path):
    from tests.test_gateway_context import _context_builder

    class _AngryStore:
        def get_tool_messages_since(self, *args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

    # Fail-soft matches the other lanes: one source going down must not take the
    # whole context package with it.
    assert _context_builder(_AngryStore())._island_bump_lines("s-1") == []


def test_rendering_nothing_yields_no_heading():
    assert render_island_bumps([]) == ""


def test_rendered_bumps_carry_the_heading_the_resident_named():
    assert render_island_bumps(["星星 Cmaj7 · 她说想养一只橘猫"]) == (
        f"{BUMP_HEADING}\n- 星星 Cmaj7 · 她说想养一只橘猫"
    )


# ── the island text must not move when a bump appears ─────────────────────

_LAYERS = {
    "stable": "stable charter",
    "mem": "# 我之前落下的星星\n- Am7 · 旧的那颗",
    "island_bumps": f"{BUMP_HEADING}\n- 星星 Cmaj7 · 她说想养一只橘猫",
}
_HISTORY = [
    {"role": "user", "content": "早"},
    {"role": "assistant", "content": "早呀"},
    {"role": "user", "content": "在吗"},
]


def _assemble(layers: dict) -> list[dict]:
    messages, _ = context_layers.assemble_layered_messages(
        [dict(message) for message in _HISTORY],
        layers,
        memory_island_anchor_offset=0,
    )
    return messages


def test_a_bump_rides_on_the_island_message_without_touching_its_content():
    with_bump = _assemble(_LAYERS)
    without = _assemble({**_LAYERS, "island_bumps": ""})
    island = next(msg for msg in with_bump if msg.get(MEMORY_ISLAND_BUMP_KEY))
    plain = next(msg for msg in without if msg.get("content") == _LAYERS["mem"])
    # Byte-identical island content is the whole point: it is the cache prefix
    # anchor, and memory_island hashes exactly this text to decide its version.
    assert island["content"] == plain["content"] == _LAYERS["mem"]
    assert island[MEMORY_ISLAND_BUMP_KEY] == _LAYERS["island_bumps"]


def test_the_bump_follows_the_island_anchor_rather_than_a_position_of_its_own():
    messages, meta = context_layers.assemble_layered_messages(
        [dict(message) for message in _HISTORY],
        _LAYERS,
        memory_island_anchor_offset=2,
    )
    island_idx = next(
        idx for idx, msg in enumerate(messages) if msg.get(MEMORY_ISLAND_BUMP_KEY)
    )
    assert island_idx == meta["memory_island_insert_index"]
    assert messages[island_idx].get("_shenyu_context_layer") == MEMORY_ISLAND_LAYER


def test_openai_path_emits_the_bump_as_its_own_message_after_the_island():
    sanitized = _sanitize_openai_compatible_messages(_assemble(_LAYERS))
    contents = [msg.get("content") for msg in sanitized]
    island_idx = contents.index(_LAYERS["mem"])
    assert contents[island_idx + 1] == _LAYERS["island_bumps"]
    assert MEMORY_ISLAND_BUMP_KEY not in sanitized[island_idx]


def test_anthropic_path_puts_the_bump_after_the_cached_island_block():
    _, messages = _openai_to_anthropic(_assemble(_LAYERS), cache_layers=_LAYERS)
    island = next(
        msg
        for msg in messages
        if isinstance(msg.get("content"), list)
        and any(
            isinstance(block, dict) and "memory_island" in str(block.get("text", ""))
            for block in msg["content"]
        )
    )
    blocks = island["content"]
    assert len(blocks) == 2
    # The breakpoint sits on the island block; the bump trails it, so a changed
    # bump cannot invalidate the island's own cache read.
    assert blocks[0].get("cache_control")
    assert not blocks[1].get("cache_control")
    assert blocks[1]["text"] == _LAYERS["island_bumps"]


def test_the_island_block_text_is_unchanged_by_the_presence_of_a_bump():
    _, with_bump = _openai_to_anthropic(_assemble(_LAYERS), cache_layers=_LAYERS)
    plain_layers = {**_LAYERS, "island_bumps": ""}
    _, without = _openai_to_anthropic(_assemble(plain_layers), cache_layers=plain_layers)

    def island_text(messages: list[dict]) -> str:
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list) and content and isinstance(content[0], dict):
                text = str(content[0].get("text", ""))
                if "memory_island" in text:
                    return text
        raise AssertionError("no island block")

    assert island_text(with_bump) == island_text(without)


def test_recall_bump_keeps_first_sentence_and_deduplicates_sources():
    rows = [
        {"tool_name": "shenyu_recall", "tool_args_json": '{"query":"水獭"}', "content": '{"ok":true,"items":[{"source_type":"journal","source_id":"j1","content":"第一句。第二句和内部元数据不进来。"},{"source_type":"journal","source_id":"j2","content":"另一条记忆！更多。"}]}'},
        {"tool_name": "shenyu_recall", "tool_args_json": '{"query":"长隆"}', "content": '{"ok":true,"items":[{"source_type":"journal","source_id":"j1","content":"第一句。第二句。"}]}'},
    ]
    assert bump_lines_from_tool_rows(rows) == [
        "想起 水獭、长隆：第一句。",
        "想起 水獭：另一条记忆！",
    ]


def test_recall_bump_ignores_empty_or_failed_results():
    rows = [
        {"tool_name": "shenyu_recall", "tool_args_json": '{"query":"无"}', "content": '{"ok":true,"items":[]}'},
        {"tool_name": "shenyu_recall", "tool_args_json": '{"query":"错"}', "content": '{"ok":false,"items":[{"source_type":"journal","source_id":"j1","content":"不应出现"}]}'},
    ]
    assert bump_lines_from_tool_rows(rows) == []
