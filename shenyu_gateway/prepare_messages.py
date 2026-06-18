from __future__ import annotations

import json
from typing import Any, Optional

from .runtime import json_dumps as _json_dumps, logger, now as _now, parse_ts as _parse_ts
from .context_layers import trim_cold_start_sources as _trim_cold_start_sources
from .tool_registry import is_gateway_native_tool
from .tool_loop import _tool_call_name


def cold_start_idle_minutes(session: dict) -> float:
    last_active = _parse_ts(session.get("last_active_at"))
    if not last_active:
        return 0.0
    return max((_now() - last_active).total_seconds() / 60.0, 0.0)


def maybe_prepare_cold_start_snapshot(
    session: dict,
    is_first_turn: bool,
    current_message_count: int,
    *,
    cfg: Any,
    store: Any,
) -> Optional[dict]:
    if not cfg.enable_cold_start:
        return None

    target_messages = cfg.cold_start_message_limit or cfg.max_client_messages or 8
    fill_count = max(int(target_messages) - max(int(current_message_count or 0), 0), 0)

    active = store.latest_active_cold_start_snapshot(session["id"])
    if active:
        if fill_count <= 0:
            store.complete_cold_start_snapshot(active["id"])
            return None
        active["sources"] = _trim_cold_start_sources(active.get("sources") or [], fill_count)
        active["source_message_count"] = sum(len(source.get("messages") or []) for source in active.get("sources") or [])
        active["source_session_tags"] = sorted(
            {source.get("session_tag") for source in active.get("sources") or [] if source.get("session_tag")}
        )
        return active

    if fill_count <= 0:
        return None

    reason = ""
    since = None
    idle_minutes = cold_start_idle_minutes(session)
    if is_first_turn:
        reason = "new_window"
    elif idle_minutes >= max(cfg.cold_start_idle_minutes, 1):
        reason = "stale_window_cross_activity"
        since = session.get("last_active_at")
    else:
        return None

    source_session = store.latest_context_source_session(
        exclude_session_id=None if is_first_turn else session["id"],
        since=since,
    )
    sources = store.latest_session_context(
        source_session["session_tag"],
        limit_messages=fill_count,
        since=since,
    ) if source_session else []
    if not sources:
        return None

    return store.write_cold_start_snapshot(
        session_id=session["id"],
        session_tag=session["session_tag"],
        reason=reason,
        sources=sources,
        trigger_last_active_at=session.get("last_active_at"),
        max_injections=max(cfg.max_client_messages or cfg.cold_start_message_limit or 8, 1),
    )


def prune_runtime_state(*, cfg: Any, store: Any, session_id: Optional[str] = None) -> dict[str, int]:
    if store is None:
        return {}
    return store.prune_runtime_state(
        session_id=session_id,
        message_retention=cfg.gateway_message_retention,
        context_snapshot_retention=cfg.gateway_context_snapshot_retention,
        raw_window_retention=cfg.gateway_context_snapshot_retention,
        cold_start_retention=cfg.gateway_cold_start_retention,
    )


def json_clone(value: Any) -> Any:
    return json.loads(_json_dumps(value))


def message_tool_call_ids(message: dict) -> list[str]:
    ids: list[str] = []
    for tool_call in message.get("tool_calls") or []:
        if isinstance(tool_call, dict) and tool_call.get("id"):
            ids.append(str(tool_call["id"]))
    return ids


def trailing_client_tool_results(
    messages: list[dict],
    assistant_idx: int,
    expected_ids: set[str],
) -> tuple[int, list[dict]]:
    if not expected_ids:
        return assistant_idx + 1, []
    found: set[str] = set()
    tool_results: list[dict] = []
    next_idx = assistant_idx + 1
    while next_idx < len(messages) and messages[next_idx].get("role") == "tool":
        tool_call_id = str(messages[next_idx].get("tool_call_id") or "")
        if tool_call_id not in expected_ids:
            return assistant_idx + 1, []
        found.add(tool_call_id)
        tool_results.append(messages[next_idx])
        next_idx += 1
    if found != expected_ids:
        return assistant_idx + 1, []
    return next_idx, tool_results


def inject_pending_gateway_tool_turns(
    messages: list[dict],
    store: Any,
    session_id: str,
) -> tuple[list[dict], dict[str, Any]]:
    rebuilt: list[dict] = []
    pending_ids: list[str] = []
    gateway_tool_messages_count = 0
    idx = 0

    while idx < len(messages):
        message = messages[idx]
        tool_calls = message.get("tool_calls") or []
        if message.get("role") != "assistant" or not isinstance(tool_calls, list) or not tool_calls:
            rebuilt.append(message)
            idx += 1
            continue
        if any(is_gateway_native_tool(_tool_call_name(call)) for call in tool_calls if isinstance(call, dict)):
            rebuilt.append(message)
            idx += 1
            continue

        client_tool_call_ids = message_tool_call_ids(message)
        next_idx, client_tool_results = trailing_client_tool_results(
            messages,
            idx,
            set(client_tool_call_ids),
        )
        if not client_tool_results:
            rebuilt.append(message)
            idx += 1
            continue

        pending = store.find_pending_gateway_tool_turn(session_id, client_tool_call_ids)
        if not pending:
            pending_count = store.count_pending_gateway_tool_turns(session_id)
            logger.info(
                "[GatewayTool] No pending mixed transcript found for client tool ids: %s (active_pending=%d)",
                ",".join(client_tool_call_ids),
                pending_count,
            )
            rebuilt.append(message)
            idx += 1
            continue

        original_assistant_message = pending.get("original_assistant_message") or message
        gateway_tool_messages = pending.get("gateway_tool_messages") or []
        rebuilt.append(json_clone(original_assistant_message))
        rebuilt.extend(json_clone(gateway_tool_messages))
        rebuilt.extend(client_tool_results)
        pending_ids.append(str(pending.get("id")))
        gateway_tool_messages_count += len(gateway_tool_messages)
        idx = next_idx

    return rebuilt, {
        "pending_gateway_tool_turns_injected": len(pending_ids),
        "pending_gateway_tool_turn_ids": pending_ids,
        "pending_gateway_tool_messages": gateway_tool_messages_count,
    }
