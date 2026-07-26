from __future__ import annotations

import re
from typing import Any, Optional

from ..embeddings import vector_literal as _vector_literal
from ..recall import recall_terms
from ..runtime import logger
from ..utils import json_dict as _json_dict
from ..utils import normalize_text as _normalize_text

# ---------------------------------------------------------------------------
# Table name constants
# ---------------------------------------------------------------------------
STAR_TABLE = "shenyu_stars"
STAR_LINK_TABLE = "shenyu_star_links"
STAR_RUN_TABLE = "shenyu_star_recall_runs"
STAR_CANDIDATE_TABLE = "shenyu_star_recall_candidates"
STAR_FEEDBACK_TABLE = "shenyu_star_feedback"
STAR_ACTIVATION_TABLE = "shenyu_star_activations"

# ---------------------------------------------------------------------------
# Version constants
# ---------------------------------------------------------------------------
STAR_RANKER_VERSION = "star-ranker-v4"
STAR_FEATURE_SCHEMA_VERSION = "star-features-v4"
STAR_WEIGHTS_VERSION = "rrf-v1"

# ---------------------------------------------------------------------------
# SQL select string
# ---------------------------------------------------------------------------
STAR_SELECT = (
    "id,session_tag,content,chord,chord_root,chord_quality,chord_tension,status,is_constant,"
    "reviewed_at,activation_count,last_activated_at,source_model,source_session_id,source_excerpt,"
    "search_tokens,embedding_model,embedding_status,metadata,created_at,updated_at"
)

# ---------------------------------------------------------------------------
# Feedback sets
# ---------------------------------------------------------------------------
POSITIVE_FEEDBACK = {"positive", "connected", "should_surface", "missed"}
NEGATIVE_FEEDBACK = {"negative", "skipped"}
FEEDBACK_VALUES = POSITIVE_FEEDBACK | NEGATIVE_FEEDBACK
FEEDBACK_ALIASES = {
    "bad": "negative",
    "good": "positive",
    "neutral": "skipped",
}

# ---------------------------------------------------------------------------
# Admin scorers
# ---------------------------------------------------------------------------
ADMIN_SCORERS = {"圆圆", "圆儿", "admin"}

# ---------------------------------------------------------------------------
# Explicit-mention stopwords
# ---------------------------------------------------------------------------
EXPLICIT_MENTION_STOPWORDS = {
    "一个",
    "不是",
    "不能",
    "今天",
    "什么",
    "但是",
    "你好",
    "可以",
    "只是",
    "因为",
    "如果",
    "就是",
    "我们",
    "所以",
    "时候",
    "明天",
    "昨天",
    "没有",
    "现在",
    "真的",
    "觉得",
    "这个",
    "这么",
    "那个",
    "一起",
    "and",
    "are",
    "but",
    "for",
    "not",
    "the",
    "you",
}

DIRECT_REFERENCE_HARD_KINDS = frozenset({"star_id", "exact_phrase"})
DIRECT_REFERENCE_SOFT_KIND = "recall_unique"
_DIRECT_REFERENCE_INTENT_MARKERS = (
    "还记得",
    "记不记得",
    "你记得",
    "我记得",
    "之前那次",
    "以前那次",
    "那次",
    "那天",
    "那颗星",
    "星星里",
    "写下的",
    "记下的",
    "当时",
    "想起",
    "回忆",
)
_DIRECT_REFERENCE_STOPWORDS = EXPLICIT_MENTION_STOPWORDS | {
    "沈予",
    "圆圆",
    "圆儿",
    "星星",
    "记忆",
    "事情",
    "东西",
    "关系",
    "知道",
    "怎么",
    "为什么",
    "已经",
    "还是",
    "我的",
    "你的",
    "她的",
    "他的",
    "这里",
    "那里",
    "那只",
    "那件",
    "那段",
    "那个",
    "一下",
    "一下子",
}
for _marker in _DIRECT_REFERENCE_INTENT_MARKERS:
    _DIRECT_REFERENCE_STOPWORDS.update(recall_terms(_marker))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(float(value or 0.0), max_value))


def _safe_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# _vector_literal and _json_dict are shared implementations imported above
# (embeddings.vector_literal / utils.json_dict) - keep recall and stars on the
# same pgvector precision and JSON coercion contracts.


