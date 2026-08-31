from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shenyu_gateway.embeddings import vector_literal as _vector_literal
from shenyu_gateway.utils import json_dict as _json_dict
from shenyu_gateway.utils import normalize_text as _normalize_text


RECALL_CHUNK_MIN_CHARS = 140


RECALL_CHUNK_MAX_CHARS = 900


EMBEDDING_TEXT_MAX_CHARS = 1600


RECALL_EXCERPT_MAX_CHARS = 720


RECALL_MODES = {"auto", "exact", "fuzzy", "verbatim"}


_TITLE_WRAPPER_RE = re.compile(r"[《》〈〉「」『』【】\[\]（）()“”\"'‘’\s·:：,，。！？!?、]+")


_QUOTED_TITLE_RE = re.compile(r"[《〈「『【]([^》〉」』】]{1,120})[》〉」』】]")


def normalize_recall_title(value: Any) -> str:
    return _TITLE_WRAPPER_RE.sub("", _normalize_text(value).strip().lower())


def classify_recall_mode(query: str, mode: Optional[str] = None) -> str:
    requested = str(mode or "auto").strip().lower()
    if requested in RECALL_MODES - {"auto"}:
        return requested
    text = (query or "").strip()
    if any(term in text for term in ("原话", "逐字", "当时怎么说", "当时说了什么", "聊天记录")):
        return "verbatim"
    if _QUOTED_TITLE_RE.search(text) or re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]", text):
        return "exact"
    return "fuzzy"


def infer_recall_date(query: str) -> Optional[str]:
    match = re.search(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", query or "")
    if not match:
        return None
    year = int(match.group(1) or datetime.now(timezone.utc).year)
    month = int(match.group(2))
    day = int(match.group(3))
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _exact_title_query_values(query: str) -> set[str]:
    values = {normalize_recall_title(query)}
    for match in _QUOTED_TITLE_RE.finditer(query or ""):
        values.add(normalize_recall_title(match.group(1)))
    return {value for value in values if value}


def _shorten(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _excerpt(text: str, limit: int = RECALL_EXCERPT_MAX_CHARS) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


# _json_dict is the shared total variant re-exported from utils.json_dict above.


_GENERIC_CN_PREFIXES = ("是", "在", "有", "我", "你", "他", "她", "它", "这", "那", "不", "没")


_GENERIC_CN_SUFFIXES = ("的", "了", "个", "吗", "呢", "吧", "啊", "呀", "嘛")


def is_generic_chinese_fragment(text: str) -> bool:
    """True if a short pure-CJK term is a generic prefix/suffix-led fragment.

    Judges only the prefix/suffix generic test; callers layer their own
    length/allowlist rules on top.
    """
    if not text or not re.fullmatch(r"[一-鿿]+", text):
        return False
    if len(text) <= 1:
        return True
    if len(text) <= 4 and (
        text.startswith(_GENERIC_CN_PREFIXES) or text.endswith(_GENERIC_CN_SUFFIXES)
    ):
        return True
    return False


_MEM_NOTE_KEYWORD_STOP_TERMS = {
    "0", "mem", "note", "一下", "可以", "东西", "为什么", "什么", "现在", "到底", "还是",
    "不是", "自己", "我们", "你们", "他们", "她们", "怎么", "没有", "不会", "知道",
    "觉得", "一些", "所以", "因为", "如果", "已经", "这样", "那样", "然后", "关于",
    "但是", "今天", "昨天", "明天", "以后", "之前", "之后", "时候", "感觉", "需要",
    "真的", "可能", "一点", "这种", "那个", "这个", "工具", "便签", "命中", "逻辑",
    "对话", "回答", "情绪", "心情", "喜欢", "帮我", "我把", "你的", "我的",
}


_MEM_NOTE_KEYWORD_JUNK_TERMS = {
    "tool_call_id", "tool_call", "tool_use", "tool_use_id", "tool", "name", "arguments",
    "function", "type", "content", "role", "assistant", "user", "system", "id", "ok",
    "error", "status", "null", "true", "false",
}


def _mem_note_keyword_anchor_is_specific(value: Any) -> bool:
    """Shared keyword predicate retained outside the unified Recall corpus."""
    text = _normalize_text(value).strip()
    normalized = text.lower()
    if not normalized or len(normalized) < 2:
        return False
    if normalized in _MEM_NOTE_KEYWORD_STOP_TERMS or normalized in _MEM_NOTE_KEYWORD_JUNK_TERMS:
        return False
    if normalized.isdigit():
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]+", text):
        if len(text) <= 2:
            return text in {"和弦", "海信", "上游", "预设", "气泡"} or text.lower() in {"mem"}
        if is_generic_chinese_fragment(text):
            return False
        return True
    if re.fullmatch(r"[A-Za-z0-9_.+-]+", text):
        return len(text) >= 4
    return len(text) >= 3


def recall_terms(text: str) -> list[str]:
    raw = (text or "").replace("\n", " ")
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str):
        normalized = term.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)

    for token in re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]+", raw):
        add(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) >= 2:
            for size in (2, 3):
                if len(token) < size:
                    continue
                for idx in range(0, len(token) - size + 1):
                    add(token[idx : idx + size])
    return terms


