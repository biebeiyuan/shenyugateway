"""盼圃。

这里守的是三件事，按重要性排：

1. **园况是一条线，不是抽奖。** 同一天不变、隔天可以走、摘下来的定格永不重算。
   如果哪天有人把它改回随机抽，本文件第一组测试必须变红。
2. **盼圃不催。** 没有预计日期的果子不过期，过了日期的也不过期；没有任何
   自动注入路径把它塞进提示词。
3. **谁先看见谁摘要摔得好看。** 输的那个看到"已经被谁摘了、他写了什么"，
   而不是报错，也绝不覆盖对方的摘果感言。
"""

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.orchard import (
    CONDITIONS_GREEN,
    CONDITIONS_PICKED,
    GARDEN_ORDINARY,
    classify_weather,
    garden_line,
    green_condition,
    pick_condition,
)
from shenyu_gateway.orchard_service import ACTOR_SHENYU, ACTOR_YUANYUAN, OrchardService
from shenyu_gateway.runtime import local_today
from shenyu_gateway.store import GatewayStore
from tests.fake_postgrest import apply_order, project_select


def _fruit(**kwargs):
    row = {
        "id": "fruit-1",
        "name": "蒜冒尖",
        "planted_by": ACTOR_YUANYUAN,
        "planted_at": "2026-08-01T02:00:00+00:00",
        "due_on": None,
        "status": "green",
    }
    row.update(kwargs)
    return row


# ── 一、园况是一条线 ──────────────────────────────────────────────────


def test_the_same_fruit_says_the_same_thing_all_day():
    """一天里贴三张纸条，园况不该跟着变——否则果子看起来精神分裂。"""
    fruit = _fruit()
    day = date(2026, 8, 20)

    first = green_condition(fruit, note_count=1, last_note_at="2026-08-19T00:00:00+00:00", today=day)
    again = green_condition(fruit, note_count=1, last_note_at="2026-08-19T00:00:00+00:00", today=day)

    assert first == again


def test_the_line_can_move_from_one_day_to_the_next():
    """确定性不等于冻住：种子里有日子，所以隔天可以换一句。

    只断言"存在某一天说法不同"，不断言具体哪天——后者会把文案表锁死。
    """
    fruit = _fruit()
    said = {
        green_condition(fruit, note_count=1, last_note_at="2026-08-05T00:00:00+00:00", today=date(2026, 8, d))[1]
        for d in range(6, 20)
    }
    assert len(said) > 1


def test_a_fruit_nobody_touches_drifts_toward_wilting():
    """没人贴纸条越久，越往蔫的那边走。这是"墙等人"看得见的那一半。"""
    fruit = _fruit(planted_at="2026-06-01T02:00:00+00:00")
    buckets = [
        green_condition(fruit, note_count=1, last_note_at=f"2026-08-{day:02d}T00:00:00+00:00", today=date(2026, 8, 30))[0]
        for day in (28, 18, 2)
    ]
    fresh, middling, forgotten = buckets
    assert fresh not in {"dusty", "nibbled", "wilting"}
    assert middling in {"dusty", "nibbled"}
    assert forgotten == "wilting"


def test_a_tended_fruit_reads_as_growing():
    fruit = _fruit(planted_at="2026-07-01T02:00:00+00:00")
    bucket, text = green_condition(
        fruit, note_count=5, last_note_at="2026-08-29T00:00:00+00:00", today=date(2026, 8, 30)
    )
    assert bucket == "tended"
    assert text in CONDITIONS_GREEN["tended"]


def test_a_dateless_fruit_that_hung_a_long_time_is_underground():
    """蒜就在这一档：看不见进展不等于被忘了。"""
    fruit = _fruit(due_on=None, planted_at="2026-07-20T02:00:00+00:00")
    bucket, text = green_condition(
        fruit, note_count=2, last_note_at="2026-08-28T00:00:00+00:00", today=date(2026, 8, 30)
    )
    assert bucket == "underground"
    assert text in CONDITIONS_GREEN["underground"]


def test_a_near_due_fruit_swells_and_a_past_due_one_just_keeps_hanging():
    near = _fruit(id="fruit-near", due_on="2026-09-01")
    late = _fruit(id="fruit-late", due_on="2026-08-01")

    assert green_condition(near, today=date(2026, 8, 30))[0] == "swelling"
    # 过了日子不是"过期"，只是说出来。
    assert green_condition(late, today=date(2026, 8, 30))[0] == "overdue"


def test_picked_condition_does_not_depend_on_which_day_it_was_picked():
    """定格进库的那句话不该因为"今天是哪天"而不同。"""
    fruit = _fruit(due_on="2026-09-01")
    one = pick_condition(fruit, note_count=2, last_note_at="2026-08-29T00:00:00+00:00", today=date(2026, 8, 30))
    two = pick_condition(fruit, note_count=2, last_note_at="2026-08-29T00:00:00+00:00", today=date(2026, 9, 1))
    assert one[1] == two[1]


def test_picking_early_reads_green_and_picking_on_time_reads_ripe():
    fruit = _fruit(due_on="2026-09-30")
    assert pick_condition(fruit, today=date(2026, 8, 1))[0] == "green_picked"
    assert pick_condition(fruit, today=date(2026, 9, 28))[0] == "ripe"


def test_a_long_wait_nobody_shared_can_come_up_hollow():
    """现实可以不如预期。这一档存在是刻意的，不要为了好听删掉它。"""
    fruit = _fruit(due_on=None, planted_at="2026-06-01T02:00:00+00:00")
    bucket, text = pick_condition(
        fruit, note_count=0, last_note_at=None, today=date(2026, 8, 30)
    )
    assert bucket == "hollow"
    assert text in CONDITIONS_PICKED["hollow"]


