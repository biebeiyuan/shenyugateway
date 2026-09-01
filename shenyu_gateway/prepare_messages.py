from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import Request

from .chat_archive import ChatArchiveService, archive_window_safely
from .client_extra import expired_image_note_text
from .context_layers import (
    assemble_layered_messages,
    bridge_messages_from_snapshot,
    expired_image_fingerprints as _expired_image_fingerprints,
    non_system_message_count as _non_system_message_count,
    trim_client_extra_bundle_attachments as _trim_client_extra_bundle_attachments,
    trim_client_image_blocks as _trim_client_image_blocks,
    trim_client_tool_system_messages as _trim_client_tool_system_messages,
    trim_cold_start_sources as _trim_cold_start_sources,
    trim_mcp_tool_results as _trim_mcp_tool_results,
    trim_package_install_tool_results as _trim_package_install_tool_results,
)
from .echo import strip_leading_echo, trim_assistant_echoes
from .context_window import (
    classify_history_event,
    DEFAULT_ISLAND_TAIL_MESSAGES,
    compact_history_event_messages,
    deduplicate_bridge_messages,
    insert_bridge_messages,
    normalize_history_event_messages,
    select_chunked_window,
)
from .gateway_tools import GatewayToolService
from .mcp_registry import registry as _mcp_registry
from .private_capture import is_room_mode as _is_room_mode
from .request_logs import _mark_request_log_phase
from .runtime import iso_now as _iso_now, json_dumps as _json_dumps, logger, now as _now, parse_ts as _parse_ts
from .system_prefix_buffer import buffer_seconds_from_ttl, resolve_system_prefix
from .sessions import SessionManager
from .store import NEXT_REQUEST_COLD_START_TAG
from .tool_loop import _latest_user_text, _tool_call_name
from .tool_registry import is_gateway_native_tool


# Fire-and-forget background tasks (e.g. chat archiving). The event loop only keeps
# a weak reference to tasks created via asyncio.create_task, so an un-retained task
# can be garbage-collected mid-run and silently lose the archive write. Hold a strong
# reference here and drop it on completion — same pattern the lifespan workers use.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def pwa_history_ready_for_cold_start(client_name: str, message_count: int, cfg: Any) -> bool:
    """Once PWA owns a full client window, stop re-injecting handoff history."""
    if (client_name or "").strip().casefold() not in {"shenyu-pwa", "pwa", "shenyu-web"}:
        return False
    limit = int(getattr(cfg, "max_client_messages", 0) or 0)
    if limit <= 0:
        limit = int(getattr(cfg, "cold_start_message_limit", 0) or 0)
    return limit > 0 and int(message_count or 0) >= limit


def _resolve_client_profile(request: Request, client_name: str, cfg: Any) -> dict[str, Any]:
    """Resolve client-facing capabilities without changing provider behavior."""
    normalized_name = (client_name or "").strip().casefold()
    pwa_client = normalized_name in {"shenyu-pwa", "pwa", "shenyu-web"}
    requested_events = (request.headers.get("X-Shenyu-Tool-Events") or "").strip().casefold()
    requested_details = (request.headers.get("X-Shenyu-Tool-Details") or "").strip().casefold()
    emit_tool_events = pwa_client or requested_events in {"1", "true", "yes", "on"}
    emit_tool_event_details = emit_tool_events and requested_details in {"1", "true", "yes", "on"}
    configured_surface = str(getattr(cfg, "client_tool_surface", "all") or "all").strip().lower()
    return {
        "name": client_name or "unknown-client",
        "client_tool_surface": "none" if pwa_client else configured_surface,
        "emit_tool_events": emit_tool_events,
        "emit_tool_event_details": emit_tool_event_details,
        "emit_response_meta": pwa_client,
        "emit_echo_events": pwa_client,
        "tool_event_protocol": "sse+json" if emit_tool_events else "none",
    }


