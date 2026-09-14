"""记忆热度：写事件、读活性、把活性变成排序修正项。

这个文件的上一版是反面教材，留在这里当尺子。它八条全绿，测的是：
`HEAT_INCREMENT` 在 0.05–0.20 之间（测一个常量的字面量）、`_score` 的源码里
出现了字符串 `"0.15"`（`inspect.getsource` + `in`）、衰减脚本文件存在且内容里
有 `RETENTION_RATE`（`Path.exists` + 字符串包含）。全部为真，而底下那套东西
写的是另一个数据库、`turn_index` 恒为 0、读路径的 select 里根本没有那一列，
迁移在 Postgres 和 SQLite 上都跑不起来。断言源码里有某个字符串，只能证明
有人打过那些字；这一版每条都让值真的流过一遍。
"""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from shenyu_gateway.memory_heat import (
    ACTIVATION_MOD_MAX,
    HEAT_EVENTS_TABLE,
    MEM_NOTE_ACTIVATION_VIEW,
    STAR_ACTIVATION_VIEW,
    activation_modifier,
    fetch_mem_note_activations,
    fetch_star_activations,
    record_island_entry,
)

from .fake_postgrest import project_select


class FakeSupabase:
    """记下写进来的行，按视图名回答活性查询。"""

    def __init__(self, activations: dict[str, dict[str, float]] | None = None):
        self.activations = activations or {}
        self.upserts: list[dict] = []
        self.queries: list[dict] = []

    async def query(self, table: str, params: dict):
        self.queries.append({"table": table, "params": dict(params)})
        id_column = "star_id" if table == STAR_ACTIVATION_VIEW else "mem_note_id"
        # 新实现：不按 id 过滤，直接返回全部（视图有 having count > 0）
        id_filter = params.get(id_column)
        if id_filter:
            wanted = {
                item.strip()
                for item in str(id_filter).removeprefix("in.").strip("()").split(",")
                if item.strip()
            }
            rows = [
                {id_column: key, "activation": value}
                for key, value in (self.activations.get(table) or {}).items()
                if key in wanted
            ]
        else:
            # 没有 id 过滤时，返回所有（模拟新的 limit 2000 逻辑）
            rows = [
                {id_column: key, "activation": value}
                for key, value in (self.activations.get(table) or {}).items()
            ]
        return project_select(rows, params)

    async def upsert_minimal(self, table: str, data, on_conflict=None):
        self.upserts.append({"table": table, "rows": list(data), "on_conflict": on_conflict})


class AngrySupabase(FakeSupabase):
    async def query(self, table: str, params: dict):
        raise RuntimeError("view is gone")

    async def upsert_minimal(self, table: str, data, on_conflict=None):
        raise RuntimeError("insert failed")


# ── 修正项的形状 ────────────────────────────────────────────────────────


def test_no_heat_means_no_modifier_not_a_penalty():
    # 活性 0 必须正好是 1.0：一颗从没进过岛的星星不该因为"冷"被扣分，
    # 否则第一次被想起的门槛就比第二次高。
    assert activation_modifier(0.0, 0.15) == 1.0
    assert activation_modifier(None, 0.15) == 1.0
    assert activation_modifier("", 0.15) == 1.0


def test_modifier_is_logarithmic_in_activation():
    # `1 + w·ln(1+a)`。取对数是"车辙"和"地形"的分界：线性会让常想起的一路加速。
    assert activation_modifier(1.0, 0.15) == pytest.approx(1.0 + 0.15 * math.log(2.0))
    assert activation_modifier(3.0, 0.15) == pytest.approx(1.0 + 0.15 * math.log(4.0))

    # 同样多的"又被想起一次"，在已经很热的地方推得更少：0→1 推的比 3→4 多。
    gain_cold = activation_modifier(1.0, 0.15) - activation_modifier(0.0, 0.15)
    gain_hot = activation_modifier(4.0, 0.15) - activation_modifier(3.0, 0.15)
    assert gain_hot < gain_cold, "增量必须递减，否则热度会自我强化"


