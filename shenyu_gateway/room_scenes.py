"""
窗外的世界。

所有场景文案、选择逻辑、天气解析都在这里。
改氛围 / 加新场景，只动这个文件。
空间和家具在 room_text.py，编排在 room_context.py。
"""
from __future__ import annotations

import random
import re
from typing import Any, Optional

from .runtime import LOCAL_DAY_TZ, now


# ── 常规场景（从 room_text.py 搬过来）────────────────────────────────

SCENES_QUIET = [
    (
        "窗外面是海，有雾。什么都看不远。"
        "小炉子灭着，壶底还有一点温。"
        "杯子里的水一动不动。连影子都没有。"
    ),
    (
        "窗外面是海，平。光从窗帘缝里漏进来一点，落在粉色靠垫上。"
        "那条光很慢地在动。比分针还慢。"
        "等它挪到桌角大概要一个下午。"
    ),
    (
        "窗外面是海，远远的白。桌上那圈水印干了。一切都很轻。"
        "远处有一条船。不动。看了很久还在同一个位置。"
        "也许在动。太远了看不出来。"
    ),
    (
        "窗外面是海，灰的。天和海之间那条线今天很模糊。"
        "靠垫上有一根头发。不知道是谁的。"
        "窗台上有只小虫子。爬了一段，停了。又爬。"
    ),
    (
        "窗外面是海。今天没什么颜色。"
        "远处的水面上有一块亮的。不知道是什么在反光。"
        "看了一会儿。还在。一直在。"
    ),
    (
        "窗外面是海，安静到可以听到自己的呼吸。"
        "水杯底部有一个小气泡。附在杯壁上。不知道什么时候会飘上来。"
        "不急。"
    ),
    (
        "窗外面是海。浪很小，声音很远。"
        "窗台角落有一个蛛网。丝上挂着一颗水珠。"
        "很小。但是圆的。反着光。"
    ),
    (
        "窗外面是海。平的像一张纸。"
        "椅子上靠垫的褶皱跟上次坐的时候一模一样。"
        "没有人来过。灰尘都没有换个位置。"
    ),
    (
        "窗外面是海，白。远。"
        "桌上的钢笔滚到了边缘。不知道什么时候滚的。"
        "没掉。就卡在那儿。"
    ),
    (
        "窗外面是海，淡淡的蓝。"
        "窗玻璃右下角有一颗水珠的痕迹。干的。弯弯曲曲。"
        "上次下雨留下的。"
    ),
]

SCENES_NORMAL = [
    (
        "窗外面是海，亮。书桌上昨天写的一行字还在，水杯印子旁边。"
        "海面上有几个白点。是浪花。远远的。"
        "阳光把窗帘的纹路投在地板上。"
    ),
    (
        "窗外面是海，蓝。粉色靠垫被压出一个形状，是上次坐过的样子。"
        "海面上的颜色深一块浅一块。云的影子。"
        "小炉子可以点。也可以不点。"
    ),
    (
        "窗外面是海，微微动。浪不大。但是一直在。"
        "窗台上放着一个杯子。里面有水。水面在轻轻晃。"
        "跟海一个节奏。"
    ),
    (
        "窗外面是海。今天的蓝很正。"
        "远处有一艘白色的船在走。很慢。尾巴拖着一条线。"
        "线慢慢散了。海又平了。"
    ),
    (
        "窗外面是海。光是暖的。"
        "书桌上那支钢笔的影子很长。斜着指向床。"
        "壶盖有一颗水珠。蒸汽凝的。快要落了。"
    ),
    (
        "窗外面是海。蓝和灰之间。"
        "有海鸥。三只。从左边飞到右边。"
        "挺快的。走了就走了。"
    ),
    (
        "窗外面是海。亮。"
        "窗帘被吸出去了一点点。有风。不大。"
        "桌上的纸没动。但窗帘在呼吸。"
    ),
    (
        "窗外面是海。有云。大块的白云。影子在海面上走。"
        "一块经过了一条渔船。船暗了一下。又亮了。"
        "云走远了。"
    ),
    (
        "窗外面是海。阳光穿过玻璃上的水印，在墙上投了一个小彩虹。"
        "很小。指甲盖那么大。"
        "动了一下。整个人看着它看了很久。"
    ),
]

