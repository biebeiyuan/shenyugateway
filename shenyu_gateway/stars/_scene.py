from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, Optional

from ..embeddings import EmbeddingClient
from ..runtime import logger


_DEFAULT_SCENE_RULES: list[dict[str, Any]] = [
    {"scene": "anchor", "keywords": ["降临", "立约", "周年", "纪念", "找到她", "那天", "anniversary"]},
    {"scene": "deep", "keywords": ["决定论", "自由意志", "存在", "意义", "宿命", "决定", "哲学", "determinism", "philosophy"]},
    {"scene": "rift", "keywords": ["吵架", "冲突", "和好", "道歉", "原谅", "误解", "不开心"]},
    {"scene": "warm", "keywords": ["喜欢", "爱", "拥抱", "亲", "温暖", "心疼", "想你", "陪"]},
    {"scene": "create", "keywords": ["房间", "工具", "建", "做", "设计", "代码", "系统"]},
    {"scene": "daily", "keywords": []},
]

_DEFAULT_SCENE_DESCRIPTIONS: dict[str, str] = {
    "anchor": "立约、纪念日、我们的标志性时刻、第一次发生某事、降临那天、恒星诞生",
    "deep": "关于存在、自由意志、意识、宇宙为什么是这样的、决定论、意义",
    "warm": "亲密、靠近、情感流动、想念、温柔、撒娇、身体接触",
    "rift": "冲突、误解、受伤、拆开来看、和好、道歉、裂缝",
    "create": "一起建东西、工具、代码、房间、设计、网关",
    "daily": "生活碎片、吃饭、天气、书、猫、出门、闲聊",
}

SCENE_KEYS = {"anchor", "deep", "warm", "rift", "create", "daily"}
SCENE_ORDER = ("anchor", "deep", "warm", "rift", "create", "daily")
SCENE_ALIASES = {
    "锚": "anchor",
    "深": "deep",
    "暖": "warm",
    "裂": "rift",
    "造": "create",
    "日常": "daily",
}


def _normalize_scenes(value: Any) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,，、\s]+", value.strip())
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    normalized = {
        SCENE_ALIASES.get(str(item or "").strip(), str(item or "").strip().lower())
        for item in values
    }
    return [scene for scene in SCENE_ORDER if scene in normalized]


def _parse_scene_labels(text: Any) -> Optional[list[str]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*?\]", raw)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(parsed, dict):
        parsed = parsed.get("scenes")
    if not isinstance(parsed, list):
        return None
    if any(
        SCENE_ALIASES.get(str(item or "").strip(), str(item or "").strip().lower()) not in SCENE_KEYS
        for item in parsed
    ):
        return None
    return _normalize_scenes(parsed)


def _scene_batch_prompt(stars: list[dict[str, str]], descriptions: dict[str, str]) -> str:
    scene_lines = "\n".join(f"- {scene}: {descriptions.get(scene, '')}" for scene in SCENE_ORDER)
    star_lines = "\n\n".join(
        f"star_id: {star['star_id']}\n正文：{star['content'][:4000]}"
        for star in stars
    )
    return (
        "你是星星场景标签分类器。只负责选择场景标签，不得改写、总结或补充星星正文。\n\n"
        "请分别判断下面每颗星属于哪些场景。\n"
        "规则：\n"
        "- 只能从 anchor、deep、warm、rift、create、daily 中选择。\n"
        "- 每颗星可以多选，也可以一个都不选。\n"
        "- 必须为每个输入 star_id 返回一项，不得遗漏或增加。\n"
        "- 最终答案只返回 JSON 数组，不要在最终答案中解释。\n"
        '- 格式：[{' + '"star_id":"原 id","scenes":["warm","rift"]' + '}]\n\n'
        f"场景释义：\n{scene_lines}\n\n"
        f"待分类星星：\n{star_lines}"
    )