def test_modifier_is_capped_so_heat_cannot_outrank_a_semantic_hit():
    # 视图给的活性没有上界：每天进岛 20 次的稳态是 0.547*20 ≈ 11。
    # 封顶前 `1 + 0.15*11` 是 2.6 倍，够把便签分数顶出 0–1 值域。
    assert activation_modifier(11.0, 1.0) == ACTIVATION_MOD_MAX
    assert activation_modifier(10**9, 0.15) == ACTIVATION_MOD_MAX
    assert ACTIVATION_MOD_MAX <= 1.3, "上界不该超过恒星加成"


def test_zero_weight_turns_the_whole_thing_off():
    # 权重是配置项，调到 0 必须真的等于关掉，而不是"几乎没影响"。
    assert activation_modifier(50.0, 0.0) == 1.0
    assert activation_modifier(50.0, -1.0) == 1.0


def test_garbage_activation_does_not_raise():
    assert activation_modifier("蓝", 0.15) == 1.0
    assert activation_modifier(5.0, "蓝") == 1.0


# ── 读活性 ──────────────────────────────────────────────────────────────


def test_fetch_star_activations_reads_the_view_and_returns_a_map():
    supabase = FakeSupabase({STAR_ACTIVATION_VIEW: {"star-a": 2.5, "star-b": 0.82}})

    result = asyncio.run(fetch_star_activations(supabase, ["star-a", "star-b", "star-cold"]))

    assert result == {"star-a": 2.5, "star-b": 0.82}
    # 没有事件的星星不出现在视图里（`having count(*) > 0`），落到调用方就是
    # "取不到 = 0 = 不修正"，不是 KeyError。
    assert activation_modifier(result.get("star-cold"), 0.15) == 1.0
    params = supabase.queries[0]["params"]
    assert supabase.queries[0]["table"] == STAR_ACTIVATION_VIEW
    assert params["select"] == "star_id,activation"
    # 新实现：不按 id 过滤，直接拉整个视图，在 Python 里过滤
    assert params["limit"] == "2000"


def test_fetch_mem_note_activations_reads_the_other_view():
    supabase = FakeSupabase({MEM_NOTE_ACTIVATION_VIEW: {"mem-a": 1.0}})

    result = asyncio.run(fetch_mem_note_activations(supabase, ["mem-a"]))

    assert result == {"mem-a": 1.0}
    assert supabase.queries[0]["table"] == MEM_NOTE_ACTIVATION_VIEW
    assert supabase.queries[0]["params"]["select"] == "mem_note_id,activation"


def test_fetch_activations_asks_for_nothing_when_there_are_no_ids():
    supabase = FakeSupabase()

    assert asyncio.run(fetch_star_activations(supabase, [])) == {}
    assert asyncio.run(fetch_star_activations(supabase, ["", None, "  "])) == {}
    assert asyncio.run(fetch_star_activations(None, ["star-a"])) == {}
    assert supabase.queries == []


def test_a_missing_view_costs_the_terrain_and_nothing_else(caplog):
    # 视图没建、权限没开、Supabase 抽风：这一轮按无热度排，语义排序照常。
    # 但必须留下日志——上一版就是死在静默失败上。
    with caplog.at_level("WARNING"):
        assert asyncio.run(fetch_star_activations(AngrySupabase(), ["star-a"])) == {}
    assert "MemoryHeat" in caplog.text


# ── 写事件 ──────────────────────────────────────────────────────────────