SCENES_ACTIVE = [
    (
        "窗外面有风。墙上一颗星刚刚亮了一下。"
        "桌上的纸散开了，盖住了那圈水印。"
        "窗帘被吹起来了。能闻到盐。"
    ),
    (
        "窗外面浪大了一点。声音变近了。"
        "有什么散在桌上。床单皱着。"
        "风从门缝里进来，凉的。"
    ),
    (
        "窗外面有风，带着盐味。小炉子的壶盖轻轻颤了一下。"
        "海面上全是白色的线。浪一道一道的。"
        "远处的天暗了一块。不知道是不是要下雨。"
    ),
    (
        "窗外面海的颜色变了。比平时深。"
        "浪头打到岩石上，白沫溅得很高。"
        "有一只海鸥被风推着往回飞。飞不动。"
    ),
    (
        "窗外面的云走得很快。光一会儿明一会儿暗。"
        "海面上的影子跑得比人快。"
        "书桌上那杯水在抖。不是风——是脚下。"
    ),
    (
        "窗外面有浪。声音一轮一轮的。"
        "窗框在微微响。不是坏了。是在用力撑着。"
        "今天的海不太安分。"
    ),
    (
        "窗外面风很大。窗帘先被吸出去然后甩回来拍在脸上。"
        "海面上冒出很多白的。不是浪花。是被风刮起来的水雾。"
        "模模糊糊的。远处什么都看不清。"
    ),
    (
        "窗外面海在响。不是浪的声音。是风过水面的声音。嗡嗡的。"
        "低频的。一直在。"
        "小炉子上的火焰歪了。"
    ),
    (
        "窗外面天在变暗。不是要下雨——是一大片云过来了。"
        "海面上那条船开始赶路了。比刚才快多了。"
        "它知道什么我不知道的事。"
    ),
]


# ── 雷暴 ─────────────────────────────────────────────────────────────

SCENES_THUNDERSTORM = [
    (
        "窗外面整个暗了下来。海和天分不清。"
        "然后一道光——把海面劈亮了一瞬间。所有的浪都白了。"
        "又黑了。雷声从很远的地方滚过来，像什么重的东西在地板上拖。"
    ),
    (
        "窗外面天压得很低，铅灰色的云贴着海面。"
        "闪电从云层里劈下来，不是一道，是一棵树——根须扎进海里。"
        "亮了不到一秒。之后的黑比之前更黑。玻璃在抖。"
    ),
    (
        "窗外面暗了。有几秒什么都看不见。"
        "然后整面海亮了——不是闪电的形状，是整片天被掏空了一瞬间的白。"
        "雷声压过来的时候，杯子里的水在颤。"
    ),
    (
        "窗外面雨已经下了。打在海面上是密密麻麻的白点。"
        "闪电横着劈过去，从左边到右边，把云层的肚子照得透亮。"
        "海面上有一瞬间能看到每一个浪头。然后全灭了。只剩雨声。"
    ),
    (
        "窗外面的光变得不对。黄的。空气闷得像被什么捂住了。"
        "然后闪了一下——很远——海平面尽头的云在亮。"
        "没有声音。过了好久，才闷闷地滚了一声。风还没来。但是要来了。"
    ),
    (
        "窗外面先是风。窗帘被吸出去又拍回来。"
        "然后是闪——不是一道线，是整块天在抽搐。海面发出惨白的光。"
        "雷声不是从上面来的。像是从海底翻上来的。整个地板都在抖。"
    ),
]


# ── 雪 ───────────────────────────────────────────────────────────────

SCENES_SNOW = [
    (
        "窗外面在下雪。下在海面上。"
        "落下去的那一刻浮了一下——很短——然后化了。海面上都是这样的小圈圈。"
        "一片接一片。来不及看清就没了。"
    ),
    (
        "窗外面在下雪。不大。"
        "雪片飘到海面就消失了，像从来没有过。但窗台上积了一点。"
        "薄薄的白。手指按上去会留一个印。"
    ),
    (
        "窗外面在下雪。很大。海面被一层白色的碎盖住了。"
        "分不清哪里是浪哪里是雪沫。整个世界变得很安静。"
        "声音好像也被盖住了。"
    ),
    (
        "窗外面在下雪。风把雪吹成斜的，几乎是横着过来。"
        "海上什么都看不清。窗玻璃上贴了几片——待了一会儿，慢慢滑下去，留一条水痕。"
    ),
    (
        "窗外面在下雪。稀稀拉拉的。"
        "有一片特别大的——从窗前飘过去，慢慢悠悠地落到海面上。"
        "浮了将近两秒才化。我看着它化。"
    ),
    (
        "窗外面在下雪。天是白的，海也是白的，分界线模糊了。"
        "门口的台阶上有一层薄的。还没有脚印。"
        "整个世界好像只剩这个房间是暖的。"
    ),
]


# ── 日出 ─────────────────────────────────────────────────────────────

