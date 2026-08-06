from __future__ import annotations

from typing import Any, Optional


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def response_meta_enabled(context_meta: Optional[dict[str, Any]]) -> bool:
    profile = (context_meta or {}).get("client_profile") or {}
    return bool(isinstance(profile, dict) and profile.get("emit_response_meta"))


def _context_trim_in_rounds(window: dict[str, Any]) -> Optional[int]:
    try:
        high_water = int(window.get("context_high_water"))
        retained_messages = int(window.get("client_non_system_retained"))
    except (TypeError, ValueError):
        return None
    if high_water <= 0 or retained_messages < 0:
        return None
    # The current request already contains its user message. Each following
    # normal PWA turn adds the current assistant plus the next user message.
    return max(1, ((high_water - retained_messages) // 2) + 1)


def build_response_meta(
    context_meta: Optional[dict[str, Any]],
    cache_usage: Optional[dict[str, Any]],
    *,
    heartbeat_captured: bool = False,
    tool_rounds: int = 0,
    first_tool_round_cache_hit: bool = False,
) -> dict[str, Any]:
    """Build the content-free client status summary for one assistant reply."""
    window = (context_meta or {}).get("client_message_window") or {}
    retained = _non_negative_int(window.get("human_turn_groups_retained"))
    cache = cache_usage or {}
    cache_percent = cache.get("cache_read_percent")
    if not isinstance(cache_percent, (int, float)):
        cache_percent = None
    read_tokens = _non_negative_int(cache.get("cache_read_input_tokens"))
    total_tokens = _non_negative_int(cache.get("total_input_tokens"))
    rounds = _non_negative_int(tool_rounds)
    return {
        "context_rounds": retained,
        "context_trim_in_rounds": _context_trim_in_rounds(window),
        "cache_read_percent": round(float(cache_percent), 1) if cache_percent is not None else None,
        "cache_read_input_tokens": read_tokens,
        "cache_total_input_tokens": total_tokens,
        "tool_rounds": rounds,
        "first_tool_round_cache_hit": bool(rounds and first_tool_round_cache_hit),
        "heartbeat_captured": bool(heartbeat_captured),
    }


def attach_response_meta(
    completion: dict[str, Any],
    context_meta: Optional[dict[str, Any]],
    cache_usage: Optional[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    completion.setdefault("shenyu", {})["response_meta"] = build_response_meta(
        context_meta,
        cache_usage,
        **kwargs,
    )
    return completion