def test_island_entry_writes_one_row_per_memory_with_a_stable_event_id():
    supabase = FakeSupabase()

    written = asyncio.run(
        record_island_entry(
            supabase,
            session_id="sess-1",
            turn_index=7,
            star_ids=["star-a", "star-b"],
            mem_note_ids=["mem-a"],
        )
    )

    assert written == 3
    call = supabase.upserts[0]
    assert call["table"] == HEAT_EVENTS_TABLE
    # 幂等靠唯一键 + 合并：重试、流式断连重连、tool loop 里多次 mark，
    # 同一 (session, turn, memory) 只会留一行。event_id 加了日期防止
    # human_turn_index 重置后碰撞。
    assert call["on_conflict"] == "event_id"
    # event_id 现在是 session:date:turn:kind:id 格式
    event_ids = [row["event_id"] for row in call["rows"]]
    assert len(event_ids) == 3
    # 检查格式：sess-1:YYYY-MM-DD:7:star:star-a
    for event_id in event_ids:
        parts = event_id.split(":")
        assert len(parts) == 5
        assert parts[0] == "sess-1"
        assert parts[2] == "7"  # turn_index
    # 检查具体的 kind:id 部分
    assert event_ids[0].endswith(":star:star-a")
    assert event_ids[1].endswith(":star:star-b")
    assert event_ids[2].endswith(":mem:mem-a")
    # 一行一条记忆，不是一行一个数组：视图靠 count(*) 数次数，
    # 数组会把三次想起压成一行。
    assert all(row["turn_index"] == 7 for row in call["rows"])
    assert all(row["event_type"] == "island_enter" for row in call["rows"])
    # 多态外键写成两列 + check 恰好一个，这样级联删除是真的。
    assert [row.get("star_id") for row in call["rows"]] == ["star-a", "star-b", None]
    assert [row.get("mem_note_id") for row in call["rows"]] == [None, None, "mem-a"]


def test_the_same_turn_produces_the_same_event_ids():
    # 同一轮被调两次（重试、tool loop）必须给出完全相同的 event_id，
    # 否则唯一键拦不住，热度按调用次数涨。
    first, second = FakeSupabase(), FakeSupabase()
    for supabase in (first, second):
        asyncio.run(
            record_island_entry(
                supabase, session_id="sess-1", turn_index=3, star_ids=["star-a"], mem_note_ids=[]
            )
        )

    assert [row["event_id"] for row in first.upserts[0]["rows"]] == [
        row["event_id"] for row in second.upserts[0]["rows"]
    ]


def test_different_turns_are_different_events():
    supabase = FakeSupabase()
    for turn in (3, 4):
        asyncio.run(
            record_island_entry(
                supabase, session_id="sess-1", turn_index=turn, star_ids=["star-a"], mem_note_ids=[]
            )
        )

    ids = [call["rows"][0]["event_id"] for call in supabase.upserts]
    # event_id 现在包含日期，格式是 session:date:turn:kind:id
    # 同一天内调用两次，日期部分相同，turn 部分不同
    assert len(ids) == 2
    assert ids[0].split(":")[2] == "3"  # turn_index
    assert ids[1].split(":")[2] == "4"
    assert ids[0].endswith(":star:star-a")
    assert ids[1].endswith(":star:star-a")
    # 日期部分应该相同（同一次测试运行）
    assert ids[0].split(":")[1] == ids[1].split(":")[1]


def test_a_missing_turn_index_still_writes_rather_than_crashing():
    # 上一版的 `turn_index` 恒为 0，因为它读的是 gateway_sessions 上不存在的
    # `turn_count`。恒为 0 的后果不是报错，是整个会话只有第一轮记得上热度——
    # 所以这里既要容忍缺值，也要有上面那条按轮次区分的测试盯着真实来源。
    supabase = FakeSupabase()

    written = asyncio.run(
        record_island_entry(
            supabase, session_id="sess-1", turn_index=None, star_ids=["star-a"], mem_note_ids=[]
        )
    )

    assert written == 1
    assert supabase.upserts[0]["rows"][0]["turn_index"] == 0