def _node_id(value: Any) -> str:
    return str(value or "").strip()


def _id_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = re.split(r"[,，\s]+", value.strip())
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        star_id = _node_id(item)
        if star_id and star_id not in seen:
            seen.add(star_id)
            result.append(star_id)
    return result


def _star_search_text(row: dict[str, Any]) -> str:
    metadata = _json_dict(row.get("metadata"))
    return "\n".join(
        part
        for part in [
            str(row.get("content") or ""),
            str(row.get("chord") or ""),
            str(row.get("chord_root") or ""),
            str(row.get("chord_quality") or ""),
            " ".join(str(item) for item in row.get("search_tokens") or []),
            " ".join(str(value) for value in metadata.values()),
        ]
        if part
    )


def _token_overlap(query: str, text: str, row_tokens: Optional[list[Any]] = None) -> tuple[float, list[str]]:
    query_terms = recall_terms(query)
    if not query_terms:
        return 0.0, []
    hay = (text or "").lower()
    tokens = {str(item).strip().lower() for item in row_tokens or [] if str(item).strip()}
    hits = []
    for term in query_terms:
        if term in tokens or term in hay:
            hits.append(term)
    return _clamp(len(set(hits)) / max(len(set(query_terms)), 1)), hits


def _significant_hit(term: Any) -> bool:
    text = str(term or "").strip().lower()
    if not text:
        return False
    if text in EXPLICIT_MENTION_STOPWORDS:
        return False
    if re.fullmatch(r"[一-鿿]+", text):
        return len(text) >= 2
    return bool(re.search(r"[a-z0-9]", text)) and len(text) >= 3


def _compact_reference_text(value: Any) -> str:
    normalized = _normalize_text(value).strip().lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized)


def _query_star_ids(query: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in re.finditer(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b",
            str(query or ""),
        )
    }


def _meaningful_reference_phrase(phrase: str) -> bool:
    if not phrase or phrase.isdigit():
        return False
    semantic = re.sub(r"[0-9第年月日号天点分时周早晚凌晨中午]+", "", phrase)
    return len(semantic) >= 4


def _reference_phrase_candidates(query: str) -> set[str]:
    raw = str(query or "")[:2000]
    compact = _compact_reference_text(raw)[:1200]
    if not compact:
        return set()
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", compact))
    short_min = 6 if has_cjk else 10
    window = 8 if has_cjk else 12
    phrases: set[str] = set()
    if short_min <= len(compact) <= window + 6:
        phrases.add(compact)
    if len(compact) >= window:
        phrases.update(compact[index : index + window] for index in range(len(compact) - window + 1))
    for match in re.finditer(r"[\"“”「」『』]([^\"“”「」『』]{1,160})[\"“”「」『』]", raw):
        quoted = _compact_reference_text(match.group(1))
        quoted_has_cjk = bool(re.search(r"[\u4e00-\u9fff]", quoted))
        quoted_min = 6 if quoted_has_cjk else 10
        quoted_window = 8 if quoted_has_cjk else 12
        if quoted_min <= len(quoted) <= 64:
            phrases.add(quoted)
        if len(quoted) > 64:
            phrases.update(
                quoted[index : index + quoted_window]
                for index in range(len(quoted) - quoted_window + 1)
            )
    return {phrase for phrase in phrases if _meaningful_reference_phrase(phrase)}


def _reference_anchor(term: Any) -> str:
    compact = _compact_reference_text(term)
    if not compact or compact in _DIRECT_REFERENCE_STOPWORDS or compact.isdigit():
        return ""
    if re.fullmatch(r"[\u4e00-\u9fff]+", compact):
        return compact if len(compact) >= 2 else ""
    return compact if len(compact) >= 4 else ""


