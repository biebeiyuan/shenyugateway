from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..recall import recall_terms
from ..runtime import logger
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
STAR_RANKER_VERSION = "star-ranker-v3"
STAR_FEATURE_SCHEMA_VERSION = "star-features-v3"
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


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"value": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value}


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
