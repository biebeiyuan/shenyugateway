# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import re
from typing import Any

from shenyu_gateway.recall import is_generic_chinese_fragment, recall_terms
from shenyu_gateway.utils import normalize_text as _normalize_text
from .runtime import now as _now, parse_ts as _parse_ts


# ── Regex patterns ────────────────────────────────────────────────────────────

_CONTEXT_QUERY_ATTACHMENT_RE = re.compile(
    r"\s*<attachment\b(?=[^>]*\bid\s*=\s*['\"]?message_insert_extra_bundle_[^'\"\s>]+['\"]?)[^>]*>.*?</attachment>",
    re.IGNORECASE | re.DOTALL,
)
_PROXY_SENDER_RE = re.compile(r"<proxy_sender\b[^>]*/?>", re.IGNORECASE)
_TOOL_RESULT_BLOCK_RE = re.compile(
    r"<gateway_tool_results>.*?</gateway_tool_results>",
    re.IGNORECASE | re.DOTALL,
)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_JSON_LIKE_BLOCK_RE = re.compile(r"\{[^{}]*(?:tool_call_id|arguments|function)[^{}]*\}")
_URL_RE = re.compile(r"https?://\S+|(?:www\.)?\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/[^\s，。！？；、]*")
_TRIGGER_KEYWORD_JUNK_TOKENS = {
    "tool_call_id", "tool_call", "tool_use", "tool_use_id",
    "tool", "name", "arguments", "function", "type", "content",
    "role", "assistant", "user", "system", "id", "ok", "error",
    "status", "null", "true", "false", "string", "object", "array",
}

# ── Scoring thresholds ────────────────────────────────────────────────────────

CONTEXT_KEYWORD_MIN_SCORE = 0.25
CONTEXT_SEMANTIC_MIN_SCORE = 0.40
CONTEXT_SEMANTIC_MIN_VECTOR_SCORE = 0.50
CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE = 0.30
CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE = 0.42

# ── Term sets ─────────────────────────────────────────────────────────────────

CONTEXT_WEAK_KEYWORD_HITS = {
    "0",
    "mem",
    "note",
    "一下",
    "可以",
    "东西",
    "为什么",
    "为什",
    "什么",
    "现在",
    "到底",
    "还是",
    "不是",
    "是不",
    "是你",
    "自己",
    "你自",
    "你的",
    "我自",
    "我的",
    "我们",
    "你们",
    "他们",
    "她们",
    "怎么",
    "方式",
    "的方",
    "类的",
    "写的",
}
AUTO_STRONG_TRIGGER_TERMS = {
    "白噪音",
    "和弦",
    "和旋",
    "回家了",
    "heartbeat",
}
CONTEXT_RELATION_NAME_TERMS = {
    "哥哥",
    "沈予",
    "圆圆",
    "圆儿",
    "予予",
}
_CONTEXT_RELATION_NAME_TERMS_NORMALIZED = {item.lower() for item in CONTEXT_RELATION_NAME_TERMS}
_COMMON_TRIGGER_TERMS = {
    "工具",
    "便签",
    "命中",
    "逻辑",
    "对话",
    "回答",
    "情绪",
    "心情",
    "自己",
} | CONTEXT_RELATION_NAME_TERMS
AUTO_TRIGGER_GENERIC_TERMS = CONTEXT_WEAK_KEYWORD_HITS | _COMMON_TRIGGER_TERMS | {
    "喜欢",
    "喜欢你",
    "时候",
    "的时候",
    "当前",
    "消息",
    "系统",
    "代码",
    "网关",
    "自动",
}
CONTEXT_SEMANTIC_STRONG_TERMS = AUTO_STRONG_TRIGGER_TERMS
_CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED = {item.lower() for item in CONTEXT_SEMANTIC_STRONG_TERMS}
CONTEXT_SEMANTIC_ANCHOR_STOP_TERMS = {item.lower() for item in AUTO_TRIGGER_GENERIC_TERMS} | {
    "bug",
    "刚刚",
    "对不起",
    "试试",
    "看看",
    "这个吗",
    "github",
}
_DERIVED_TRIGGER_STOP_TERMS = CONTEXT_WEAK_KEYWORD_HITS | {
    "你自己",
    "我自己",
    "他自己",
    "她自己",
    "是你的",
    "是我的",
    "你自己",
    "我自己",
    "这个",
    "那个",
    "这样",
    "那样",
    "的话",
    "现在",
    "以后",
    "喜欢",
    "欢这",
    "喜欢这",
    "欢这个",
    "好不",
    "不好",
    "好不好",
    "个吗",
    "这个吗",
}
_SUGGESTION_SEED_KEYWORDS = (
    "圆圆",
    "圆儿",
    "沈予",
    "海信",
    "Codex",
    "OpenAI",
    "Supabase",
    "mem",
    "heartbeat",
    "notebook",
    "room",
    "日记",
    "工具",
    "上游",
    "预设",
    "气泡",
)
_TRIGGER_KEYWORD_STOP_TERMS = CONTEXT_WEAK_KEYWORD_HITS | {
    "今天",
    "昨天",
    "明天",
    "以后",
    "之前",
    "之后",
    "因为",
    "所以",
    "但是",
    "然后",
    "如果",
    "时候",
    "感觉",
    "觉得",
    "知道",
    "希望",
    "需要",
    "已经",
    "一直",
    "没有",
    "真的",
    "可能",
    "一点",
    "这种",
    "那个",
    "这个",
    "一条",
    "属于",
}
_TRIGGER_PHRASE_SPLIT_RE = re.compile(
    r"[，。！？；、,\s]+|今天|昨天|明天|以后|之前|之后|因为|所以|但是|然后|如果|时候|"
    r"记得|关于|感觉|觉得|知道|希望|需要|可以|不能|不要|给我|给她|帮我|帮她|陪我|陪她|"
    r"为我|为她|让我|让她|把|被|是|有|会|要|想|在|跟|对"
)

