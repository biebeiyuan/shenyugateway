from __future__ import annotations

import re
from typing import Any

from ..utils import normalize_text as _normalize_text
from ._helpers import _clamp, _chord_parts, _node_id


CHORD_QUALITY_FAMILIES: dict[str, set[str]] = {
    "minor_family": {"minor", "dominant"},
    "major_family": {"major"},
    "tension_family": {"dim", "aug"},
    "sus_family": {"sus"},
}


def _quality_family(quality: str) -> str:
    for family, members in CHORD_QUALITY_FAMILIES.items():
        if quality in members:
            return family
    return ""


def _chord_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_chord = str(left.get("chord") or "").strip().casefold()
    right_chord = str(right.get("chord") or "").strip().casefold()
    if left_chord and right_chord and left_chord == right_chord:
        return 1.0
    score = 0.0
    if left.get("chord_root") and left.get("chord_root") == right.get("chord_root"):
        score += 0.55
    left_q = left.get("chord_quality") or ""
    right_q = right.get("chord_quality") or ""
    if left_q and right_q:
        if left_q == right_q:
            score += 0.25
        elif _quality_family(left_q) == _quality_family(right_q) != "":
            score += 0.15
    return _clamp(score, 0.0, 0.85)


def _extract_chord_from_query(query: str) -> dict[str, str]:
    text = query or ""
    for match in re.finditer(r"\b([A-Ga-g](?:#|b)?(?:maj|min|m|dim|aug|sus|add)?[0-9#b+\-/]*)\b", text):
        chord = match.group(1).strip()
        root, quality = _chord_parts(chord)
        if root:
            return {"chord": chord, "chord_root": root, "chord_quality": quality}
    return {"chord": "", "chord_root": "", "chord_quality": ""}


def _split_chord_sequence(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        parts = [_node_id(item) for item in value]
        return [part for part in parts if part]
    text = _normalize_text(value).strip()
    if not text:
        return []
    normalized = (
        text.replace("→", "|")
        .replace("⇒", "|")
        .replace("->", "|")
        .replace("=>", "|")
        .replace("｜", "|")
        .replace("•", "|")
        .replace("·", "|")
        .replace("；", "|")
        .replace(";", "|")
        .replace("，", "|")
        .replace(",", "|")
        .replace("\n", "|")
    )
    normalized = re.sub(r"\s+/\s+", "|", normalized)
    parts = [part.strip() for part in normalized.split("|") if part.strip()]
    return parts if len(parts) > 1 else [text]
