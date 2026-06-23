from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Optional

from .room_text import (
    DOORS,
    DRAWERS_INTRO,
    ROOM_CHARTER,
    ROOM_FORMAT_HINT,
    SCENES_ACTIVE,
    SCENES_NORMAL,
    SCENES_QUIET,
    TRACE_PHRASES,
    ZONE_ORDER,
    door_priority,
    door_text,
    door_zone,
)
from .runtime import logger, now, parse_ts


# ── Charge Calculation ─────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def compute_charge(
    *,
    hot_star_score: float,
    hours_since_last_visit: Optional[float],
    unlinked_candidate_count: int,
    recent_message_count: int,
    undone_pin_count: int,
    refractory_hours: int = 4,
) -> float:
    """Compute room charge from 5 signals. Returns 0-1 scalar, not stored."""
    sig_knot_heat = _clamp(hot_star_score)

    if hours_since_last_visit is None:
        sig_absence = 0.8
    else:
        sig_absence = _clamp(hours_since_last_visit / 72.0)

    sig_unlinked = _clamp(unlinked_candidate_count / 5.0)
    sig_flow = _clamp(recent_message_count / 30.0)
    sig_pins = _clamp(undone_pin_count / 3.0)

    raw = (
        0.25 * sig_knot_heat
        + 0.20 * sig_absence
        + 0.20 * sig_unlinked
        + 0.15 * sig_flow
        + 0.20 * sig_pins
    )

    if hours_since_last_visit is not None and hours_since_last_visit < refractory_hours:
        decay = hours_since_last_visit / refractory_hours
        raw *= decay

    return _clamp(raw)


# ── Atmosphere ─────────────────────────────────────────────────────────

def render_scene(charge: float) -> str:
    if charge < 0.3:
        scenes = SCENES_QUIET
    elif charge < 0.7:
        scenes = SCENES_NORMAL
    else:
        scenes = SCENES_ACTIVE
    idx = int((charge * 100) % len(scenes))
    return scenes[idx]


# ── Trace ──────────────────────────────────────────────────────────────

def render_last_trace(traces: list[dict]) -> str:
    if not traces:
        return ""
    last = traces[0]
    action = last.get("action", "")
    return TRACE_PHRASES.get(action, f"上次来的时候，做了点什么({action})。")


# ── Door Rendering ─────────────────────────────────────────────────────

# Low charge: only show "always" priority doors + top N active ones
_LOW_CHARGE_EXTRA = 2


def render_doors(door_specs: list[dict], charge: float) -> str:
    """Render spatial door descriptions.

    door_specs: list of {key, count} from collect_door_counts().
    charge: 0-1 scalar.

    Returns the full room spatial text (zones, doors, actions).
    """
    if not door_specs:
        return ""

    count_map = {d["key"]: d.get("count", 0) for d in door_specs}

    # Decide which doors are visible
    if charge < 0.3:
        always = [d for d in DOORS if door_priority(d["key"]) == "always"]
        rest = [d for d in DOORS if door_priority(d["key"]) != "always" and count_map.get(d["key"], 0) > 0]
        rest.sort(key=lambda d: count_map.get(d["key"], 0), reverse=True)
        visible = always + rest[:_LOW_CHARGE_EXTRA]
    elif charge < 0.7:
        visible = list(DOORS)
    else:
        visible = list(DOORS)

    # Sort within visibility: active doors first (by count desc), then quiet
    # But preserve zone grouping — sort by (zone_order, -count)
    zone_idx = {z: i for i, z in enumerate(ZONE_ORDER)}

    def sort_key(d: dict) -> tuple:
        zi = zone_idx.get(door_zone(d["key"]), 99)
        c = count_map.get(d["key"], 0)
        return (zi, -c)

    visible.sort(key=sort_key)

    # Render by zone
    lines: list[str] = []
    seen_zones: set[str] = set()
    drawers_zone_has_read_box = any(
        d["key"] == "read_box" for d in visible
    )

    for door in visible:
        key = door["key"]
        zone = door_zone(key)
        count = count_map.get(key, 0)

        # Zone separator: blank line between zones
        if zone not in seen_zones:
            if seen_zones:
                lines.append("")
            seen_zones.add(zone)

            # Drawers special: if read_box is not visible but other drawer
            # doors are, prepend the intro line
            if zone == "drawers" and not drawers_zone_has_read_box:
                lines.append(DRAWERS_INTRO)
                lines.append("")

        text = door_text(key, count)
        lines.append(text)

    return "\n".join(lines)


# ── Full Layer Assembly ────────────────────────────────────────────────

def render_room_layers(
    charge: float,
    last_traces: list[dict],
    door_specs: list[dict],
) -> dict[str, str]:
    """Return {layer_name: text} matching assemble_layered_messages() keys."""
    scene = render_scene(charge)
    trace_line = render_last_trace(last_traces)
    doors = render_doors(door_specs, charge)

    slow_parts = [scene]
    if trace_line:
        slow_parts.append(trace_line)

    return {
        "stable": ROOM_CHARTER,
        "slow": "\n".join(slow_parts),
        "mem": "",
        "heartbeat": "",
        "tool_policy": doors,
        "format": ROOM_FORMAT_HINT,
    }


# ── Charge Signal Collection ──────────────────────────────────────────

async def collect_charge_signals(
    *,
    store: Any,
    star_service: Any,
    cfg: Any,
) -> dict[str, Any]:
    """Gather the 5 charge signals from real data sources."""
    hot_star_score = 0.0
    try:
        if star_service and star_service.supabase:
            from .stars import STAR_ACTIVATION_TABLE
            rows = await star_service.supabase.query(
                STAR_ACTIVATION_TABLE,
                {"select": "star_id,activated_at", "order": "activated_at.desc", "limit": "30"},
            )
            if rows:
                now_dt = now()
                total = 0.0
                for row in rows:
                    dt = parse_ts(row.get("activated_at"))
                    if dt:
                        age_days = max((now_dt - dt).total_seconds() / 86400.0, 0.05)
                        total += math.pow(age_days, -0.5)
                if total > 0:
                    hot_star_score = _clamp((math.log(total) + 2.5) / 4.5)
    except Exception:
        logger.debug("[Room] Failed to compute hot_star_score")

    hours_since_last_visit: Optional[float] = None
    last_visit = store.last_room_visit_at() if store else None
    if last_visit:
        dt = parse_ts(last_visit)
        if dt:
            hours_since_last_visit = max((now() - dt).total_seconds() / 3600.0, 0.0)

    unlinked_candidate_count = 0
    try:
        if star_service and star_service.supabase:
            from .stars import STAR_CANDIDATE_TABLE
            rows = await star_service.supabase.query(
                STAR_CANDIDATE_TABLE,
                {
                    "select": "id",
                    "action_status": "eq.pending",
                    "shown": "eq.true",
                    "limit": "20",
                },
            )
            unlinked_candidate_count = len(rows) if rows else 0
    except Exception:
        logger.debug("[Room] Failed to count unlinked candidates")

    recent_message_count = 0
    if store:
        since_iso = (now() - timedelta(hours=6)).isoformat()
        recent_message_count = store.room_message_count_since(since_iso)

    undone_pin_count = store.room_pin_count_undone() if store else 0

    return {
        "hot_star_score": hot_star_score,
        "hours_since_last_visit": hours_since_last_visit,
        "unlinked_candidate_count": unlinked_candidate_count,
        "recent_message_count": recent_message_count,
        "undone_pin_count": undone_pin_count,
    }