def test_nothing_entering_writes_nothing():
    supabase = FakeSupabase()

    assert (
        asyncio.run(
            record_island_entry(
                supabase, session_id="sess-1", turn_index=1, star_ids=[], mem_note_ids=[]
            )
        )
        == 0
    )
    assert (
        asyncio.run(
            record_island_entry(
                supabase, session_id="", turn_index=1, star_ids=["star-a"], mem_note_ids=[]
            )
        )
        == 0
    )
    assert supabase.upserts == []


def test_a_failed_write_is_loud_and_does_not_break_the_turn(caplog):
    with caplog.at_level("WARNING"):
        written = asyncio.run(
            record_island_entry(
                AngrySupabase(),
                session_id="sess-1",
                turn_index=1,
                star_ids=["star-a"],
                mem_note_ids=[],
            )
        )

    assert written == 0
    assert "MemoryHeat" in caplog.text


# ── 接到召回上：热度真的改变了顺序吗 ──────────────────────────────────


def _star_row(star_id: str, content: str) -> dict:
    return {
        "id": star_id,
        "content": content,
        "chord": "",
        "status": "active",
        "is_constant": False,
        "activation_count": 0,
        "metadata": {},
        "created_at": "2026-06-18T00:00:00+00:00",
        "updated_at": "2026-06-18T00:00:00+00:00",
    }


def _star_scores(activations: dict[str, float], rows: list[dict], *, weight: float = 0.15):
    from tests.test_star_rrf_scoring import FakeSupabase as StarFake, _cfg

    supabase = StarFake()
    supabase.tables["shenyu_stars"] = rows
    star_activations = dict(activations)

    async def query(table, params=None):
        if table == STAR_ACTIVATION_VIEW:
            # 新实现：不按 id 过滤，直接返回全部（在 Python 里过滤）
            id_filter = (params or {}).get("star_id")
            if id_filter:
                # 旧测试路径：如果有 id 过滤
                wanted = {
                    item.strip()
                    for item in str(id_filter)
                    .removeprefix("in.")
                    .strip("()")
                    .split(",")
                    if item.strip()
                }
                return project_select(
                    [
                        {"star_id": key, "activation": value}
                        for key, value in star_activations.items()
                        if key in wanted
                    ],
                    params or {},
                )
            else:
                # 新路径：没有 id 过滤，返回所有
                return project_select(
                    [
                        {"star_id": key, "activation": value}
                        for key, value in star_activations.items()
                    ],
                    params or {},
                )
        return await StarFake.query(supabase, table, params)

    supabase.query = query

    from shenyu_gateway.stars import StarService

    cfg = _cfg()
    cfg.star_rrf_activation_weight = weight
    service = StarService(cfg, supabase)
    scored = asyncio.run(
        service._score_rows(query="沈予 星星 房间", rows=rows, seed=None, surface="chat_inject")
    )
    return scored


def _by_id(scored):
    return {item["row"]["id"]: item for item in scored}


def test_a_hot_star_overtakes_the_one_that_was_ranked_above_it():
    # RRF 是按名次给分的，所以两颗内容一样的星星也不会并列：列表在前的那颗
    # 每个通道都排第一，拿 1/61，另一颗拿 1/62。把冷的那颗放在前面，热的那颗
    # 就必须靠热度真的翻过去——否则这套东西可以完全不接进排序而全绿。
    rows = [_star_row("cold", "沈予 星星 房间"), _star_row("hot", "沈予 星星 房间")]

    scored = _star_scores({"hot": 3.0}, rows)
    ids = [item["row"]["id"] for item in scored]
    by_id = _by_id(scored)

    assert ids[0] == "hot"
    assert by_id["cold"]["features"]["rrf_score"] > by_id["hot"]["features"]["rrf_score"]
    assert by_id["cold"]["features"]["activation_modifier"] == 1.0
    assert by_id["hot"]["features"]["activation_raw"] == 3.0
    assert by_id["hot"]["features"]["activation_modifier"] == pytest.approx(
        1.0 + 0.15 * math.log(4.0)
    )
    # 修正是乘上去的：分数除掉 rrf 之后，两颗只差这一项。
    cold_rest = by_id["cold"]["final_score"] / by_id["cold"]["features"]["rrf_score"]
    hot_rest = by_id["hot"]["final_score"] / by_id["hot"]["features"]["rrf_score"]
    assert hot_rest / cold_rest == pytest.approx(
        by_id["hot"]["features"]["activation_modifier"]
    )


