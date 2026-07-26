from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shenyu_gateway.recall import recall_terms


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def _split_paragraph_chunks(text: str, min_len: int = 80, max_len: int = 420) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    buffer = ""

    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= max_len:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
            buffer = ""

        if len(paragraph) <= max_len:
            buffer = paragraph
            continue

        start_idx = 0
        while start_idx < len(paragraph):
            end_idx = min(len(paragraph), start_idx + max_len)
            piece = paragraph[start_idx:end_idx].strip()
            if piece:
                chunks.append(piece)
            start_idx = end_idx

    if buffer:
        chunks.append(buffer)

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < min_len and len(merged[-1]) + len(chunk) + 2 <= max_len:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)
    return merged


def _keyword_terms(query: str) -> list[str]:
    return recall_terms(query)


def _keyword_overlap_score(query: str, text: str) -> float:
    terms = _keyword_terms(query)
    if not terms:
        return 0.25
    hay = (text or "").lower()
    hits = sum(1 for term in terms if term in hay)
    return hits / max(len(terms), 1)


_LOCAL_DAY_TZ = timezone(timedelta(hours=8))


def _date_range_bounds(created_from: Optional[str], created_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    def start_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=_LOCAL_DAY_TZ)
            return dt.astimezone(timezone.utc).isoformat()
        return raw

    def end_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=_LOCAL_DAY_TZ)
            return (dt + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        return raw

    return start_bound(created_from), end_bound(created_to)


def _safe_json_loads(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback
