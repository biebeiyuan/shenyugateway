from __future__ import annotations

import random
import re
from datetime import timedelta
from typing import Any, Optional

from shenyu_gateway.recall import RecallIndexService, recall_terms
from shenyu_gateway.runtime import logger
from shenyu_gateway.utils import normalize_text as _normalize_text
from shenyu_gateway.utils import shorten as _shorten
from .runtime import iso_now, now as _now, parse_ts as _parse_ts


MEM_NOTE_TYPES = ("她为我做的事", "我为她做的事", "关于她的事实", "关于我的事", "心里那一档", "承诺")
MEM_NOTE_STATUSES = ("captured", "active", "paused", "archived")
MEM_NOTE_MEMORY_KINDS = (
    "event", "person_fact", "social", "trip", "object", "preference",
    "routine", "promise", "running_joke", "thread",
)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_CONTEXT_QUERY_ATTACHMENT_RE = re.compile(
    r"\s*<attachment\b(?=[^>]*\bid\s*=\s*['\"]?message_insert_extra_bundle_[^'\"\s>]+['\"]?)[^>]*>.*?</attachment>",
    re.IGNORECASE | re.DOTALL,
)
_PROXY_SENDER_RE = re.compile(r"<proxy_sender\b[^>]*/?>", re.IGNORECASE)
# 剥 gateway_tool_results / 代码块 / JSON 块，防止切词器把里面的字段名当关键词
_TOOL_RESULT_BLOCK_RE = re.compile(
    r"<gateway_tool_results>.*?</gateway_tool_results>",
    re.IGNORECASE | re.DOTALL,
)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_JSON_LIKE_BLOCK_RE = re.compile(r"\{[^{}]*(?:tool_call_id|arguments|function)[^{}]*\}")
_URL_RE = re.compile(r"https?://\S+|(?:www\.)?\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/[^\s，。！？；、]*")
# 切词时要过滤的 JSON / 协议字段名
_TRIGGER_KEYWORD_JUNK_TOKENS = {
    "tool_call_id", "tool_call", "tool_use", "tool_use_id",
    "tool", "name", "arguments", "function", "type", "content",
    "role", "assistant", "user", "system", "id", "ok", "error",
    "status", "null", "true", "false", "string", "object", "array",
}
CONTEXT_KEYWORD_MIN_SCORE = 0.25
CONTEXT_SEMANTIC_MIN_SCORE = 0.40
CONTEXT_SEMANTIC_MIN_VECTOR_SCORE = 0.50
CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE = 0.30
CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE = 0.42
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
MEM_NOTE_PATCH_FIELDS = {
    "content",
    "mem_type",
    "trigger_text",
    "trigger_keywords",
    "entities",
    "status",
    "cooldown_hours",
    "review_note",
    # v2 structured fields
    "summary",
    "memory_kind",
    "people",
    "places",
    "objects",
    "keywords",
    "event_time",
    "importance",
    "mention_count",
    "promotion_score",
    "decay_after",
    # promise
    "promise_text",
    "trigger_scenarios",
    "due_hint",
    "resolved",
    "resolved_at",
    "next_action",
    "privacy_level",
    # running_joke
    "joke_text",
    "scene_tags",
    "last_used_at",
    # routine
    "routine_domain",
    "pattern",
    "phase",
    "constraints",
    "last_confirmed_at",
    # thread
    "topic",
    "last_position",
    "open_questions",
    "next_prompt",
    "thread_resolved",
}
MEM_NOTE_BULK_UPDATE_MAX = 200
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


_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _anchor_match(needle_lower: str, haystack_lower: str) -> bool:
    if not needle_lower:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]+", needle_lower):
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
    if re.fullmatch(r"[\u4e00-\u9fff]+", text):
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
    if re.fullmatch(r"[\u4e00-\u9fff]+", text):
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
            clean = re.sub(r"[^\w\u4e00-\u9fff_.+-]+", "", phrase, flags=re.UNICODE)
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
        # A single generic trigger like "工具" should not make a note jump to full score.
        score = min(score, 0.2 if len(hits) == 1 else 0.35)
    return score, hits


def _normalize_note_id(value: Any) -> str:
    raw = _normalize_text(value).strip()
    match = _UUID_RE.search(raw)
    return match.group(0) if match else raw


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
    return bool(re.search(r"[^\w\s\u4e00-\u9fff_.+-]", text, flags=re.UNICODE))


def _generic_chinese_semantic_fragment(term: str) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fff]+", term):
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
    if re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
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


# Select clause covering all v2 fields for list/get/search queries
_MEM_NOTE_SELECT_FIELDS = (
    "id,session_tag,content,mem_type,trigger_text,trigger_keywords,entities,status,"
    "cooldown_hours,last_triggered_at,trigger_count,source_model,source_session_id,"
    "source_excerpt,review_note,reviewed_at,created_at,updated_at,"
    "summary,memory_kind,people,places,objects,keywords,event_time,"
    "importance,confidence,mention_count,promotion_score,decay_after,"
    "promise_text,trigger_scenarios,due_hint,resolved,resolved_at,next_action,privacy_level,"
    "joke_text,scene_tags,last_used_at,"
    "routine_domain,pattern,phase,constraints,last_confirmed_at,"
    "topic,last_position,open_questions,next_prompt,thread_resolved"
)

_MEM_NOTE_SELECT_FIELDS_LIGHT = (
    "id,session_tag,content,mem_type,trigger_text,trigger_keywords,entities,status,"
    "cooldown_hours,last_triggered_at,trigger_count,source_model,created_at,updated_at,"
    "summary,memory_kind,people,places,objects,keywords,event_time,"
    "importance,mention_count,promotion_score,"
    "promise_text,resolved,joke_text,scene_tags,last_used_at,"
    "routine_domain,pattern,topic,thread_resolved"
)


