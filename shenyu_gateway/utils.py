from __future__ import annotations

import json
from typing import Any


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        iterable = sorted(value, key=str) if isinstance(value, set) else value
        parts: list[str] = []
        for item in iterable:
            if item is None:
                continue
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
                continue
            parts.append(normalize_text(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