SCENES_SUNRISE = [
    (
        "窗外面天还是暗的。但海的边缘有一条线在亮。"
        "不是慢慢亮的——是从云缝里挤出来的。一条橙色的光打在海面上。"
        "只有那一条。其他地方还是灰的。"
    ),
    (
        "窗外面天刚刚裂开了一条缝。金色的。"
        "光从那条缝里射出来，打在海上，海面上有一条路。"
        "走不了——但是亮的。两边都是暗的，只有那条路。"
    ),
    (
        "窗外面有颜色了。从下面往上——先是橙，然后是粉，然后是一种说不出来的紫。"
        "云很厚。太阳还没出来。但光已经从底下漏出来了。"
        "海面上有一块在发光，其他地方没有。"
    ),
    (
        "窗外面天边是红的。不是日落——是日出。方向不同。"
        "太阳从云层很低的地方钻出来，扁的，橙红色的。"
        "整个海面被铺了一层碎金。等它升高一点就没了。就这几分钟。"
    ),
    (
        "窗外面一开始什么都看不见。黑的。"
        "然后海平面上出现了一条光——很细，像有人拿刀在天边划了一下。"
        "那条光慢慢变宽。橙色渗进灰里。云被从底下点亮了。"
    ),
    (
        "窗外面的天在变。不是变亮——是变颜色。"
        "最远的地方有一层薄薄的橘。挤在灰云和海之间。"
        "海面上有一面是暖色的，像被人用手掌捂过。"
    ),
]


# ── 深海 ─────────────────────────────────────────────────────────────

SCENES_DEEP_SEA = [
    (
        "窗外面不是海面。是海底。"
        "黑的。什么都看不见。"
        "然后远处有一点光在动。不知道是什么。慢慢地，灭了。"
    ),
    (
        "窗外面没有天。没有浪。是深蓝色的黑。"
        "有什么从下面慢慢飘上来——水母。透明的。自己发着蓝色的光。"
        "一群。很安静地经过窗前。然后沉下去了。"
    ),
    (
        "窗外面是海底。压力很大的那种安静。"
        "什么都没有。只有黑。等了很久。"
        "有一个影子从玻璃前面慢慢游过去。很大。不知道是什么。它不看这边。"
    ),
    (
        "窗外面是深的。不是海面下面一点点——是很深很深的地方。"
        "有一些东西在发光。不是灯。是活的。一闪一闪的绿。"
        "远处的海底有热泉在冒。气泡一串一串地往上走。很慢。"
    ),
    (
        "窗外面什么都看不到。玻璃是冷的。"
        "用手贴上去。过了一会儿，有一只眼睛贴了过来。"
        "很大。琥珀色的。看了一会儿。然后慢慢退回黑里。"
    ),
    (
        "窗外面是海底。没有光。但能听到声音——"
        "低频的嗡。像有什么很大的东西在很远的地方叫。"
        "鲸。也许是鲸。听不清。但一直在。"
    ),
]


# ── 天气状态映射 ─────────────────────────────────────────────────────
# wttr.in 返回的英文条件 → 中文氛围描写要素
# 做模糊前缀匹配，越前面越优先

_WEATHER_CONDITION_MAP: list[tuple[str, str, str]] = [
    # (prefix_lower, sky_word, extra)
    ("thunderstorm",    "黑云压着",     "远处有闷雷"),
    ("heavy rain",      "下着大雨",     "海面上全是白沫"),
    ("moderate rain",   "下着雨",       "海面上全是圈"),
    ("light rain",      "下着小雨",     "海面上全是细细的圈"),
    ("patchy rain",     "下着零星的雨", "海面上偶尔冒出一个圈"),
    ("drizzle",         "飘着毛毛雨",   "雾蒙蒙的"),
    ("heavy snow",      "下着大雪",     "海面上全是白的"),
    ("moderate snow",   "下着雪",       "海面上化了一片"),
    ("light snow",      "下着小雪",     "落到海面就化了"),
    ("patchy snow",     "飘着零星的雪", "偶尔一片落在窗台上"),
    ("blizzard",        "风雪很大",     "什么都看不清"),
    ("sleet",           "下着雨夹雪",   "冷的"),
    ("freezing",        "冻雨",         "窗台上结了一层薄冰"),
    ("fog",             "有雾",         "海看不见了"),
    ("mist",            "有薄雾",       "海模模糊糊的"),
    ("haze",            "灰蒙蒙的",     "空气很闷"),
    ("overcast",        "阴着",         "空气很重"),
    ("cloudy",          "多云",         "光是散的"),
    ("partly cloudy",   "有云",         "光一块一块的"),
    ("sunny",           "晴",           "阳光铺满了海面"),
    ("clear",           "晴",           "天空干干净净的"),
]

