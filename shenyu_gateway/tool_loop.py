from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from fastapi import HTTPException

from .request_logs import (
    _mark_request_log_phase,
    _message_log_preview,
    _payload_without_image_blocks,
    _record_completion_finish_reason,
    _upstream_payload_summary,
)
from .response_capture import AssistantTagFilter, split_private_assistant_tags
from .echo import EchoStreamFilter, split_leading_echo, strip_leading_echo
from .private_capture import restore_assistant_echo
from .private_capture import unpack_private_capture_result as _unpack_private_capture_result
from .response_meta import build_response_meta, response_meta_enabled
from .runtime import json_dumps as _json_dumps
from .runtime import logger, now_ts as _now_ts
from .store._admin import TOOL_ERROR_CONFIG_PHRASES
from .streaming import (
    StreamReplayAccumulator,
    _apply_openai_stream_chunk,
    _new_stream_chunk_id,
    _new_stream_completion,
    _stream_content_event,
    _stream_echo_event,
    _stream_final_event,
    _stream_keepalive_event,
    _stream_reasoning_event,
    _stream_role_event,
    _stream_response_meta_event,
    _stream_tool_event,
    close_stream_reader,
    flush_stream_tail_events,
    read_next_stream_chunk,
)
from .tool_registry import is_gateway_native_tool
from .upstream_adapter import (
    ANTHROPIC_CONTENT_BLOCKS_KEY,
    ANTHROPIC_THINKING_CONFIG_KEY,
    _anthropic_to_openai_completion,
    _assistant_tool_call_message,
    _cache_usage_summary,
    _completion_to_stream_events,
)
from .upstream_response_evidence import (
    ensure_upstream_response_evidence,
    observe_normalized_completion,
    observe_normalized_stream_chunk,
    observe_upstream_nonstream_response,
    upstream_response_evidence_snapshot,
)
from .utils import coerce_json_object as _coerce_json_object
from .utils import normalize_text as _normalize_text
from .utils import shorten as _shorten


@dataclass
class InternalToolLoopContext:
    request: Any
    body: Any
    prepared_messages: list[dict]
    meta: dict
    log_entry: Optional[dict]
    cfg: Any
    store: Any
    sessions: Any
    build_upstream_request: Callable[..., Awaitable[tuple[dict, dict, str, dict, dict]]]
    call_upstream_json: Callable[..., Awaitable[dict]]
    stream_upstream_openai_chunks: Callable[..., AsyncIterator[dict]]
    execute_gateway_tool: Callable[..., Awaitable[dict]]
    record_upstream_payload: Callable[..., None]
    aggregate_cache_usage: Callable[[list[dict]], dict]
    finalize_assistant_private_content: Callable[..., tuple[str, str, str, dict[str, Any]]]
    store_heartbeat: Callable[[str, dict, str], None]
    mark_context_consumed: Callable[[dict], None]
    write_completion_context_snapshot: Callable[[dict, str], Any]
    record_response_text: Callable[[dict, str], None]
    last_fallback_meta: dict[str, Any] = field(default_factory=lambda: {"applied": False})

    @property
    def session(self) -> dict:
        return self.meta["session"]

    @property
    def session_id(self) -> str:
        return self.session["id"]

    @property
    def session_tag(self) -> str:
        return self.session["session_tag"]


def _content_text_only(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item)
                continue
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text = item["text"]
                if text.strip():
                    parts.append(text)
        return "\n".join(parts)
    return _normalize_text(content)


def _anthropic_thinking_block_meta(assistant_message: dict) -> dict[str, Any]:
    blocks = assistant_message.get(ANTHROPIC_CONTENT_BLOCKS_KEY)
    if not isinstance(blocks, list):
        return {"preserved": False, "blocks": 0, "signature_present": False, "redacted_present": False}
    thinking_blocks = [
        block
        for block in blocks
        if isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"}
    ]
    return {
        "preserved": bool(thinking_blocks),
        "blocks": len(thinking_blocks),
        "signature_present": any(bool(block.get("signature")) for block in thinking_blocks),
        "redacted_present": any(block.get("type") == "redacted_thinking" for block in thinking_blocks),
    }


def _strip_anthropic_private_blocks(assistant_message: dict) -> None:
    assistant_message.pop(ANTHROPIC_CONTENT_BLOCKS_KEY, None)
    assistant_message.pop(ANTHROPIC_THINKING_CONFIG_KEY, None)


def _attach_anthropic_thinking_config(completion: dict, payload: dict, upstream: dict) -> None:
    if upstream.get("protocol") != "anthropic":
        return
    assistant_message = completion.get("choices", [{}])[0].get("message", {})
    if not assistant_message.get(ANTHROPIC_CONTENT_BLOCKS_KEY):
        return
    config: dict[str, Any] = {}
    if isinstance(payload.get("thinking"), dict):
        config["thinking"] = json.loads(json.dumps(payload["thinking"], ensure_ascii=False))
        config["output_config"] = json.loads(
            json.dumps(payload.get("output_config") or {}, ensure_ascii=False)
        )
    if config:
        assistant_message[ANTHROPIC_THINKING_CONFIG_KEY] = config


