"""盼圃的园况：一颗果子长成什么样，从它自己的履历算出来。

圆圆提这个功能时问过要不要接 LLM，或者做个大池子随机抽。两条都不走，理由是
同一件事：**如果每次随机抽，同一颗果子今天"被虫啃了"、明天"长得挺好"、
后天又"被虫啃了"，那就不是一条线，是噪音。** 几次之后就露出池子的底，
园况从"这颗果子的样子"退化成装饰性文案。

所以这里的园况来自五个真实的量——挂了多少天、上次有人贴纸条到现在多少天、
一共几张纸条、预计日期还有多远（或过了多久）、当下的月份——加权出候选档位，
再用 `(fruit_id + 今天)` 做确定性种子在档位里抽一句。两个后果都是要的：

- 同一天贴三张纸条，园况说法不变（不会精神分裂）。
- 隔一天它自己会走，而且是往履历指的那个方向走。

没人管的果子慢慢往"蔫了""落了灰"那边走；被贴过很多纸条的往"比上次大了"
那边走；到日子的会"鼓起来"；没日子又挂了很久的会走到"埋在土里没动静，
但根还活着"——那恰好就是蒜。

摘的时候**不重新掷**：`pick_condition()` 用同一批量算出摘下那天的定格，
写进 `shenyu_orchard_fruits.picked_condition`。所以"熟得刚好"或"还有点涩"
不是抽奖结果，是这颗果子一路长成的样子。这是"每颗果子有一条线"真正成立的
地方，改这里之前先想清楚会不会把它改回抽奖。

措辞是圆圆的房子里的说法，改文案只动本文件的常量表。
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Optional

from .runtime import LOCAL_DAY_TZ, local_today, parse_local_date, parse_ts

# ── 挂着时的园况档位 ─────────────────────────────────────────────────
# key 是存进库里的稳定标识，value 是沈予和圆圆读到的话。加档位要同时想清楚
# 它由哪个量推上来——一个没有任何履历能选中的档位就是永不出现的死文案。

CONDITIONS_GREEN: dict[str, list[str]] = {
    # 刚挂上去，什么都还没发生。
    "fresh": [
        "青着，硬的。刚挂上去的样子。",
        "还小。叶子是新的那种绿。",
        "枝上多了一颗。看着有精神。",
    ],
    # 有人常来看（纸条多且新）。
    "tended": [
        "比上次大了一点。有人常来看它。",
        "青着，但沉手。长得挺好。",
        "叶子舒展着。这一片的土是湿的。",
    ],
    # 挂了一阵，还有人管，只是慢。
    "steady": [
        "还青着。不快，但一直在长。",
        "老样子。没什么变化，也没坏。",
        "青的。摸上去凉。",
    ],
    # 很久没人贴纸条了。
    "dusty": [
        "叶子上落了灰。有一阵没人来过了。",
        "还挂着。藤有点干。",
        "青着，只是没人碰过。枝头静得很。",
    ],
    # 更久没人管。
    "wilting": [
        "叶子卷起来了一点。缺水。",
        "有点蔫。不至于掉，但看着累。",
        "枝垂下去了些。它还在等。",
    ],
    # 磕碰：挂久了总会有的小意外。
    "nibbled": [
        "被虫啃了一小口。不深，皮还好。",
        "侧面有个小疤。什么时候磕的不知道。",
        "叶子上有几个洞。虫来过又走了。",
    ],
    # 预计日期临近。
    "swelling": [
        "一夜鼓起来了。日子快到了。",
        "颜色开始转。看着像要熟了。",
        "沉了不少。掂在手里有分量。",
    ],
    # 过了预计日期还挂着——不催，只是说出来。
    "overdue": [
        "日子过了，它还挂着。没掉。",
        "该熟的那天过去了。它自己有主意。",
        "还在枝上。比说好的晚，但没走。",
    ],
    # 没有预计日期，挂了很久——蒜就在这一档。
    "underground": [
        "埋在土里没动静。但根还活着。",
        "地面上什么都看不见。底下的事看不见而已。",
        "还没冒尖。土是松的，有人翻过。",
    ],
    # 冬天。
    "dormant": [
        "冷。枝上没什么变化，收着劲。",
        "这时节不长。等回暖。",
        "叶子落了。芽在里面。",
    ],
}

# ── 摘的时候的定格 ───────────────────────────────────────────────────
# 现实可以不如预期，圆圆的原话是"这天到了，实际是这样的——"，所以这里
# 有涩的、空的、比想的小的。不要为了好听把它们删掉。

CONDITIONS_PICKED: dict[str, list[str]] = {
    "ripe": [
        "熟得刚好。",
        "正是这个时候。皮一碰就下来了。",
        "熟透了，甜。等得值。",
    ],
    "overripe": [
        "熟过头了，甜得发闷。",
        "再等一天就该掉了。刚好赶上。",
        "有点软。味道很浓。",
    ],
    "green_picked": [
        "还有点涩。摘早了。",
        "硬的。要放几天才好吃。",
        "青味还在。也算摘下来了。",
    ],
    "half_good": [
        "一半好，一半有虫眼。",
        "切开一边是好的。另一边算了。",
        "有疤，但里面是好的。",
    ],
    "smaller": [
        "比想的小。",
        "没长到该有的个头。味道还在。",
        "小小的一颗。分量不重。",
    ],
    "hollow": [
        "摘下来才发现里面是空的。",
        "轻。晃一晃有声音。",
        "外面看着好，剖开是空的。",
    ],
    "quiet": [
        "摘了。就是普通的一颗。",
        "没什么特别。摘下来了。",
        "该摘就摘了。",
    ],
}

# ── 天气 ─────────────────────────────────────────────────────────────
# 跟着圆圆所在地的实况走（`weather.py` 的 QWeather，默认邵阳）。用他所在地的
# 天气而不是沈予窗外那片海，是因为盼圃是他们俩共同的墙：他那天淋了雨，
# 沈予在盼圃里看得见。
#
# 只有会在果子上留下后果的天气才记进 shenyu_orchard_weather。普通的阴晴多云
# 进不来——不是漏了，是它们什么也没改变，记下来只会把那张表变成天气日志。

# QWeather 中文实况 text 里的关键词 → (极端天气种类, 园子里那句话)。
# 顺序即优先级：先命中的赢，所以"雷阵雨"要排在"雨"前面。
_EXTREME_WEATHER_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("冰雹",), "hail", "下了冰雹。砸在叶子上噼里啪啦的。"),
    (("沙尘", "扬沙", "浮尘"), "dust", "起了沙尘。天是土色的，叶子上积了一层。"),
    (("台风", "飓风"), "storm", "台风过境。园子里什么都在响。"),
    (("暴雨", "大暴雨", "特大暴雨"), "downpour", "下暴雨。地上积了水，土泡软了。"),
    # 「强雷阵雨」记，普通「雷阵雨」不记：邵阳夏天几乎隔天一场雷，那不是
    # 值得记的天气，是夏天本身。一件天天发生的事记下来只会变成噪音。
    (("强雷阵雨", "大雷"), "thunder", "打雷。雨点很大，砸得叶子直往下弯。"),
    (("暴雪", "大雪"), "snow", "下大雪。园子盖上了一层白。"),
    (("狂风", "大风", "飙风", "强风"), "gale", "刮大风。枝子被压得贴到地上。"),
    (("雪", "雨夹雪", "冻雨"), "snow", "下雪。落在枝上一会儿就化了。"),
]

# 温度极端单独判：QWeather 的 text 不会说"今天很冷"，那是温度的事。
#
# 门槛按邵阳定，而且刻意定得高：35 度在这里一年有二十来天，那是夏天的常态而
# 不是一件事；38 度才是真的把土晒裂。同理 0 度——邵阳冬天下探到 2 度不稀奇。
# 判断标准是"这一天值不值得记进果子的履历"，不是"气象学上算不算极端"。
_COLD_SNAP_C = 0
_HEAT_WAVE_C = 38

# 一场天气在果子上留下什么。key 对上 shenyu_orchard_weather.kind。
_WEATHER_SCARS: dict[str, str] = {
    "hail": "half_good",
    "dust": "smaller",
    "storm": "half_good",
    "downpour": "watered_down",
    "thunder": "half_good",
    "snow": "sweetened",
    "gale": "smaller",
    "cold_snap": "sweetened",
    "heat_wave": "sun_scorched",
}

# 留了疤的果子摘下来是什么样。这几档只能由天气推上来，普通履历到不了。
CONDITIONS_WEATHERED: dict[str, list[str]] = {
    "watered_down": [
        "涨了水，味淡。那场雨太大了。",
        "个头不小，咬开水汪汪的。淡。",
    ],
    "sweetened": [
        "冻过一次，反而更甜。",
        "挨过那场冷，糖都收进去了。",
    ],
    "sun_scorched": [
        "向阳那面晒出一块疤。背面是好的。",
        "皮有点厚。那阵子太热了。",
    ],
}

# 平常天气的园子。没有极端天气可说时，四个动作的回执用这一档，
# 免得"园子今天怎样"变成一句永远缺席的话。
GARDEN_ORDINARY: list[str] = [
    "园子里没什么事。土是干的。",
    "今天风不大。叶子偶尔动一下。",
    "天阴着。园子安静。",
    "有太阳。地上一格一格的光。",
]


def classify_weather(weather: Optional[dict[str, Any]]) -> Optional[tuple[str, str]]:
    """实况 → (极端天气种类, 园子里那句话)，普通天气返回 None。

    `weather` 是 `weather.py::QWeatherService.current()` 的返回。取不到天气
    （`available` 为假）也返回 None：盼圃不该因为天气接口挂了而打不开。
    """
    if not isinstance(weather, dict) or not weather.get("available"):
        return None
    text = str(weather.get("text") or "")
    for keywords, kind, line in _EXTREME_WEATHER_RULES:
        if any(word in text for word in keywords):
            return kind, line
    temp = weather.get("temp_c")
    try:
        temp_c = float(temp) if temp is not None else None
    except (TypeError, ValueError):
        temp_c = None
    if temp_c is not None:
        if temp_c <= _COLD_SNAP_C:
            return "cold_snap", f"冷。{int(temp_c)}度，园子冻着。"
        if temp_c >= _HEAT_WAVE_C:
            return "heat_wave", f"热。{int(temp_c)}度，土晒得发烫。"
    return None


def garden_line(
    weather: Optional[dict[str, Any]] = None,
    *,
    today: Optional[date] = None,
) -> str:
    """园子今天什么天。一句真话，跟着实况走。

    普通天气按日子确定性地挑一句，所以同一天四个动作说的是同一句——
    贴张纸条不该让天气变了。
    """
    extreme = classify_weather(weather)
    if extreme:
        return extreme[1]
    day = today or local_today()
    return _pick_line("garden", GARDEN_ORDINARY, [day.isoformat()])


def fruit_took_scar(fruit_id: Any, on_day: Any, kind: Any) -> bool:
    """这场天气有没有打到这颗果子。

    同一场冰雹有的果子中了有的没中，而且永远是同一批——所以不需要在天气那张
    表里给每颗果子存疤，疤是从 (果子, 那天, 天气种类) 推出来的。约三成命中：
    再高就变成"凡是下过冰雹的果子全有疤"，那和没有随机性一样无聊。
    """
    seed = f"{fruit_id}|{on_day}|{kind}".encode("utf-8")
    return hashlib.sha256(seed).digest()[0] < 77


def weather_scar(
    fruit: dict[str, Any],
    weather_events: Optional[list[dict[str, Any]]] = None,
) -> Optional[tuple[str, str, str]]:
    """这颗果子挂着期间挨过的那场天气，返回 (档位, 那句话, 天气种类)。

    `weather_events` 是 `shenyu_orchard_weather` 里落在它挂着那段时间内的行，
    调用方按 `on_day` 正序取。挨过好几场时取**最后一场**：摘下来时看到的是
    最近那次留下的样子，早先的疤已经长过去了。

    挨过天气不等于留疤——`fruit_took_scar` 决定这颗中没中。
    """
    if not weather_events:
        return None
    fruit_id = str(fruit.get("id") or "")
    hit: Optional[tuple[str, str, str]] = None
    for event in weather_events:
        kind = str(event.get("kind") or "").strip()
        bucket = _WEATHER_SCARS.get(kind)
        if not bucket:
            continue
        if not fruit_took_scar(fruit_id, event.get("on_day"), kind):
            continue
        lines = CONDITIONS_WEATHERED.get(bucket) or CONDITIONS_PICKED.get(bucket)
        if not lines:
            continue
        # 种子里带上天气和那天，所以同一颗果子挨不同的天气说的不是同一句。
        hit = (bucket, _pick_line(bucket, lines, [fruit_id, kind]), kind)
    return hit

# 越久没人贴纸条，就越往蔫的那边走。天数是圆圆家的节奏，不是通用常数。
_STALE_DUSTY_DAYS = 10
_STALE_WILTING_DAYS = 25
# 没有预计日期、挂过这么久，才算"埋在土里"。
_UNDERGROUND_DAYS = 21
# 预计日期还剩这么多天以内算临近。
_SWELLING_WINDOW_DAYS = 5


def _fruit_day(value: Any) -> Optional[date]:
    """把库里的 timestamptz 或 date 读成本地日。"""
    parsed = parse_local_date(value)
    if parsed is not None:
        return parsed
    dt = parse_ts(value)
    return dt.astimezone(LOCAL_DAY_TZ).date() if dt else None


def _days_between(earlier: Optional[date], later: date) -> Optional[int]:
    if earlier is None:
        return None
    return (later - earlier).days


def _pick_line(bucket: str, lines: list[str], seed_parts: list[str]) -> str:
    """在一个档位里确定性地挑一句。

    种子里放什么决定了这句话什么时候会变。挂着时放 (fruit_id, 档位, 今天)：
    同一天说法不变，隔天可能换一句。摘的时候放 (fruit_id, 档位) 而不放日子——
    定格进库的那句话不该因为"今天是哪天"而不同。
    """
    if not lines:
        return ""
    digest = hashlib.sha256("|".join([bucket, *seed_parts]).encode("utf-8")).digest()
    return lines[digest[0] % len(lines)]


def green_condition(
    fruit: dict[str, Any],
    *,
    note_count: int = 0,
    last_note_at: Any = None,
    today: Optional[date] = None,
) -> tuple[str, str]:
    """挂着的果子此刻是什么样，返回 (档位 key, 那句话)。

    只读这颗果子自己的履历。`note_count` 和 `last_note_at` 由调用方从
    `shenyu_orchard_notes` 聚合出来，本函数不查库——这样它是纯函数，能测。
    """
    day = today or local_today()
    fruit_id = str(fruit.get("id") or "")
    planted_day = _fruit_day(fruit.get("planted_at")) or day
    hung_days = max(0, _days_between(planted_day, day) or 0)

    # 上次被碰过是什么时候：有纸条按最后一张算，没纸条按挂上去那天算。
    touched_day = _fruit_day(last_note_at) or planted_day
    quiet_days = max(0, _days_between(touched_day, day) or 0)

    due_day = _fruit_day(fruit.get("due_on"))
    days_to_due = _days_between(day, due_day) if due_day else None

    bucket = _green_bucket(
        hung_days=hung_days,
        quiet_days=quiet_days,
        note_count=max(0, int(note_count or 0)),
        days_to_due=days_to_due,
        month=day.month,
    )
    seed = [fruit_id, day.isoformat()]
    return bucket, _pick_line(bucket, CONDITIONS_GREEN.get(bucket, []), seed)


def _green_bucket(
    *,
    hung_days: int,
    quiet_days: int,
    note_count: int,
    days_to_due: Optional[int],
    month: int,
) -> str:
    """五个量 → 一个档位。顺序就是优先级，最要紧的先判。"""
    # 日子快到了，这件事盖过其他所有状态——它是这颗果子当下最真的样子。
    if days_to_due is not None and 0 <= days_to_due <= _SWELLING_WINDOW_DAYS:
        return "swelling"
    # 过了日子还挂着。说出来，但不催。
    if days_to_due is not None and days_to_due < 0:
        return "overdue"
    # 刚挂上去，还没有履历可读。
    if hung_days <= 2:
        return "fresh"
    # 刚刚有人来看过，而且来得勤。这一档排在"埋在土里"和"落了灰"前面：
    # 昨天还有人贴纸条的果子，说"比上次大了"比说"没人来过"真。
    if note_count >= 3 and quiet_days <= 3:
        return "tended"
    # 很久没人碰。挂得越久越往蔫走，但中间留一档"被虫啃了"当小意外——
    # 用挂了多少天决定要不要走这一档，所以它对同一颗果子是稳定的。
    #
    # 没人来过这件事排在「埋在土里」前面，是因为对一颗没日子的果子来说两句
    # 都是真的，而更值得说的是那个变化：有人隔几天就来看、它仍然什么都没长，
    # 那是「埋在土里没动静」；一个月没人来过，那就是落了灰。
    if quiet_days >= _STALE_WILTING_DAYS:
        return "wilting"
    if quiet_days >= _STALE_DUSTY_DAYS:
        return "nibbled" if hung_days % 3 == 0 else "dusty"
    # 没日子 + 挂很久：蒜这一类。它不是被忘了，是本来就看不见进展。
    if days_to_due is None and hung_days >= _UNDERGROUND_DAYS:
        return "underground"
    # 冬天不长。
    if month in (12, 1, 2):
        return "dormant"
    return "steady"


def pick_condition(
    fruit: dict[str, Any],
    *,
    note_count: int = 0,
    last_note_at: Any = None,
    today: Optional[date] = None,
    weather_events: Optional[list[dict[str, Any]]] = None,
) -> tuple[str, str]:
    """摘下这一刻定格的园况，返回 (档位 key, 那句话)。

    用的是同一批量，所以结果是这颗果子一路长成的样子，不是摘的瞬间掷的骰子。
    这两个值写进库，之后永远不再重算。

    挨过极端天气而且中了的果子，天气盖过履历判定：一颗被冰雹打过的果子，
    最真的样子是"有疤，但里面是好的"，而不是"熟得刚好"。天气是这里唯一一个
    两个人都管不了的输入，所以它有权改写结局。
    """
    scar = weather_scar(fruit, weather_events)
    if scar:
        bucket, text, _kind = scar
        return bucket, text
    day = today or local_today()
    fruit_id = str(fruit.get("id") or "")
    planted_day = _fruit_day(fruit.get("planted_at")) or day
    hung_days = max(0, _days_between(planted_day, day) or 0)
    touched_day = _fruit_day(last_note_at) or planted_day
    quiet_days = max(0, _days_between(touched_day, day) or 0)
    due_day = _fruit_day(fruit.get("due_on"))
    days_to_due = _days_between(day, due_day) if due_day else None

    bucket = _picked_bucket(
        hung_days=hung_days,
        quiet_days=quiet_days,
        note_count=max(0, int(note_count or 0)),
        days_to_due=days_to_due,
    )
    # 种子里不放日子：定格进库的那句话不该取决于摘的那天是哪天。
    return bucket, _pick_line(bucket, CONDITIONS_PICKED.get(bucket, []), [fruit_id])


def _picked_bucket(
    *,
    hung_days: int,
    quiet_days: int,
    note_count: int,
    days_to_due: Optional[int],
) -> str:
    # 有日子的果子：按摘的时机相对那天来判。
    if days_to_due is not None:
        if days_to_due > _SWELLING_WINDOW_DAYS:
            # 离日子还远就摘了。
            return "green_picked"
        if days_to_due < -14:
            return "overripe"
        if days_to_due <= 0 and quiet_days >= _STALE_WILTING_DAYS:
            # 到了日子，但很久没人管——一半好一半有虫眼。
            return "half_good"
        return "ripe"
    # 没日子的果子：靠"等了多久、有没有人陪着等"来判。
    if hung_days <= 2:
        # 挂上去就摘了，几乎没等。
        return "quiet"
    if quiet_days >= _STALE_WILTING_DAYS:
        return "hollow" if hung_days >= _UNDERGROUND_DAYS else "smaller"
    if note_count >= 3:
        return "ripe"
    if note_count >= 1:
        return "ripe" if hung_days >= 7 else "quiet"
    return "smaller" if hung_days >= _UNDERGROUND_DAYS else "quiet"
