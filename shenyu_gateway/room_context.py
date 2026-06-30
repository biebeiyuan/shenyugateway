from __future__ import annotations

import math
import random
from datetime import timedelta
from typing import Any, Optional

from .room_scenes import select_scene
from .room_text import (
    DOORS,
    DRAWERS_INTRO,
    ROOM_CHARTER,
    ROOM_FORMAT_HINT,
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

def render_scene(
    charge: float,
    *,
    weather_data: Optional[dict] = None,
    hours_since_last_visit: Optional[float] = None,
    prev_scene: Optional[dict] = None,
) -> tuple[str, str]:
    """Return (scene_text, scene_tag)."""
    return select_scene(
        charge,
        weather_data=weather_data,
        hours_since_last_visit=hours_since_last_visit,
        prev_scene=prev_scene,
    )


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


def visible_room_doors(door_specs: list[dict], charge: float) -> list[dict]:
    """Return the doors visible in the room at the current charge."""
    if not door_specs:
        return []

    count_map = {d["key"]: d.get("count", 0) for d in door_specs}

    if charge < 0.3:
        always = [d for d in DOORS if door_priority(d["key"]) == "always"]
        rest = [d for d in DOORS if door_priority(d["key"]) != "always" and count_map.get(d["key"], 0) > 0]
        rest.sort(key=lambda d: count_map.get(d["key"], 0), reverse=True)
        visible = always + rest[:_LOW_CHARGE_EXTRA]
    else:
        visible = list(DOORS)

    zone_idx = {z: i for i, z in enumerate(ZONE_ORDER)}

    def sort_key(d: dict) -> tuple:
        zi = zone_idx.get(door_zone(d["key"]), 99)
        c = count_map.get(d["key"], 0)
        return (zi, -c)

    visible.sort(key=sort_key)
    return visible


def visible_room_tool_names(door_specs: list[dict], charge: float) -> list[str]:
    """Return room_* tool names for currently visible doors."""
    return [str(door.get("tool") or "") for door in visible_room_doors(door_specs, charge) if door.get("tool")]


def render_doors(door_specs: list[dict], charge: float) -> str:
    """Render spatial door descriptions.

    door_specs: list of {key, count} from collect_door_counts().
    charge: 0-1 scalar.

    Returns the full room spatial text (zones, doors, actions).
    """
    if not door_specs:
        return ""

    count_map = {d["key"]: d.get("count", 0) for d in door_specs}
    visible = visible_room_doors(door_specs, charge)

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


# ── Passive Spatial Hints ──────────────────────────────────────────────
# Leak active door state into the scene as spatial observations,
# so Shenyu "notices" things without needing to call a tool first.

_PASSIVE_HINTS: dict[str, list[str]] = {
    "drawer_notes": [
        "中间那层抽屉没关紧，纸条的一角露在外面。",
        "抽屉缝里漏出一角纸。好像有人塞了新的。",
    ],
    "read_box": [
        "最上面那个木盒子好像沉了一点。",
        "木盒子的盖子没盖严。",
    ],
    "notebook": [
        "笔记本翻开着，最后一页有新写的几行。",
    ],
    "wall_pins": [
        "门边墙上多了几张便签，颜色是新的。",
    ],
}

_MAX_PASSIVE_HINTS = 3


def _render_passive_hints(door_specs: list[dict]) -> str:
    """Pick up to 2 spatial hints for doors with activity, plus star wall summary."""
    count_map = {d["key"]: d.get("count", 0) for d in door_specs}
    active = [key for key, count in count_map.items() if count > 0 and key in _PASSIVE_HINTS]
    hints = []

    # Star map wall: real data summary (always rendered if stars exist)
    star_spec = next((d for d in door_specs if d["key"] == "star_map"), None)
    if star_spec and star_spec.get("total", 0) > 0:
        star_hint = _render_star_wall_hint(star_spec)
        if star_hint:
            hints.append(star_hint)

    if not active:
        return "\n".join(hints)
    random.shuffle(active)
    for key in active[:_MAX_PASSIVE_HINTS]:
        hints.append(random.choice(_PASSIVE_HINTS[key]))
    return "\n".join(hints)


def _render_star_wall_hint(spec: dict) -> str:
    """Build star wall passive hint from real statistics."""
    total = spec.get("total", 0)
    links = spec.get("links", 0)
    latest = spec.get("latest")
    fading = spec.get("fading")

    # Line 1: total count + constellation lines
    if links > 0:
        line1 = f"星图墙亮着{total}颗星，{links}条星座线。"
    else:
        line1 = f"星图墙亮着{total}颗星。"

    parts = [line1]

    # Line 2: most recent star
    if latest:
        chord = latest.get("chord") or ""
        content = latest.get("content") or ""
        created_at = latest.get("created_at") or ""
        days_ago = _days_since(created_at)
        snippet = f"{chord}，{content}" if chord else content
        if snippet:
            if days_ago is not None and days_ago > 7:
                parts.append(f"最亮的那颗是{_human_time_ago(days_ago)}的——{snippet}")
            else:
                parts.append(f"最近的一颗还亮着——{snippet}")

    # Line 3: fading star
    if fading:
        chord = fading.get("chord") or ""
        last_at = fading.get("last_activated_at") or ""
        days_ago = _days_since(last_at)
        if chord and days_ago is not None:
            parts.append(f"角落里有一颗在暗——{chord}，{_human_time_ago(days_ago)}。")

    return "\n".join(parts)


def _days_since(iso_str: str) -> int | None:
    if not iso_str:
        return None
    dt = parse_ts(iso_str)
    if not dt:
        return None
    return max(int((now() - dt).total_seconds() / 86400.0), 0)


def _human_time_ago(days: int) -> str:
    if days < 1:
        return "今天"
    if days == 1:
        return "昨天"
    if days < 7:
        return f"{days}天前"
    weeks = days // 7
    if weeks == 1:
        return "一周前"
    if weeks < 5:
        return f"{weeks}周前"
    return f"{days}天前"


# ── Full Layer Assembly ────────────────────────────────────────────────

def render_room_layers(
    charge: float,
    last_traces: list[dict],
    door_specs: list[dict],
    *,
    weather_data: Optional[dict] = None,
    hours_since_last_visit: Optional[float] = None,
    prev_scene: Optional[dict] = None,
) -> tuple[dict[str, str], str]:
    """Return ({layer_name: text}, scene_tag)."""
    scene_text, scene_tag = render_scene(
        charge,
        weather_data=weather_data,
        hours_since_last_visit=hours_since_last_visit,
        prev_scene=prev_scene,
    )
    trace_line = render_last_trace(last_traces)
    passive_hints = _render_passive_hints(door_specs)
    doors = render_doors(door_specs, charge)

    slow_parts = [scene_text]
    if passive_hints:
        slow_parts.append(passive_hints)
    if trace_line:
        slow_parts.append(trace_line)

    layers = {
        "stable": ROOM_CHARTER,
        "slow": "\n".join(slow_parts),
        "mem": "",
        "heartbeat": "",
        "tool_policy": doors,
        "format": ROOM_FORMAT_HINT,
    }
    return layers, scene_tag


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
