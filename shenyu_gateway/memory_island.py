from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .runtime import local_day_of, local_today, parse_local_date
from .stars import render_star_context
from .utils import human_time_ago, shorten


STAR_SOFT_DIRECT_COOLDOWN_TURNS = 8
_STAR_HARD_DIRECT_KINDS = frozenset({"star_id", "exact_phrase"})
MEM_DUE_REMINDER_MODE = "due_reminder"


def _mem_date_note(item: dict[str, Any]) -> list[str]:
    """带日期的便签多说两句：这个日子到了没有，这张是多久前记的。

    只按 Asia/Shanghai 的整天算，所以同一天里渲染结果不变——动态岛是缓存断点，
    一句话每小时变一次会白烧掉一次缓存。
    """
    remind_on = parse_local_date(item.get("remind_on"))
    if not remind_on:
        return []
    today = local_today()
    if remind_on == today:
        parts = ["说的就是今天"]
    elif remind_on < today:
        parts = [f"说的是{remind_on.isoformat()}，已经过了"]
    else:
        parts = [f"说的是{remind_on.isoformat()}"]
    written_on = local_day_of(item.get("created_at"))
    if written_on:
        parts.append(f"{human_time_ago(max((today - written_on).days, 0))}记的")
    return parts


def render_mem_notes(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = ["## 我之前写下的便签，可能用的到。"]
    for item in items:
        summary = str(item.get("summary") or "").strip()
        content = str(item.get("content") or "").strip()
        text = summary or content
        if not text:
            continue
        mem_type = str(item.get("mem_type") or "").strip()
        prefix = f"{mem_type}：" if mem_type else ""
        anchors = _mem_date_note(item)
        for label, key in (("人", "people"), ("地", "places"), ("物", "objects")):
            values = item.get(key) or []
            if values:
                anchors.append(f"{label}：{'、'.join(str(value) for value in values[:3])}")
        suffix = f"（{'；'.join(anchors)}）" if anchors else ""
        lines.append(f"- {prefix}{shorten(text, 180)}{suffix}")
    return "\n".join(lines) if len(lines) > 1 else ""


def render_memory_island(stars: list[dict[str, Any]], mem_notes: list[dict[str, Any]]) -> str:
    blocks = []
    star_text = render_star_context(stars)
    if star_text:
        blocks.append("# 我之前落下的星星\n" + star_text)
    mem_text = render_mem_notes(mem_notes)
    if mem_text:
        blocks.append(mem_text)
    return "\n\n".join(blocks)


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or "")


def _render_item(kind: str, item: dict[str, Any]) -> str:
    if kind == "star":
        return render_star_context([item])
    return render_mem_notes([item])


