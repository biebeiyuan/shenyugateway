from __future__ import annotations

import re
from typing import Any, Optional

from shenyu_gateway.utils import normalize_text as _normalize_text
from ..runtime import now as _now, parse_ts as _parse_ts
from ._helpers import (
    MEM_NOTE_MEMORY_KIND_ALIASES,
    MEM_NOTE_MEMORY_KINDS,
    MEM_NOTE_STATUSES,
    MEM_NOTE_TYPES,
)


class ValidationMixin:

    def _mem_type(self, value: Any, allow_empty: bool = False) -> Optional[str]:
        raw = _normalize_text(value).strip()
        if not raw and allow_empty:
            return None
        return raw if raw in MEM_NOTE_TYPES else "心里那一档"

    def _memory_kind(self, value: Any) -> Optional[str]:
        raw = _normalize_text(value).strip().lower() if value else ""
        if not raw:
            return None
        if raw in MEM_NOTE_MEMORY_KINDS:
            return raw
        if raw in MEM_NOTE_MEMORY_KIND_ALIASES:
            return MEM_NOTE_MEMORY_KIND_ALIASES[raw]
        for kind in MEM_NOTE_MEMORY_KINDS:
            if kind in raw or raw in kind:
                return kind
        return None

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

    def _auto_surface_eligibility(self, row: dict[str, Any]) -> tuple[bool, str]:
        """Return whether a note may participate in automatic Memory Island recall."""
        if row.get("status") != "active":
            return False, "stored"
        active_error = self._active_validation_error(row)
        if active_error:
            return False, "missing_trigger"
        if (row.get("memory_kind") or "") == "promise" and bool(row.get("resolved")):
            return False, "resolved_promise"
        return True, "active"