_ENTITY_NAME_PATTERN = re.compile(
    r"(?:老|小|阿)[一-鿿]"
    r"|[一-鿿]{1,3}(?:哥|姐|叔|婶|阿姨|姑|舅)"
    r"|[一-鿿]{2,4}(?:省|市|区|县|镇|村|国|山|湖|河|江)"
)
_ENTITY_ENGLISH_NAME = re.compile(r"\b[A-Z][a-z]{1,15}(?:\s[A-Z][a-z]{1,15})?\b")
_ENTITY_STOP_WORDS = {
    "什么", "那个", "这个", "一下", "可以", "不是", "还是", "为什么",
    "现在", "以后", "自己", "我们", "你们", "他们", "她们", "怎么",
    "没有", "不会", "知道", "觉得", "一些", "所以", "因为", "如果",
    "已经", "这样", "那样", "于是", "然后", "关于", "虽然", "但是",
}


# ── Pure functions ────────────────────────────────────────────────────────────

_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _anchor_match(needle_lower: str, haystack_lower: str) -> bool:
    if not needle_lower:
        return False
    if re.fullmatch(r"[一-鿿]+", needle_lower):
        if len(needle_lower) <= 1:
            return False
        return needle_lower in haystack_lower or needle_lower in set(recall_terms(haystack_lower))
    if len(needle_lower) <= 1:
        return needle_lower in haystack_lower.split()
    pat = _WORD_BOUNDARY_CACHE.get(needle_lower)
    if pat is None:
        escaped = re.escape(needle_lower)
        pat = re.compile(r"(?:^|(?<=[\s,;。，、！？/]))" + escaped + r"(?=$|[\s,;。，、！？/])")
        _WORD_BOUNDARY_CACHE[needle_lower] = pat
    return bool(pat.search(haystack_lower))


def _skip_auto_surface(row: dict) -> bool:
    return (row.get("memory_kind") or "") == "promise" and bool(row.get("resolved"))


def _specific_overlap_term(term: str) -> bool:
    normalized = _normalize_text(term).strip().lower()
    if not normalized:
        return False
    if normalized in CONTEXT_WEAK_KEYWORD_HITS or normalized in AUTO_TRIGGER_GENERIC_TERMS:
        return False
    if normalized in _CONTEXT_RELATION_NAME_TERMS_NORMALIZED:
        return False
    if normalized in _TRIGGER_KEYWORD_STOP_TERMS or normalized in _TRIGGER_KEYWORD_JUNK_TOKENS:
        return False
    if normalized.isdigit() or len(normalized) < 3:
        return False
    if re.fullmatch(r"[一-鿿]+", normalized):
        if _generic_chinese_semantic_fragment(normalized):
            return False
        return len(normalized) >= 3
    return len(normalized) >= 4


