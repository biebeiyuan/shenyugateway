from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .runtime import json_dumps as _json_dumps
from .runtime import logger
from .runtime import now_ts as _now_ts
from .echo import strip_leading_echo
from .utils import normalize_text as _normalize_text
from .upstream_adapter import ANTHROPIC_CONTENT_BLOCKS_KEY


def _new_stream_chunk_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _stream_chunk_base(model: str, *, chunk_id: Optional[str] = None, created: Optional[int] = None) -> dict:
    return {
        "id": chunk_id or _new_stream_chunk_id(),
        "object": "chat.completion.chunk",
        "created": created if created is not None else _now_ts(),
        "model": model,
    }


def _stream_content_event(
    model: str,
    content: str,
    *,
    finish_reason: Optional[str] = None,
    chunk_id: Optional[str] = None,
    created: Optional[int] = None,
) -> str:
    body = {
        **_stream_chunk_base(model, chunk_id=chunk_id, created=created),
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"


def _stream_reasoning_event(
    model: str,
    reasoning: str,
    *,
    finish_reason: Optional[str] = None,
    chunk_id: Optional[str] = None,
    created: Optional[int] = None,
) -> str:
    body = {
        **_stream_chunk_base(model, chunk_id=chunk_id, created=created),
        "choices": [{"index": 0, "delta": {"reasoning_content": reasoning}, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"


def _stream_echo_event(
    model: str,
    echo: str,
    *,
    chunk_id: Optional[str] = None,
    created: Optional[int] = None,
) -> str:
    body = {
        **_stream_chunk_base(model, chunk_id=chunk_id, created=created),
        "type": "shenyu.echo_delta",
        "object": "shenyu.echo_delta",
        "echo": echo,
    }
    return f"event: shenyu_echo\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"


def flush_stream_tail_events(
    model: str,
    *,
    echo_filter: Any,
    tag_filter: Any,
    emit_echo_events: bool,
    chunk_id: Optional[str] = None,
    created: Optional[int] = None,
) -> tuple[list[str], str]:
    """Drain both end-of-stream filters into SSE events plus the visible tail text."""
    echo_remaining, echo_tail = echo_filter.finish()
    events: list[str] = []
    if emit_echo_events and echo_tail:
        events.append(_stream_echo_event(model, echo_tail, chunk_id=chunk_id, created=created))
    remaining = tag_filter.feed(echo_remaining) + tag_filter.flush()
    if remaining:
        events.append(
            _stream_content_event(
                model,
                remaining,
                finish_reason=None,
                chunk_id=chunk_id,
                created=created,
            )
        )
    return events, remaining


def _stream_role_event(model: str, *, chunk_id: Optional[str] = None, created: Optional[int] = None) -> str:
    body = {
        **_stream_chunk_base(model, chunk_id=chunk_id, created=created),
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"


def _stream_final_event(
    model: str,
    finish_reason: str = "stop",
    *,
    chunk_id: Optional[str] = None,
    created: Optional[int] = None,
) -> str:
    body = {
        **_stream_chunk_base(model, chunk_id=chunk_id, created=created),
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"


def _stream_keepalive_event(model: str, *, chunk_id: Optional[str] = None, created: Optional[int] = None) -> str:
    # OpenAI-compatible empty delta; some clients/proxies do not treat SSE comments
    # as activity, so this keeps long internal tool loops visibly alive to parsers.
    return _stream_content_event(model, "", finish_reason=None, chunk_id=chunk_id, created=created)


def _stream_tool_event(
    model: str,
    event: dict[str, Any],
    *,
    chunk_id: Optional[str] = None,
    created: Optional[int] = None,
) -> str:
    """Emit a client-opt-in SSE event without changing OpenAI chat chunks."""
    body = {
        "type": "shenyu.tool_event",
        "object": "shenyu.tool_event",
        "id": chunk_id or _new_stream_chunk_id(),
        "created": created if created is not None else _now_ts(),
        "model": model,
        "event": event,
    }
    return f"event: shenyu_tool\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"


def _stream_response_meta_event(
    model: str,
    metadata: dict[str, Any],
    *,
    chunk_id: Optional[str] = None,
    created: Optional[int] = None,
) -> str:
    """Emit content-free PWA status metadata without changing chat chunks."""
    body = {
        "type": "shenyu.response_meta",
        "object": "shenyu.response_meta",
        "id": chunk_id or _new_stream_chunk_id(),
        "created": created if created is not None else _now_ts(),
        "model": model,
        "meta": metadata,
    }
    return f"event: shenyu_meta\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"


def _sse_response(generator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Strong references to detached drain tasks: asyncio only keeps weak refs to
# running tasks, so without this set a drained stream could be GC'd mid-flight.
_DETACHED_STREAM_TASKS: set[asyncio.Task] = set()

# Safety valve for the detached drain: if the upstream never finishes, cancel it
# eventually so the producer's finally-blocks run and partial text is persisted.
_DETACHED_DRAIN_MAX_SECONDS = 30 * 60.0

_QUEUE_END = object()


def resilient_sse_response(
    inner_gen,
    *,
    model: str,
    keepalive_interval: float = 15.0,
    on_client_disconnect: Optional[Callable[[], None]] = None,
) -> StreamingResponse:
    """SSE response that survives client disconnects.

    The inner generator runs in a detached producer task feeding a queue. The
    HTTP response only consumes the queue, so when the client goes away (mobile
    background / lock screen), the producer keeps draining the upstream to its
    natural end and all completion callbacks (session persistence, snapshots,
    heartbeats) fire as if the client had stayed. Queue reads that time out
    emit OpenAI-compatible keepalive deltas so proxies (e.g. Cloudflare Tunnel,
    ~100s idle cutoff) never see a silent connection.
    """
    queue: asyncio.Queue = asyncio.Queue()
    producer_error: list[BaseException] = []

    async def _produce() -> None:
        try:
            async for event in inner_gen:
                queue.put_nowait(event)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - relayed to the consumer
            producer_error.append(exc)
        finally:
            queue.put_nowait(_QUEUE_END)

    producer = asyncio.create_task(_produce())

    def _detach_producer() -> None:
        if producer.done():
            return
        if on_client_disconnect is not None:
            with suppress(Exception):
                on_client_disconnect()
        _DETACHED_STREAM_TASKS.add(producer)
        producer.add_done_callback(_DETACHED_STREAM_TASKS.discard)

        async def _watchdog() -> None:
            with suppress(asyncio.CancelledError):
                await asyncio.wait({producer}, timeout=_DETACHED_DRAIN_MAX_SECONDS)
            if not producer.done():
                logger.warning("Detached SSE drain exceeded %.0fs; cancelling upstream read.", _DETACHED_DRAIN_MAX_SECONDS)
                producer.cancel()

        watchdog = asyncio.create_task(_watchdog())
        _DETACHED_STREAM_TASKS.add(watchdog)
        watchdog.add_done_callback(_DETACHED_STREAM_TASKS.discard)
        logger.info("Client disconnected mid-stream; continuing upstream drain in background.")

    async def _consume():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=keepalive_interval)
                except asyncio.TimeoutError:
                    yield _stream_keepalive_event(model)
                    continue
                if event is _QUEUE_END:
                    break
                yield event
            if producer_error:
                raise producer_error[0]
        except (asyncio.CancelledError, GeneratorExit):
            # Client went away (uvicorn cancels the response task) — keep the
            # producer alive so the upstream reply still gets persisted.
            _detach_producer()
            raise

    return StreamingResponse(
        _consume(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _stream_gateway_error_events(model: str, error: str):
    chunk_id = _new_stream_chunk_id()
    created = _now_ts()
    message = (error or "Gateway request failed.").strip()
    yield _stream_content_event(model, f"\n\n[网关错误] {message}\n", finish_reason=None, chunk_id=chunk_id, created=created)
    yield _stream_final_event(model, chunk_id=chunk_id, created=created)
    yield "data: [DONE]\n\n"


def _new_stream_completion(model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": _now_ts(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": None,
            }
        ],
        "usage": {},
    }


def _ensure_stream_tool_call(tool_calls: list[dict], index: int) -> dict:
    while len(tool_calls) <= index:
        tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    call = tool_calls[index]
    call.setdefault("type", "function")
    function = call.setdefault("function", {})
    function.setdefault("name", "")
    function.setdefault("arguments", "")
    return call


def _stream_tool_call_name(tool_call: dict) -> str:
    function = tool_call.get("function") if isinstance(tool_call, dict) else {}
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def _compact_stream_tool_calls(completion: dict) -> None:
    choice = completion.get("choices", [{}])[0]
    message = choice.get("message", {})
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        message.pop("tool_calls", None)
        if choice.get("finish_reason") == "tool_calls":
            choice["finish_reason"] = "stop"
        return
    compacted = [
        call
        for call in tool_calls
        if isinstance(call, dict) and _stream_tool_call_name(call)
    ]
    if compacted:
        message["tool_calls"] = compacted
    else:
        message.pop("tool_calls", None)
        if choice.get("finish_reason") == "tool_calls":
            choice["finish_reason"] = "stop"


def _apply_openai_stream_chunk(completion: dict, data: dict) -> None:
    anthropic_blocks = data.get(ANTHROPIC_CONTENT_BLOCKS_KEY)
    if isinstance(anthropic_blocks, list) and anthropic_blocks:
        completion["choices"][0]["message"][ANTHROPIC_CONTENT_BLOCKS_KEY] = json.loads(
            json.dumps(anthropic_blocks, ensure_ascii=False)
        )
    choices = data.get("choices") or []
    if not choices:
        if data.get("usage"):
            completion["usage"] = data.get("usage") or {}
        return
    choice = choices[0]
    delta = choice.get("delta") or {}
    message = completion["choices"][0]["message"]
    if delta.get("role"):
        message["role"] = delta["role"]
    if delta.get("content"):
        message["content"] = _normalize_text(message.get("content")) + str(delta.get("content") or "")
    if delta.get("reasoning_content"):
        message["reasoning_content"] = _normalize_text(message.get("reasoning_content")) + str(
            delta.get("reasoning_content") or ""
        )
    if delta.get("tool_calls"):
        tool_calls = message.setdefault("tool_calls", [])
        for call_delta in delta.get("tool_calls") or []:
            index = int(call_delta.get("index") or 0)
            call = _ensure_stream_tool_call(tool_calls, index)
            if call_delta.get("id"):
                call["id"] = call_delta["id"]
            if call_delta.get("type"):
                call["type"] = call_delta["type"]
            fn_delta = call_delta.get("function") or {}
            function = call.setdefault("function", {})
            if fn_delta.get("name"):
                function["name"] = fn_delta["name"]
            if "arguments" in fn_delta:
                arguments = fn_delta.get("arguments")
                if arguments is None:
                    arguments = ""
                elif not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                function["arguments"] = str(function.get("arguments") or "") + arguments
    if choice.get("finish_reason") is not None:
        completion["choices"][0]["finish_reason"] = choice.get("finish_reason")
        if choice.get("finish_reason") == "tool_calls":
            _compact_stream_tool_calls(completion)
    if data.get("usage"):
        completion["usage"] = data.get("usage") or {}


_GATEWAY_ERROR_TEXT_LIMIT = 1200


def _error_reason_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None or isinstance(value, (bool, int, float)):
        return str(value).strip() if value is not None else ""
    if not isinstance(value, dict):
        return ""

    nested_error = value.get("error")
    if isinstance(nested_error, dict):
        reason = _error_reason_from_value(nested_error)
        if reason:
            return reason

    for key in ("message", "error_description"):
        reason = _error_reason_from_value(value.get(key))
        if reason:
            return reason

    nested_detail = value.get("detail")
    if isinstance(nested_detail, dict):
        reason = _error_reason_from_value(nested_detail)
        if reason:
            return reason

    for key in ("detail", "error", "code", "type"):
        reason = _error_reason_from_value(value.get(key))
        if reason:
            return reason
    return ""


def _http_error_detail_parts(detail: Any) -> tuple[str, str]:
    raw_detail = detail.strip() if isinstance(detail, str) else _json_dumps(detail)
    parsed_detail = detail
    if isinstance(detail, str):
        try:
            parsed_detail = json.loads(detail)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_detail = detail
    reason = _error_reason_from_value(parsed_detail) or raw_detail
    return reason, raw_detail


def _gateway_error_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        reason, raw_detail = _http_error_detail_parts(exc.detail)
        parts = [f"HTTP {exc.status_code}", f"原因（原文）：{reason}"]
        if raw_detail and raw_detail != reason:
            parts.append(f"原始返回：{raw_detail}")
        return "\n".join(parts)[:_GATEWAY_ERROR_TEXT_LIMIT]
    message = str(exc).strip() or type(exc).__name__
    return f"原因（原文）：{message}"[:_GATEWAY_ERROR_TEXT_LIMIT]


def _gateway_error_completion(model: str, error: str) -> dict:
    content = f"[网关错误] {(error or 'Gateway request failed.').strip()}"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": _now_ts(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {},
    }


def _unstreamed_text_suffix(text: str, streamed_text: str) -> str:
    if not streamed_text:
        return text
    if text.startswith(streamed_text):
        return text[len(streamed_text):]
    trimmed_streamed = streamed_text.rstrip()
    if trimmed_streamed and text.startswith(trimmed_streamed):
        return text[len(trimmed_streamed):]
    marker = "<gateway_tool_results>"
    marker_index = text.find(marker)
    if marker_index >= 0:
        start = marker_index
        while start > 0 and text[start - 1] in "\r\n":
            start -= 1
        return text[start:]
    return ""


def _completion_with_unstreamed_deltas(
    completion: dict,
    *,
    streamed_content: str = "",
    streamed_reasoning: str = "",
) -> dict:
    if not streamed_content and not streamed_reasoning:
        return completion
    replay = dict(completion)
    choices = list(replay.get("choices") or [])
    if not choices:
        return replay
    choice = dict(choices[0])
    message = dict(choice.get("message") or {})
    if streamed_content:
        # A tool-loop completion may still contain the model-facing leading
        # echo block even though the visible body was already streamed. Strip
        # that private wrapper before calculating the unstreamed suffix, or a
        # client-tool continuation can lose text after the first visible delta.
        message["content"] = _unstreamed_text_suffix(
            strip_leading_echo(_normalize_text(message.get("content"))),
            streamed_content,
        )
    if streamed_reasoning and message.get("reasoning_content"):
        message["reasoning_content"] = _unstreamed_text_suffix(
            _normalize_text(message.get("reasoning_content")),
            streamed_reasoning,
        )
    choice["message"] = message
    choices[0] = choice
    replay["choices"] = choices
    return replay


@dataclass
class StreamReplayAccumulator:
    """Track streamed deltas so replay can skip content the client already saw."""

    visible_output_sent: bool = False
    tool_call_seen: bool = False
    _content_parts: list[str] = field(default_factory=list)
    _reasoning_parts: list[str] = field(default_factory=list)

    @property
    def streamed_content(self) -> str:
        return "".join(self._content_parts)

    @property
    def streamed_reasoning(self) -> str:
        return "".join(self._reasoning_parts)

    def mark_tool_call_seen(self) -> None:
        self.tool_call_seen = True

    def should_skip_visible_delta(self) -> bool:
        return self.tool_call_seen

    def record_reasoning(self, reasoning: str) -> str:
        if reasoning:
            self._reasoning_parts.append(reasoning)
        return reasoning

    def record_content(self, content: str) -> str:
        if content:
            self.visible_output_sent = self.visible_output_sent or bool(content.strip())
            self._content_parts.append(content)
        return content

    def mark_visible_output(self, content: str) -> None:
        if content:
            self.visible_output_sent = self.visible_output_sent or bool(content.strip())

    def replay_completion(self, completion: dict) -> dict:
        return _completion_with_unstreamed_deltas(
            completion,
            streamed_content=self.streamed_content,
            streamed_reasoning=self.streamed_reasoning,
        )


@dataclass(frozen=True)
class StreamReadResult:
    kind: str
    data: Optional[dict[str, Any]] = None


async def close_stream_reader(*, upstream_chunks, next_chunk) -> None:
    if not next_chunk.done():
        next_chunk.cancel()
        with suppress(asyncio.CancelledError):
            await next_chunk
    await upstream_chunks.aclose()


async def read_next_stream_chunk(
    *,
    upstream_chunks,
    next_chunk,
    request=None,
    timeout: float = 2.0,
) -> StreamReadResult:
    """Await the pending chunk task with a keepalive timeout.

    Pass `request=None` when the surrounding response is wrapped by
    `resilient_sse_response`: client disconnects are handled there, and the
    upstream read must keep going so the reply still gets persisted.
    """
    done, _ = await asyncio.wait({next_chunk}, timeout=timeout)
    if next_chunk not in done:
        if request is not None and await request.is_disconnected():
            await close_stream_reader(upstream_chunks=upstream_chunks, next_chunk=next_chunk)
            return StreamReadResult("disconnected")
        return StreamReadResult("keepalive")
    try:
        data = next_chunk.result()
    except StopAsyncIteration:
        return StreamReadResult("exhausted")
    return StreamReadResult("chunk", data=data)