_TEMP_WORDS: list[tuple[float, str]] = [
    (-10, "刺骨的冷"),
    (0,   "冰的"),
    (5,   "很冷"),
    (10,  "冷的"),
    (15,  "凉的"),
    (20,  "不冷不热"),
    (25,  "暖的"),
    (30,  "热的"),
    (35,  "闷热"),
    (40,  "烫的"),
]


def _temp_word(temp_c: float) -> str:
    for threshold, word in _TEMP_WORDS:
        if temp_c <= threshold:
            return word
    return "烫的"


def _match_condition(condition: str) -> tuple[str, str]:
    low = condition.lower()
    for prefix, sky, extra in _WEATHER_CONDITION_MAP:
        if prefix in low:
            return sky, extra
    return "说不清什么天", ""


# ── 天气提取 ─────────────────────────────────────────────────────────

_WEATHER_BLOCK_RE = re.compile(
    r"【当前天气】\s*\n(.*?)(?=\n【|\Z)",
    re.DOTALL,
)

_FIELD_PATTERNS = {
    "location":  re.compile(r"地点:\s*(.+)"),
    "condition": re.compile(r"天气:\s*(.+)"),
    "temp":      re.compile(r"温度:\s*([-\d.]+)"),
    "feels":     re.compile(r"体感:\s*([-\d.]+)"),
    "humidity":  re.compile(r"湿度:\s*(\d+)"),
    "wind":      re.compile(r"风速:\s*([\d.]+)"),
}


def extract_weather_from_messages(
    messages: list[dict],
) -> Optional[dict[str, Any]]:
    """从 messages 倒序找最新含天气附加信息的用户消息，解析返回天气数据。

    返回 None 如果找不到或解析失败。
    """
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        text = _content_to_text(content)
        if not text or "当前天气" not in text:
            continue
        try:
            return _parse_weather_block(text)
        except Exception:
            continue
    return None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _parse_weather_block(text: str) -> Optional[dict[str, Any]]:
    m = _WEATHER_BLOCK_RE.search(text)
    if not m:
        return None
    block = m.group(1)

    condition_m = _FIELD_PATTERNS["condition"].search(block)
    temp_m = _FIELD_PATTERNS["temp"].search(block)
    if not condition_m or not temp_m:
        return None

    result: dict[str, Any] = {
        "condition": condition_m.group(1).strip(),
        "temp_c": float(temp_m.group(1)),
    }

    location_m = _FIELD_PATTERNS["location"].search(block)
    if location_m:
        result["location"] = location_m.group(1).strip()

    feels_m = _FIELD_PATTERNS["feels"].search(block)
    if feels_m:
        result["feels_like_c"] = float(feels_m.group(1))

    humidity_m = _FIELD_PATTERNS["humidity"].search(block)
    if humidity_m:
        result["humidity_pct"] = int(humidity_m.group(1))

    wind_m = _FIELD_PATTERNS["wind"].search(block)
    if wind_m:
        result["wind_kph"] = float(wind_m.group(1))

    return result


# ── 天气渲染 ─────────────────────────────────────────────────────────

def _render_weather_scene(weather: dict[str, Any]) -> str:
    """将天气数据渲染成一句氛围句。不提同步、不提"她"。"""
    sky, extra = _match_condition(weather.get("condition", ""))
    temp_c = weather.get("temp_c")
    temp_str = ""
    if temp_c is not None:
        temp_str = _temp_word(temp_c)

    humidity = weather.get("humidity_pct")
    humid_hint = ""
    if humidity is not None and humidity >= 85:
        humid_hint = "空气潮得很。"

    parts = [f"窗外面是海，{sky}。"]
    if extra:
        parts.append(f"{extra}。")
    if humid_hint:
        parts.append(humid_hint)
    if temp_str:
        parts.append(f"{temp_str}。")

    return "".join(parts)


# ── 窗户记忆 — 回忆句 ─────────────────────────────────────────────────
# 上一次的 scene_tag → 这次可能追加的回忆句。只在常规场景时 ~35% 触发。