def _direct_reference_kinds(query: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    """Return high-confidence direct-reference kinds keyed by active star id."""
    query_text = str(query or "")
    query_lower = query_text.lower()
    content_by_id = {
        _node_id(row.get("id")): _compact_reference_text(row.get("content"))
        for row in rows
        if _node_id(row.get("id")) and row.get("content")
    }
    result: dict[str, str] = {}
    for star_id in content_by_id:
        if len(star_id) >= 8 and star_id.lower() in query_lower:
            result[star_id] = "star_id"

    phrases = _reference_phrase_candidates(query_text)
    if phrases:
        phrases_by_length: dict[int, set[str]] = {}
        for phrase in phrases:
            phrases_by_length.setdefault(len(phrase), set()).add(phrase)
        phrase_owners: dict[str, set[str]] = {}
        for star_id, content in content_by_id.items():
            for length, query_phrases in phrases_by_length.items():
                if len(content) < length:
                    continue
                content_phrases = {
                    content[index : index + length]
                    for index in range(len(content) - length + 1)
                }
                for phrase in query_phrases & content_phrases:
                    phrase_owners.setdefault(phrase, set()).add(star_id)
        for phrase, owners in phrase_owners.items():
            if len(owners) != 1:
                continue
            star_id = next(iter(owners))
            result.setdefault(star_id, "exact_phrase")

    if not any(marker in query_text for marker in _DIRECT_REFERENCE_INTENT_MARKERS):
        return result

    anchor_text = query_text
    for marker in _DIRECT_REFERENCE_INTENT_MARKERS:
        anchor_text = anchor_text.replace(marker, " ")
    anchors = {
        anchor
        for term in recall_terms(anchor_text[:1200])
        if (anchor := _reference_anchor(term))
    }
    anchor_owners: dict[str, set[str]] = {}
    for anchor in anchors:
        owners = {star_id for star_id, content in content_by_id.items() if anchor in content}
        if len(owners) == 1:
            anchor_owners[anchor] = owners
    evidence: dict[str, list[str]] = {}
    for anchor, owners in anchor_owners.items():
        star_id = next(iter(owners))
        evidence.setdefault(star_id, []).append(anchor)
    qualifying = list(evidence)
    if len(qualifying) == 1:
        result.setdefault(qualifying[0], DIRECT_REFERENCE_SOFT_KIND)
    return result


def _chord_parts(chord: str) -> tuple[str, str]:
    clean = (chord or "").strip()
    if not clean:
        return "", ""
    clean = clean.replace("♭", "b").replace("♯", "#").replace("Δ", "maj")
    match = re.match(r"^\s*([A-Ga-g](?:#|b)?)(.*)$", clean)
    if not match:
        return "", ""
    root = match.group(1).upper()
    quality_raw = (match.group(2) or "").strip()
    quality_lower = quality_raw.lower()
    quality = ""
    if "dim" in quality_lower or "°" in quality_raw:
        quality = "dim"
    elif "aug" in quality_lower or "+" in quality_raw:
        quality = "aug"
    elif "sus" in quality_lower:
        quality = "sus"
    elif "maj" in quality_lower or quality_raw.startswith("M"):
        quality = "major"
    elif quality_lower.startswith("min") or quality_raw.startswith("m") or "-" in quality_raw:
        quality = "minor"
    elif "7" in quality_raw:
        quality = "dominant"
    return root, quality


def _feedback_value(value: Any) -> str:
    key = _node_id(value).lower()
    return FEEDBACK_ALIASES.get(key, key)


def parse_star_payload(star: Any) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if isinstance(star, dict):
        attrs.update(_json_dict(star.get("attrs")))
        content = _normalize_text(star.get("content")).strip()
        if star.get("chord") and not attrs.get("chord"):
            attrs["chord"] = star.get("chord")
        if star.get("chords") is not None and not attrs.get("chords"):
            attrs["chords"] = star.get("chords")
        if star.get("chord_sequence") is not None and not attrs.get("chord_sequence"):
            attrs["chord_sequence"] = star.get("chord_sequence")
    else:
        content = _normalize_text(star).strip()

    chord = _normalize_text(attrs.get("chord") or "").strip()
    if not chord and content:
        for delimiter in ("·", "•", "|", "｜"):
            if delimiter not in content:
                continue
            head, body = content.split(delimiter, 1)
            if 1 <= len(head.strip()) <= 32:
                chord = head.strip()
                content = body.strip()
                break
    root, quality = _chord_parts(chord)
    return {
        "content": content,
        "chord": chord,
        "chord_root": root,
        "chord_quality": quality,
        "attrs": attrs,
    }


def _cfg_float(cfg: Any, name: str, default: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return _clamp(_safe_float(getattr(cfg, name, default), default), min_value, max_value)
