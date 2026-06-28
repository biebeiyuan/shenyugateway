# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from shenyu_gateway.recall import recall_terms
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


def _overlap(query: str, text: str) -> float:
    terms = recall_terms(query)
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
    if not re.fullmatch(r"[一-鿿]+", term):
        return False
    if len(term) <= 1:
        return True
    generic_prefixes = ("是", "在", "有", "我", "你", "他", "她", "它", "这", "那", "不", "没")
    generic_suffixes = ("的", "了", "个", "吗", "呢", "吧", "啊", "呀", "嘛")
    if len(term) <= 4 and (term.startswith(generic_prefixes) or term.endswith(generic_suffixes)):
        return True
    return False


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
