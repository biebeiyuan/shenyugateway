from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional


MEMORY_ISLAND_LAYER = "memory_island"
INTERNAL_LAYER_KEY = "_shenyu_context_layer"
DEFAULT_ISLAND_TAIL_MESSAGES = 32
DEFAULT_RAW_TOOL_PROTECTION_TURNS = 18


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def message_fingerprint(message: dict[str, Any]) -> str:
    payload = {
        key: message.get(key)
        for key in ("role", "content", "name", "tool_call_id", "tool_calls")
        if message.get(key) is not None
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def non_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if message.get("role") != "system"]


def common_prefix_length(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> int:
    count = 0
    for old, new in zip(left, right):
        if message_fingerprint(old) != message_fingerprint(new):
            break
        count += 1
    return count


def human_turn_groups(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Return complete slicing boundaries without splitting tool transcripts."""
    if not messages:
        return []
    starts = [index for index, message in enumerate(messages) if message.get("role") == "user"]
    if not starts:
        return [(0, len(messages))]
    if starts[0] > 0:
        starts.insert(0, 0)
    return [
        (start, starts[index + 1] if index + 1 < len(starts) else len(messages))
        for index, start in enumerate(starts)
    ]


def group_safe_start(messages: list[dict[str, Any]], desired_start: int) -> int:
    desired_start = max(0, min(int(desired_start or 0), len(messages)))
    if desired_start >= len(messages):
        return len(messages)
    for start, end in human_turn_groups(messages):
        if start <= desired_start < end:
            return start
    return desired_start


def _last_group_start(messages: list[dict[str, Any]]) -> int:
    groups = human_turn_groups(messages)
    return groups[-1][0] if groups else 0


def _has_tool_continuation(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        if message.get("role") == "tool":
            return True
        if message.get("role") == "assistant" and message.get("tool_calls"):
            return True
    return False


def classify_history_event(
    previous_messages: Optional[list[dict[str, Any]]],
    current_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    previous = non_system_messages(previous_messages or [])
    current = non_system_messages(current_messages)
    prefix = common_prefix_length(previous, current)
    detail = {
        "event_class": "initial",
        "common_prefix_messages": prefix,
        "previous_non_system_messages": len(previous),
        "current_non_system_messages": len(current),
        "new_human_turn": bool(current),
    }
    if not previous:
        return detail
    if len(previous) == len(current) == prefix:
        detail.update(event_class="retry", new_human_turn=False)
        return detail
    if prefix == len(previous) and len(current) > len(previous):
        appended = current[prefix:]
        if any(message.get("role") == "user" for message in appended):
            detail.update(event_class="new_user", new_human_turn=True)
        elif _has_tool_continuation(appended):
            detail.update(event_class="client_tool_continuation", new_human_turn=False)
        else:
            detail.update(event_class="continuation", new_human_turn=False)
        return detail
    if prefix == len(current) and len(current) < len(previous):
        detail.update(event_class="roll", new_human_turn=False)
        return detail

    previous_tail_start = _last_group_start(previous)
    current_tail_start = _last_group_start(current)
    if prefix >= previous_tail_start and prefix >= current_tail_start:
        detail.update(
            event_class="edit_tail",
            new_human_turn=bool(current and current[-1].get("role") == "user"),
        )
        return detail
    detail.update(event_class="branch", new_human_turn=True)
    return detail


def overflow_messages_for_limit(limit: Optional[int]) -> int:
    if not limit or limit <= 0:
        return 0
    rounded = int(round((int(limit) * 0.20) / 4.0) * 4)
    return max(20, min(rounded, 40))


def _new_epoch_id() -> str:
    return f"epoch_{uuid.uuid4().hex[:12]}"


def _anchor_offset(messages: list[dict[str, Any]], tail_messages: int) -> int:
    if not messages:
        return 0
    desired = max(0, len(messages) - max(int(tail_messages or 0), 0))
    return group_safe_start(messages, desired)


def select_chunked_window(
    messages: list[dict[str, Any]],
    *,
    limit: Optional[int],
    previous_state: Optional[dict[str, Any]],
    event_class: str,
    island_tail_messages: int = DEFAULT_ISLAND_TAIL_MESSAGES,
    raw_tool_protection_turns: int = DEFAULT_RAW_TOOL_PROTECTION_TURNS,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    system_prefix = [message for message in messages if message.get("role") == "system"]
    history = non_system_messages(messages)
    overflow = overflow_messages_for_limit(limit)
    high_water = int(limit or 0) + overflow if limit and limit > 0 else None
    previous_state = previous_state or {}

    reset_reason = ""
    if previous_state and previous_state.get("base_limit") != limit:
        reset_reason = "config_changed"
    state_compatible = bool(
        previous_state
        and previous_state.get("epoch_id")
        and previous_state.get("base_limit") == limit
        and event_class not in {"initial", "branch"}
    )
    if state_compatible:
        start = max(0, int(previous_state.get("window_start_index") or 0))
        if start > len(history):
            state_compatible = False
            reset_reason = "history_shorter_than_window_start"

    if not state_compatible:
        desired = max(0, len(history) - int(limit or len(history))) if limit and limit > 0 else 0
        start = group_safe_start(history, desired)
        epoch_id = _new_epoch_id()
        reset_reason = reset_reason or ("history_branch" if event_class == "branch" else "initial_window")
        epoch_reset = True
    else:
        epoch_id = str(previous_state["epoch_id"])
        epoch_reset = False

    retained = history[start:]
    high_water_deferred = bool(
        high_water
        and len(retained) > high_water
        and event_class in {"client_tool_continuation", "continuation"}
    )
    if high_water and len(retained) > high_water and not high_water_deferred:
        desired = max(0, len(history) - int(limit or len(history)))
        start = group_safe_start(history, desired)
        retained = history[start:]
        epoch_id = _new_epoch_id()
        reset_reason = "message_high_water"
        epoch_reset = True

    if epoch_reset:
        anchor_offset = _anchor_offset(retained, island_tail_messages)
    else:
        anchor_offset = max(0, min(int(previous_state.get("island_anchor_offset") or 0), len(retained)))

    groups = human_turn_groups(retained)
    state = {
        "epoch_id": epoch_id,
        "base_limit": limit,
        "overflow_messages": overflow,
        "high_water": high_water,
        "window_start_index": start,
        "island_anchor_offset": anchor_offset,
        "last_event_class": event_class,
        "reset_reason": reset_reason,
        "epoch_reset": epoch_reset,
        "raw_protected_turns": min(len(groups), max(int(raw_tool_protection_turns or 0), 0)),
        "island_state": previous_state.get("island_state") or {},
    }
    meta = {
        "client_messages_original": len(messages),
        "client_messages_retained": len(system_prefix) + len(retained),
        "client_non_system_original": len(history),
        "client_non_system_retained": len(retained),
        "max_client_messages": limit,
        "context_overflow_messages": overflow,
        "context_high_water": high_water,
        "context_epoch_id": epoch_id,
        "context_epoch_reset": epoch_reset,
        "context_epoch_reset_reason": reset_reason,
        "client_messages_trim_start": start,
        "memory_island_anchor_offset": anchor_offset,
        "human_turn_groups_retained": len(groups),
        "raw_tool_protection_turns": state["raw_protected_turns"],
        "context_high_water_deferred": high_water_deferred,
    }
    return system_prefix + retained, state, meta


def insert_bridge_messages(
    client_messages: list[dict[str, Any]],
    bridge_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not bridge_messages:
        return list(client_messages)
    insert_at = next(
        (index for index, message in enumerate(client_messages) if message.get("role") != "system"),
        len(client_messages),
    )
    merged = list(client_messages)
    merged[insert_at:insert_at] = list(bridge_messages)
    return merged