def _latest_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return _content_text_only(msg.get("content"))
    return ""


def _extract_tool_calls(completion: dict) -> list[dict]:
    choices = completion.get("choices") or []
    if not choices:
        return []
    choice = choices[0]
    message = choice.get("message", {})
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        message.pop("tool_calls", None)
        if choice.get("finish_reason") == "tool_calls":
            choice["finish_reason"] = "stop"
        return []
    valid_tool_calls = [
        call
        for call in tool_calls
        if isinstance(call, dict) and _tool_call_name(call).strip()
    ]
    if tool_calls != valid_tool_calls:
        if valid_tool_calls:
            message["tool_calls"] = valid_tool_calls
        else:
            message.pop("tool_calls", None)
            if choice.get("finish_reason") == "tool_calls":
                choice["finish_reason"] = "stop"
    return valid_tool_calls


def _tool_call_name(tool_call: dict) -> str:
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def _tool_call_arguments(tool_call: dict) -> dict:
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    if not isinstance(function, dict):
        function = {}
    raw_args = function.get("arguments")
    if raw_args is None:
        return {}
    args = _coerce_json_object(raw_args)
    if args is not None:
        return args
    return {} if not raw_args else {"raw_arguments": raw_args}


def _tool_call_log_preview(tool_calls: list[dict]) -> list[dict]:
    previews = []
    for call in tool_calls[:8]:
        previews.append(
            {
                "id": call.get("id"),
                "name": _tool_call_name(call),
                "arguments_preview": _shorten(json.dumps(_tool_call_arguments(call), ensure_ascii=False), 240),
            }
        )
    return previews


def _all_tool_calls_are_gateway_native(tool_calls: list[dict]) -> bool:
    names = [_tool_call_name(call) for call in tool_calls]
    return bool(names) and all(is_gateway_native_tool(name) for name in names)


def _tool_call_cache_key(name: str, args: dict) -> str:
    try:
        args_text = json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        args_text = _json_dumps(args or {})
    return f"{name}:{args_text}"


def _tool_events_enabled(ctx: InternalToolLoopContext) -> bool:
    profile = ctx.meta.get("client_profile") if isinstance(ctx.meta, dict) else None
    return bool(isinstance(profile, dict) and profile.get("emit_tool_events"))


def _tool_event_details_enabled(ctx: InternalToolLoopContext) -> bool:
    profile = ctx.meta.get("client_profile") if isinstance(ctx.meta, dict) else None
    return bool(isinstance(profile, dict) and profile.get("emit_tool_event_details"))


def _echo_events_enabled(ctx: InternalToolLoopContext) -> bool:
    profile = ctx.meta.get("client_profile") if isinstance(ctx.meta, dict) else None
    return bool(isinstance(profile, dict) and profile.get("emit_echo_events"))


def _next_process_order(ctx: InternalToolLoopContext) -> int:
    order = max(0, int(ctx.meta.get("_client_process_order") or 0))
    ctx.meta["_client_process_order"] = order + 1
    return order


def _record_echo_segment(ctx: InternalToolLoopContext, echo: str) -> Optional[dict[str, Any]]:
    if not (echo or "").strip():
        return None
    segment = {"content": echo, "stream_order": _next_process_order(ctx)}
    ctx.meta.setdefault("echo_segments", []).append(segment)
    return segment


def _combined_echo_text(ctx: InternalToolLoopContext) -> str:
    segments = ctx.meta.get("echo_segments") if isinstance(ctx.meta, dict) else None
    if not isinstance(segments, list):
        return ""
    return "".join(
        str(item.get("content") or "")
        for item in segments
        if isinstance(item, dict)
    )


def _record_tool_event(
    ctx: InternalToolLoopContext,
    *,
    phase: str,
    tool_call: dict,
    name: str,
    round_index: int,
    cached: Optional[bool] = None,
    result: Optional[dict] = None,
    duration_ms: Optional[int] = None,
) -> Optional[dict]:
    if not _tool_events_enabled(ctx):
        return None
    args = _tool_call_arguments(tool_call)
    event = {
        "phase": phase,
        "tool_call_id": str(tool_call.get("id") or ""),
        "name": name,
        "target_tool": _target_tool_name(name, args),
        "round": round_index + 1,
    }
    order_key = str(tool_call.get("id") or f"{name}:{round_index}")
    process_orders = ctx.meta.setdefault("_tool_process_orders", {})
    if phase == "tool_start" or order_key not in process_orders:
        process_orders[order_key] = _next_process_order(ctx)
    event["stream_order"] = process_orders[order_key]
    if cached is not None:
        event["cached"] = bool(cached)
    if duration_ms is not None:
        event["duration_ms"] = max(0, int(duration_ms))
    if result is not None:
        raw_ok = result.get("ok") if isinstance(result, dict) else None
        event["ok"] = raw_ok if isinstance(raw_ok, bool) else None
        if isinstance(result, dict) and result.get("error_kind"):
            event["error_kind"] = str(result["error_kind"])
    if _tool_event_details_enabled(ctx):
        event["input"] = args
        if result is not None:
            # This is the exact JSON string appended to the next upstream tool-result message.
            event["output"] = _json_dumps(result)
    ctx.meta.setdefault("tool_events", []).append(event)
    if ctx.log_entry is not None:
        # Tool details are for the current opted-in client only. Request logs retain the
        # existing compact diagnostic metadata and must not persist raw resident data.
        log_event = {key: value for key, value in event.items() if key not in {"input", "output"}}
        ctx.log_entry.setdefault("tool_events", []).append(log_event)
    return event


