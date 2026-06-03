from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .runtime import json_dumps as _json_dumps
from .runtime import now_ts as _now_ts
from .utils import normalize_text as _normalize_text


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


def _apply_openai_stream_chunk(completion: dict, data: dict) -> None:
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
    if data.get("usage"):
        completion["usage"] = data.get("usage") or {}


def _gateway_error_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else _json_dumps(exc.detail)
        return f"{exc.status_code}: {detail}"[:800]
    return str(exc)[:800]


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
        message["content"] = _unstreamed_text_suffix(_normalize_text(message.get("content")), streamed_content)
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
    request,
    timeout: float = 2.0,
) -> StreamReadResult:
    done, _ = await asyncio.wait({next_chunk}, timeout=timeout)
    if next_chunk not in done:
        if await request.is_disconnected():
            await close_stream_reader(upstream_chunks=upstream_chunks, next_chunk=next_chunk)
            return StreamReadResult("disconnected")
        return StreamReadResult("keepalive")
    try:
        data = next_chunk.result()
    except StopAsyncIteration:
        return StreamReadResult("exhausted")
    return StreamReadResult("chunk", data=data)