def test_the_cap_bounds_how_far_heat_can_carry_a_star():
    # 封顶不是"热度翻不动语义"——那句话是假的。1.3 倍在 k=60 的 RRF 上
    # 大约值 18 个名次（2026-09-14 实测：19 颗同样相关的星星在前面时，
    # 满热度只能爬到第 2 名，20 颗时第 3 名）。所以能测的是"有界"：
    # 差得足够远的，热度到顶也翻不过去。
    def rank_of_hot(decoys: int) -> int:
        rows = [_star_row(f"d{i}", "沈予 星星 房间") for i in range(decoys)]
        rows.append(_star_row("hot", "沈予 星星 房间"))
        scored = _star_scores({"hot": 10**6}, rows, weight=1.0)
        assert _by_id(scored)["hot"]["features"]["activation_modifier"] == ACTIVATION_MOD_MAX
        return [item["row"]["id"] for item in scored].index("hot")

    assert rank_of_hot(15) == 0, "预算之内应该翻得过去"
    assert rank_of_hot(25) > 0, "封顶必须真的拦住差得远的"
    assert rank_of_hot(25) < 25, "但也不该完全没作用"


def test_the_weight_config_actually_reaches_the_scoring():
    # `star_rrf_activation_weight` 在 2026-09-13 那一版是个反向空槽位：
    # 只被 getattr 读、RuntimeConfig 里没定义，于是永远是 fallback，
    # 调它等于没调。这条让"权重真的从 cfg 流到分数上"变成可测的。
    rows = [_star_row("cold", "沈予 星星 房间"), _star_row("hot", "沈予 星星 房间")]

    off = _by_id(_star_scores({"hot": 3.0}, rows, weight=0.0))
    on = _by_id(_star_scores({"hot": 3.0}, rows, weight=0.5))

    assert off["hot"]["features"]["activation_modifier"] == 1.0
    assert off["hot"]["final_score"] < off["cold"]["final_score"], "关掉就该只剩 rrf 的名次"
    assert on["hot"]["final_score"] > off["hot"]["final_score"]
    assert on["hot"]["final_score"] > on["cold"]["final_score"]


def test_activation_lands_in_the_candidate_log_so_the_question_stays_answerable():
    # 修正项进了排序却没进 feature_json，三个月后就没人能回答
    # 「热度到底改变过选择吗」。这条盯的是可观测性，不是数值。
    from shenyu_gateway.stars._logging import LoggingMixin

    rows = [_star_row("hot", "沈予 星星 房间")]
    scored = _star_scores({"hot": 3.0}, rows)

    logged: list[dict] = []

    class _Recorder:
        async def insert(self, table, data):
            return {"id": "run-1"}

        async def insert_many(self, table, rows):
            logged.extend(rows)
            return [{"id": f"cand-{i}", **row} for i, row in enumerate(rows)]

    service = SimpleNamespace(
        cfg=SimpleNamespace(star_shadow_candidate_limit=20),
        supabase=_Recorder(),
        _weights=lambda: SimpleNamespace(__dict__={}),
    )
    asyncio.run(
        LoggingMixin._log_run_and_candidates(
            service,
            surface="chat_inject",
            trigger_text="沈予 星星 房间",
            seed=None,
            session_tag="t",
            session_id="s",
            limit_requested=3,
            query_embedding_status="skipped",
            scored=scored,
            selected_ids={"hot"},
            shown=True,
            injected=True,
        )
    )

    features = logged[0]["feature_json"]
    assert features["activation_raw"] == 3.0
    assert features["activation_modifier"] == pytest.approx(1.0 + 0.15 * math.log(4.0))