def _attach_tool_events(completion: dict, ctx: InternalToolLoopContext) -> dict:
    events = ctx.meta.get("tool_events") if isinstance(ctx.meta, dict) else None
    if not events:
        return completion
    completion.setdefault("shenyu", {})["tool_events"] = json.loads(_json_dumps(events))
    return completion


def _attach_echo_segments(completion: dict, ctx: InternalToolLoopContext) -> dict:
    if not _echo_events_enabled(ctx):
        return completion
    segments = ctx.meta.get("echo_segments") if isinstance(ctx.meta, dict) else None
    if not isinstance(segments, list) or not segments:
        return completion
    shenyu = completion.setdefault("shenyu", {})
    shenyu["echo"] = _combined_echo_text(ctx)
    shenyu["echo_segments"] = json.loads(_json_dumps(segments))
    return completion


def _tool_response_meta(ctx: InternalToolLoopContext) -> dict[str, Any]:
    rounds = list((ctx.log_entry or {}).get("internal_tool_rounds") or [])
    first_cache = (rounds[0].get("cache_usage") or {}) if rounds else {}
    tool_rounds = sum(1 for round_item in rounds if round_item.get("tools"))
    return build_response_meta(
        ctx.meta,
        (ctx.log_entry or {}).get("cache_usage") or {},
        heartbeat_captured=bool(ctx.meta.get("heartbeat_captured")),
        tool_rounds=tool_rounds,
        first_tool_round_cache_hit=bool(
            tool_rounds and first_cache.get("cache_read_input_tokens", 0) > 0
        ),
    )


async def _execute_mixed_gateway_tool_calls(
    ctx: InternalToolLoopContext,
    completion: dict,
    tool_calls: list[dict],
) -> tuple[dict, list[dict], list[dict]]:
    """Execute gateway-native calls from a mixed tool batch and leave client calls for the client."""
    normalized_tool_calls = [_ensure_tool_call_id(call, index) for index, call in enumerate(tool_calls)]
    assistant_message = completion.get("choices", [{}])[0].get("message", {})
    base_content = _normalize_text(assistant_message.get("content"))
    assistant_message["content"] = base_content
    assistant_message["tool_calls"] = normalized_tool_calls

    gateway_calls = [call for call in normalized_tool_calls if is_gateway_native_tool(_tool_call_name(call))]
    client_calls = [call for call in normalized_tool_calls if not is_gateway_native_tool(_tool_call_name(call))]
    if not gateway_calls or not client_calls:
        return completion, gateway_calls, client_calls

    gateway_tool_messages: list[dict] = []
    for tool_call in gateway_calls:
        name = _tool_call_name(tool_call)
        args = _tool_call_arguments(tool_call)
        try:
            result = await ctx.execute_gateway_tool(name, args, session_tag=ctx.session_tag, cfg=ctx.cfg)
        except Exception as exc:
            logger.exception("[GatewayTool] Mixed tool call failed: %s", name)
            result = {"ok": False, "error": str(exc), "error_kind": "exception"}
        result = _decorate_tool_error_result(result)
        ctx.sessions.log_tool_result(ctx.session_id, name, args, result)
        if isinstance(result, dict) and result.get("ok") is False:
            _record_tool_error(ctx, name, args, result)
        gateway_tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "name": name,
                "content": _json_dumps(result),
            }
        )

    original_assistant_message = _pending_assistant_tool_call_message(assistant_message, normalized_tool_calls)
    ctx.store.create_pending_gateway_tool_turn(
        session_id=ctx.session_id,
        session_tag=ctx.session_tag or "",
        client_tool_call_ids=[str(call.get("id")) for call in client_calls if call.get("id")],
        original_assistant_message=original_assistant_message,
        gateway_tool_messages=gateway_tool_messages,
    )
    assistant_message["tool_calls"] = client_calls
    logger.info(
        "[GatewayTool] Executed %d native calls from mixed batch; forwarding %d client calls with hidden transcript.",
        len(gateway_calls),
        len(client_calls),
    )
    return completion, gateway_calls, client_calls


def _pending_assistant_tool_call_message(assistant_message: dict, tool_calls: list[dict]) -> dict:
    pending_copy = dict(assistant_message or {})
    clean_content, _ = split_private_assistant_tags(
        strip_leading_echo(_normalize_text(pending_copy.get("content")))
    )
    pending_copy["content"] = clean_content
    return _assistant_tool_call_message(pending_copy, tool_calls)