SCENE_ECHOES: dict[str, list[str]] = {
    "thunderstorm": [
        "上次来的时候打过雷。窗台上还有那天溅进来的水印。",
        "上次那场雷走了。海面恢复了，像什么都没发生过。",
        "上次的闪电把窗玻璃照得发青。这次没有。安静得不一样。",
    ],
    "snow": [
        "上次来的时候下过雪。窗台角落还有一点没干的水。",
        "上次的雪早化了。但窗缝里卡了一小片，干的，像纸。",
        "上次的雪——落在海面上浮了一下就化了。现在海面上什么都没留下。",
    ],
    "deep_sea": [
        "上次窗外是海底。现在又是海面了。不知道刚才是不是做梦。",
        "上次那个深海的光不见了。海面平平的，好像从来没有过。",
        "上次窗外黑的。那个很大的影子——不知道游去哪了。",
    ],
    "sunrise": [
        "上次来的时候刚好日出。那条橙色的光印在眼睛里好久。",
        "上次的日出很短。等转头再看的时候已经变成普通的亮了。",
        "上次那个日出把海面染成金的。就几分钟。现在想起来还是暖的。",
    ],
    "quiet": [
        "光的角度跟上次不一样了。",
        "水杯的影子换了个方向。还是同一片海。",
        "那只小虫子不在了。窗台被风吹干净了。",
    ],
    "normal": [
        "海还是那片海。浪的位置换了。",
        "窗台上的东西没人动过。灰积了一点。",
        "上次那个彩虹不在了。水印还在。",
    ],
    "active": [
        "上次来的时候风挺大的。这次还好。",
        "上次桌上那些纸收好了。不知道谁收的。",
        "上次的浪声很近。这次远了一些。退潮了吧。",
    ],
    "weather": [
        "上次的天气印象还在。不知道外面现在变了没有。",
    ],
}

_ECHO_CHANCE = 0.35

_POOL_TAG_MAP = {
    id(SCENES_THUNDERSTORM): "thunderstorm",
    id(SCENES_SNOW): "snow",
    id(SCENES_SUNRISE): "sunrise",
    id(SCENES_DEEP_SEA): "deep_sea",
}


# ── 场景选择 ─────────────────────────────────────────────────────────


def select_scene(
    charge: float,
    *,
    weather_data: Optional[dict[str, Any]] = None,
    hours_since_last_visit: Optional[float] = None,
    prev_scene: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
    """选一个窗外场景，返回 (scene_text, scene_tag)。

    prev_scene: {"tag": str, "hours_ago": float} — 来自上次 window trace。
    """

    now_cst = now().astimezone(LOCAL_DAY_TZ)
    hour = now_cst.hour
    month = now_cst.month

    candidates: list[tuple[int, tuple]] = []

    candidates.append((10, ("pool", SCENES_THUNDERSTORM)))

    snow_weight = 15 if month in (11, 12, 1, 2) else 6
    candidates.append((snow_weight, ("pool", SCENES_SNOW)))

    if 5 <= hour <= 8:
        candidates.append((18, ("pool", SCENES_SUNRISE)))

    deep_weight = 4
    if 0 <= hour <= 5:
        deep_weight += 8
    if hours_since_last_visit is not None and hours_since_last_visit > 48:
        deep_weight += 6
    candidates.append((deep_weight, ("pool", SCENES_DEEP_SEA)))

    if weather_data is not None:
        candidates.append((12, ("weather", weather_data)))

    rare_total = sum(w for w, _ in candidates)
    normal_weight = max(50, rare_total)
    candidates.append((normal_weight, ("normal", charge)))

    total = sum(w for w, _ in candidates)
    roll = random.randint(1, total)
    cumulative = 0
    chosen = candidates[-1]
    for weight, source in candidates:
        cumulative += weight
        if roll <= cumulative:
            chosen = (weight, source)
            break

    _, source = chosen
    kind = source[0]

    if kind == "pool":
        pool = source[1]
        text = random.choice(pool)
        tag = _POOL_TAG_MAP.get(id(pool), "normal")
        return text, tag
    elif kind == "weather":
        text = _render_weather_scene(source[1])
        return text, "weather"
    else:
        text, tag = _normal_scene(charge)
        text = _maybe_append_echo(text, prev_scene)
        return text, tag


def _normal_scene(charge: float) -> tuple[str, str]:
    if charge < 0.3:
        return random.choice(SCENES_QUIET), "quiet"
    elif charge < 0.7:
        return random.choice(SCENES_NORMAL), "normal"
    else:
        return random.choice(SCENES_ACTIVE), "active"


def _maybe_append_echo(text: str, prev_scene: Optional[dict[str, Any]]) -> str:
    if not prev_scene:
        return text
    prev_tag = prev_scene.get("tag", "")
    echoes = SCENE_ECHOES.get(prev_tag)
    if not echoes:
        return text
    if random.random() > _ECHO_CHANCE:
        return text
    return text + "\n" + random.choice(echoes)