def split_recall_chunks(text: str, min_chars: int = RECALL_CHUNK_MIN_CHARS, max_chars: int = RECALL_CHUNK_MAX_CHARS) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []

    parts = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    if not parts:
        parts = [clean]

    chunks: list[str] = []
    buffer = ""
    for part in parts:
        candidate = f"{buffer}\n\n{part}".strip() if buffer else part
        if len(candidate) <= max_chars:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
            buffer = ""

        if len(part) <= max_chars:
            buffer = part
            continue

        sentences = [item.strip() for item in re.split(r"(?<=[。！？!?；;])", part) if item.strip()]
        if not sentences:
            sentences = [part]
        sentence_buffer = ""
        for sentence in sentences:
            sentence_candidate = f"{sentence_buffer}{sentence}".strip() if sentence_buffer else sentence
            if len(sentence_candidate) <= max_chars:
                sentence_buffer = sentence_candidate
                continue
            if sentence_buffer:
                chunks.append(sentence_buffer)
                sentence_buffer = ""
            start = 0
            while start < len(sentence):
                piece = sentence[start : start + max_chars].strip()
                if piece:
                    chunks.append(piece)
                start += max_chars
        if sentence_buffer:
            buffer = sentence_buffer

    if buffer:
        chunks.append(buffer)

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < min_chars and len(merged[-1]) + len(chunk) + 2 <= max_chars:
            merged[-1] = f"{merged[-1]}\n\n{chunk}"
        else:
            merged.append(chunk)
    return merged


def build_embedding_text(title: str, tags: list[Any], body: str, max_chars: int = EMBEDDING_TEXT_MAX_CHARS) -> str:
    tag_text = " ".join(str(tag) for tag in tags[:24] if str(tag).strip())
    prefix_parts = []
    if title:
        prefix_parts.append(f"标题：{title.strip()}")
    if tag_text:
        prefix_parts.append(f"标签：{tag_text}")
    prefix = "\n".join(prefix_parts).strip()
    body_label = "正文："
    available = max_chars - len(prefix) - len(body_label) - (2 if prefix else 0)
    available = max(160, available)
    clean_body = (body or "").strip()
    if len(clean_body) > available:
        clean_body = clean_body[:available].rstrip()
    parts = [part for part in [prefix, body_label + clean_body if clean_body else ""] if part]
    return "\n\n".join(parts)[:max_chars].strip()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            text += "T00:00:00+00:00"
        text = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date_bound(value: Any, *, end_of_day: bool = False) -> Optional[datetime]:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        dt = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        return dt + timedelta(days=1) - timedelta(microseconds=1) if end_of_day else dt
    return _parse_dt(value)


def _iso_dt(value: Any) -> Optional[str]:
    dt = _parse_dt(value)
    return dt.isoformat() if dt else None


# _vector_literal is the shared pgvector serializer re-exported from
# embeddings.vector_literal above (single .9g-precision contract with stars/).


def _recency_score(value: Any) -> float:
    dt = _parse_dt(value)
    if not dt:
        return 0.3
    days = max((datetime.now(timezone.utc) - dt).days, 0)
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.75
    if days <= 180:
        return 0.55
    if days <= 365:
        return 0.4
    return 0.3