def _ensure_tool_call_id(tool_call: dict, index: int = 0) -> dict:
    normalized = json.loads(_json_dumps(tool_call if isinstance(tool_call, dict) else {}))
    if not normalized.get("id"):
        normalized["id"] = f"call_gw_{uuid.uuid4().hex[:12]}_{index}"
    normalized.setdefault("type", "function")
    function = normalized.setdefault("function", {})
    if not isinstance(function, dict):
        normalized["function"] = {}
    return normalized


async def run_internal_tool_loop(ctx: InternalToolLoopContext) -> dict:
    working_messages = list(ctx.prepared_messages)
    upstream_usages: list[dict] = []
    tool_result_cache: dict[str, dict] = {}
    latest_user_text = _latest_user_text(ctx.prepared_messages)

    for round_index in range(max(1, ctx.cfg.max_internal_tool_rounds)):
        _mark_request_log_phase(ctx.log_entry, "tool_loop.round_build_start", detail={"round": round_index + 1})
        payload, headers, _, cache_meta, upstream = await ctx.build_upstream_request(
            ctx.request,
            ctx.body,
            messages_override=working_messages,
            meta=ctx.meta,
        )
        _mark_request_log_phase(
            ctx.log_entry,
            "tool_loop.round_build_done",
            detail={"round": round_index + 1, "messages": len(working_messages)},
        )
        ctx.record_upstream_payload(ctx.log_entry, payload, headers)
        round_log = _start_round_log(ctx, round_index, working_messages)
        _record_round_request(ctx, round_log, payload, headers, working_messages, cache_meta)
        if ctx.log_entry is not None and round_index == 0:
            ctx.log_entry["prompt_cache"] = cache_meta

        response_evidence = ensure_upstream_response_evidence(
            upstream,
            payload,
            "nonstream",
            reset=True,
        )
        _record_round_response_evidence(ctx, round_log, upstream)
        _mark_request_log_phase(ctx.log_entry, "upstream.nonstream_start", detail={"round": round_index + 1})
        raw = await ctx.call_upstream_json(ctx.request, upstream["chat_url"], payload, headers)
        observe_upstream_nonstream_response(response_evidence, raw)
        _mark_request_log_phase(ctx.log_entry, "upstream.nonstream_done", detail={"round": round_index + 1})
        upstream_usages.append(raw.get("usage", {}))
        _record_round_usage(
            ctx,
            round_log,
            raw.get("usage", {}),
            upstream_usages,
            protocol=upstream.get("protocol", ""),
        )

        proto = upstream["protocol"]
        completion = (
            _anthropic_to_openai_completion(ctx.body.model, raw)
            if proto == "anthropic"
            else {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": _now_ts(),
                "model": ctx.body.model,
                "choices": raw.get("choices", []),
                "usage": raw.get("usage", {}),
            }
        )
        observe_normalized_completion(response_evidence, completion)
        _record_round_response_evidence(ctx, round_log, upstream)
        _attach_anthropic_thinking_config(completion, payload, upstream)
        tool_calls = _extract_tool_calls(completion)
        _record_completion_finish_reason(ctx.log_entry, completion, round_log=round_log)
        _record_round_response(round_log, completion)
        if not tool_calls or not _all_tool_calls_are_gateway_native(tool_calls):
            await _finalize_non_gateway_tool_reply(
                ctx,
                completion,
                tool_calls,
                round_log,
                latest_user_text=latest_user_text,
            )
            if response_meta_enabled(ctx.meta):
                completion.setdefault("shenyu", {})["response_meta"] = _tool_response_meta(ctx)
            return _attach_echo_segments(_attach_tool_events(completion, ctx), ctx)

        assistant_message = completion.get("choices", [{}])[0].get("message", {})
        intermediate_echo = split_leading_echo(_content_text_only(assistant_message.get("content"))).echo
        _record_echo_segment(ctx, intermediate_echo)
        _append_assistant_tool_call_message(working_messages, completion, tool_calls, round_log)
        for tool_call in tool_calls:
            _record_tool_event(
                ctx,
                phase="tool_start",
                tool_call=tool_call,
                name=_tool_call_name(tool_call),
                round_index=round_index,
            )
            result, args, name, cached, duration_ms = await _execute_internal_tool_call(
                ctx,
                tool_call,
                tool_result_cache,
                log_label="Internal tool call failed",
            )
            _record_tool_event(
                ctx,
                phase="tool_end",
                tool_call=tool_call,
                name=name,
                round_index=round_index,
                cached=cached,
                result=result,
                duration_ms=duration_ms,
            )
            _append_tool_round_log(round_log, name, args, cached, result, duration_ms=duration_ms)
            working_messages.append(_tool_result_message(tool_call, name, result))

    raise HTTPException(status_code=500, detail="Exceeded internal gateway tool rounds.")