def _assistant_lineage(messages: list[dict], stored_messages: list[dict]) -> dict[str, Any]:
    client_text = strip_leading_echo(next(
        (
            str(message.get("content") or "")
            for message in reversed(messages)
            if message.get("role") == "assistant" and isinstance(message.get("content"), str)
        ),
        "",
    ))
    stored_text = strip_leading_echo(next(
        (
            str(message.get("content") or "")
            for message in reversed(stored_messages)
            if message.get("role") == "assistant"
        ),
        "",
    ))
    if not client_text or not stored_text:
        return {
            "available": False,
            "match": None,
            "client_chars": len(client_text),
            "stored_chars": len(stored_text),
        }
    client_hash = hashlib.sha256(client_text.encode("utf-8")).hexdigest()
    stored_hash = hashlib.sha256(stored_text.encode("utf-8")).hexdigest()
    return {
        "available": True,
        "match": client_hash == stored_hash,
        "client_chars": len(client_text),
        "stored_chars": len(stored_text),
        "client_sha256": client_hash[:16],
        "stored_sha256": stored_hash[:16],
    }


def _spawn_background_task(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


@dataclass(frozen=True)
class PrepareMessagesDeps:
    cfg: Any
    store: Any
    supabase_client: Any
    context_builder_factory: Callable[..., Any]
    client_name_from_request: Callable[[Request], str]
    session_tag_from_request: Callable[..., str]
    resolve_upstream: Callable[[], dict]
    maybe_prepare_cold_start_snapshot: Callable[..., Optional[dict]]
    prune_runtime_state: Callable[..., dict]


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

    target_messages = cfg.max_client_messages or cfg.cold_start_message_limit or 8
    fill_count = max(int(target_messages) - max(int(current_message_count or 0), 0), 0)

    active = store.latest_active_cold_start_snapshot(session["id"])
    if active:
        return active

    if fill_count <= 0:
        return None

    pending_next_request = store.latest_next_request_cold_start_snapshot()
    if pending_next_request:
        pending_sources = _trim_cold_start_sources(pending_next_request.get("sources") or [], fill_count)
        bound = store.write_cold_start_snapshot(
            session_id=session["id"],
            session_tag=session["session_tag"],
            reason=pending_next_request.get("reason") or f"manual_preview:{NEXT_REQUEST_COLD_START_TAG}",
            sources=pending_sources,
            trigger_last_active_at=session.get("last_active_at"),
            max_injections=1,
        )
        store.complete_cold_start_snapshot(pending_next_request["id"])
        return bound

    if not is_first_turn:
        return None

    source_session = store.latest_context_source_session(
        exclude_session_id=session["id"],
        since=None,
    )
    sources = store.latest_session_context(
        source_session["session_tag"],
        limit_messages=target_messages,
        since=None,
    ) if source_session else []
    if not sources:
        return None

    fixed_sources = _trim_cold_start_sources(sources, fill_count)
    snapshot = store.write_cold_start_snapshot(
        session_id=session["id"],
        session_tag=session["session_tag"],
        reason="new_window",
        sources=fixed_sources,
        trigger_last_active_at=session.get("last_active_at"),
        max_injections=1,
    )
    return snapshot


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


def _memory_island_force_reason(event_meta: dict[str, Any], window_state: dict[str, Any]) -> str:
    if window_state.get("reset_reason") == "message_high_water":
        return "message_high_water"
    if event_meta.get("event_class") == "branch":
        return "history_branch"
    return ""


def json_clone(value: Any) -> Any:
    return json.loads(_json_dumps(value))


def message_tool_call_ids(message: dict) -> list[str]:
    ids: list[str] = []
    for tool_call in message.get("tool_calls") or []:
        if isinstance(tool_call, dict) and tool_call.get("id"):
            ids.append(str(tool_call["id"]))
    return ids


def _tool_call_arguments_for_match(tool_call: dict) -> Any:
    function = tool_call.get("function") or {}
    arguments = function.get("arguments") if isinstance(function, dict) else None
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return arguments


def _client_visible_assistant_fingerprint(message: dict, tool_call_ids: set[str]) -> str:
    visible_calls = []
    for tool_call in message.get("tool_calls") or []:
        if not isinstance(tool_call, dict) or str(tool_call.get("id") or "") not in tool_call_ids:
            continue
        function = tool_call.get("function") or {}
        visible_calls.append(
            {
                "id": str(tool_call.get("id") or ""),
                "type": str(tool_call.get("type") or "function"),
                "name": str(function.get("name") or "") if isinstance(function, dict) else "",
                "arguments": _tool_call_arguments_for_match(tool_call),
            }
        )
    visible_calls.sort(key=lambda item: item["id"])
    payload = {
        "content": message.get("content") or "",
        "tool_calls": visible_calls,
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


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
    pending_lineage_mismatches = 0
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
        visible_ids = set(client_tool_call_ids)
        if _client_visible_assistant_fingerprint(message, visible_ids) != _client_visible_assistant_fingerprint(
            original_assistant_message,
            visible_ids,
        ):
            pending_lineage_mismatches += 1
            logger.info(
                "[GatewayTool] Pending transcript lineage mismatch for client tool ids: %s",
                ",".join(client_tool_call_ids),
            )
            rebuilt.append(message)
            idx += 1
            continue
        gateway_tool_messages = pending.get("gateway_tool_messages") or []
        rebuilt.append(json_clone(original_assistant_message))
        rebuilt.extend(json_clone(gateway_tool_messages))
        rebuilt.extend(client_tool_results)
        pending_ids.append(str(pending.get("id")))
        gateway_tool_messages_count += len(gateway_tool_messages)
        idx = next_idx

    meta = {
        "pending_gateway_tool_turns_injected": len(pending_ids),
        "pending_gateway_tool_turn_ids": pending_ids,
        "pending_gateway_tool_messages": gateway_tool_messages_count,
    }
    if pending_lineage_mismatches:
        meta["pending_gateway_tool_lineage_mismatches"] = pending_lineage_mismatches
    return rebuilt, meta


def _album_notes_for_expired_images(messages: list[dict], store: Any) -> dict[str, str]:
    """过期占位块的指纹 → 沈予存这张图时写下的那句话。

    查不到、没有 store、或查库出错都返回空字典：占位退回通用那句，图不会因此丢，
    也绝不让相册查询挡住一次对话。
    """
    fingerprints = _expired_image_fingerprints(messages)
    if not fingerprints or store is None:
        return {}
    try:
        rows = store.album_notes_by_fingerprints(fingerprints)
    except Exception as exc:
        logger.warning("[Album] 过期图备注查询失败，退回通用占位: %s", exc)
        return {}
    notes: dict[str, str] = {}
    for digest, row in (rows or {}).items():
        text = expired_image_note_text(row.get("note"), row.get("mood"))
        if text:
            notes[str(digest)] = text
    return notes


async def prepare_messages(
    request: Request,
    body: Any,
    deps: PrepareMessagesDeps,
) -> tuple[list[dict], dict]:
    cfg = deps.cfg
    store = deps.store
    log_entry = getattr(request.state, "shenyu_log_entry", None)
    _mark_request_log_phase(
        log_entry,
        "prepare.start",
        now_iso=_iso_now(),
        detail={"messages": len(body.messages), "tools": len(body.tools or [])},
    )
    sessions = SessionManager(store, cfg)
    tools = GatewayToolService()
    builder = deps.context_builder_factory(store, sessions, tools)

    client_name = deps.client_name_from_request(request)
    session_tag = deps.session_tag_from_request(request, client_name=client_name)
    client_profile = _resolve_client_profile(request, client_name, cfg)
    session = sessions.open_session(session_tag=session_tag, client_name=client_name)
    _mark_request_log_phase(
        log_entry,
        "prepare.session_opened",
        now_iso=_iso_now(),
        detail={"session_tag": session_tag, "client_name": client_name},
    )
    non_system_count = sum(1 for m in body.messages if m.role != "system")
    is_first_turn = non_system_count <= 1 or sessions.is_first_turn(session)

    raw_messages = [message.model_dump(exclude_none=True) for message in body.messages]
    raw_messages_for_archive, _ = _trim_client_image_blocks(raw_messages, keep_recent_messages=0)
    raw_messages_for_lineage = compact_history_event_messages(raw_messages)
    raw_messages_for_event = normalize_history_event_messages(raw_messages_for_lineage)
    raw_user_text = _latest_user_text(raw_messages_for_event)
    previous_raw_windows = store.get_recent_raw_request_windows(session["id"], limit=1)
    previous_raw_messages = previous_raw_windows[0].get("messages") if previous_raw_windows else None
    event_meta = classify_history_event(previous_raw_messages, raw_messages_for_lineage)
    lineage_meta = _assistant_lineage(
        raw_messages_for_lineage,
        store.get_recent_dialogue_messages(session["id"], limit=8),
    )
    store.write_raw_request_window(
        session_id=session["id"],
        session_tag=session_tag,
        client_name=client_name,
        messages=raw_messages_for_lineage,
        latest_user_text=raw_user_text,
    )
    _mark_request_log_phase(
        log_entry,
        "prepare.raw_window_stored",
        now_iso=_iso_now(),
        detail={"raw_messages": len(raw_messages_for_event)},
    )
    raw_message_count = _non_system_message_count(raw_messages)
    cold_start_snapshot = None
    pwa_handoff_retired = False
    pwa_history_ready = pwa_history_ready_for_cold_start(client_name, raw_message_count, cfg)
    if not pwa_history_ready:
        cold_start_snapshot = deps.maybe_prepare_cold_start_snapshot(session, is_first_turn, raw_message_count)
    elif pwa_history_ready:
        active_snapshot = store.latest_active_cold_start_snapshot(session["id"])
        if active_snapshot:
            store.complete_cold_start_snapshot(active_snapshot["id"])
            pwa_handoff_retired = True
    bridge_messages = bridge_messages_from_snapshot(cold_start_snapshot)
    deduplicated_bridge_messages, bridge_overlap_messages = deduplicate_bridge_messages(
        raw_messages,
        bridge_messages,
    )
    window_input = insert_bridge_messages(raw_messages, bridge_messages)
    previous_window_state = None if pwa_handoff_retired else store.get_context_window_state(session["id"])
    messages, window_state, trim_meta = select_chunked_window(
        window_input,
        limit=cfg.max_client_messages,
        previous_state=previous_window_state,
        event_class=event_meta["event_class"],
        head_slide_messages=int(event_meta.get("head_slide_messages") or 0),
        island_tail_messages=getattr(
            cfg, "island_tail_messages", DEFAULT_ISLAND_TAIL_MESSAGES
        ),
    )
    trim_meta.update(event_meta)
    trim_meta["assistant_lineage"] = lineage_meta
    trim_meta["cold_start_bridge_messages"] = max(
        0,
        len(deduplicated_bridge_messages) - int(window_state.get("window_start_index") or 0),
    )
    trim_meta["cold_start_bridge_overlap_messages"] = bridge_overlap_messages
    # A fully overlapping bridge is still part of the fixed cold-start handoff:
    # the client may omit that history again on its next request. Only retire
    # the snapshot after an actually inserted bridge has been pushed entirely
    # out by the rolling window.
    if (
        cold_start_snapshot
        and deduplicated_bridge_messages
        and trim_meta["cold_start_bridge_messages"] == 0
    ):
        store.complete_cold_start_snapshot(cold_start_snapshot["id"])
        window_state["window_start_index"] = max(
            0,
            int(window_state.get("window_start_index") or 0) - len(bridge_messages),
        )
        cold_start_snapshot = None
    client_tool_surface = client_profile["client_tool_surface"]
    messages, tool_system_trim_meta = _trim_client_tool_system_messages(
        messages,
        surface=client_tool_surface,
    )
    trim_meta.update(tool_system_trim_meta)
    messages, attachment_trim_meta = _trim_client_extra_bundle_attachments(messages, keep_recent_messages=3)
    trim_meta.update(attachment_trim_meta)
    messages, package_trim_meta = _trim_package_install_tool_results(messages, keep_recent=1)
    trim_meta.update(package_trim_meta)
    messages, mcp_trim_meta = _trim_mcp_tool_results(
        messages,
        keep_recent=getattr(cfg, "mcp_tool_result_keep_recent", 3),
    )
    trim_meta.update(mcp_trim_meta)
    await _mcp_registry.ensure_fresh(cfg)
    # 过期图占位块带着图片字节指纹。沈予存过相册的那些图，占位换成他当时写的那句
    # 话，而不是通用占位——这是「再看到这张图，读到的是自己写的」的落点。
    # 一次批量查库，不在裁剪循环里逐张查；查不到就沿用通用占位。
    album_notes = _album_notes_for_expired_images(messages, store)
    messages, image_trim_meta = _trim_client_image_blocks(
        messages,
        keep_recent_messages=2,
        album_notes=album_notes,
    )
    trim_meta.update(image_trim_meta)
    _mark_request_log_phase(
        log_entry,
        "prepare.client_messages_trimmed",
        now_iso=_iso_now(),
        detail={
            "original": len(raw_messages),
            "retained": len(messages),
            "max_client_messages": cfg.max_client_messages,
        },
    )
    user_text = _latest_user_text(messages)
    current_message_count = _non_system_message_count(messages)
    upstream = deps.resolve_upstream()
    archive_service = ChatArchiveService(store, deps.supabase_client, cfg)
    if archive_service.enabled():
        _spawn_background_task(
            archive_window_safely(
                archive_service,
                session_tag=session_tag,
                client_name=client_name,
                messages=raw_messages_for_archive,
            )
        )
    _mark_request_log_phase(
        log_entry,
        "prepare.cold_start_checked",
        now_iso=_iso_now(),
        detail={
            "injected": bool(cold_start_snapshot),
            "is_first_turn": is_first_turn,
            "event_class": event_meta["event_class"],
            "epoch_id": window_state["epoch_id"],
            "epoch_reset": window_state["epoch_reset"],
        },
    )
    snapshot_messages, _ = _trim_client_image_blocks(messages, keep_recent_messages=0)
    store.write_request_context_snapshot(
        session_id=session["id"],
        session_tag=session_tag,
        client_name=client_name,
        messages=snapshot_messages,
        latest_user_text=_latest_user_text(snapshot_messages),
    )
    _mark_request_log_phase(
        log_entry,
        "prepare.snapshot_stored",
        now_iso=_iso_now(),
        detail={"snapshot_messages": len(snapshot_messages)},
    )
    # Session snapshots keep the PWA transcript exactly as the client returned it.
    # Echo expiry applies only to the upstream-facing copy so old echoes remain
    # visible after a thread handoff or local-history restore.
    messages, echo_trim_meta = trim_assistant_echoes(
        messages,
        keep_subsequent_user_turns=getattr(cfg, "echo_retention_turns", 1),
    )
    trim_meta.update(echo_trim_meta)
    messages, pending_gateway_meta = inject_pending_gateway_tool_turns(
        messages,
        store,
        session_id=session["id"],
    )
    trim_meta.update(pending_gateway_meta)
    deps.prune_runtime_state(session["id"])
    _mark_request_log_phase(
        log_entry,
        "prepare.pending_tools_pruned",
        now_iso=_iso_now(),
        detail={"pending_gateway_tool_turns": len(pending_gateway_meta.get("pending_gateway_tool_turn_ids", []))},
    )

    # ── Room Mode Branch ───────────────────────────────────────────
    is_room = bool(
        getattr(cfg, "enable_room_mode", True)
        and _is_room_mode(user_text)
    )

    if is_room:
        package = await builder.build_room_context_package(session, trace_log=log_entry, messages=messages)
        layers = package["layers"]
        _mark_request_log_phase(
            log_entry,
            "prepare.room_layers_rendered",
            now_iso=_iso_now(),
            detail={"charge": package.get("charge")},
        )
        messages, layer_meta = assemble_layered_messages(messages, layers, cold_start_snapshot=None)
        trim_meta.update(layer_meta)
        store.upsert_context_window_state(session["id"], window_state)
        store.log_context_window_event(
            session_id=session["id"],
            session_tag=session["session_tag"],
            event_class=event_meta["event_class"],
            epoch_id=window_state["epoch_id"],
            detail={**trim_meta, "is_room": True},
        )
        _mark_request_log_phase(log_entry, "prepare.done", now_iso=_iso_now(), detail={"prepared_messages": len(messages), "mode": "room"})
        return messages, {
            "session": session,
            "package": package,
            "is_first_turn": is_first_turn,
            "snapshot_messages": snapshot_messages,
            "snapshot_latest_user_text": _latest_user_text(snapshot_messages),
            "cache_layers": layers,
            "client_message_window": trim_meta,
            "pending_gateway_tool_turn_ids": pending_gateway_meta.get("pending_gateway_tool_turn_ids", []),
            "cold_start_snapshot": None,
            "context_window_state": window_state,
            "context_event": event_meta,
            "is_room": True,
            "client_profile": client_profile,
            "upstream": upstream,
        }

    # ── Normal Path ────────────────────────────────────────────────
    previous_island_state = window_state.get("island_state") or {}
    if not previous_island_state and cold_start_snapshot:
        for source in reversed(cold_start_snapshot.get("sources") or []):
            source_session_id = source.get("session_id")
            if not source_session_id:
                continue
            source_window_state = store.get_context_window_state(str(source_session_id)) or {}
            previous_island_state = source_window_state.get("island_state") or {}
            if previous_island_state:
                break

    island_force_reason = _memory_island_force_reason(event_meta, window_state)
    package = await builder.build_context_package(
        session,
        current_user_text=user_text,
        is_first_turn=is_first_turn,
        cold_start_snapshot=cold_start_snapshot,
        client_name=client_name,
        context_event=event_meta,
        previous_island_state=previous_island_state,
        force_island_rewrite=bool(island_force_reason),
        force_island_reason=island_force_reason,
        trace_log=log_entry,
    )
    _mark_request_log_phase(
        log_entry,
        "prepare.context_package_built",
        now_iso=_iso_now(),
        detail={
            "mem_notes": len(package.get("mem_notes") or []),
            "stars": len(package.get("stars") or []),
            "calendar_days": len((package.get("calendar_context") or {}).get("day") or []),
        },
    )
    layers = builder.render_layered_additions(
        package,
        client_tool_surface=client_profile["client_tool_surface"],
    )
    window_state["island_state"] = package.get("memory_island_state") or {}

    # 系统前缀缓冲闸：heartbeat / 日历新写的内容先憋着，等到点或裁剪再顶上去，
    # 别让每次心跳注入都刷掉 system.end 前那一大块缓存。撤东西（删已注入 heartbeat、
    # 清日历页）不受缓冲拦，立即刷新。位置和顺序不动——这里只换文本内容。
    chosen_slow, chosen_heartbeat, system_prefix_state, prefix_decision = resolve_system_prefix(
        window_state.get("system_prefix_state"),
        layers.get("slow") or "",
        layers.get("heartbeat") or "",
        buffer_seconds=buffer_seconds_from_ttl(getattr(cfg, "anthropic_cache_ttl", "")),
        epoch_reset=bool(window_state.get("epoch_reset")),
    )
    layers["slow"] = chosen_slow
    layers["heartbeat"] = chosen_heartbeat
    window_state["system_prefix_state"] = system_prefix_state

    _mark_request_log_phase(
        log_entry,
        "prepare.layers_rendered",
        now_iso=_iso_now(),
        detail={key: len(value or "") for key, value in layers.items()},
    )

    messages, layer_meta = assemble_layered_messages(
        messages,
        layers,
        cold_start_snapshot=None,
        memory_island_anchor_offset=window_state.get("island_anchor_offset"),
    )
    trim_meta.update(layer_meta)
    store.upsert_context_window_state(session["id"], window_state)
    store.log_context_window_event(
        session_id=session["id"],
        session_tag=session["session_tag"],
        event_class=event_meta["event_class"],
        epoch_id=window_state["epoch_id"],
        detail={
            **trim_meta,
            "memory_island_decision": package.get("memory_island_decision") or {},
            "memory_island_version": (package.get("memory_island_state") or {}).get("version"),
            "system_prefix_decision": prefix_decision,
        },
    )
    _mark_request_log_phase(
        log_entry,
        "prepare.done",
        now_iso=_iso_now(),
        detail={"prepared_messages": len(messages)},
    )

    return messages, {
        "session": session,
        "package": package,
        "is_first_turn": is_first_turn,
        "snapshot_messages": snapshot_messages,
        "snapshot_latest_user_text": _latest_user_text(snapshot_messages),
        "cache_layers": layers,
        "client_message_window": trim_meta,
        "pending_gateway_tool_turn_ids": pending_gateway_meta.get("pending_gateway_tool_turn_ids", []),
        "cold_start_snapshot": cold_start_snapshot,
        "context_window_state": window_state,
        "context_event": event_meta,
        "client_profile": client_profile,
        "upstream": upstream,
    }