def _fingerprints(kind: str, items: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for item in items:
        item_id = _item_id(item)
        if not item_id:
            continue
        rendered = _render_item(kind, item)
        result[item_id] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return result


def _log_item(kind: str, item: dict[str, Any]) -> dict[str, str]:
    content = str(item.get("content") or "").strip()
    if kind == "star":
        return {
            "id": _item_id(item),
            "text": shorten(content, 220),
            "label": str(item.get("chord") or "").strip(),
        }
    return {
        "id": _item_id(item),
        "text": shorten(str(item.get("summary") or content).strip(), 180),
        "label": str(item.get("mem_type") or "").strip(),
    }


def _lane_log_content(
    kind: str,
    old_items: list[dict[str, Any]],
    current_items: list[dict[str, Any]],
) -> dict[str, Any]:
    old_by_id = {_item_id(item): item for item in old_items if _item_id(item)}
    current_by_id = {_item_id(item): item for item in current_items if _item_id(item)}
    old_fingerprints = _fingerprints(kind, old_items)
    current_fingerprints = _fingerprints(kind, current_items)
    added_ids = set(current_by_id) - set(old_by_id)
    removed_ids = set(old_by_id) - set(current_by_id)
    updated_ids = {
        item_id
        for item_id in set(old_by_id) & set(current_by_id)
        if old_fingerprints.get(item_id) != current_fingerprints.get(item_id)
    }
    return {
        "current": [
            {
                **_log_item(kind, item),
                "change": (
                    "added"
                    if _item_id(item) in added_ids
                    else "updated"
                    if _item_id(item) in updated_ids
                    else "retained"
                ),
            }
            for item in current_items
        ],
        "removed": [_log_item(kind, item) for item in old_items if _item_id(item) in removed_ids],
        "updated": [
            {
                "id": item_id,
                "before": _log_item(kind, old_by_id[item_id]),
                "after": _log_item(kind, current_by_id[item_id]),
            }
            for item_id in current_by_id
            if item_id in updated_ids
        ],
        "added_count": len(added_ids),
        "removed_count": len(removed_ids),
        "updated_count": len(updated_ids),
    }


def memory_island_log_content(
    previous_state: dict[str, Any] | None,
    current_state: dict[str, Any] | None,
) -> dict[str, Any]:
    previous_state = previous_state or {}
    current_state = current_state or {}
    return {
        "version": current_state.get("version"),
        "star_count": len(current_state.get("stars") or []),
        "mem_count": len(current_state.get("mem_notes") or []),
        "rendered_text": current_state.get("rendered_text") or "",
        "stars": _lane_log_content(
            "star",
            list(previous_state.get("stars") or []),
            list(current_state.get("stars") or []),
        ),
        "mem_notes": _lane_log_content(
            "mem",
            list(previous_state.get("mem_notes") or []),
            list(current_state.get("mem_notes") or []),
        ),
    }


def _overlap(old_items: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> float:
    old_ids = {_item_id(item) for item in old_items if _item_id(item)}
    new_ids = {_item_id(item) for item in new_items if _item_id(item)}
    denominator = max(len(old_ids), len(new_ids))
    return len(old_ids & new_ids) / denominator if denominator else 1.0


def _legacy_forced_new_item(kind: str, old_items: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> bool:
    old_ids = {_item_id(item) for item in old_items if _item_id(item)}
    for item in new_items:
        if _item_id(item) in old_ids:
            continue
        if kind == "star" and item.get("force_island_rewrite") is True:
            return True
        if kind == "mem" and (
            item.get("search_mode") == "entity" or item.get("memory_kind") == "promise"
        ):
            return True
    return False


def _star_direct_force_reason(
    old_items: list[dict[str, Any]],
    proposed_items: list[dict[str, Any]],
    *,
    soft_seen_at: dict[str, int],
    human_turn_index: int,
    soft_direct_cooldown_turns: int,
) -> str:
    old_ids = {_item_id(item) for item in old_items if _item_id(item)}
    for item in proposed_items:
        star_id = _item_id(item)
        if not star_id or star_id in old_ids:
            continue
        kind = str(item.get("direct_reference_kind") or "")
        if kind in _STAR_HARD_DIRECT_KINDS:
            return f"direct_{kind}"
        if kind == "recall_unique":
            last_seen = soft_seen_at.get(star_id)
            if last_seen is None or human_turn_index - last_seen >= soft_direct_cooldown_turns:
                return "direct_recall_unique"
    return ""


def _soft_seen_turns(previous_state: dict[str, Any]) -> dict[str, int]:
    raw = previous_state.get("star_soft_direct_seen_at") or {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for star_id, value in raw.items():
        try:
            turn_index = int(value)
        except (TypeError, ValueError):
            continue
        clean_id = str(star_id or "").strip()
        if clean_id and turn_index >= 0:
            result[clean_id] = turn_index
    return result


def _choose_lane(
    kind: str,
    old_items: list[dict[str, Any]],
    proposed_items: list[dict[str, Any]],
    *,
    force_reason: str,
    overlap_threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    overlap = _overlap(old_items, proposed_items)
    old_fingerprints = _fingerprints(kind, old_items)
    new_fingerprints = _fingerprints(kind, proposed_items)
    shared_ids = set(old_fingerprints) & set(new_fingerprints)
    content_changed = any(old_fingerprints[item_id] != new_fingerprints[item_id] for item_id in shared_ids)
    legacy_forced_new = _legacy_forced_new_item(kind, old_items, proposed_items)
    empty_transition = bool(old_items) != bool(proposed_items)
    retain = bool(old_items) and not (
        force_reason
        or content_changed
        or legacy_forced_new
        or empty_transition
        or overlap < overlap_threshold
    )
    chosen = old_items if retain else proposed_items
    old_ids = {_item_id(item) for item in old_items if _item_id(item)}
    entering = [] if retain else [item for item in chosen if _item_id(item) not in old_ids]
    reason = "retained_overlap" if retain else "proposal_applied"
    if force_reason:
        reason = force_reason
    elif content_changed:
        reason = "content_changed"
    elif legacy_forced_new:
        reason = "direct_candidate"
    elif empty_transition:
        reason = "empty_transition"
    elif overlap < overlap_threshold:
        reason = "overlap_below_threshold"
    return chosen, entering, {
        "decision": "retained" if retain else "rewritten",
        "reason": reason,
        "overlap": round(overlap, 4),
        "old_count": len(old_items),
        "proposed_count": len(proposed_items),
        "chosen_count": len(chosen),
    }


def resolve_memory_island(
    previous_state: dict[str, Any] | None,
    proposed_stars: list[dict[str, Any]],
    proposed_mem_notes: list[dict[str, Any]],
    *,
    force: bool = False,
    force_reason: str = "",
    active_star_ids: set[str] | None = None,
    active_mem_note_ids: set[str] | None = None,
    advance_human_turn: bool = False,
    soft_direct_cooldown_turns: int = STAR_SOFT_DIRECT_COOLDOWN_TURNS,
    overlap_threshold: float = 2 / 3,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    previous_state = previous_state or {}
    old_stars = list(previous_state.get("stars") or [])
    old_mem = list(previous_state.get("mem_notes") or [])
    try:
        human_turn_index = max(0, int(previous_state.get("human_turn_index") or 0))
    except (TypeError, ValueError):
        human_turn_index = 0
    if advance_human_turn:
        human_turn_index += 1
    try:
        soft_direct_cooldown_turns = max(0, min(int(soft_direct_cooldown_turns), 100))
    except (TypeError, ValueError):
        soft_direct_cooldown_turns = STAR_SOFT_DIRECT_COOLDOWN_TURNS
    soft_seen_at = _soft_seen_turns(previous_state)
    external_force_reason = str(force_reason or "").strip() or ("forced" if force else "")
    star_force_reason = external_force_reason
    if not star_force_reason and active_star_ids is not None:
        old_star_ids = {_item_id(item) for item in old_stars if _item_id(item)}
        active_ids = {str(item or "").strip() for item in active_star_ids if str(item or "").strip()}
        if old_star_ids - active_ids:
            star_force_reason = "inactive_item"
    if not star_force_reason:
        star_force_reason = _star_direct_force_reason(
            old_stars,
            list(proposed_stars or []),
            soft_seen_at=soft_seen_at,
            human_turn_index=human_turn_index,
            soft_direct_cooldown_turns=soft_direct_cooldown_turns,
        )
    mem_force_reason = external_force_reason
    proposed_mem = list(proposed_mem_notes or [])
    if not mem_force_reason:
        # 到日子的提醒要挂上来，别等下一次重写——那个日子只有今天。
        old_mem_ids_for_due = {_item_id(item) for item in old_mem if _item_id(item)}
        if any(
            item.get("search_mode") == MEM_DUE_REMINDER_MODE
            and _item_id(item) not in old_mem_ids_for_due
            for item in proposed_mem
        ):
            mem_force_reason = "due_reminder"
    if active_mem_note_ids is not None:
        old_mem_ids = {_item_id(item) for item in old_mem if _item_id(item)}
        active_mem_ids = {
            str(item or "").strip()
            for item in active_mem_note_ids
            if str(item or "").strip()
        }
        inactive_old_mem_ids = old_mem_ids - active_mem_ids
        if inactive_old_mem_ids:
            proposed_mem = [
                item for item in proposed_mem if _item_id(item) not in inactive_old_mem_ids
            ]
            if not mem_force_reason:
                mem_force_reason = "inactive_item"
    stars, entering_stars, star_meta = _choose_lane(
        "star",
        old_stars,
        list(proposed_stars or []),
        force_reason=star_force_reason,
        overlap_threshold=overlap_threshold,
    )
    mem_notes, entering_mem, mem_meta = _choose_lane(
        "mem",
        old_mem,
        proposed_mem,
        force_reason=mem_force_reason,
        overlap_threshold=overlap_threshold,
    )
    chosen_star_ids = {_item_id(item) for item in stars if _item_id(item)}
    for item in proposed_stars or []:
        star_id = _item_id(item)
        if star_id in chosen_star_ids and item.get("direct_reference_kind") == "recall_unique":
            soft_seen_at[star_id] = human_turn_index
    rendered_text = render_memory_island(stars, mem_notes)
    rendered_hash = hashlib.sha256(rendered_text.encode("utf-8")).hexdigest()
    old_hash = str(previous_state.get("rendered_hash") or "")
    changed = rendered_hash != old_hash
    state = {
        "version": str(previous_state.get("version") or "") if not changed else f"island_{uuid.uuid4().hex[:12]}",
        "stars": stars,
        "mem_notes": mem_notes,
        "rendered_text": previous_state.get("rendered_text") if not changed else rendered_text,
        "rendered_hash": rendered_hash,
        "star_fingerprints": _fingerprints("star", stars),
        "mem_fingerprints": _fingerprints("mem", mem_notes),
        "human_turn_index": human_turn_index,
        "star_soft_direct_seen_at": soft_seen_at,
    }
    if not state["version"]:
        state["version"] = f"island_{uuid.uuid4().hex[:12]}"
    meta = {
        "changed": changed,
        "decision": "rewritten" if changed else "retained",
        "star": star_meta,
        "mem": mem_meta,
        "human_turn_index": human_turn_index,
        "force_reason": external_force_reason,
    }
    return state, {"stars": entering_stars, "mem_notes": entering_mem}, meta