async def run_internal_tool_loop_stream(ctx: InternalToolLoopContext):
    working_messages = list(ctx.prepared_messages)
    upstream_usages: list[dict] = []
    tool_result_cache: dict[str, dict] = {}
    latest_user_text = _latest_user_text(ctx.prepared_messages)
    stream_chunk_id = _new_stream_chunk_id()
    stream_created = _now_ts()

    _mark_request_log_phase(ctx.log_entry, "stream.role_start")
    yield _stream_role_event(ctx.body.model, chunk_id=stream_chunk_id, created=stream_created)
    _mark_request_log_phase(ctx.log_entry, "stream.role_sent")

    for round_index in range(max(1, ctx.cfg.max_internal_tool_rounds)):
        _mark_request_log_phase(ctx.log_entry, "tool_loop.round_build_start", detail={"round": round_index + 1})
        payload, headers, _, cache_meta, upstream = await ctx.build_upstream_request(
            ctx.request,
            ctx.body,
            messages_override=working_messages,
            meta=ctx.meta,
        )
        _mark_request_log_phase(
            ctx.log_entry,
            "tool_loop.round_build_done",
            detail={"round": round_index + 1, "messages": len(working_messages)},
        )
        payload["stream"] = True
        ctx.record_upstream_payload(ctx.log_entry, payload, headers)
        round_log = _start_round_log(ctx, round_index, working_messages, stream=True)
        _record_round_request(ctx, round_log, payload, headers, working_messages, cache_meta)
        if ctx.log_entry is not None and round_index == 0:
            ctx.log_entry["prompt_cache"] = cache_meta

        completion = _new_stream_completion(ctx.body.model)
        tag_filter = AssistantTagFilter()
        echo_filter = EchoStreamFilter()
        stream_replay = StreamReplayAccumulator()
        first_upstream_chunk_seen = False
        response_evidence = ensure_upstream_response_evidence(
            upstream,
            payload,
            "stream",
            reset=True,
        )
        _record_round_response_evidence(ctx, round_log, upstream)

        _mark_request_log_phase(ctx.log_entry, "upstream.stream_start", detail={"round": round_index + 1})
        upstream_chunks = ctx.stream_upstream_openai_chunks(ctx.request, payload, headers, ctx.body.model, upstream)
        next_chunk = asyncio.create_task(anext(upstream_chunks))
        try:
            while True:
                read_result = await read_next_stream_chunk(
                    upstream_chunks=upstream_chunks,
                    next_chunk=next_chunk,
                    request=ctx.request,
                )
                if read_result.kind == "keepalive":
                    yield _stream_keepalive_event(ctx.body.model, chunk_id=stream_chunk_id, created=stream_created)
                    continue
                if read_result.kind == "disconnected":
                    if ctx.log_entry is not None:
                        ctx.log_entry["status"] = "client_disconnected"
                        ctx.log_entry["error"] = "Client disconnected during native internal gateway tool stream."
                    return
                if read_result.kind == "exhausted":
                    _mark_request_log_phase(ctx.log_entry, "upstream.stream_exhausted", detail={"round": round_index + 1})
                    if not first_upstream_chunk_seen:
                        if round_log is not None:
                            started = round_log.pop("_started_monotonic", None)
                            if started is not None:
                                round_log["upstream_duration_ms"] = max(
                                    0, int((time.monotonic() - float(started)) * 1000)
                                )
                        raise HTTPException(status_code=502, detail="上游返回空流，未收到任何有效响应事件。")
                    break

                data = read_result.data or {}
                if not first_upstream_chunk_seen:
                    first_upstream_chunk_seen = True
                    _mark_request_log_phase(ctx.log_entry, "upstream.stream_first_chunk", detail={"round": round_index + 1})
                next_chunk = asyncio.create_task(anext(upstream_chunks))
                observe_normalized_stream_chunk(response_evidence, data)
                _apply_openai_stream_chunk(completion, data)
                choice = (data.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if delta.get("tool_calls"):
                    stream_replay.mark_tool_call_seen()
                    continue
                if stream_replay.should_skip_visible_delta():
                    continue
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield _stream_reasoning_event(
                        ctx.body.model,
                        stream_replay.record_reasoning(reasoning),
                        chunk_id=stream_chunk_id,
                        created=stream_created,
                    )
                text = delta.get("content")
                if text:
                    echo_visible, echo_delta, _echo_closed = echo_filter.feed(text)
                    if echo_delta and (ctx.meta.get("client_profile") or {}).get("emit_echo_events"):
                        yield _stream_echo_event(
                            ctx.body.model,
                            echo_delta,
                            chunk_id=stream_chunk_id,
                            created=stream_created,
                        )
                    filtered = tag_filter.feed(echo_visible)
                    if filtered:
                        yield _stream_content_event(
                            ctx.body.model,
                            stream_replay.record_content(filtered),
                            chunk_id=stream_chunk_id,
                            created=stream_created,
                        )
        finally:
            await close_stream_reader(upstream_chunks=upstream_chunks, next_chunk=next_chunk)
            _record_round_response_evidence(ctx, round_log, upstream)

        usage = completion.get("usage") or {}
        _attach_anthropic_thinking_config(completion, payload, upstream)
        upstream_usages.append(usage)
        _record_round_usage(
            ctx,
            round_log,
            usage,
            upstream_usages,
            protocol=upstream.get("protocol", ""),
        )
        _mark_request_log_phase(ctx.log_entry, "upstream.stream_round_done", detail={"round": round_index + 1})

        tool_calls = _extract_tool_calls(completion)
        _record_completion_finish_reason(ctx.log_entry, completion, round_log=round_log)
        _record_round_response(round_log, completion)
        tail_events, remaining = flush_stream_tail_events(
            ctx.body.model,
            echo_filter=echo_filter,
            tag_filter=tag_filter,
            emit_echo_events=_echo_events_enabled(ctx),
            chunk_id=stream_chunk_id,
            created=stream_created,
        )
        if remaining:
            stream_replay.mark_visible_output(remaining)
        for chunk in tail_events:
            yield chunk
        if not tool_calls or not _all_tool_calls_are_gateway_native(tool_calls):
            await _finalize_non_gateway_tool_reply(
                ctx,
                completion,
                tool_calls,
                round_log,
                latest_user_text=latest_user_text,
            )
            ctx.mark_context_consumed(ctx.meta)
            if ctx.log_entry is not None:
                ctx.log_entry["status"] = "ok"
                ctx.record_response_text(ctx.log_entry, _normalize_text(completion.get("choices", [{}])[0].get("message", {}).get("content")))

            if tool_calls:
                if response_meta_enabled(ctx.meta):
                    yield _stream_response_meta_event(
                        ctx.body.model,
                        _tool_response_meta(ctx),
                        chunk_id=stream_chunk_id,
                        created=stream_created,
                    )
                replay_completion = stream_replay.replay_completion(completion)
                for chunk in _completion_to_stream_events(
                    replay_completion,
                    include_role=False,
                    content_chunk_chars=1200,
                    chunk_id=stream_chunk_id,
                ):
                    yield chunk
            else:
                fallback_meta = ctx.last_fallback_meta
                if fallback_meta["applied"] and not stream_replay.visible_output_sent:
                    yield _stream_content_event(
                        ctx.body.model,
                        fallback_meta["text"],
                        chunk_id=stream_chunk_id,
                        created=stream_created,
                    )
                if response_meta_enabled(ctx.meta):
                    yield _stream_response_meta_event(
                        ctx.body.model,
                        _tool_response_meta(ctx),
                        chunk_id=stream_chunk_id,
                        created=stream_created,
                    )
                yield _stream_final_event(
                    ctx.body.model,
                    completion.get("choices", [{}])[0].get("finish_reason") or "stop",
                    chunk_id=stream_chunk_id,
                    created=stream_created,
                )
                yield "data: [DONE]\n\n"
                _mark_request_log_phase(ctx.log_entry, "stream.done_sent")
            return

        _record_echo_segment(ctx, echo_filter.echo_text)
        _append_assistant_tool_call_message(working_messages, completion, tool_calls, round_log)
        for tool_call in tool_calls:
            started_event = _record_tool_event(
                ctx,
                phase="tool_start",
                tool_call=tool_call,
                name=_tool_call_name(tool_call),
                round_index=round_index,
            )
            if started_event:
                yield _stream_tool_event(
                    ctx.body.model,
                    started_event,
                    chunk_id=stream_chunk_id,
                    created=stream_created,
                )
            result, args, name, cached, duration_ms = await _execute_internal_tool_call(
                ctx,
                tool_call,
                tool_result_cache,
                log_label="Internal stream tool call failed",
            )
            finished_event = _record_tool_event(
                ctx,
                phase="tool_end",
                tool_call=tool_call,
                name=name,
                round_index=round_index,
                cached=cached,
                result=result,
                duration_ms=duration_ms,
            )
            _append_tool_round_log(round_log, name, args, cached, result, duration_ms=duration_ms)
            working_messages.append(_tool_result_message(tool_call, name, result))
            if await ctx.request.is_disconnected():
                if ctx.log_entry is not None:
                    ctx.log_entry["status"] = "client_disconnected"
                    ctx.log_entry["error"] = "Client disconnected during native internal gateway tool execution."
                return
            if finished_event:
                yield _stream_tool_event(
                    ctx.body.model,
                    finished_event,
                    chunk_id=stream_chunk_id,
                    created=stream_created,
                )
            yield _stream_keepalive_event(ctx.body.model, chunk_id=stream_chunk_id, created=stream_created)

    raise HTTPException(status_code=500, detail="Exceeded internal gateway tool rounds.")


def _start_round_log(
    ctx: InternalToolLoopContext,
    round_index: int,
    working_messages: list[dict],
    *,
    stream: bool = False,
) -> Optional[dict]:
    if ctx.log_entry is None:
        return None
    round_log = {
        "round": round_index + 1,
        "messages_count": len(working_messages),
        "tools": [],
        "_started_monotonic": time.monotonic(),
    }
    if stream:
        round_log["stream"] = True
    ctx.log_entry.setdefault("internal_tool_rounds", []).append(round_log)
    return round_log


def _record_round_usage(
    ctx: InternalToolLoopContext,
    round_log: Optional[dict],
    usage: dict,
    upstream_usages: list[dict],
    *,
    protocol: str = "",
) -> None:
    if ctx.log_entry is not None:
        ctx.log_entry["usage"] = usage
        ctx.log_entry["cache_usage"] = ctx.aggregate_cache_usage(upstream_usages, protocol)
    if round_log is not None:
        round_log["usage"] = usage
        round_log["cache_usage"] = _cache_usage_summary(usage, protocol=protocol)


def _record_round_response_evidence(
    ctx: InternalToolLoopContext,
    round_log: Optional[dict],
    upstream: dict,
) -> None:
    evidence = upstream_response_evidence_snapshot(upstream)
    if evidence is None:
        return
    if ctx.log_entry is not None:
        ctx.log_entry["upstream_response_evidence"] = evidence
    if round_log is not None:
        round_log["upstream_response_evidence"] = evidence


def _record_round_request(
    ctx: InternalToolLoopContext,
    round_log: Optional[dict],
    payload: dict,
    headers: dict,
    working_messages: list[dict],
    cache_meta: dict,
) -> None:
    if round_log is None:
        return
    round_log["messages_preview"] = [_message_log_preview(message) for message in working_messages]
    round_log["upstream_payload_summary"] = _upstream_payload_summary(payload, headers)
    round_log["prompt_cache"] = cache_meta
    if ctx.log_entry is not None and ctx.log_entry.get("request_payloads_retained"):
        round_log["messages"] = _payload_without_image_blocks({"messages": working_messages})["messages"]
        round_log["upstream_payload"] = _payload_without_image_blocks(payload)


def _record_round_response(round_log: Optional[dict], completion: dict) -> None:
    if round_log is None:
        return
    assistant_message = completion.get("choices", [{}])[0].get("message", {})
    clean_content, _ = split_private_assistant_tags(
        strip_leading_echo(_content_text_only(assistant_message.get("content")))
    )
    round_log["response_full"] = clean_content
    round_log["response_preview"] = _shorten(clean_content, 1200)
    started = round_log.pop("_started_monotonic", None)
    if started is not None:
        round_log["upstream_duration_ms"] = max(0, int((time.monotonic() - float(started)) * 1000))


async def _finalize_non_gateway_tool_reply(
    ctx: InternalToolLoopContext,
    completion: dict,
    tool_calls: list[dict],
    round_log: Optional[dict],
    *,
    latest_user_text: str,
) -> None:
    if round_log is not None:
        round_log["final"] = True
        round_log["tool_calls_count"] = len(tool_calls)
        if tool_calls:
            round_log["returned_tool_calls"] = _tool_call_log_preview(tool_calls)
    if tool_calls:
        completion, mixed_gateway_calls, client_tool_calls = await _execute_mixed_gateway_tool_calls(
            ctx,
            completion,
            tool_calls,
        )
        if mixed_gateway_calls and client_tool_calls and round_log is not None:
            round_log["returned_tool_calls"] = _tool_call_log_preview(client_tool_calls)

    assistant_message = completion.get("choices", [{}])[0].get("message", {})
    thinking_meta = _anthropic_thinking_block_meta(assistant_message)
    if round_log is not None:
        round_log["anthropic_thinking"] = thinking_meta
    if tool_calls and not mixed_gateway_calls and thinking_meta["preserved"]:
        ctx.store.create_pending_gateway_tool_turn(
            session_id=ctx.session_id,
            session_tag=ctx.session_tag or "",
            client_tool_call_ids=[str(call.get("id")) for call in tool_calls if call.get("id")],
            original_assistant_message=_pending_assistant_tool_call_message(assistant_message, tool_calls),
            gateway_tool_messages=[],
        )
    clean_content, heartbeat_content, echo_content, fallback_meta = _unpack_private_capture_result(
        ctx.finalize_assistant_private_content(
            assistant_message,
            latest_user_text=latest_user_text,
        )
    )
    _record_echo_segment(ctx, echo_content)
    ctx.last_fallback_meta = fallback_meta
    ctx.meta["heartbeat_captured"] = bool(heartbeat_content)
    if heartbeat_content:
        ctx.store_heartbeat(ctx.session_id, ctx.session, heartbeat_content)
    if fallback_meta["applied"] and ctx.log_entry is not None:
        ctx.log_entry["empty_visible_response_fallback"] = True
        ctx.log_entry["empty_visible_response_fallback_detail"] = dict(fallback_meta)
    _strip_anthropic_private_blocks(assistant_message)
    model_content = restore_assistant_echo(clean_content, _combined_echo_text(ctx))
    ctx.sessions.log_assistant_output(ctx.session_id, {**assistant_message, "content": model_content})
    ctx.write_completion_context_snapshot(ctx.meta, model_content)


def _append_assistant_tool_call_message(
    working_messages: list[dict],
    completion: dict,
    tool_calls: list[dict],
    round_log: Optional[dict],
) -> None:
    assistant_message = completion["choices"][0]["message"]
    working_messages.append(_assistant_tool_call_message(assistant_message, tool_calls))
    if round_log is not None:
        round_log["tool_calls_count"] = len(tool_calls)
        round_log["gateway_tool_calls"] = _tool_call_log_preview(tool_calls)


async def _execute_internal_tool_call(
    ctx: InternalToolLoopContext,
    tool_call: dict,
    tool_result_cache: dict[str, dict],
    *,
    log_label: str,
) -> tuple[dict, dict, str, bool, int]:
    args = _tool_call_arguments(tool_call)
    name = _tool_call_name(tool_call)
    cache_key = _tool_call_cache_key(name, args)
    cached = cache_key in tool_result_cache
    if cached:
        result = {
            "ok": True,
            "cached_duplicate": True,
            "result": tool_result_cache[cache_key],
        }
        duration_ms = 0
    else:
        t0 = time.monotonic()
        try:
            result = await ctx.execute_gateway_tool(name, args, session_tag=ctx.session_tag, cfg=ctx.cfg)
        except Exception as exc:
            logger.exception("[GatewayTool] %s: %s", log_label, name)
            result = {"ok": False, "error": str(exc), "error_kind": "exception"}
        result = _decorate_tool_error_result(result)
        duration_ms = int((time.monotonic() - t0) * 1000)
        tool_result_cache[cache_key] = result
        ctx.sessions.log_tool_result(ctx.session_id, name, args, result)
        if isinstance(result, dict) and result.get("ok") is False:
            _record_tool_error(ctx, name, args, result)
    return result, args, name, cached, duration_ms


def _append_tool_round_log(
    round_log: Optional[dict],
    name: str,
    args: dict,
    cached: bool,
    result: dict,
    *,
    duration_ms: int = 0,
) -> None:
    if round_log is None:
        return
    entry: dict[str, Any] = {
        "name": name,
        "cached_duplicate": cached,
        "args_preview": _json_dumps(args)[:300],
        "result_preview": _shorten(_json_dumps(result), 300),
        "ok": result.get("ok") if isinstance(result, dict) else None,
        "duration_ms": duration_ms,
    }
    if name == "shenyu_gateway_tool":
        entry["target_tool"] = _target_tool_name(name, args)
    round_log["tools"].append(entry)


def _target_tool_name(name: str, args: dict) -> str:
    return str(args.get("tool") or args.get("name") or args.get("action") or "") if name == "shenyu_gateway_tool" else name


def _classify_tool_error(result: dict) -> str:
    if not isinstance(result, dict):
        return "exception"
    declared = result.get("error_kind")
    if declared in {"validation", "config", "exception"}:
        return str(declared)
    error_text = str(result.get("error") or result.get("message") or "")
    lowered = error_text.lower()
    if any(phrase in lowered for phrase in TOOL_ERROR_CONFIG_PHRASES):
        return "config"
    exception_markers = (
        "traceback",
        "exception",
        "attributeerror",
        "typeerror",
        "object has no attribute",
    )
    if any(marker in lowered for marker in exception_markers):
        return "exception"
    return "validation"


def _decorate_tool_error_result(result: Any) -> Any:
    """Keep the machine-readable error and add a short resident-facing hint."""
    if not isinstance(result, dict) or result.get("ok") is not False:
        return result
    decorated = dict(result)
    error_kind = _classify_tool_error(decorated)
    decorated["error_kind"] = error_kind
    decorated.setdefault(
        "ps",
        (
            "圆儿ps:予予你又抓到一个家里的bug^ ^"
            if error_kind in {"exception", "config"}
            else "圆儿ps:予予你仔细看有没有暴露给你正确的方法呀，没有的话一会告诉我！又抓到家里的bug了！"
        ),
    )
    return decorated


def _record_tool_error(ctx: InternalToolLoopContext, name: str, args: dict, result: dict) -> None:
    try:
        target = _target_tool_name(name, args)
        error_text = result.get("error") or result.get("message") or str(result)
        error_kind = _classify_tool_error(result)
        error_source = "execute" if error_kind == "exception" else "result"
        ctx.store.log_tool_error(
            session_id=ctx.session_id,
            session_tag=getattr(ctx, "session_tag", None),
            tool_name=name,
            target_tool=target or None,
            args=args,
            error_text=str(error_text),
            error_source=error_source,
            error_kind=error_kind,
        )
    except Exception:
        logger.debug("[ToolErrorLog] Failed to record tool error", exc_info=True)


def _tool_result_message(tool_call: dict, name: str, result: dict) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call.get("id"),
        "name": name,
        "content": _json_dumps(result),
    }