def test_every_bucket_the_algorithm_can_return_has_words():
    """一个算得出来却没有文案的档位会静默返回空串。"""
    from shenyu_gateway.orchard import _green_bucket, _picked_bucket

    green_seen = set()
    picked_seen = set()
    for hung in (0, 3, 8, 22, 40, 90):
        for quiet in (0, 2, 5, 12, 30, 60):
            for notes in (0, 1, 4):
                for due in (None, -30, -3, 0, 3, 20):
                    for month in range(1, 13):
                        green_seen.add(
                            _green_bucket(
                                hung_days=hung,
                                quiet_days=quiet,
                                note_count=notes,
                                days_to_due=due,
                                month=month,
                            )
                        )
                    picked_seen.add(
                        _picked_bucket(
                            hung_days=hung,
                            quiet_days=quiet,
                            note_count=notes,
                            days_to_due=due,
                        )
                    )

    assert green_seen <= set(CONDITIONS_GREEN)
    assert picked_seen <= set(CONDITIONS_PICKED)
    # 地板：证明上面的扫描真的走遍了分支，而不是只碰到两三个档位。
    assert len(green_seen) >= 8
    assert len(picked_seen) >= 5
    for bucket in green_seen:
        assert CONDITIONS_GREEN[bucket]
    for bucket in picked_seen:
        assert CONDITIONS_PICKED[bucket]


# ── 二、盼圃不响 ──────────────────────────────────────────────────────