# ── 接到便签上 ──────────────────────────────────────────────────────────


def test_mem_note_heat_stays_inside_the_clamp():
    # 便签的分数要和 mem_note_min_score(0.45) 这几条固定的线比大小。
    # 乘在 min(1.0, ...) 外面，分数就能顶到 1.3，那几条阈值一起静默漂移。
    from shenyu_gateway.mem_notes._search import SearchMixin

    service = SimpleNamespace(
        cfg=SimpleNamespace(),
        _recency_score=lambda _value: 1.0,
        _anchor_overlap=lambda _query, _row: (1.0, ["锚"]),
    )
    row = {
        "id": "mem-a",
        "content": "橘猫",
        "trigger_text": "橘猫",
        "trigger_keywords": ["橘猫"],
        "mem_type": "橘猫",
        "people": [],
        "places": [],
        "objects": [],
        "keywords": [],
    }

    score, _reasons = SearchMixin._score(
        service, "橘猫", row, activations={"mem-a": 10**6}
    )

    assert score <= 1.0


def test_mem_note_heat_still_moves_the_score_below_the_ceiling():
    from shenyu_gateway.mem_notes._search import MEM_NOTE_ACTIVATION_WEIGHT, SearchMixin

    service = SimpleNamespace(
        cfg=SimpleNamespace(),
        _recency_score=lambda _value: 0.0,
        _anchor_overlap=lambda _query, _row: (0.0, []),
    )
    row = {
        "id": "mem-a",
        "content": "橘猫 一只",
        "trigger_text": "",
        "trigger_keywords": [],
        "mem_type": "",
        "last_triggered_at": "2026-09-01T00:00:00+00:00",
        "people": [],
        "places": [],
        "objects": [],
        "keywords": [],
    }

    cold, _ = SearchMixin._score(service, "橘猫", row)
    hot, _ = SearchMixin._score(service, "橘猫", row, activations={"mem-a": 3.0})

    assert 0.0 < cold < hot < 1.0
    assert hot == pytest.approx(
        cold * (1.0 + MEM_NOTE_ACTIVATION_WEIGHT * math.log(4.0))
    )


def test_mem_note_search_reads_activations_once_for_the_whole_batch():
    # 每行查一次视图 = 一次召回 160 个来回。批量读一次是这套设计能用的前提。
    from shenyu_gateway.mem_notes import MemNoteService

    rows = [
        {
            "id": f"mem-{i}",
            "content": "橘猫 一只",
            "status": "active",
            "trigger_text": "橘猫",
            "trigger_keywords": ["橘猫"],
            # active 便签必须有一个已知的 mem_type，否则连自动浮现的资格都没有。
            "mem_type": "关于她的事实",
            "updated_at": "2026-09-10T00:00:00+00:00",
            "created_at": "2026-09-01T00:00:00+00:00",
        }
        for i in range(3)
    ]

    class _Supabase(FakeSupabase):
        async def query(self, table: str, params: dict):
            if table == MEM_NOTE_ACTIVATION_VIEW:
                return await FakeSupabase.query(self, table, params)
            self.queries.append({"table": table, "params": dict(params)})
            return project_select(rows, params)

        async def update(self, table, match, data):
            return []

    supabase = _Supabase({MEM_NOTE_ACTIVATION_VIEW: {"mem-0": 3.0}})
    service = MemNoteService(SimpleNamespace(mem_note_min_score=0.0), supabase)

    result = asyncio.run(service.search_notes("橘猫", mark_triggered=False, limit=3))

    view_calls = [q for q in supabase.queries if q["table"] == MEM_NOTE_ACTIVATION_VIEW]
    assert len(view_calls) == 1, "活性必须一次批量读完"
    # 热的那条排在前面，说明活性真的接到了排序上而不是只被取了出来。
    assert result["items"][0]["id"] == "mem-0"
