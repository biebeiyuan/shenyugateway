from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shenyu_gateway.recall import recall_terms
from shenyu_gateway.runtime import LOCAL_DAY_TZ


def _keyword_terms(query: str) -> list[str]:
    return recall_terms(query)


def _keyword_overlap_score(query: str, text: str) -> float:
    terms = _keyword_terms(query)
    if not terms:
        return 0.25
    hay = (text or "").lower()
    hits = sum(1 for term in terms if term in hay)
    return hits / max(len(terms), 1)


def _date_range_bounds(created_from: Optional[str], created_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    def start_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=LOCAL_DAY_TZ)
            return dt.astimezone(timezone.utc).isoformat()
        return raw

    def end_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=LOCAL_DAY_TZ)
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