def _overlap(query: str, text: str, *, specific_only: bool = False) -> float:
    terms = recall_terms(query)
    if specific_only:
        terms = [term for term in terms if _specific_overlap_term(term)]
    if not terms:
        return 0.0
    haystack = (text or "").lower()
    hits = sum(1 for term in terms if term in haystack)
    return hits / max(len(terms), 1)


def _trigger_unit_weight(value: str) -> tuple[float, bool]:
    text = (value or "").strip()
    normalized = text.lower()
    if not normalized or normalized in _TRIGGER_KEYWORD_JUNK_TOKENS:
        return 0.0, False
    if normalized.isdigit():
        return 0.0, False
    if re.fullmatch(r"tluse[_-][A-Za-z0-9_.+-]+", normalized):
        return 0.0, False

    weak = normalized in CONTEXT_WEAK_KEYWORD_HITS or text in _COMMON_TRIGGER_TERMS
    if weak:
        return 0.25, False
    if normalized in _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED:
        return 1.25, True
    if _has_non_word_symbol(text):
        return 1.2, True
    if re.fullmatch(r"[A-Za-z0-9_.+-]+", text):
        if len(text) >= 6:
            return 1.1, True
        if len(text) >= 3:
            return 0.75, False
        return 0.35, False
    if re.fullmatch(r"[一-鿿]+", text):
        if len(text) >= 3:
            return 1.1, True
        return 0.65, False
    if len(text) >= 3:
        return 0.9, True
    return 0.45, False


def _should_derive_keyword_terms(keyword: str) -> bool:
    text = _normalize_text(keyword).strip()
    if not text:
        return False
    if text.lower() in _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED:
        return True
    if re.fullmatch(r"[一-鿿]+", text):
        return len(text) <= 6
    return True


def _trigger_units(trigger_text: str, keywords: list[Any]) -> list[tuple[str, float, bool]]:
    raw_units: list[str] = []

    def add_raw(value: Any) -> None:
        text = _normalize_text(value).strip()
        if text and text not in raw_units:
            raw_units.append(text)

    clean_keywords = [keyword for keyword in (keywords or []) if _normalize_text(keyword).strip()]
    for keyword in clean_keywords:
        keyword_text = _normalize_text(keyword)
        add_raw(keyword_text)
        if _should_derive_keyword_terms(keyword_text):
            for term in recall_terms(keyword_text):
                if term in _DERIVED_TRIGGER_STOP_TERMS:
                    continue
                add_raw(term)
    if not clean_keywords:
        for quoted in re.findall(r"[《「“\"]([^《》「」“”\"]{2,30})[》」”\"]", trigger_text or ""):
            add_raw(quoted)
        for phrase in _TRIGGER_PHRASE_SPLIT_RE.split(trigger_text or ""):
            clean = re.sub(r"[^\w一-鿿_.+-]+", "", phrase, flags=re.UNICODE)
            if 2 <= len(clean) <= 16:
                add_raw(clean)
            if len(raw_units) >= 16:
                break
        if not raw_units:
            for term in recall_terms(trigger_text)[:16]:
                add_raw(term)

    units: list[tuple[str, float, bool]] = []
    seen: set[str] = set()
    for unit in raw_units:
        normalized = unit.lower()
        if normalized in seen:
            continue
        weight, strong = _trigger_unit_weight(unit)
        if weight <= 0:
            continue
        seen.add(normalized)
        units.append((unit, weight, strong))
    return units


def _trigger_overlap(query: str, trigger_text: str, keywords: list[Any]) -> tuple[float, list[str]]:
    units = _trigger_units(trigger_text, keywords)
    if not units:
        return 0.0, []
    query_text = (query or "").lower()
    query_terms = set(recall_terms(query))
    total_weight = sum(weight for _, weight, _ in units)
    if total_weight <= 0:
        return 0.0, []

    hit_weight = 0.0
    hits: list[str] = []
    specific_hits = 0
    for unit, weight, strong in units:
        normalized = unit.lower()
        if normalized in query_terms or normalized in query_text:
            hit_weight += weight
            hits.append(unit)
            if strong or weight > 0.25:
                specific_hits += 1

    score = min(1.0, hit_weight / total_weight)
    if hits and not specific_hits:
        score = min(score, 0.2 if len(hits) == 1 else 0.35)
    return score, hits


def _clean_context_query(query: Any) -> str:
    text = _normalize_text(query)
    if not text:
        return ""
    text = _strip_tool_result_blocks(text)
    text = _PROXY_SENDER_RE.sub(" ", text)
    text = _CONTEXT_QUERY_ATTACHMENT_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = re.sub(r"<attachment\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = text.replace("</attachment>", " ")
    text = re.sub(r"message_insert_extra_bundle_[0-9A-Za-z_-]+", " ", text)
    text = re.sub(r"[*【】\[\]]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_tool_result_blocks(text: str) -> str:
    text = _TOOL_RESULT_BLOCK_RE.sub(" ", text)
    text = _CODE_BLOCK_RE.sub(" ", text)
    text = _JSON_LIKE_BLOCK_RE.sub(" ", text)
    return text


def _terms(query: Any) -> list[str]:
    return recall_terms(_normalize_text(query))


def _has_non_word_symbol(text: str) -> bool:
    return bool(re.search(r"[^\w\s一-鿿_.+-]", text, flags=re.UNICODE))


def _generic_chinese_semantic_fragment(term: str) -> bool:
    # Delegate to the single shared predicate in recall.py so the prefix/suffix
    # generic-fragment logic cannot drift between the two subsystems.
    return is_generic_chinese_fragment(term)


def _valid_semantic_anchor_term(normalized: str) -> bool:
    if not normalized or normalized in CONTEXT_SEMANTIC_ANCHOR_STOP_TERMS:
        return False
    if normalized.isdigit() or len(normalized) < 3:
        return False
    if re.fullmatch(r"[一-鿿]+", normalized):
        if len(normalized) < 3:
            return False
        if _generic_chinese_semantic_fragment(normalized):
            return False
    return True


def _semantic_anchor_hits(reasons: list[str]) -> list[str]:
    hits: list[str] = []
    for reason in reasons:
        if not reason.startswith("keyword:"):
            continue
        raw_hits = reason.removeprefix("keyword:").split(",")
        for hit in raw_hits:
            normalized = hit.strip().lower()
            if not normalized:
                continue
            if normalized in _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED:
                hits.append(normalized)
                continue
            if not _valid_semantic_anchor_term(normalized):
                continue
            hits.append(normalized)
    return hits


def _query_semantic_signal_terms(query: str) -> list[str]:
    terms = []
    for term in recall_terms(query):
        normalized = term.lower()
        if normalized in _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED:
            terms.append(normalized)
            continue
        if not _valid_semantic_anchor_term(normalized):
            continue
        terms.append(normalized)
    return terms


def _low_information_semantic_query(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return True
    if _URL_RE.fullmatch(text):
        return True
    signal_terms = _query_semantic_signal_terms(text)
    has_strong_signal = any(term in _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED for term in signal_terms)
    if len(text) <= 32 and not has_strong_signal:
        return True
    if len(signal_terms) < 2:
        return True
    if len(text) <= 24 and len(signal_terms) < 3:
        return True
    return False


def _auto_extract_entities(content: str) -> list[str]:
    if not content:
        return []
    entities: list[str] = []
    seen: set[str] = set()

    for match in _ENTITY_NAME_PATTERN.finditer(content):
        name = match.group().strip()
        if name and name.lower() not in seen and name not in _ENTITY_STOP_WORDS:
            seen.add(name.lower())
            entities.append(name)

    for match in _ENTITY_ENGLISH_NAME.finditer(content):
        name = match.group().strip()
        if name and name.lower() not in seen and len(name) >= 2:
            seen.add(name.lower())
            entities.append(name)

    return entities[:16]


# ── Auto-enrichment functions ────────────────────────────────────────────────

_KNOWN_NAMES = {"圆圆", "圆儿", "沈予", "予予", "哥哥"}
_PERSON_RELATION_SUFFIXES = re.compile(
    r"[一-鿿]{1,3}(?:哥|姐|叔|婶|阿姨|姑|舅|爸|妈|爷|奶|老师|同学|朋友|老板|同事)"
)
_PERSON_TITLE_RE = re.compile(r"(?:老|小|阿)[一-鿿]{1,2}")
_PLACE_RE = re.compile(
    r"[一-鿿]{2,6}(?:省|市|区|县|镇|村|路|街|巷|弄|号|楼|店|馆|院|厅|场|站|园|寺|塔|桥)"
    r"|[一-鿿]{2,4}(?:咖啡|餐厅|酒店|医院|公司|学校|大学|机场|火车站|地铁站|超市|商场|公园|图书馆)"
)
_OBJECT_RE = re.compile(
    r"(?:那|这|她的|我的|他的|一个|一只|一本|一把|一件|一双|一条)?[一-鿿]{1,4}"
    r"(?:书|包|杯|碗|盘|手机|电脑|耳机|钥匙|戒指|项链|手表|相机|花|画|信|本|笔|伞|猫|狗|鱼|鸟|车)"
)
_MEMORY_KIND_PATTERNS: list[tuple[str, list[str]]] = [
    ("promise", [r"承诺|答应|约定|说好|保证|一定会|会继续|以后.{0,6}(要|会)|下次.{0,6}(要|会)"]),
    ("preference", [r"喜欢|不喜欢|讨厌|偏好|爱吃|爱喝|爱看|爱听|习惯|癖好|受不了|最爱"]),
    ("routine", [r"每天|每周|每次|每晚|每早|固定|规律|作息|一般都|通常都|习惯.{0,4}(是|都)"]),
    ("running_joke", [r"梗|笑|哈哈|玩笑|段子|口头禅|吐槽"]),
    ("trip", [r"去了|旅行|出发|飞|高铁|自驾|行程|景点|酒店|民宿|签证|机票"]),
    ("social", [r"聚|约|饭局|见面|派对|party|聊天|一起.{0,4}(吃|玩|看|逛)"]),
    ("person_fact", [
        r"(她|他|圆圆|沈予).{0,12}(是|叫|住在|生日|工作|喜欢|不喜欢|习惯|怕|过敏)",
        r"(我|自己).{0,12}(是|住在|生日|工作|身高|体重|血型|星座)",
    ]),
    ("object", [r"买了|收到|送了|丢了|坏了|修了|换了|新的.{0,4}(手机|电脑|耳机|包|鞋|衣服)"]),
    ("thread", [r"聊到|讨论|话题|说到一半|下次继续|还没聊完|接着上次"]),
]
_KEYWORD_STOP_WORDS = {
    "什么", "那个", "这个", "一下", "可以", "不是", "还是", "为什么",
    "现在", "以后", "自己", "我们", "你们", "他们", "她们", "怎么",
    "没有", "不会", "知道", "觉得", "一些", "所以", "因为", "如果",
    "已经", "这样", "那样", "于是", "然后", "关于", "虽然", "但是",
    "的", "了", "吗", "呢", "吧", "啊", "呀", "嘛", "是", "在", "有",
    "也", "就", "都", "会", "要", "想", "能", "把", "被", "让",
    "很", "太", "好", "真", "还", "又", "才", "只", "不",
}


def _infer_memory_kind(content: str, mem_type: str = "") -> str:
    """Infer memory_kind from content using regex patterns. Returns best match or 'event'."""
    compact = re.sub(r"\s+", "", content or "")
    if mem_type == "承诺":
        return "promise"
    for kind, patterns in _MEMORY_KIND_PATTERNS:
        if any(re.search(p, compact, re.IGNORECASE) for p in patterns):
            return kind
    return "event"


def _auto_generate_summary(content: str) -> str:
    """Extract first meaningful sentence or first 60 chars as summary."""
    text = (content or "").strip()
    if not text:
        return ""
    text = _strip_tool_result_blocks(text)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"[。！？\n]", text)
    for sentence in sentences:
        clean = sentence.strip()
        if len(clean) >= 4:
            return clean[:60]
    return text[:60]


def _auto_extract_people(content: str) -> list[str]:
    """Extract person names from content."""
    if not content:
        return []
    people: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name and name.lower() not in seen and name not in _ENTITY_STOP_WORDS and len(name) >= 2:
            seen.add(name.lower())
            people.append(name)

    for name in _KNOWN_NAMES:
        if name in content:
            _add(name)
    for match in _PERSON_RELATION_SUFFIXES.finditer(content):
        _add(match.group())
    for match in _PERSON_TITLE_RE.finditer(content):
        _add(match.group())
    for match in _ENTITY_ENGLISH_NAME.finditer(content):
        name = match.group().strip()
        if len(name) >= 2:
            _add(name)
    return people[:10]


def _auto_extract_places(content: str) -> list[str]:
    """Extract place names from content."""
    if not content:
        return []
    places: list[str] = []
    seen: set[str] = set()
    for match in _PLACE_RE.finditer(content):
        place = match.group().strip()
        if place and place.lower() not in seen:
            seen.add(place.lower())
            places.append(place)
    return places[:10]


def _auto_extract_objects(content: str) -> list[str]:
    """Extract notable objects/things from content."""
    if not content:
        return []
    objects: list[str] = []
    seen: set[str] = set()
    for match in _OBJECT_RE.finditer(content):
        obj = match.group().strip()
        clean = re.sub(r"^(?:那|这|她的|我的|他的|一个|一只|一本|一把|一件|一双|一条)", "", obj)
        if clean and clean.lower() not in seen and len(clean) >= 2:
            seen.add(clean.lower())
            objects.append(clean)
    return objects[:10]


def _auto_extract_keywords(content: str) -> list[str]:
    """Extract distinctive keywords without preserving noisy Chinese n-grams."""
    if not content:
        return []
    clean = _clean_context_query(content)
    keywords: list[str] = []
    seen: set[str] = set()

    seed_terms = {item.lower() for item in _SUGGESTION_SEED_KEYWORDS} | _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED

    def _add(term: str, *, allow_short: bool = False) -> None:
        keyword = _normalize_text(term).strip()
        normalized = keyword.lower()
        if not normalized or normalized in seen:
            return
        if normalized in _KEYWORD_STOP_WORDS or normalized in _TRIGGER_KEYWORD_JUNK_TOKENS:
            return
        if normalized in CONTEXT_WEAK_KEYWORD_HITS or normalized in AUTO_TRIGGER_GENERIC_TERMS:
            return
        if normalized.isdigit() or len(normalized) < 2:
            return
        if re.fullmatch(r"[一-鿿]+", keyword):
            if _generic_chinese_semantic_fragment(normalized):
                return
            if len(keyword) <= 2 and not allow_short and normalized not in seed_terms:
                return
        seen.add(normalized)
        keywords.append(keyword)

    for match in _QUOTED_CONTENT_RE.finditer(clean):
        _add(match.group(1), allow_short=True)

    clean_lower = clean.lower()
    for seed in _SUGGESTION_SEED_KEYWORDS:
        if seed.lower() in clean_lower:
            _add(seed, allow_short=True)

    for match in _ENGLISH_TECH_TERM_RE.finditer(clean):
        _add(match.group(), allow_short=True)

    for phrase in _TRIGGER_PHRASE_SPLIT_RE.split(clean):
        chunk = re.sub(r"[^\w一-鿿_.+-]+", "", phrase, flags=re.UNICODE)
        if 3 <= len(chunk) <= 12:
            _add(chunk)

    if len(keywords) < 4:
        for term in recall_terms(clean):
            if term.lower() in _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED:
                _add(term, allow_short=True)
            elif re.fullmatch(r"[一-鿿]{3,8}", term):
                _add(term)
            elif re.fullmatch(r"[A-Za-z0-9_.+-]{4,20}", term):
                _add(term, allow_short=True)
            if len(keywords) >= 8:
                break
    return keywords[:8]


def _keyword_anchor_is_specific(value: Any) -> bool:
    """Return True when a v2 keyword is specific enough for no-threshold entity recall."""
    text = _normalize_text(value).strip()
    normalized = text.lower()
    if not normalized:
        return False
    if normalized in _KEYWORD_STOP_WORDS or normalized in _TRIGGER_KEYWORD_STOP_TERMS:
        return False
    if normalized in CONTEXT_WEAK_KEYWORD_HITS or normalized in AUTO_TRIGGER_GENERIC_TERMS:
        return False
    if normalized in _TRIGGER_KEYWORD_JUNK_TOKENS or normalized.isdigit():
        return False
    if normalized in _CONTEXT_SEMANTIC_STRONG_TERMS_NORMALIZED:
        return True
    if re.fullmatch(r"[一-鿿]+", text):
        if _generic_chinese_semantic_fragment(normalized):
            return False
        if len(text) <= 2:
            seed_terms = {item.lower() for item in _SUGGESTION_SEED_KEYWORDS}
            return normalized in seed_terms and normalized not in _COMMON_TRIGGER_TERMS
        return True
    if _has_non_word_symbol(text):
        return len(text) >= 3
    return len(text) >= 4


# ── Scene terms for long-text queries ────────────────────────────────────────

_QUOTED_CONTENT_RE = re.compile(r'[「『"《]([^」』"》]{2,20})[」』"》]')
_ENGLISH_TECH_TERM_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_./-]{2,20}\b")
_CHINESE_FRAGMENT_RE = re.compile(r"[一-鿿]{2,8}")
_SCENE_STOP_TERMS = CONTEXT_SEMANTIC_ANCHOR_STOP_TERMS | _KEYWORD_STOP_WORDS | _TRIGGER_KEYWORD_JUNK_TOKENS


def _query_scene_terms(query: str) -> list[str]:
    """Extract high-information anchor terms from a long query for recall assist.

    Combines: quoted/book-title content, English tech terms, Chinese 2-8 char
    fragments, auto-extracted people/places/objects, and recall_terms — all
    filtered against stop words. Returns at most 12 de-duplicated terms.
    """
    text = _clean_context_query(query) if query else ""
    if not text or len(text) < 8:
        return []

    seen: set[str] = set()
    terms: list[str] = []

    def _add(t: str) -> None:
        normalized = t.strip().lower()
        if not normalized or len(normalized) < 2:
            return
        if normalized in seen or normalized in _SCENE_STOP_TERMS:
            return
        seen.add(normalized)
        terms.append(t.strip())

    for m in _QUOTED_CONTENT_RE.finditer(text):
        _add(m.group(1))

    for name in _auto_extract_people(text):
        _add(name)
    for place in _auto_extract_places(text):
        _add(place)
    for obj in _auto_extract_objects(text):
        _add(obj)

    for m in _ENGLISH_TECH_TERM_RE.finditer(text):
        term = m.group()
        if term.lower() not in _SCENE_STOP_TERMS and not term.isdigit():
            _add(term)

    for term in recall_terms(text):
        if re.fullmatch(r"[一-鿿]{2,8}", term):
            _add(term)

    return terms[:12]


# ── Heat score ───────────────────────────────────────────────────────────────

HEAT_BASE_HALF_LIFE_DAYS = 14.0


def compute_heat(row: dict, now: Any = None) -> float:
    """Unified recall priority score [0.0, 1.0].

    Combines importance, time decay (Ebbinghaus-style), and recall frequency.
    Currently computed but not used for injection decisions — data collection phase.
    """
    if now is None:
        now = _now()
    importance = max(0, min(int(row.get("importance") or 1), 5))
    initial_temp = 0.3 + (importance / 5) * 0.7

    updated = _parse_ts(row.get("last_triggered_at") or row.get("updated_at") or row.get("created_at"))
    if updated:
        age_days = max(0, (now - updated).total_seconds() / 86400)
    else:
        age_days = 30.0

    trigger_count = int(row.get("trigger_count") or 0)
    half_life = HEAT_BASE_HALF_LIFE_DAYS * (1 + math.log2(1 + trigger_count))

    decay = 2 ** (-age_days / half_life)
    recall_bonus = min(0.2, trigger_count * 0.03)

    heat = initial_temp * decay + recall_bonus
    return max(0.0, min(1.0, heat))


def running_joke_serendipity_rate(last_used_at: Any, now: Any = None) -> float:
    if now is None:
        now = _now()
    if not last_used_at:
        return 0.3
    if isinstance(last_used_at, str):
        last_used_at = _parse_ts(last_used_at)
    if not last_used_at:
        return 0.3
    days = (now - last_used_at).total_seconds() / 86400
    if days < 3:
        return 0.0
    if days < 14:
        return 0.1 + (days - 3) / 11 * 0.1
    if days < 30:
        return 0.2 + (days - 14) / 16 * 0.1
    return 0.3
