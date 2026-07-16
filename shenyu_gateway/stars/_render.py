from __future__ import annotations

from typing import Any, Optional

from ..utils import shorten as _shorten


def render_star_context(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = []
    for item in items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        chord = (item.get("chord") or "").strip()
        prefix = f"{chord} · " if chord else ""
        lines.append(f"- {prefix}{_shorten(content, 220)}")
    return "\n".join(lines)


class RenderMixin:
    def _public_star(self, row: dict[str, Any]) -> dict[str, Any]:
        from ._helpers import _json_dict, _node_id
        from ._chord import _split_chord_sequence

        metadata = _json_dict(row.get("metadata"))
        scenes = metadata.get("scenes")
        if not isinstance(scenes, list):
            legacy_scene = _node_id(metadata.get("scene"))
            scenes = [legacy_scene] if legacy_scene else []
        chord_sequence = metadata.get("chord_sequence")
        if not isinstance(chord_sequence, list):
            chord_sequence = []
        chord_sequence = [part for part in (_node_id(item) for item in chord_sequence) if part]
        if not chord_sequence:
            parsed_sequence = _split_chord_sequence(row.get("chord"))
            if len(parsed_sequence) > 1:
                chord_sequence = parsed_sequence
        return {
            "id": row.get("id"),
            "session_tag": row.get("session_tag"),
            "content": row.get("content") or "",
            "chord": row.get("chord") or "",
            "chord_sequence": chord_sequence,
            "chord_root": row.get("chord_root") or "",
            "chord_quality": row.get("chord_quality") or "",
            "scenes": scenes,
            "status": row.get("status") or "active",
            "is_constant": bool(row.get("is_constant")),
            "reviewed_at": row.get("reviewed_at"),
            "activation_count": row.get("activation_count") or 0,
            "last_activated_at": row.get("last_activated_at"),
            "source_model": row.get("source_model") or "",
            "source_session_id": row.get("source_session_id"),
            "source_excerpt": row.get("source_excerpt") or "",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _public_candidate(self, item: dict[str, Any], *, run_id: Optional[str]) -> dict[str, Any]:
        row = item.get("row") or {}
        features = item.get("features") or {}
        star = self._public_star(row)
        return {
            **star,
            "run_id": run_id,
            "candidate_id": item.get("candidate_id"),
            "score": round(float(item.get("final_score") or 0.0), 4),
            "scores": {key: round(float(value or 0.0), 4) for key, value in features.items() if isinstance(value, (int, float))},
            "keyword_hits": item.get("keyword_hits") or [],
            "direct_reference_kind": str(item.get("direct_reference_kind") or ""),
        }