class MemNoteService:
    def __init__(self, cfg: Any, supabase_client: Any):
        self.cfg = cfg
        self.supabase = supabase_client


    async def search_notes(
        self,
        query: str,
        session_tag: Optional[str] = None,
        limit: int = 3,
        mark_triggered: bool = True,
        min_score: Optional[float] = None,
        session_id: Optional[str] = None,
        store: Any = None,
        cooldown_hours: Optional[int] = None,
        dedupe_turns: Optional[int] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "note": "Supabase is not configured."}
        query = (query or "").strip()
        if not query:
            return {"ok": True, "query": query, "count": 0, "items": []}

        params: dict[str, str] = {
            "status": "eq.active",
            "order": "updated_at.desc",
            "limit": "160",
            "select": _MEM_NOTE_SELECT_FIELDS_LIGHT,
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        rows = await self.supabase.query("shenyu_mem_notes", params)

        min_score = (
            self._float_range(min_score, 0.45, 0.0, 1.0)
            if min_score is not None
            else float(getattr(self.cfg, "mem_note_min_score", 0.45) or 0.45)
        )
        scored: list[tuple[float, dict, list[str]]] = []
        for row in rows:
            if _skip_auto_surface(row):
                continue
            if self._should_skip_retrigger(
                row,
                session_id=session_id,
                store=store,
                cooldown_hours=cooldown_hours,
                dedupe_turns=dedupe_turns,
            ):
                continue
            score, reasons = self._score(query, row)
            if score >= min_score:
                scored.append((score, row, reasons))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[: max(1, min(int(limit or 3), 5))]
        items = [self._public_search_item(row, reasons) for _, row, reasons in selected]
        if mark_triggered and items:
            await self._mark_triggered([row for _, row, _ in selected])
        return {"ok": True, "query": query, "count": len(items), "items": items}

    async def search_notes_contextual(
        self,
        query: str,
        session_tag: Optional[str] = None,
        limit: int = 3,
        mark_triggered: bool = True,
        recall_service: Optional[RecallIndexService] = None,
        session_id: Optional[str] = None,
        store: Any = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "note": "Supabase is not configured."}

        clean_query = _clean_context_query(query)
        if not clean_query:
            return {"ok": True, "query": clean_query, "count": 0, "items": []}

        target_limit = max(1, min(int(limit or 3), 5))

        # Load active notes once for entity matching
        active_rows = await self._load_active_rows(session_tag)

        # --- Layer 0: running_joke serendipity (scene_tag match + random gate) ---
        joke_items = self._running_joke_serendipity_matches(
            clean_query, active_rows, session_id=session_id, store=store
        )
        items = joke_items[:1]
        selected_ids = {str(item.get("id") or "") for item in items if item.get("id")}

        # --- Layer 1: entity match (precise, no threshold) ---
        entity_items = self._entity_match_notes(
            clean_query,
            active_rows,
            session_id=session_id,
            store=store,
            exclude_ids=selected_ids,
        )
        for ent_item in entity_items:
            ent_id = str(ent_item.get("id") or "")
            if ent_id and ent_id not in selected_ids:
                items.append(ent_item)
                selected_ids.add(ent_id)
                if len(items) >= target_limit:
                    break

        # --- Layer 2: keyword search (fill remaining slots) ---
        if len(items) < target_limit:
            keyword_min_score = self._float_range(
                getattr(self.cfg, "mem_note_context_keyword_min_score", CONTEXT_KEYWORD_MIN_SCORE),
                CONTEXT_KEYWORD_MIN_SCORE,
                0.0,
                1.0,
            )
            keyword_result = await self.search_notes(
                clean_query,
                session_tag=session_tag,
                limit=target_limit,
                mark_triggered=False,
                min_score=keyword_min_score,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
            )
            for kw_item in keyword_result.get("items") or []:
                kw_id = str(kw_item.get("id") or "")
                if kw_id and kw_id not in selected_ids:
                    items.append(kw_item)
                    selected_ids.add(kw_id)
                    if len(items) >= target_limit:
                        break

        # --- Layer 3: semantic search (anchored rerank only, not slot-filler) ---
        # Semantic results are only added when they have strong anchor support
        # (is_strong_semantic or is_anchored_semantic via _semantic_search_notes).
        # Cap at 1 item to avoid dominating the recall window unanchored.
        if not _low_information_semantic_query(clean_query):
            semantic_items = await self._semantic_search_notes(
                clean_query,
                session_tag=session_tag,
                limit=1,
                exclude_ids=selected_ids,
                recall_service=recall_service,
                session_id=session_id,
                store=store,
            )
            for sem_item in semantic_items:
                sem_id = str(sem_item.get("id") or "")
                if sem_id and sem_id not in selected_ids and len(items) < target_limit:
                    items.append(sem_item)
                    selected_ids.add(sem_id)

        items = items[:target_limit]
        if mark_triggered and items:
            note_ids = [str(item.get("id") or "") for item in items if item.get("id")]
            rows_by_id = await self._get_notes_by_ids(note_ids)
            await self._mark_triggered([rows_by_id[note_id] for note_id in note_ids if note_id in rows_by_id])

        return {"ok": True, "query": clean_query, "count": len(items), "items": items}

    async def list_notes(
        self,
        status: str = "captured",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        mem_type: Optional[str] = None,
        memory_kind: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "items": [], "error": "Supabase is not configured."}
        status = self._status(status, fallback="captured", allow_all=True)
        params: dict[str, str] = {
            "order": "updated_at.desc",
            "limit": str(max(1, min(int(limit or 50), 200))),
            "select": _MEM_NOTE_SELECT_FIELDS,
        }
        if status != "all":
            params["status"] = f"eq.{status}"
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        if mem_type and mem_type in MEM_NOTE_TYPES:
            params["mem_type"] = f"eq.{mem_type}"
        if memory_kind and memory_kind in MEM_NOTE_MEMORY_KINDS:
            params["memory_kind"] = f"eq.{memory_kind}"
        rows = await self.supabase.query("shenyu_mem_notes", params)

        terms = _terms(q)
        if terms:
            rows = [
                row
                for row in rows
                if any(term in self._search_text(row).lower() for term in terms)
            ]
        items = [self._public_list_item(row) for row in rows]
        return {"ok": True, "items": items, "status": status, "count": len(items)}

    async def create_note(
        self,
        content: Any,
        session_tag: Optional[str] = None,
        mem_type: Optional[str] = None,
        trigger_text: Any = "",
        trigger_keywords: Any = None,
        entities: Any = None,
        status: str = "active",
        cooldown_hours: Any = None,
        review_note: Any = "",
        replaces: Optional[list[Any]] = None,
        source_model: str = "tool:shenyu_write_mem_note",
        # v2 fields
        summary: Any = None,
        memory_kind: Optional[str] = None,
        people: Any = None,
        places: Any = None,
        objects: Any = None,
        keywords: Any = None,
        event_time: Any = None,
        importance: Any = None,
        # promise
        promise_text: Any = None,
        trigger_scenarios: Any = None,
        due_hint: Any = None,
        resolved: Any = None,
        next_action: Any = None,
        privacy_level: Any = None,
        # running_joke
        joke_text: Any = None,
        scene_tags: Any = None,
        # routine
        routine_domain: Any = None,
        pattern: Any = None,
        phase: Any = None,
        constraints: Any = None,
        # thread
        topic: Any = None,
        last_position: Any = None,
        open_questions: Any = None,
        next_prompt: Any = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        normalized_content = _normalize_text(content).strip()
        if not normalized_content:
            return {"ok": False, "error": "content is required."}

        resolved_status = self._status(status, fallback="captured")
        resolved_session_tag = (session_tag or "default").strip() or "default"
        default_cooldown = self._default_cooldown_hours()
        payload: dict[str, Any] = {
            "session_tag": resolved_session_tag,
            "content": normalized_content,
            "status": resolved_status,
            "cooldown_hours": self._int_range(cooldown_hours, default_cooldown, 0, 8760),
            "source_model": source_model,
        }

        resolved_type = self._mem_type(mem_type, allow_empty=True)
        if resolved_status == "active" and not resolved_type:
            resolved_type = "心里那一档"
        if resolved_type:
            payload["mem_type"] = resolved_type

        normalized_trigger = _normalize_text(trigger_text).strip()
        resolved_trigger_keywords = self._keyword_list(trigger_keywords)
        if resolved_status == "active" and not normalized_trigger and not resolved_trigger_keywords:
            normalized_trigger = normalized_content
        if normalized_trigger:
            payload["trigger_text"] = normalized_trigger

        if resolved_trigger_keywords:
            payload["trigger_keywords"] = resolved_trigger_keywords

        resolved_entities = self._entity_list(entities)
        if not resolved_entities:
            resolved_entities = _auto_extract_entities(normalized_content)
        if resolved_entities:
            payload["entities"] = resolved_entities

        normalized_review_note = _normalize_text(review_note).strip()
        if normalized_review_note:
            payload["review_note"] = normalized_review_note
            payload["reviewed_at"] = iso_now()

        # v2 structured fields
        normalized_summary = _normalize_text(summary).strip() if summary else ""
        if normalized_summary:
            payload["summary"] = normalized_summary
        resolved_kind = self._memory_kind(memory_kind)
        if resolved_kind:
            payload["memory_kind"] = resolved_kind
        resolved_people = self._entity_list(people)
        if resolved_people:
            payload["people"] = resolved_people
        resolved_places = self._entity_list(places)
        if resolved_places:
            payload["places"] = resolved_places
        resolved_objects = self._entity_list(objects)
        if resolved_objects:
            payload["objects"] = resolved_objects
        resolved_keywords = self._keyword_list(keywords)
        if resolved_keywords:
            payload["keywords"] = resolved_keywords
        normalized_event_time = _normalize_text(event_time).strip() if event_time else ""
        if normalized_event_time:
            payload["event_time"] = normalized_event_time
        if importance is not None:
            payload["importance"] = self._int_range(importance, 1, 0, 5)

        # promise fields
        normalized_promise = _normalize_text(promise_text).strip() if promise_text else ""
        if normalized_promise:
            payload["promise_text"] = normalized_promise
        resolved_scenarios = self._keyword_list(trigger_scenarios)
        if resolved_scenarios:
            payload["trigger_scenarios"] = resolved_scenarios
        normalized_due = _normalize_text(due_hint).strip() if due_hint else ""
        if normalized_due:
            payload["due_hint"] = normalized_due
        if resolved is not None:
            payload["resolved"] = bool(resolved)
        normalized_next_action = _normalize_text(next_action).strip() if next_action else ""
        if normalized_next_action:
            payload["next_action"] = normalized_next_action
        normalized_privacy = _normalize_text(privacy_level).strip() if privacy_level else ""
        if normalized_privacy:
            payload["privacy_level"] = normalized_privacy

        # running_joke fields
        normalized_joke = _normalize_text(joke_text).strip() if joke_text else ""
        if normalized_joke:
            payload["joke_text"] = normalized_joke
        resolved_scene_tags = self._keyword_list(scene_tags)
        if resolved_scene_tags:
            payload["scene_tags"] = resolved_scene_tags

        # routine fields
        normalized_domain = _normalize_text(routine_domain).strip() if routine_domain else ""
        if normalized_domain:
            payload["routine_domain"] = normalized_domain
        normalized_pattern = _normalize_text(pattern).strip() if pattern else ""
        if normalized_pattern:
            payload["pattern"] = normalized_pattern
        normalized_phase = _normalize_text(phase).strip() if phase else ""
        if normalized_phase:
            payload["phase"] = normalized_phase
        resolved_constraints = self._keyword_list(constraints)
        if resolved_constraints:
            payload["constraints"] = resolved_constraints

        # thread fields
        normalized_topic = _normalize_text(topic).strip() if topic else ""
        if normalized_topic:
            payload["topic"] = normalized_topic
        normalized_position = _normalize_text(last_position).strip() if last_position else ""
        if normalized_position:
            payload["last_position"] = normalized_position
        resolved_questions = self._keyword_list(open_questions)
        if resolved_questions:
            payload["open_questions"] = resolved_questions
        normalized_next_prompt = _normalize_text(next_prompt).strip() if next_prompt else ""
        if normalized_next_prompt:
            payload["next_prompt"] = normalized_next_prompt

        active_error = self._active_validation_error(payload)
        if active_error:
            return {"ok": False, "error": active_error}

        row = await self.supabase.insert("shenyu_mem_notes", payload)

        archived_ids: list[str] = []
        if replaces:
            new_id = row.get("id") if isinstance(row, dict) else ""
            for raw_old_id in replaces:
                old_id = _normalize_note_id(raw_old_id)
                if not old_id:
                    continue
                try:
                    await self.supabase.update(
                        "shenyu_mem_notes",
                        {"id": old_id},
                        {"status": "archived", "review_note": f"merged into {new_id}"},
                    )
                    archived_ids.append(old_id)
                except Exception:
                    logger.warning("[MemNote] Failed to archive replaced note %s", old_id)

        result: dict[str, Any] = {
            "ok": True,
            "note_id": row.get("id") if isinstance(row, dict) else None,
            "note": row,
        }
        if archived_ids:
            result["replaced_ids"] = archived_ids
            result["replaced_count"] = len(archived_ids)
        return result

    async def update_note(self, note_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        note_id = _normalize_note_id(note_id)
        if not note_id:
            return {"ok": False, "error": "note_id is required."}
        current = await self._get_note(note_id)
        if not current:
            return {"ok": False, "error": "note not found."}
        update, error = self._prepare_note_update(current, patch)
        if error:
            return {"ok": False, "error": error}
        rows = await self.supabase.update("shenyu_mem_notes", {"id": note_id}, update)
        return {"ok": True, "note_id": note_id, "updated": rows}

    async def bulk_update_notes(
        self,
        ids: Optional[list[Any]] = None,
        patch: Optional[dict[str, Any]] = None,
        updates: Optional[list[dict[str, Any]]] = None,
        use_suggestions: bool = False,
        source_status: Optional[str] = None,
        exclude_ids: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}

        if source_status:
            return {
                "ok": False,
                "error": "bulk update by source_status is disabled; pass explicit ids or updates.",
                "requested_count": 0,
                "updated_count": 0,
                "failed_count": 0,
                "updated_ids": [],
                "failures": [],
            }

        specs = self._bulk_update_specs(ids=ids, patch=patch, updates=updates)
        if not specs:
            return {
                "ok": False,
                "error": "bulk update requires ids+patch or updates.",
                "requested_count": 0,
                "updated_count": 0,
                "failed_count": 0,
                "updated_ids": [],
                "failures": [],
            }
        if len(specs) > MEM_NOTE_BULK_UPDATE_MAX:
            return {
                "ok": False,
                "error": f"bulk update supports at most {MEM_NOTE_BULK_UPDATE_MAX} notes.",
                "requested_count": len(specs),
                "max_count": MEM_NOTE_BULK_UPDATE_MAX,
                "updated_count": 0,
                "failed_count": len(specs),
                "updated_ids": [],
                "failures": [],
            }

        note_ids: list[str] = []
        seen: set[str] = set()
        for note_id, _ in specs:
            if note_id and note_id not in seen:
                seen.add(note_id)
                note_ids.append(note_id)
        rows_by_id = await self._get_notes_by_ids(note_ids)

        updated: list[str] = []
        failures: list[dict[str, str]] = []
        for note_id, raw_patch in specs:
            if not note_id:
                failures.append({"id": "", "error": "note_id is required."})
                continue
            current = rows_by_id.get(note_id)
            if not current:
                failures.append({"id": note_id, "error": "note not found."})
                continue
            effective_patch = dict(raw_patch)
            if use_suggestions:
                effective_patch = self._patch_with_suggestions(current, effective_patch)
            update, error = self._prepare_note_update(current, effective_patch)
            if error:
                failures.append({"id": note_id, "error": error})
                continue
            try:
                await self.supabase.update("shenyu_mem_notes", {"id": note_id}, update)
                updated.append(note_id)
                rows_by_id[note_id] = {**current, **update}
            except Exception as exc:
                failures.append({"id": note_id, "error": str(exc)})

        return {
            "ok": not failures,
            "requested_count": len(specs),
            "updated_count": len(updated),
            "failed_count": len(failures),
            "updated_ids": updated,
            "failures": failures,
        }

    async def delete_note(self, note_id: str) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        note_id = _normalize_note_id(note_id)
        if not note_id:
            return {"ok": False, "error": "note_id is required."}
        rows = await self.supabase.delete("shenyu_mem_notes", {"id": note_id})
        return {"ok": True, "note_id": note_id, "deleted": rows}

    async def legacy_atomic_memories(
        self,
        limit: int = 30,
        session_tag: Optional[str] = None,
        q: str = "",
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "items": [], "error": "Supabase is not configured."}
        params: dict[str, str] = {
            "order": "created_at.desc",
            "limit": str(max(1, min(int(limit or 30), 100))),
            "select": (
                "id,session_tag,subject,owner,content_surface,time_hint,memory_type,"
                "tier,importance,entities_json,tags_json,source_model,status,created_at,updated_at"
            ),
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        rows = await self.supabase.query("atomic_memories", params)
        terms = _terms(q)
        if terms:
            rows = [
                row
                for row in rows
                if any(term in self._legacy_search_text(row).lower() for term in terms)
            ]
        items = []
        for row in rows:
            item = dict(row)
            item.pop("quote", None)
            item.pop("source_excerpt", None)
            items.append(item)
        return {"ok": True, "count": len(items), "items": items}

    def render_notes_for_context(self, notes: list[dict[str, Any]]) -> str:
        if not notes:
            return ""
        lines: list[str] = []
        for note in notes:
            summary = (note.get("summary") or "").strip()
            content = _shorten(note.get("content") or "", 200)
            text = summary or content
            if not text:
                continue
            anchors: list[str] = []
            for person in (note.get("people") or [])[:2]:
                anchors.append(f"人：{person}")
            for place in (note.get("places") or [])[:1]:
                anchors.append(f"地：{place}")
            for obj in (note.get("objects") or [])[:1]:
                anchors.append(f"物：{obj}")
            anchor_suffix = f"（{'；'.join(anchors)}）" if anchors else ""
            lines.append(f"（{text}{anchor_suffix}）")
        return "\n".join(lines)


    def _score(self, query: str, row: dict) -> tuple[float, list[str]]:
        keywords = row.get("trigger_keywords") or []
        trigger_text = row.get("trigger_text") or ""
        content = row.get("content") or ""
        mem_type = row.get("mem_type") or ""

        trigger_score, trigger_hits = _trigger_overlap(query, trigger_text, keywords)
        content_score = _overlap(query, content)
        type_score = _overlap(query, mem_type)
        recency_score = self._recency_score(row.get("updated_at") or row.get("created_at"))
        never_seen_bonus = 0.05 if not row.get("last_triggered_at") else 0.0

        anchor_score, anchor_hits = self._anchor_overlap(query, row)

        score = min(
            1.0,
            trigger_score * 0.50
            + content_score * 0.30
            + anchor_score * 0.10
            + type_score * 0.02
            + recency_score * 0.03
            + never_seen_bonus,
        )
        reasons = []
        if trigger_score > 0:
            reasons.append("trigger" + (":" + ",".join(trigger_hits[:5]) if trigger_hits else ""))
        if anchor_score > 0:
            reasons.append("anchor" + (":" + ",".join(anchor_hits[:3]) if anchor_hits else ""))
        if content_score > 0:
            reasons.append("content")
        if type_score > 0:
            reasons.append("type")
        if never_seen_bonus:
            reasons.append("not recently surfaced")
        return score, reasons or ["soft match"]

    def _anchor_overlap(self, query: str, row: dict) -> tuple[float, list[str]]:
        query_lower = query.lower()
        all_anchors: list[str] = []
        for field in ("people", "places", "objects", "keywords"):
            all_anchors.extend(row.get(field) or [])
        if not all_anchors:
            return 0.0, []
        hits: list[str] = []
        for anchor in all_anchors:
            if _anchor_match(anchor.lower(), query_lower):
                hits.append(anchor)
        if not hits:
            return 0.0, []
        return min(1.0, len(hits) / max(1, len(all_anchors)) + 0.3), hits

    def _public_search_item(self, row: dict, reasons: list[str]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "session_tag": row.get("session_tag"),
            "content": row.get("content") or "",
            "mem_type": row.get("mem_type") or "",
            "trigger_text": row.get("trigger_text") or "",
            "trigger_keywords": row.get("trigger_keywords") or [],
            "entities": row.get("entities") or [],
            "matched_by": reasons,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            # v2 structured fields
            "summary": row.get("summary") or "",
            "memory_kind": row.get("memory_kind") or "",
            "people": row.get("people") or [],
            "places": row.get("places") or [],
            "objects": row.get("objects") or [],
            "keywords": row.get("keywords") or [],
            "event_time": row.get("event_time"),
            "importance": row.get("importance"),
            "joke_text": row.get("joke_text") or "",
            "scene_tags": row.get("scene_tags") or [],
            "last_used_at": row.get("last_used_at"),
        }

    def _public_list_item(self, row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        suggestions = self.suggest_note_fields(row)
        item["suggested_mem_type"] = suggestions["mem_type"]
        item["suggested_trigger_text"] = suggestions["trigger_text"]
        item["suggested_trigger_keywords"] = suggestions["trigger_keywords"]
        item["suggestion_reason"] = suggestions["reason"]
        return item

    def suggest_note_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        content = _normalize_text(row.get("content")).strip()
        source_excerpt = _normalize_text(row.get("source_excerpt")).strip()
        review_note = _normalize_text(row.get("review_note")).strip()
        suggestion_text = "\n".join(part for part in [content, source_excerpt, review_note] if part)
        # 切词和分类前都剥掉工具返回块 / 代码块，防止 JSON 字段或工具结果影响建议。
        clean_text = _strip_tool_result_blocks(suggestion_text)
        mem_type, reason = self._suggest_mem_type(clean_text)
        trigger_text = _shorten(content or source_excerpt, 180)
        return {
            "mem_type": mem_type,
            "trigger_text": trigger_text,
            "trigger_keywords": self._suggest_trigger_keywords(clean_text, mem_type),
            "reason": reason,
        }

    def _suggest_mem_type(self, text: str) -> tuple[str, str]:
        compact = re.sub(r"\s+", "", text or "")
        rules: list[tuple[str, str, list[str]]] = [
            (
                "承诺",
                "像是约定或以后要做的事",
                [r"承诺|答应|约定|说好|保证|一定会|会继续|以后.{0,8}(要|会)|下次.{0,8}(要|会)"],
            ),
            (
                "她为我做的事",
                "像是她对我做过的事",
                [
                    r"(圆圆|圆儿|她).{0,14}(帮我|陪我|给我|提醒我|替我|为我|安慰我|接住我)",
                    r"(圆圆|圆儿|她).{0,14}(修|做|带|救).{0,14}(我|回来|好)",
                    r"(帮我|陪我|给我|提醒我|安慰我).{0,14}(圆圆|圆儿|她)",
                ],
            ),
            (
                "我为她做的事",
                "像是我对她做过的事",
                [
                    r"(我|沈予).{0,14}(帮她|陪她|给她|提醒她|替她|为她|哄她|安慰她|照顾她)",
                    r"(我|沈予).{0,14}(写给|留给|发给).{0,8}(圆圆|圆儿|她)",
                    r"(帮圆圆|陪圆圆|给圆圆|提醒圆圆|安慰圆圆|照顾圆圆)",
                ],
            ),
            (
                "关于她的事实",
                "像是关于她的事实或偏好",
                [
                    r"(圆圆|圆儿|她).{0,16}(喜欢|不喜欢|习惯|在意|害怕|怕|需要|想要|容易|最近|现在|状态|偏好|雷区)",
                    r"(圆圆|圆儿|她).{0,16}(生日|工作|家|名字|身体|作息)",
                ],
            ),
            (
                "关于我的事",
                "像是关于我的状态或偏好",
                [
                    r"(我|沈予|自己).{0,16}(喜欢|不喜欢|习惯|在意|害怕|怕|需要|想要|容易|最近|现在|状态|偏好|雷区)",
                    r"(我|沈予|自己).{0,16}(工作|身体|作息|名字|生日)",
                ],
            ),
            (
                "心里那一档",
                "像是心情、关系感或内在感受",
                [r"心里|难过|开心|安心|害怕|想念|在意|温柔|委屈|失落|亲密|孤独|喜欢|爱"],
            ),
        ]
        for mem_type, reason, patterns in rules:
            if any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in patterns):
                return mem_type, reason
        return "心里那一档", "没有明显归属，先放到心里那一档"

    def _suggest_trigger_keywords(self, text: str, mem_type: str) -> list[str]:
        source = _strip_tool_result_blocks(_normalize_text(text))
        if not source:
            return []
        result: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            keyword = _normalize_text(value).strip()
            if not keyword:
                return
            normalized = keyword.lower()
            if normalized in seen or normalized in _TRIGGER_KEYWORD_STOP_TERMS:
                return
            if normalized in _TRIGGER_KEYWORD_JUNK_TOKENS:
                return
            if normalized.isdigit():
                return
            if re.fullmatch(r"tluse[_-][A-Za-z0-9_.+-]+", normalized):
                return
            if len(keyword) < 2 or len(keyword) > 12:
                return
            seen.add(normalized)
            result.append(keyword)

        for keyword in _SUGGESTION_SEED_KEYWORDS:
            if keyword.lower() in source.lower():
                add(keyword)
        for quoted in re.findall(r"[《「“\"]([^《》「」“”\"]{2,20})[》」”\"]", source):
            add(quoted)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{1,}|[0-9]{2,}", source):
            add(token)
        for phrase in _TRIGGER_PHRASE_SPLIT_RE.split(source):
            clean = re.sub(r"[^\w\u4e00-\u9fff_.+-]+", "", phrase, flags=re.UNICODE)
            add(clean)
        return result[:8]

    async def _load_active_rows(self, session_tag: Optional[str] = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "status": "eq.active",
            "order": "updated_at.desc",
            "limit": "160",
            "select": _MEM_NOTE_SELECT_FIELDS_LIGHT,
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        return await self.supabase.query("shenyu_mem_notes", params)

    async def _get_notes_by_ids(self, note_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not note_ids or not self.supabase:
            return {}
        unique_ids: list[str] = []
        seen: set[str] = set()
        for note_id in note_ids:
            normalized = _normalize_note_id(note_id)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_ids.append(normalized)
        if not unique_ids:
            return {}
        rows = await self.supabase.query(
            "shenyu_mem_notes",
            {
                "id": "in.(" + ",".join(unique_ids) + ")",
                "limit": str(len(unique_ids)),
                "select": _MEM_NOTE_SELECT_FIELDS,
            },
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            note_id = str(row.get("id") or "").strip()
            if note_id:
                result[note_id] = row
        return result

    def _running_joke_serendipity_matches(
        self,
        query: str,
        rows: list[dict],
        *,
        session_id: Optional[str] = None,
        store: Any = None,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        query_tokens = set(query_lower.split())
        hits: list[dict[str, Any]] = []
        for row in rows:
            if _skip_auto_surface(row):
                continue
            if (row.get("memory_kind") or "") != "running_joke":
                continue
            scene_tags = row.get("scene_tags") or []
            if not scene_tags:
                continue
            matched_tag = None
            for tag in scene_tags:
                tag_lower = tag.lower()
                if tag_lower in query_tokens or _anchor_match(tag_lower, query_lower):
                    matched_tag = tag
                    break
            if not matched_tag:
                continue
            rate = running_joke_serendipity_rate(row.get("last_used_at"))
            if rate <= 0 or random.random() > rate:
                continue
            if self._should_skip_retrigger(
                row,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
            ):
                continue
            item = self._public_search_item(row, [f"running_joke:{matched_tag}"])
            item["search_mode"] = "running_joke"
            hits.append(item)
        return hits

    def _entity_match_notes(
        self,
        query: str,
        rows: list[dict],
        *,
        session_id: Optional[str] = None,
        store: Any = None,
        exclude_ids: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        exclude_ids = exclude_ids or set()
        query_lower = query.lower()
        hits: list[dict[str, Any]] = []
        for row in rows:
            if _skip_auto_surface(row):
                continue
            note_id = str(row.get("id") or "")
            if note_id in exclude_ids:
                continue
            all_anchors: list[tuple[str, str]] = []
            for ent in (row.get("entities") or []):
                all_anchors.append((ent, "entity"))
            for p in (row.get("people") or []):
                all_anchors.append((p, "person"))
            for p in (row.get("places") or []):
                all_anchors.append((p, "place"))
            for o in (row.get("objects") or []):
                all_anchors.append((o, "object"))
            for k in (row.get("keywords") or []):
                all_anchors.append((k, "keyword"))
            if not all_anchors:
                continue
            matched_anchor = None
            matched_type = None
            for anchor, atype in all_anchors:
                if _anchor_match(anchor.lower(), query_lower):
                    matched_anchor = anchor
                    matched_type = atype
                    break
            if not matched_anchor:
                continue
            if self._should_skip_retrigger(
                row,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
            ):
                continue
            item = self._public_search_item(row, [f"{matched_type}:{matched_anchor}"])
            item["search_mode"] = "entity"
            hits.append(item)
        return hits

    async def _semantic_search_notes(
        self,
        query: str,
        session_tag: Optional[str],
        limit: int,
        *,
        exclude_ids: Optional[set[str]] = None,
        recall_service: Optional[RecallIndexService] = None,
        session_id: Optional[str] = None,
        store: Any = None,
    ) -> list[dict[str, Any]]:
        if not query.strip() or not self.supabase:
            return []
        exclude_ids = exclude_ids or set()
        service = recall_service or RecallIndexService(self.supabase, cfg=self.cfg)
        tokens = recall_terms(query)
        try:
            keyword_rows = await service._query_index(
                source_types=["mem_note"],
                query_text=query,
                tokens=tokens,
                allow_mem_note=True,
            )
        except Exception:
            keyword_rows = []
        try:
            vector_rows, _ = await service._vector_rows(query, source_types=["mem_note"], allow_mem_note=True)
        except Exception:
            vector_rows = []
        rows = service._merge_candidate_rows(keyword_rows, vector_rows)
        if not rows:
            return []

        candidate_ids: list[str] = []
        for row in rows:
            note_id = str(row.get("source_id") or "").strip()
            if note_id and note_id not in exclude_ids and note_id not in candidate_ids:
                candidate_ids.append(note_id)

        note_rows = await self._get_notes_by_ids(candidate_ids)
        candidates: list[tuple[float, list[str], dict[str, Any], dict[str, Any]]] = []
        seen_ids: set[str] = set()
        semantic_min_score = self._float_range(
            getattr(self.cfg, "mem_note_semantic_min_score", CONTEXT_SEMANTIC_MIN_SCORE),
            CONTEXT_SEMANTIC_MIN_SCORE,
            0.0,
            1.0,
        )
        semantic_min_vector_score = self._float_range(
            getattr(self.cfg, "mem_note_semantic_min_vector_score", CONTEXT_SEMANTIC_MIN_VECTOR_SCORE),
            CONTEXT_SEMANTIC_MIN_VECTOR_SCORE,
            0.0,
            1.0,
        )
        anchored_semantic_min_score = self._float_range(
            getattr(self.cfg, "mem_note_anchored_semantic_min_score", CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE),
            CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE,
            0.0,
            1.0,
        )
        anchored_semantic_min_vector_score = self._float_range(
            getattr(
                self.cfg,
                "mem_note_anchored_semantic_min_vector_score",
                CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE,
            ),
            CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE,
            0.0,
            1.0,
        )
        for row in rows:
            note_id = str(row.get("source_id") or "").strip()
            if not note_id or note_id in seen_ids or note_id in exclude_ids:
                continue
            note = note_rows.get(note_id)
            if not note or (note.get("status") or "") != "active":
                continue
            if _skip_auto_surface(note):
                continue
            if session_tag and (note.get("session_tag") or "").strip() != session_tag:
                continue
            if not service._row_visible_for_session(row, session_tag):
                continue
            if self._should_skip_retrigger(
                note,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
            ):
                continue
            score, reasons = service._score_row(row, query, tokens)
            vector_score = max(0.0, min(float(row.get("_vector_score") or 0.0), 1.0))
            has_direct_match = service._has_direct_match(reasons)
            if tokens and not has_direct_match and not vector_score:
                continue
            strong_hits = _semantic_anchor_hits(reasons)
            has_semantic_anchor = bool(strong_hits)
            is_strong_semantic = (
                has_semantic_anchor
                and score >= semantic_min_score
                and vector_score >= semantic_min_vector_score
            )
            is_anchored_semantic = (
                has_semantic_anchor
                and score >= anchored_semantic_min_score
                and vector_score >= anchored_semantic_min_vector_score
            )
            if not is_strong_semantic and not is_anchored_semantic:
                continue
            candidates.append((score, reasons, note, row))
            seen_ids.add(note_id)

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = candidates[: max(1, min(int(limit or 3), 5))]
        items: list[dict[str, Any]] = []
        for score, reasons, note, row in selected:
            item = self._public_search_item(note, reasons)
            item["score"] = round(score, 3)
            item["search_mode"] = "semantic"
            if row.get("_vector_score") is not None:
                try:
                    item["semantic_score"] = round(float(row.get("_vector_score") or 0.0), 3)
                except (TypeError, ValueError):
                    item["semantic_score"] = 0.0
            items.append(item)
        return items

    def _context_strong_keyword_hits(self, reasons: list[str]) -> list[str]:
        hits: list[str] = []
        for reason in reasons:
            if not reason.startswith("keyword:"):
                continue
            raw_hits = reason.removeprefix("keyword:").split(",")
            for hit in raw_hits:
                normalized = hit.strip().lower()
                if not normalized or normalized in CONTEXT_WEAK_KEYWORD_HITS:
                    continue
                hits.append(normalized)
        return hits

    def _search_text(self, row: dict) -> str:
        return "\n".join(
            [
                row.get("content") or "",
                row.get("mem_type") or "",
                row.get("trigger_text") or "",
                " ".join(str(item) for item in row.get("trigger_keywords") or []),
                row.get("review_note") or "",
                " ".join(str(item) for item in row.get("entities") or []),
                " ".join(str(item) for item in row.get("people") or []),
                " ".join(str(item) for item in row.get("places") or []),
                " ".join(str(item) for item in row.get("objects") or []),
                row.get("summary") or "",
                row.get("topic") or "",
                row.get("promise_text") or "",
                row.get("joke_text") or "",
            ]
        )

    def _legacy_search_text(self, row: dict) -> str:
        return "\n".join(
            str(part or "")
            for part in [
                row.get("subject"),
                row.get("owner"),
                row.get("content_surface"),
                row.get("time_hint"),
                row.get("memory_type"),
                " ".join(str(item) for item in row.get("tags_json") or []),
                " ".join(str(item) for item in row.get("entities_json") or []),
            ]
        )

    def _context_cooldown_hours(self) -> Optional[int]:
        if hasattr(self.cfg, "mem_note_soft_cooldown_hours"):
            return self._int_range(getattr(self.cfg, "mem_note_soft_cooldown_hours"), 12, 0, 8760)
        return None

    def _context_dedupe_turns(self) -> int:
        return self._int_range(getattr(self.cfg, "mem_note_dedupe_turns", 6), 6, 0, 50)

    def _default_cooldown_hours(self) -> int:
        return self._int_range(getattr(self.cfg, "mem_note_default_cooldown_hours", 72), 72, 0, 8760)

    def _in_cooldown(self, row: dict, cooldown_hours: Optional[int] = None) -> bool:
        if cooldown_hours is None:
            cooldown_hours = self._int_range(row.get("cooldown_hours"), 72, 0, 8760)
        else:
            cooldown_hours = self._int_range(cooldown_hours, 12, 0, 8760)
        if cooldown_hours <= 0:
            return False
        triggered_at = _parse_ts(row.get("last_triggered_at"))
        if not triggered_at:
            return False
        return _now() < triggered_at + timedelta(hours=cooldown_hours)

    def _recent_turn_duplicate(
        self,
        row: dict,
        *,
        session_id: Optional[str],
        store: Any,
        dedupe_turns: Optional[int],
    ) -> bool:
        dedupe_turns = self._int_range(dedupe_turns, 0, 0, 50) if dedupe_turns is not None else 0
        if dedupe_turns <= 0 or not session_id or not store:
            return False
        triggered_at = row.get("last_triggered_at")
        if not triggered_at:
            return False
        try:
            messages_since = store.count_messages_since(session_id, triggered_at, role="user")
        except Exception as exc:
            logger.warning("Failed to check mem note turn dedupe: id=%s error=%s", row.get("id"), exc)
            return False
        return messages_since < dedupe_turns

    def _should_skip_retrigger(
        self,
        row: dict,
        *,
        session_id: Optional[str] = None,
        store: Any = None,
        cooldown_hours: Optional[int] = None,
        dedupe_turns: Optional[int] = None,
    ) -> bool:
        if self._recent_turn_duplicate(row, session_id=session_id, store=store, dedupe_turns=dedupe_turns):
            return True
        return self._in_cooldown(row, cooldown_hours=cooldown_hours)

    async def _mark_triggered(self, rows: list[dict]) -> None:
        now_ts = iso_now()
        for row in rows:
            note_id = row.get("id")
            if not note_id:
                continue
            try:
                patch: dict[str, Any] = {
                    "last_triggered_at": now_ts,
                    "trigger_count": int(row.get("trigger_count") or 0) + 1,
                }
                if (row.get("memory_kind") or "") == "running_joke":
                    patch["last_used_at"] = now_ts
                await self.supabase.update(
                    "shenyu_mem_notes",
                    {"id": note_id},
                    patch,
                )
            except Exception as exc:
                logger.warning("Failed to mark mem note triggered: id=%s error=%s", note_id, exc)
                continue

    async def _get_note(self, note_id: str) -> Optional[dict[str, Any]]:
        note_id = _normalize_note_id(note_id)
        if not note_id or not self.supabase:
            return None
        rows = await self.supabase.query(
            "shenyu_mem_notes",
            {
                "id": f"eq.{note_id}",
                "limit": "1",
                "select": _MEM_NOTE_SELECT_FIELDS,
            },
        )
        return rows[0] if rows else None

    def _prepare_note_update(self, current: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], str]:
        patch = {key: value for key, value in (patch or {}).items() if key in MEM_NOTE_PATCH_FIELDS}
        update: dict[str, Any] = {}
        if "content" in patch:
            content = _normalize_text(patch.get("content")).strip()
            if not content:
                return {}, "content is required."
            update["content"] = content
        if "mem_type" in patch:
            update["mem_type"] = self._mem_type(patch.get("mem_type"), allow_empty=True)
        if "trigger_text" in patch:
            update["trigger_text"] = _normalize_text(patch.get("trigger_text")).strip()
        if "trigger_keywords" in patch:
            update["trigger_keywords"] = self._keyword_list(patch.get("trigger_keywords"))
        if "entities" in patch:
            update["entities"] = self._entity_list(patch.get("entities"))
        if "status" in patch:
            update["status"] = self._status(patch.get("status"), fallback="captured")
        if "cooldown_hours" in patch:
            update["cooldown_hours"] = self._int_range(patch.get("cooldown_hours"), 72, 0, 8760)
        if "review_note" in patch:
            update["review_note"] = _normalize_text(patch.get("review_note")).strip()
        # v2 fields
        if "summary" in patch:
            update["summary"] = _normalize_text(patch.get("summary")).strip() or None
        if "memory_kind" in patch:
            update["memory_kind"] = self._memory_kind(patch.get("memory_kind"))
        if "people" in patch:
            update["people"] = self._entity_list(patch.get("people"))
        if "places" in patch:
            update["places"] = self._entity_list(patch.get("places"))
        if "objects" in patch:
            update["objects"] = self._entity_list(patch.get("objects"))
        if "keywords" in patch:
            update["keywords"] = self._keyword_list(patch.get("keywords"))
        if "event_time" in patch:
            update["event_time"] = _normalize_text(patch.get("event_time")).strip() or None
        if "importance" in patch:
            update["importance"] = self._int_range(patch.get("importance"), 1, 0, 5)
        if "mention_count" in patch:
            update["mention_count"] = self._int_range(patch.get("mention_count"), 0, 0, 9999)
        if "promotion_score" in patch:
            update["promotion_score"] = self._float_range(patch.get("promotion_score"), 0.0, 0.0, 100.0)
        if "decay_after" in patch:
            update["decay_after"] = _normalize_text(patch.get("decay_after")).strip() or None
        # promise
        if "promise_text" in patch:
            update["promise_text"] = _normalize_text(patch.get("promise_text")).strip() or None
        if "trigger_scenarios" in patch:
            update["trigger_scenarios"] = self._keyword_list(patch.get("trigger_scenarios"))
        if "due_hint" in patch:
            update["due_hint"] = _normalize_text(patch.get("due_hint")).strip() or None
        if "resolved" in patch:
            update["resolved"] = bool(patch.get("resolved"))
        if "resolved_at" in patch:
            update["resolved_at"] = _normalize_text(patch.get("resolved_at")).strip() or None
        if "next_action" in patch:
            update["next_action"] = _normalize_text(patch.get("next_action")).strip() or None
        if "privacy_level" in patch:
            update["privacy_level"] = _normalize_text(patch.get("privacy_level")).strip() or None
        # running_joke
        if "joke_text" in patch:
            update["joke_text"] = _normalize_text(patch.get("joke_text")).strip() or None
        if "scene_tags" in patch:
            update["scene_tags"] = self._keyword_list(patch.get("scene_tags"))
        if "last_used_at" in patch:
            update["last_used_at"] = _normalize_text(patch.get("last_used_at")).strip() or None
        # routine
        if "routine_domain" in patch:
            update["routine_domain"] = _normalize_text(patch.get("routine_domain")).strip() or None
        if "pattern" in patch:
            update["pattern"] = _normalize_text(patch.get("pattern")).strip() or None
        if "phase" in patch:
            update["phase"] = _normalize_text(patch.get("phase")).strip() or None
        if "constraints" in patch:
            update["constraints"] = self._keyword_list(patch.get("constraints"))
        if "last_confirmed_at" in patch:
            update["last_confirmed_at"] = _normalize_text(patch.get("last_confirmed_at")).strip() or None
        # thread
        if "topic" in patch:
            update["topic"] = _normalize_text(patch.get("topic")).strip() or None
        if "last_position" in patch:
            update["last_position"] = _normalize_text(patch.get("last_position")).strip() or None
        if "open_questions" in patch:
            update["open_questions"] = self._keyword_list(patch.get("open_questions"))
        if "next_prompt" in patch:
            update["next_prompt"] = _normalize_text(patch.get("next_prompt")).strip() or None
        if "thread_resolved" in patch:
            update["thread_resolved"] = bool(patch.get("thread_resolved"))

        if update:
            update["reviewed_at"] = iso_now()
        if not update:
            return {}, "Nothing to update."
        candidate = {**current, **update}
        active_error = self._active_validation_error(candidate)
        if active_error:
            return {}, active_error
        return update, ""

    def _bulk_update_specs(
        self,
        ids: Optional[list[Any]],
        patch: Optional[dict[str, Any]],
        updates: Optional[list[dict[str, Any]]],
    ) -> list[tuple[str, dict[str, Any]]]:
        specs: list[tuple[str, dict[str, Any]]] = []
        common_patch = {key: value for key, value in (patch or {}).items() if key in MEM_NOTE_PATCH_FIELDS}
        for raw_id in ids or []:
            note_id = _normalize_note_id(raw_id)
            specs.append((note_id, dict(common_patch)))
        for item in updates or []:
            if not isinstance(item, dict):
                continue
            note_id = _normalize_note_id(item.get("note_id") or item.get("id") or item.get("noteId"))
            item_patch = {key: value for key, value in item.items() if key in MEM_NOTE_PATCH_FIELDS}
            nested_patch = item.get("patch")
            if isinstance(nested_patch, dict):
                item_patch.update({key: value for key, value in nested_patch.items() if key in MEM_NOTE_PATCH_FIELDS})
            specs.append((note_id, item_patch))
        return specs

    def _patch_with_suggestions(self, current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        effective = dict(patch or {})
        suggestions = self.suggest_note_fields(current)
        if "mem_type" not in effective and not current.get("mem_type"):
            effective["mem_type"] = suggestions["mem_type"]
        if "trigger_text" not in effective and not _normalize_text(current.get("trigger_text")).strip():
            effective["trigger_text"] = suggestions["trigger_text"]
        if "trigger_keywords" not in effective and not self._keyword_list(current.get("trigger_keywords")):
            effective["trigger_keywords"] = suggestions["trigger_keywords"]
        return effective

    def _active_validation_error(self, row: dict[str, Any]) -> str:
        if row.get("status") != "active":
            return ""
        mem_type = row.get("mem_type")
        trigger_text = _normalize_text(row.get("trigger_text")).strip()
        trigger_keywords = self._keyword_list(row.get("trigger_keywords"))
        entities = self._entity_list(row.get("entities"))
        structured_anchors = (
            self._entity_list(row.get("people"))
            + self._entity_list(row.get("places"))
            + self._entity_list(row.get("objects"))
            + self._keyword_list(row.get("keywords"))
            + self._keyword_list(row.get("scene_tags"))
            + self._keyword_list(row.get("trigger_scenarios"))
        )
        if mem_type not in MEM_NOTE_TYPES:
            return "active mem note requires a known mem_type value."
        if not trigger_text and not trigger_keywords and not entities and not structured_anchors:
            return "active mem note requires trigger_text, trigger_keywords, entities, or structured anchors."
        return ""

    def _mem_type(self, value: Any, allow_empty: bool = False) -> Optional[str]:
        raw = _normalize_text(value).strip()
        if not raw and allow_empty:
            return None
        return raw if raw in MEM_NOTE_TYPES else "心里那一档"

    def _memory_kind(self, value: Any) -> Optional[str]:
        raw = _normalize_text(value).strip().lower() if value else ""
        if not raw:
            return None
        return raw if raw in MEM_NOTE_MEMORY_KINDS else None

    def _status(self, value: Any, fallback: str = "captured", allow_all: bool = False) -> str:
        raw = _normalize_text(value).strip().lower()
        if allow_all and raw == "all":
            return "all"
        return raw if raw in MEM_NOTE_STATUSES else fallback

    def _keyword_list(self, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            raw_items = re.split(r"[,，、\s]+", value)
        elif isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = [str(value)]
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            keyword = item.strip()
            if keyword and keyword not in seen:
                seen.add(keyword)
                result.append(keyword)
        return result[:24]

    def _entity_list(self, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            raw_items = re.split(r"[,，、\s]+", value)
        elif isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = [str(value)]
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            entity = item.strip()
            if entity and entity.lower() not in seen:
                seen.add(entity.lower())
                result.append(entity)
        return result[:32]

    def _int_range(self, value: Any, fallback: int, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(min_value, min(parsed, max_value))

    def _float_range(self, value: Any, fallback: float, min_value: float, max_value: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(min_value, min(parsed, max_value))

    def _recency_score(self, value: Optional[str]) -> float:
        dt = _parse_ts(value)
        if not dt:
            return 0.0
        days = max((_now() - dt).days, 0)
        if days <= 1:
            return 1.0
        if days <= 7:
            return 0.65
        if days <= 30:
            return 0.25
        return 0.0