def test_the_orchard_wall_has_no_automatic_context_path():
    """墙的状态不自动进提示词：沈予不 look，墙上挂着什么就不在上下文里。

    这是这面墙成立的前提：便签的 remind_on 会为了"今天该说的事"强制重写
    Memory Island，墙的状态一旦沾上自动注入，半年后就是第二个提醒系统。

    小突起是唯一的例外，且只沾一个动作：种下一颗时留一行回执（见
    `test_planting_bumps_but_the_wall_state_still_does_not`）。那是"今天我做了
    什么"的动作回执，跟落星星同类，不是把墙的状态推进提示词——所以
    `island_bumps.py` 不在下面这份"禁止碰盼圃"的清单里。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "shenyu_gateway"
    context_files = [
        root / "context_builder.py",
        root / "context_layers.py",
        root / "memory_island.py",
        root / "prepare_messages.py",
        root / "room_context.py",
    ]
    for path in context_files:
        text = path.read_text(encoding="utf-8")
        assert "orchard" not in text.lower(), f"{path.name} 把盼圃接进了上下文组装"


def test_planting_bumps_but_the_wall_state_still_does_not():
    """小突起收"种下"这个动作回执，不收墙的状态，也不收其余三个动作。

    种果子库层没查重（`plant` 直接 insert），忘了种过又种一遍是一颗静默的重复
    ——跟记重星星同一种坑，所以它进。note/pick/look 不进：分别是"一天本来就想
    贴好几张""条件更新挡着摘不了第二次""读操作"。
    """
    from shenyu_gateway.island_bumps import (
        BUMP_TOOL_NAMES,
        _ORCHARD_BUMP_ACTIONS,
    )

    assert "shenyu_orchard" in BUMP_TOOL_NAMES
    assert _ORCHARD_BUMP_ACTIONS == frozenset({"plant"})


# ── 三、库与四个动作 ──────────────────────────────────────────────────


class FakeSupabase:
    """够用的 PostgREST 替身：认 eq/in 过滤、order、limit 和条件 PATCH。"""

    def __init__(self):
        self.fruits: list[dict] = []
        self.notes: list[dict] = []
        self.weather: list[dict] = []
        self._seq = 0

    def _table(self, table):
        if table == "shenyu_orchard_fruits":
            return self.fruits
        if table == "shenyu_orchard_weather":
            return self.weather
        return self.notes

    async def upsert_minimal(self, table, data, on_conflict=None):
        rows = self._table(table)
        keys = [key.strip() for key in (on_conflict or "").split(",") if key.strip()]
        if keys:
            # 库里 (on_day, kind) 是唯一约束，所以这里也必须真的去重——
            # 一个会写出第二行的替身会把"四个动作都能放心顺手写"测成通过。
            for row in rows:
                if all(str(row.get(key)) == str(data.get(key)) for key in keys):
                    row.update(data)
                    return
        rows.append(dict(data))

    def _next_id(self, prefix):
        self._seq += 1
        return f"{prefix}-{self._seq}"

    async def insert(self, table, data):
        row = dict(data)
        if table == "shenyu_orchard_fruits":
            row.setdefault("id", self._next_id("fruit"))
            row.setdefault("planted_at", "2026-08-01T02:00:00+00:00")
            row.setdefault("status", "green")
            row.setdefault("due_on", None)
        else:
            row.setdefault("id", self._next_id("note"))
            row.setdefault("created_at", "2026-08-10T02:00:00+00:00")
        self._table(table).append(row)
        return dict(row)

    def _matches(self, row, params):
        for key, raw in (params or {}).items():
            if key in {"select", "order", "limit"}:
                continue
            value = str(raw)
            if value.startswith("eq."):
                if str(row.get(key) or "") != value[3:]:
                    return False
            elif value.startswith("in.("):
                allowed = value[4:-1].split(",")
                if str(row.get(key) or "") not in allowed:
                    return False
            elif value.startswith("gte."):
                # on_day 是 YYYY-MM-DD，字典序即日期序。
                if str(row.get(key) or "") < value[4:]:
                    return False
        return True

    async def query(self, table, params=None):
        rows = [row for row in self._table(table) if self._matches(row, params)]
        # 排序走共享 helper：`nullslast` 手写过一次就错过一次——把 None 当空串
        # 会让没日子的果子排到最前，而真库把它排到最后。
        rows = apply_order(rows, params)
        limit = (params or {}).get("limit")
        if limit:
            rows = rows[: int(limit)]
        return project_select(rows, params)

    async def update(self, table, match, data):
        updated = []
        for row in self._table(table):
            if self._matches(row, match):
                row.update(data)
                updated.append(dict(row))
        return updated


class FakeRecall:
    def __init__(self):
        self.indexed: list[tuple[dict, list]] = []

    async def index_orchard_fruit_row(self, row, notes=None):
        self.indexed.append((dict(row), list(notes or [])))
        return {"ok": True, "indexed": 1}


def _local_store(tmp_path=None):
    """真的本机卷 SQLite——天气就住在这里，不在 Supabase。"""
    import tempfile
    from pathlib import Path

    root = Path(tmp_path or tempfile.mkdtemp())
    return GatewayStore(str(root / "orchard.db"))


def _service(supabase, recall=None, weather=None, store=None):
    service = OrchardService(supabase, store=store if store is not None else _local_store())
    service._recall_index = lambda: recall or FakeRecall()

    async def fake_weather():
        return dict(weather or {})

    service._weather_now = fake_weather
    return service


def _run(coro):
    return asyncio.run(coro)


def test_plant_note_pick_look_round_trip():
    supabase = FakeSupabase()
    recall = FakeRecall()
    service = _service(supabase, recall)

    planted = _run(service.plant(name="一世出师烤的第一炉面包", actor=ACTOR_YUANYUAN))
    assert planted["ok"] is True
    fruit_id = planted["data"]["fruit"]["id"]
    assert planted["data"]["fruit"]["planted_by"] == ACTOR_YUANYUAN
    assert planted["data"]["fruit"]["due_on"] is None

    noted = _run(service.add_note(fruit_id=fruit_id, content="今天还没动静", actor=ACTOR_SHENYU))
    assert noted["ok"] is True
    # 刚贴的那张就是 fruit.notes 的最后一条，不另列一遍。
    assert noted["data"]["fruit"]["notes"][-1]["author"] == ACTOR_SHENYU

    _run(service.add_note(fruit_id=fruit_id, content="竹叶被窝呢，急什么", actor=ACTOR_YUANYUAN))

    wall = _run(service.look())
    assert len(wall["data"]["hanging"]) == 1
    hanging = wall["data"]["hanging"][0]
    assert hanging["notes"] == 2
    assert hanging["condition"]
    assert wall["data"]["picked"] == []

    picked = _run(service.pick(fruit_id=fruit_id, words="这天到了，实际是——出炉了", actor=ACTOR_SHENYU))
    assert picked["ok"] is True
    assert picked["data"]["fruit"]["status"] == "picked"
    assert picked["data"]["fruit"]["picked_words"] == "这天到了，实际是——出炉了"
    assert picked["data"]["fruit"]["condition"]
    # 摘的时候连纸条一起收进果壳里，完整一串在 fruit.notes 里（不在外面再列一遍）。
    assert [note["content"] for note in picked["data"]["fruit"]["notes"]] == [
        "今天还没动静",
        "竹叶被窝呢，急什么",
    ]

    after = _run(service.look())
    assert after["data"]["hanging"] == []
    assert len(after["data"]["picked"]) == 1


def test_picked_fruit_reads_its_stored_condition_instead_of_recomputing():
    """墙底下那排每次翻开都该是同一句，否则那条线就没了。"""
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="9月1号抽血", due_on="2026-09-01"))["data"]["fruit"]["id"]
    _run(service.pick(fruit_id=fruit_id, words="抽完了"))

    stored = supabase.fruits[0]["picked_condition_text"]
    # 库里那句被人为改成一个绝不会被算法生成的值，仍要原样读回来。
    supabase.fruits[0]["picked_condition_text"] = "这是当时定格的那句"

    shown = _run(service.look())["data"]["picked"][0]
    assert shown["condition"] == "这是当时定格的那句"
    assert stored != "这是当时定格的那句"


def test_whoever_sees_it_first_picks_it_and_the_other_is_told_gently():
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]

    first = _run(service.pick(fruit_id=fruit_id, words="冒了", actor=ACTOR_SHENYU))
    second = _run(service.pick(fruit_id=fruit_id, words="我也看见了", actor=ACTOR_YUANYUAN))

    assert first["ok"] is True
    # 第二个不该看到报错。
    assert second["ok"] is True
    assert second["data"]["already_picked"] is True
    assert ACTOR_SHENYU in second["data"]["message"]
    assert "冒了" in second["data"]["message"]
    # 也绝不能覆盖对方写的话。
    assert supabase.fruits[0]["picked_words"] == "冒了"
    assert supabase.fruits[0]["picked_by"] == ACTOR_SHENYU


def test_a_fruit_needs_a_name_and_a_bad_date_is_refused():
    service = _service(FakeSupabase())

    blank = _run(service.plant(name="   "))
    assert blank["ok"] is False and blank["error_kind"] == "validation"

    bad_date = _run(service.plant(name="蒜冒尖", due_on="九月一号"))
    assert bad_date["ok"] is False and bad_date["error_kind"] == "validation"

    # 不传日期不是错误，是常态。
    assert _run(service.plant(name="蒜冒尖"))["ok"] is True


def test_notes_are_rows_so_two_people_writing_at_once_keep_both():
    """纸条是独立的行，不是 fruits 上的 JSONB 数组——整块覆写会丢一条。"""
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]

    _run(service.add_note(fruit_id=fruit_id, content="今天还没动静", actor=ACTOR_SHENYU))
    _run(service.add_note(fruit_id=fruit_id, content="急什么", actor=ACTOR_YUANYUAN))

    assert len(supabase.notes) == 2
    assert {note["author"] for note in supabase.notes} == {ACTOR_SHENYU, ACTOR_YUANYUAN}


def test_notes_failing_to_load_does_not_close_the_whole_wall():
    supabase = FakeSupabase()
    service = _service(supabase)
    _run(service.plant(name="蒜冒尖"))

    original = supabase.query

    async def flaky(table, params=None):
        if table == "shenyu_orchard_notes":
            raise RuntimeError("notes unavailable")
        return await original(table, params)

    supabase.query = flaky
    wall = _run(service.look())

    assert wall["ok"] is True
    assert len(wall["data"]["hanging"]) == 1
    # 数不出来就不说有几张，果子照旧挂在墙上。
    assert "notes" not in wall["data"]["hanging"][0]
    assert wall["data"]["hanging"][0]["condition"]


def test_picking_a_fruit_that_is_not_there():
    result = _run(_service(FakeSupabase()).pick(fruit_id="nope"))
    assert result["ok"] is False and result["error_kind"] == "not_found"


def test_a_fruit_can_be_named_instead_of_quoting_a_uuid():
    """果子的名字本来就是一句话，比 uuid 更像人会说的话。"""
    supabase = FakeSupabase()
    service = _service(supabase)
    _run(service.plant(name="蒜冒尖"))

    noted = _run(service.add_note(name="蒜冒尖", content="今天还没动静"))
    assert noted["ok"] is True
    assert noted["data"]["fruit"]["name"] == "蒜冒尖"

    picked = _run(service.pick(name="蒜冒尖", words="冒了"))
    assert picked["ok"] is True
    assert picked["data"]["fruit"]["status"] == "picked"


def test_a_name_that_matches_several_fruits_is_never_guessed():
    """贴错纸条等于把话说到另一件事上，比多问一句糟得多。"""
    supabase = FakeSupabase()
    service = _service(supabase)
    _run(service.plant(name="蒜冒尖"))
    _run(service.plant(name="蒜冒尖"))

    result = _run(service.add_note(name="蒜冒尖", content="今天还没动静"))
    assert result["ok"] is False
    assert result["error_kind"] == "ambiguous"
    # 报错里要能看出是哪几颗，否则他没法接着说。
    assert "2 颗" in result["error"]
    assert supabase.notes == []


def test_a_name_finds_the_green_one_rather_than_something_already_picked():
    """摘了的果子不该被同一个名字重新翻出来贴纸条。"""
    supabase = FakeSupabase()
    service = _service(supabase)
    old = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    _run(service.pick(fruit_id=old, words="去年那颗"))
    new = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]

    noted = _run(service.add_note(name="蒜冒尖", content="今年的"))
    assert noted["data"]["fruit"]["id"] == new


def test_naming_nothing_at_all_says_both_ways_in():
    service = _service(FakeSupabase())
    result = _run(service.add_note(content="今天还没动静"))
    assert result["ok"] is False
    assert "fruit_id" in result["error"] and "名字" in result["error"]

    missing = _run(service.pick(name="没有这颗"))
    assert missing["ok"] is False and missing["error_kind"] == "not_found"


def test_the_wall_counts_notes_and_carries_none_of_their_text():
    """看一眼墙需要知道"底下贴着几张"，不需要每句话都甩回来。

    十颗果子各带三张纸条全文是两千多 token，而他多数时候只是想看一眼墙上都
    挂着什么。想看某一颗，贴纸条或摘的时候自然就看到了。
    """
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    for n in range(5):
        _run(service.add_note(fruit_id=fruit_id, content=f"第{n}句话"))
        supabase.notes[-1]["created_at"] = f"2026-08-{5 + n:02d}T02:00:00+00:00"

    hanging = _run(service.look())["data"]["hanging"][0]
    assert hanging["notes"] == 5
    # 正文一个字都不在墙上。
    assert "第0句话" not in json.dumps(hanging, ensure_ascii=False)
    # uuid 也不在：他要指认这颗果子用名字就行。
    assert fruit_id not in json.dumps(hanging, ensure_ascii=False)


def test_touching_one_fruit_is_where_the_notes_actually_show_up():
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    for n in range(5):
        _run(service.add_note(fruit_id=fruit_id, content=f"第{n}句"))
        supabase.notes[-1]["created_at"] = f"2026-08-{5 + n:02d}T02:00:00+00:00"

    # 贴纸条时看到的是这一颗，带正文，截断了就说省了几张。
    touched = _run(service.add_note(name="蒜冒尖", content="第5句"))["data"]["fruit"]
    assert touched["note_count"] == 6
    assert len(touched["notes"]) == 3
    assert touched["earlier_notes"] == 3
    assert [note["content"] for note in touched["notes"]] == ["第3句", "第4句", "第5句"]

    # 摘的时候整串都在，所以不该再说"还有几句更早的"。
    picked = _run(service.pick(fruit_id=fruit_id, words="摘了"))["data"]["fruit"]
    assert len(picked["notes"]) == 6
    assert "earlier_notes" not in picked


def test_the_note_just_written_is_the_last_one_even_if_its_stored_time_disagrees():
    """读到的最后一句必须是他刚说的那句。

    按 created_at 排序时，只要库里的时间和这一行有一点偏差（时钟、默认值、
    同一秒并列），新纸条就会排到中间——读起来像是最后一句不是自己刚写的。
    """
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    for n in range(2):
        _run(service.add_note(fruit_id=fruit_id, content=f"早先第{n}句"))
        supabase.notes[-1]["created_at"] = f"2026-08-2{n}T02:00:00+00:00"

    # 库给这张新纸条写了一个更早的时间。
    original = supabase.insert

    async def early_insert(table, data):
        row = await original(table, data)
        if table == "shenyu_orchard_notes":
            row["created_at"] = "2026-08-01T02:00:00+00:00"
            supabase.notes[-1]["created_at"] = row["created_at"]
        return row

    supabase.insert = early_insert
    notes = _run(service.add_note(fruit_id=fruit_id, content="我刚说的"))["data"]["fruit"]["notes"]

    assert notes[-1]["content"] == "我刚说的"
    # 而且只出现一次。
    assert [note["content"] for note in notes].count("我刚说的") == 1


def test_the_note_response_does_not_echo_the_same_line_twice():
    supabase = FakeSupabase()
    service = _service(supabase)
    _run(service.plant(name="蒜冒尖"))

    data = _run(service.add_note(name="蒜冒尖", content="今天还没动静"))["data"]
    assert "note" not in data
    assert [note["content"] for note in data["fruit"]["notes"]] == ["今天还没动静"]


def test_condition_means_the_same_thing_in_every_action():
    """一个键在两个动作里是两种东西，比缺个字段更难读。

    `condition` 一度在墙上是那句话、碰某颗果子时是档位 key（ripe/tended）。
    档位 key 是网关内部算出来的标签，对读的人没用，不进返回。
    """
    supabase = FakeSupabase()
    service = _service(supabase)
    buckets = set(CONDITIONS_GREEN) | set(CONDITIONS_PICKED)

    planted = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]
    noted = _run(service.add_note(name="蒜冒尖", content="今天还没动静"))["data"]["fruit"]
    wall = _run(service.look())["data"]["hanging"][0]
    picked = _run(service.pick(name="蒜冒尖", words="冒了"))["data"]["fruit"]
    below = _run(service.look())["data"]["picked"][0]

    for item in (planted, noted, wall, picked, below):
        assert item["condition"], "每个动作都该说出果子此刻什么样"
        # 是一句话，不是 key。
        assert item["condition"] not in buckets
        assert "condition_text" not in item


def test_notes_are_rendered_as_who_said_what_when():
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    result = _run(service.add_note(fruit_id=fruit_id, content="急什么", actor=ACTOR_YUANYUAN))

    note = result["data"]["fruit"]["notes"][0]
    assert note == {"author": ACTOR_YUANYUAN, "content": "急什么", "at": note["at"]}
    # 纸条自己的 id 没有任何动作用得上——盼圃不能改也不能删纸条。
    assert "id" not in note and "fruit_id" not in note


def test_the_wall_says_how_long_is_left_instead_of_making_him_count():
    supabase = FakeSupabase()
    service = _service(supabase)
    today = local_today()
    _run(service.plant(name="快到了", due_on=(today + timedelta(days=10)).isoformat()))
    _run(service.plant(name="就是今天", due_on=today.isoformat()))
    _run(service.plant(name="过了", due_on=(today - timedelta(days=6)).isoformat()))
    _run(service.plant(name="没日子"))

    by_name = {item["name"]: item for item in _run(service.look())["data"]["hanging"]}
    assert "还有 10 天" in by_name["快到了"]["due"]
    assert "就是今天" in by_name["就是今天"]["due"]
    # 过了不是过期：说的是"还挂着"。
    assert "过了 6 天，还挂着" in by_name["过了"]["due"]
    assert "due" not in by_name["没日子"]


def test_the_pick_response_does_not_list_the_same_notes_twice():
    """同一批东西出现两次会让人以为有两组。"""
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    _run(service.add_note(fruit_id=fruit_id, content="今天还没动静"))

    data = _run(service.pick(fruit_id=fruit_id, words="冒了"))["data"]
    assert "notes" not in data
    assert len(data["fruit"]["notes"]) == 1


def test_a_bad_action_says_which_four_exist():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)
    result = _run(service.orchard(action="water"))
    assert result["ok"] is False
    assert "plant" in result["error"] and "pick" in result["error"]


def test_the_gateway_tool_records_shenyu_as_the_one_who_did_it():
    """走工具进来的是沈予，不做参数——不让模型自己填是谁。"""
    supabase = FakeSupabase()
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=supabase, store=None)

    planted = _run(service.orchard(action="plant", name="蒜冒尖"))

    assert planted["data"]["fruit"]["planted_by"] == ACTOR_SHENYU


# ── 四、只有摘了的进 Recall ────────────────────────────────────────────


def test_only_picked_fruits_enter_recall():
    """青果子还在等，等的过程属于那面墙，不该被聊天半路翻出来。"""
    from shenyu_gateway.recall import RecallIndexService

    index = RecallIndexService(None)
    green = index._orchard_fruit_documents(_fruit())
    assert green == []

    picked = index._orchard_fruit_documents(
        _fruit(
            status="picked",
            picked_at="2026-09-01T02:00:00+00:00",
            picked_by=ACTOR_SHENYU,
            picked_words="冒尖了，比想的晚",
            picked_condition="ripe",
            picked_condition_text="熟得刚好。",
        ),
        [{"author": ACTOR_YUANYUAN, "content": "竹叶被窝呢，急什么"}],
    )
    assert len(picked) == 1
    doc = picked[0]
    assert doc.source_type == "orchard"
    assert doc.title == "蒜冒尖"
    assert "冒尖了，比想的晚" in doc.body
    # 纸条跟着果子一起进索引——等的过程也是这件事的一部分。
    assert "竹叶被窝呢，急什么" in doc.body
    # 事情发生的那天是摘下来的那天。
    assert doc.event_date.startswith("2026-09-01")


def test_picking_indexes_the_fruit_and_a_failed_index_does_not_undo_the_pick():
    supabase = FakeSupabase()
    recall = FakeRecall()
    service = _service(supabase, recall)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    _run(service.add_note(fruit_id=fruit_id, content="今天还没动静"))

    result = _run(service.pick(fruit_id=fruit_id, words="冒了"))
    assert result["data"]["recallable"] is True
    assert recall.indexed[0][0]["status"] == "picked"
    assert recall.indexed[0][1][0]["content"] == "今天还没动静"

    # 索引炸了，果子照旧是摘下来的。
    other = _run(service.plant(name="第一炉面包"))["data"]["fruit"]["id"]

    class Broken:
        async def index_orchard_fruit_row(self, row, notes=None):
            raise RuntimeError("recall down")

    service._recall_index = lambda: Broken()
    broken = _run(service.pick(fruit_id=other, words="出炉了"))

    assert broken["ok"] is True
    assert broken["data"]["recallable"] is False
    assert supabase.fruits[1]["status"] == "picked"


# ── 五、圆圆那一侧的四条路 ────────────────────────────────────────────


def _admin_client(supabase, store=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shenyu_gateway.gateway_admin_routes import GatewayAdminRouteDeps, build_gateway_admin_router

    store = store if store is not None else _local_store()
    app = FastAPI()
    app.include_router(
        build_gateway_admin_router(
            GatewayAdminRouteDeps(
                cfg=SimpleNamespace(gateway_key=""),
                get_supabase_client=lambda: supabase,
                get_session_store=lambda: store,
                require_session_store=lambda: store,
                context_builder=lambda *args: None,
                resolve_upstream=lambda: {},
                prune_runtime_state=lambda **kwargs: {},
                cold_start_idle_minutes=lambda session: 0.0,
                now=lambda: None,
                request_logs=None,
            )
        )
    )
    return TestClient(app)


def test_yuanyuan_can_plant_note_pick_and_look_over_http():
    supabase = FakeSupabase()
    client = _admin_client(supabase)

    planted = client.post("/api/gateway/orchard/fruits", json={"name": "9月1号抽血"}).json()
    fruit_id = planted["data"]["fruit"]["id"]
    # 走 Admin API 那条路进来的记作圆圆，不用填。
    assert planted["data"]["fruit"]["planted_by"] == ACTOR_YUANYUAN

    noted = client.post(
        f"/api/gateway/orchard/fruits/{fruit_id}/notes",
        json={"content": "别忘了空腹"},
    ).json()
    assert noted["data"]["fruit"]["notes"][-1]["author"] == ACTOR_YUANYUAN

    wall = client.get("/api/gateway/orchard").json()
    assert wall["data"]["hanging"][0]["name"] == "9月1号抽血"
    assert wall["data"]["hanging"][0]["condition"]

    picked = client.post(
        f"/api/gateway/orchard/fruits/{fruit_id}/pick",
        json={"words": "抽完了，四管"},
    ).json()
    assert picked["data"]["fruit"]["picked_by"] == ACTOR_YUANYUAN
    assert picked["data"]["fruit"]["picked_words"] == "抽完了，四管"


def test_the_admin_api_maps_validation_and_missing_fruit_to_real_status_codes():
    client = _admin_client(FakeSupabase())

    assert client.post("/api/gateway/orchard/fruits", json={"name": "  "}).status_code == 400
    assert (
        client.post("/api/gateway/orchard/fruits", json={"name": "蒜", "due_on": "九月"}).status_code
        == 400
    )
    assert client.post("/api/gateway/orchard/fruits/nope/pick", json={"words": ""}).status_code == 404


def test_yuanyuan_can_also_name_the_fruit_and_ambiguity_is_a_conflict():
    supabase = FakeSupabase()
    client = _admin_client(supabase)
    client.post("/api/gateway/orchard/fruits", json={"name": "蒜冒尖"})

    noted = client.post(
        "/api/gateway/orchard/notes", json={"name": "蒜冒尖", "content": "急什么"}
    )
    assert noted.status_code == 200
    assert noted.json()["data"]["fruit"]["notes"][-1]["author"] == ACTOR_YUANYUAN

    # 同名第二颗之后，不猜是哪颗。请求本身没写错，所以是 409 不是 400。
    client.post("/api/gateway/orchard/fruits", json={"name": "蒜冒尖"})
    clash = client.post(
        "/api/gateway/orchard/notes", json={"name": "蒜冒尖", "content": "又一句"}
    )
    assert clash.status_code == 409

    assert (
        client.post("/api/gateway/orchard/pick", json={"name": "没有这颗"}).status_code == 404
    )


def test_the_orchard_works_with_no_local_volume_at_all():
    """天气是给盼圃添真实感的，不是它的前提。

    没有 store（比如隔离预览）时天气整层静默缺席，果子照旧能挂能贴能摘。
    """
    supabase = FakeSupabase()
    service = OrchardService(supabase, store=None)
    service._recall_index = lambda: FakeRecall()

    async def weather():
        return {"available": True, "text": "冰雹", "temp_c": 16}

    service._weather_now = weather

    planted = _run(service.plant(name="蒜冒尖"))
    assert planted["ok"] is True
    # 天气记不下来，但今天什么天照样说得出——那句话不用查库。
    assert "冰雹" in planted["data"]["garden"]

    picked = _run(service.pick(name="蒜冒尖", words="冒了"))
    assert picked["ok"] is True
    assert picked["data"]["weathered"] == []


def test_the_orchard_api_has_no_reminder_or_due_polling_route():
    """加提醒接口之前先读 AGENTS 里关于盼圃的那一条。"""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "shenyu_gateway" / "gateway_admin_routes.py").read_text(
        encoding="utf-8"
    )
    orchard_routes = [
        line.strip()
        for line in text.splitlines()
        if "/api/gateway/orchard" in line and "@router" in line
    ]
    # 看墙、种、按 id 贴/摘、按名字贴/摘。数字写死是为了让"顺手加个到期接口"
    # 这件事必须先来改这一行。
    assert len(orchard_routes) == 6
    assert not any("due" in route or "remind" in route for route in orchard_routes)


def test_orchard_is_a_public_recall_source_type():
    from shenyu_gateway.recall._base import PUBLIC_RECALL_SOURCE_TYPES

    assert "orchard" in PUBLIC_RECALL_SOURCE_TYPES


def test_green_hangs_above_and_picked_sinks_below_as_two_groups():
    """墙的上下是数据形状，不是渲染顺序。

    沈予那侧没有渲染层——他读到的就是工具返回的 JSON，所以 hanging/picked
    两个键就是那面墙的上和下。混成一个列表加 status 字段会把"怎么排"推给
    每个消费者，而他们都可能排错。
    """
    supabase = FakeSupabase()
    service = _service(supabase)

    garlic = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    _run(service.plant(name="9月1号抽血", due_on="2026-09-01"))
    _run(service.plant(name="一世出师烤的第一炉面包", due_on="2026-09-20"))
    _run(service.pick(fruit_id=garlic, words="冒了"))

    wall = _run(service.look())["data"]
    assert [item["name"] for item in wall["picked"]] == ["蒜冒尖"]
    # 摘了的那颗绝不混进上面那排；上面每颗都还没有"谁哪天摘的"。
    assert "蒜冒尖" not in [item["name"] for item in wall["hanging"]]
    assert all("picked" not in item for item in wall["hanging"])
    assert all("picked" in item for item in wall["picked"])
    assert "9月1号抽血" in [item["name"] for item in wall["hanging"]]


def test_fruits_with_a_date_queue_by_date_and_dateless_ones_wait_at_the_end():
    """有日子的按日子排队；没日子的不排队，跟在后面按挂上去的顺序。

    没日子的果子必须走 nullslast：它们是盼圃最要紧的那一类，排到最前会把
    "快到日子了"那几颗挤下去。
    """
    supabase = FakeSupabase()
    service = _service(supabase)

    _run(service.plant(name="蒜冒尖"))
    _run(service.plant(name="面包", due_on="2026-09-20"))
    _run(service.plant(name="抽血", due_on="2026-09-01"))
    _run(service.plant(name="竹叶"))

    names = [item["name"] for item in _run(service.look())["data"]["hanging"]]
    assert names == ["抽血", "面包", "蒜冒尖", "竹叶"]


def test_the_row_below_reads_newest_first():
    """墙底下那排是"我们等到过的所有东西"，最近等到的先看见。"""
    supabase = FakeSupabase()
    service = _service(supabase)

    for name in ("第一颗", "第二颗", "第三颗"):
        fruit_id = _run(service.plant(name=name))["data"]["fruit"]["id"]
        _run(service.pick(fruit_id=fruit_id, words="摘了"))
        # picked_at 由 iso_now() 写，同一毫秒会并列，所以人为拉开顺序。
        supabase.fruits[-1]["picked_at"] = f"2026-08-{10 + len(supabase.fruits):02d}T02:00:00+00:00"

    assert [item["name"] for item in _run(service.look())["data"]["picked"]] == [
        "第三颗",
        "第二颗",
        "第一颗",
    ]


def test_the_wall_can_be_read_without_the_row_below():
    supabase = FakeSupabase()
    service = _service(supabase)
    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    _run(service.pick(fruit_id=fruit_id, words="冒了"))

    wall = _run(service.look(include_picked=False))["data"]
    assert wall["picked"] == []
    assert wall["hanging"] == []


# ── 六、天气 ──────────────────────────────────────────────────────────
# 天气是这面墙上唯一一个两个人都管不了的输入。等待之所以是等待，正因为有些事
# 不由自己决定——所以它有权改写摘果子的结局。


def test_only_weather_that_leaves_a_mark_is_recorded():
    """普通阴晴进不来。它们什么也没改变，记下来只会变成天气日志。"""
    assert classify_weather({"available": True, "text": "多云", "temp_c": 22}) is None
    assert classify_weather({"available": True, "text": "晴", "temp_c": 26}) is None
    # 取不到天气不该让盼圃打不开。
    assert classify_weather({"available": False}) is None
    assert classify_weather(None) is None

    assert classify_weather({"available": True, "text": "冰雹", "temp_c": 18})[0] == "hail"
    assert classify_weather({"available": True, "text": "特大暴雨", "temp_c": 24})[0] == "downpour"
    # 温度极端单独判：实况文本不会说"今天很冷"。
    assert classify_weather({"available": True, "text": "晴", "temp_c": -3})[0] == "cold_snap"
    assert classify_weather({"available": True, "text": "晴", "temp_c": 39})[0] == "heat_wave"


def test_everyday_summer_weather_is_not_worth_recording():
    """邵阳夏天几乎隔天一场雷，35 度有二十来天——那是夏天本身，不是一件事。

    门槛按"这一天值不值得记进果子的履历"定，不按气象学上算不算极端定。
    """
    assert classify_weather({"available": True, "text": "雷阵雨", "temp_c": 26}) is None
    assert classify_weather({"available": True, "text": "晴", "temp_c": 36}) is None
    assert classify_weather({"available": True, "text": "晴", "temp_c": 1}) is None
    # 真的过了头才记。
    assert classify_weather({"available": True, "text": "强雷阵雨", "temp_c": 26})[0] == "thunder"
    assert classify_weather({"available": True, "text": "晴", "temp_c": 38})[0] == "heat_wave"


def test_a_downpour_outranks_plain_rain_because_order_is_priority():
    assert classify_weather({"available": True, "text": "大暴雨", "temp_c": 25})[0] == "downpour"
    # 普通的雨什么也不改变。
    assert classify_weather({"available": True, "text": "小雨", "temp_c": 20}) is None
    assert classify_weather({"available": True, "text": "中雨", "temp_c": 20}) is None


def test_the_garden_line_is_stable_within_a_day():
    """贴张纸条不该让天气变了。"""
    one = garden_line(None, today=date(2026, 8, 30))
    two = garden_line(None, today=date(2026, 8, 30))
    assert one == two
    assert one in GARDEN_ORDINARY
    # 极端天气那天说的是那场天气，不是平常话。
    hail = garden_line({"available": True, "text": "冰雹", "temp_c": 18}, today=date(2026, 8, 30))
    assert "冰雹" in hail


def test_every_action_comes_back_with_what_the_garden_is_like_today():
    """圆圆要的就是这个：动作做完顺带看到园子怎样。"""
    supabase = FakeSupabase()
    service = _service(supabase, weather={"available": True, "text": "冰雹", "temp_c": 16})

    planted = _run(service.plant(name="蒜冒尖"))
    fruit_id = planted["data"]["fruit"]["id"]
    assert "冰雹" in planted["data"]["garden"]

    noted = _run(service.add_note(fruit_id=fruit_id, content="砸得厉害"))
    assert "冰雹" in noted["data"]["garden"]

    assert "冰雹" in _run(service.look())["data"]["garden"]
    assert "冰雹" in _run(service.pick(fruit_id=fruit_id, words="先摘了"))["data"]["garden"]


def test_weather_lives_on_the_local_volume_and_never_reaches_supabase():
    """判据跟相册那条一样：只有要被 Recall 想起来的东西才值得占 Supabase。

    果子和纸条要进（摘了之后是他们等到过的往事），天气不要——没人会去搜
    "那天下的那场冰雹"，它只是决定摘下来的果子长什么样的算料。
    """
    supabase = FakeSupabase()
    store = _local_store()
    service = _service(supabase, weather={"available": True, "text": "冰雹", "temp_c": 16}, store=store)

    fruit_id = _run(service.plant(name="蒜冒尖"))["data"]["fruit"]["id"]
    _run(service.add_note(fruit_id=fruit_id, content="砸得厉害"))
    _run(service.look())

    # (on_day, kind) 唯一，所以四个动作都能放心地顺手写。
    rows = store.orchard_weather_since("2000-01-01")
    assert len(rows) == 1
    assert rows[0]["kind"] == "hail"
    assert rows[0]["observed_text"] == "冰雹"
    assert rows[0]["temp_c"] == 16
    # Supabase 那边一行天气都不该有。
    assert supabase.weather == []


def test_ordinary_weather_writes_nothing():
    store = _local_store()
    service = _service(FakeSupabase(), weather={"available": True, "text": "多云", "temp_c": 22}, store=store)
    _run(service.plant(name="蒜冒尖"))
    assert store.orchard_weather_since("2000-01-01") == []


def test_the_wall_does_not_compute_per_fruit_weather():
    """看整面墙不该为每颗果子翻一遍天气——那是摘的时候才做的事。"""
    supabase = FakeSupabase()
    store = _local_store()
    service = _service(supabase, weather={"available": True, "text": "冰雹", "temp_c": 16}, store=store)
    for n in range(5):
        _run(service.plant(name=f"果子{n}"))

    calls = []
    original = store.orchard_weather_since
    store.orchard_weather_since = lambda day: calls.append(day) or original(day)

    _run(service.look())
    assert calls == []

    _run(service.pick(name="果子0", words="摘了"))
    assert len(calls) == 1


def test_a_scar_overrides_the_history_verdict_when_the_fruit_was_hit():
    """被冰雹打过的果子，最真的样子不是"熟得刚好"。"""
    from shenyu_gateway.orchard import fruit_took_scar

    fruit = _fruit(due_on="2026-09-01", planted_at="2026-08-01T02:00:00+00:00")
    # 有人一直陪着等，到日子才摘——纯履历判定是"熟得刚好"。
    history = {"note_count": 3, "last_note_at": "2026-08-30T02:00:00+00:00"}
    plain = pick_condition(fruit, today=date(2026, 9, 1), **history)
    assert plain[0] == "ripe"

    # 挑一颗确实被这场冰雹打到的果子——中没中是 (果子, 那天, 天气) 定的。
    hail = [{"on_day": "2026-08-20", "kind": "hail"}]
    hit_id = next(
        f"fruit-{n}" for n in range(200) if fruit_took_scar(f"fruit-{n}", "2026-08-20", "hail")
    )
    scarred = pick_condition(
        {**fruit, "id": hit_id}, today=date(2026, 9, 1), weather_events=hail, **history
    )
    assert scarred[0] == "half_good"
    assert scarred[1] != plain[1]

    # 没被打到的那颗仍然按履历走。
    missed_id = next(
        f"fruit-{n}" for n in range(200) if not fruit_took_scar(f"fruit-{n}", "2026-08-20", "hail")
    )
    missed = pick_condition(
        {**fruit, "id": missed_id}, today=date(2026, 9, 1), weather_events=hail, **history
    )
    assert missed[0] == "ripe"


def test_the_same_storm_hits_some_fruits_and_not_others_always_the_same_ones():
    """凡是下过冰雹的果子全有疤，和没有随机性一样无聊。"""
    from shenyu_gateway.orchard import fruit_took_scar

    hit = [fruit_took_scar(f"fruit-{n}", "2026-08-20", "hail") for n in range(200)]
    assert any(hit) and not all(hit)
    # 而且永远是同一批：同样的输入必须给同样的答案。
    again = [fruit_took_scar(f"fruit-{n}", "2026-08-20", "hail") for n in range(200)]
    assert hit == again


def test_a_fruit_only_wears_weather_it_actually_hung_through():
    """挂上去之前的天气不算它的。"""
    supabase = FakeSupabase()
    service = _service(supabase, weather={"available": True, "text": "多云", "temp_c": 22})
    # 一场发生在果子挂上去之前的冰雹。
    supabase.weather.append({"on_day": "2026-07-01", "kind": "hail", "detail": "下了冰雹。"})

    planted = _run(service.plant(name="蒜冒尖"))
    fruit_id = planted["data"]["fruit"]["id"]
    picked = _run(service.pick(fruit_id=fruit_id, words="摘了"))

    assert picked["data"]["weathered"] == []


def test_weather_never_stops_the_orchard_from_opening():
    """天气接口挂了，果子照旧能挂能摘。"""
    supabase = FakeSupabase()
    service = OrchardService(supabase)
    service._recall_index = lambda: FakeRecall()

    async def broken():
        raise RuntimeError("qweather down")

    service._weather_service = lambda: SimpleNamespace(current=broken)

    planted = _run(service.plant(name="蒜冒尖"))
    assert planted["ok"] is True
    # 没有天气时说的是平常话，不是空串——"园子今天怎样"不该永远缺席。
    assert planted["data"]["garden"] in GARDEN_ORDINARY

    picked = _run(service.pick(fruit_id=planted["data"]["fruit"]["id"], words="摘了"))
    assert picked["ok"] is True


def test_failing_to_record_weather_does_not_break_the_action():
    supabase = FakeSupabase()
    service = _service(supabase, weather={"available": True, "text": "冰雹", "temp_c": 16})

    async def broken_upsert(table, data, on_conflict=None):
        raise RuntimeError("supabase down")

    supabase.upsert_minimal = broken_upsert

    planted = _run(service.plant(name="蒜冒尖"))
    assert planted["ok"] is True
    assert "冰雹" in planted["data"]["garden"]


def test_every_weather_kind_maps_to_words_a_fruit_can_actually_wear():
    """一个能被记录、却在摘的时候没有对应说法的天气种类会静默什么也不做。"""
    from shenyu_gateway.orchard import (
        _EXTREME_WEATHER_RULES,
        _WEATHER_SCARS,
        CONDITIONS_WEATHERED,
    )

    recordable = {kind for _keywords, kind, _line in _EXTREME_WEATHER_RULES}
    recordable |= {"cold_snap", "heat_wave"}
    assert recordable <= set(_WEATHER_SCARS), "有能记录却不会留疤的天气"

    for kind, bucket in _WEATHER_SCARS.items():
        lines = CONDITIONS_WEATHERED.get(bucket) or CONDITIONS_PICKED.get(bucket)
        assert lines, f"{kind} 指向的 {bucket} 没有任何说法"

    # 地板：证明上面扫的是真的规则表，而不是空集合。
    assert len(recordable) >= 8