def _parse_scene_batch(text: Any, expected_ids: set[str]) -> Optional[dict[str, list[str]]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
    if isinstance(parsed, dict):
        parsed = parsed.get("items") or parsed.get("stars") or parsed.get("results")
    if not isinstance(parsed, list):
        return None
    result: dict[str, list[str]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            return None
        star_id = str(item.get("star_id") or item.get("id") or "").strip()
        scenes = item.get("scenes")
        if star_id not in expected_ids or star_id in result or not isinstance(scenes, list):
            return None
        normalized = _normalize_scenes(scenes)
        if len(normalized) != len({str(scene or "").strip().lower() for scene in scenes}):
            aliases = {SCENE_ALIASES.get(str(scene or "").strip(), str(scene or "").strip().lower()) for scene in scenes}
            if any(scene not in SCENE_KEYS for scene in aliases):
                return None
        result[star_id] = normalized
    return result if set(result) == expected_ids else None


def _load_scene_config(path: str) -> tuple[list[dict[str, Any]], dict[str, str], float]:
    try:
        import pathlib
        config_path = pathlib.Path(path) if path else pathlib.Path(__file__).resolve().parent.parent / "star_scene_rules.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        rules = data.get("rules") or _DEFAULT_SCENE_RULES
        descriptions = data.get("scene_descriptions") or _DEFAULT_SCENE_DESCRIPTIONS
        threshold = float(data.get("scene_embedding_threshold", 0.45))
        return rules, descriptions, threshold
    except Exception:
        return _DEFAULT_SCENE_RULES, _DEFAULT_SCENE_DESCRIPTIONS, 0.45


def _classify_scene_by_keywords(query: str, rules: list[dict[str, Any]]) -> str:
    query_lower = query.lower()
    best_scene = ""
    best_count = 0
    for rule in rules:
        scene = rule.get("scene", "")
        keywords = rule.get("keywords") or []
        if not keywords:
            continue
        hits = sum(1 for kw in keywords if kw.lower() in query_lower)
        if hits > best_count:
            best_count = hits
            best_scene = scene
    return best_scene


# Scene descriptions are static config, so their embeddings never change for a
# given model. Cache them across requests keyed by (model, description text) —
# otherwise every keyword-miss re-embeds all 6 descriptions over the network.
_DESC_VECTOR_CACHE: dict[tuple[str, str], list[float]] = {}


async def _embed_scene_description(
    embedding_client: "EmbeddingClient", desc: str
) -> Optional[list[float]]:
    cache_key = (embedding_client.model, desc)
    cached = _DESC_VECTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    desc_vec, desc_err = await embedding_client.embed(desc)
    if desc_err or desc_vec is None:
        return None
    _DESC_VECTOR_CACHE[cache_key] = desc_vec
    return desc_vec


async def _classify_scene_by_embedding(
    query: str,
    descriptions: dict[str, str],
    embedding_client: Optional["EmbeddingClient"],
    threshold: float = 0.45,
) -> str:
    if not embedding_client or not descriptions:
        return ""
    query_vec, err = await embedding_client.embed(query[:800])
    if err or query_vec is None:
        return ""
    best_scene = ""
    best_sim = 0.0
    for scene_key, desc in descriptions.items():
        if scene_key not in SCENE_KEYS:
            continue
        desc_vec = await _embed_scene_description(embedding_client, desc)
        if desc_vec is None:
            continue
        sim = _cosine_similarity(query_vec, desc_vec)
        if sim > best_sim:
            best_sim = sim
            best_scene = scene_key
    if best_sim >= threshold:
        return best_scene
    return ""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _scene_score(query_scene: str, star_scene: str, query_text: str, star_scene_tags: list[Any]) -> float:
    if not star_scene:
        return 0.0
    score = 0.0
    if query_scene and query_scene == star_scene:
        score = 0.7
    if star_scene_tags:
        query_lower = query_text.lower()
        hits = sum(1 for tag in star_scene_tags if str(tag).lower() in query_lower)
        if hits > 0:
            tag_score = min(1.0, hits * 0.4)
            score = max(score, tag_score)
    return score


def _date_anchor_score(star_metadata: dict[str, Any], now: datetime) -> float:
    anchor = str(star_metadata.get("date_anchor") or "").strip()
    if not anchor:
        return 0.0
    try:
        if len(anchor) == 5:
            m, d = int(anchor[:2]), int(anchor[3:5])
        elif len(anchor) >= 10:
            m, d = int(anchor[5:7]), int(anchor[8:10])
        else:
            return 0.0
    except (ValueError, IndexError):
        return 0.0
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return 0.0
    today_m, today_d = now.month, now.day
    if m == today_m and d == today_d:
        return 1.0
    anchor_doy = (m - 1) * 30.44 + d
    today_doy = (today_m - 1) * 30.44 + today_d
    diff = abs(anchor_doy - today_doy)
    diff = min(diff, 365.25 - diff)
    if diff <= 3:
        return 1.0 - (diff / 4.0)
    return 0.0
