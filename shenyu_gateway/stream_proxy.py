from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .response_capture import AssistantTagFilter, clean_text_from_filter_source
from .runtime import now_ts as _now_ts
from .streaming import _new_stream_chunk_id, _sse_response, _stream_content_event
from .upstream_adapter import (
    _anthropic_stop_reason_to_openai,
    _anthropic_to_openai_chunk,
    _anthropic_tool_index_override,
    _anthropic_usage_to_openai,
)

logger = logging.getLogger(__name__)


async def stream_chat(
    request: Request,
    payload: dict,
    headers: dict,
    model: str,
    upstream: dict,
    *,
    connect_error_detail: Callable[[str, Exception], str],
    private_capture_fallback_text: Callable[..., tuple[str, str]],
    private_capture_kinds: Callable[..., list[str]],
    on_complete: Optional[Callable[..., None]] = None,
    latest_user_text: str = "",
) -> StreamingResponse:
    """Forward a streaming response to the client, filtering heartbeat tags."""
    proto = upstream["protocol"]
    client = request.app.state.http
    chat_url = upstream["chat_url"]

    payload["stream"] = True
    if proto == "openai":
        stream_options = payload.get("stream_options")
        if not isinstance(stream_options, dict):
            stream_options = {}
        stream_options["include_usage"] = True
        payload["stream_options"] = stream_options

    try:
        req = client.build_request("POST", chat_url, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=502, detail=connect_error_detail(chat_url, exc))
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"连接上游超时 {chat_url}: {exc}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"上游请求失败 {chat_url}: {exc}")

    if resp.status_code >= 400:
        error_body = await resp.aread()
        await resp.aclose()
        raise HTTPException(status_code=resp.status_code, detail=error_body.decode("utf-8", errors="replace")[:500])

    collected_parts: list[str] = []
    tag_filter = AssistantTagFilter()

    if proto == "openai":
        async def generate():
            visible_output_sent = False
            tool_call_seen = False
            fallback_applied = False
            stream_usage: dict[str, Any] = {}
            stream_finish_reason: str = ""
            stream_chunk_id = _new_stream_chunk_id()
            stream_created = _now_ts()
            try:
                async for raw_line in resp.aiter_lines():
                    line = raw_line.strip()
                    if not line:
                        yield "\n"
                        continue
                    if line == "data: [DONE]":
                        remaining = tag_filter.flush()
                        if remaining:
                            yield _stream_content_event(
                                model,
                                remaining,
                                finish_reason=None,
                                chunk_id=stream_chunk_id,
                                created=stream_created,
                            )
                            visible_output_sent = visible_output_sent or bool(remaining.strip())
                        if not visible_output_sent and not tool_call_seen:
                            fallback_applied = True
                            visible_output_sent = True
                            fallback_text, _ = private_capture_fallback_text(
                                latest_user_text,
                                private_capture_kinds(
                                    heartbeat_content=tag_filter.get_heartbeat(),
                                ),
                            )
                            yield _stream_content_event(
                                model,
                                fallback_text,
                                finish_reason=None,
                                chunk_id=stream_chunk_id,
                                created=stream_created,
                            )
                        yield "data: [DONE]\n\n"
                        continue
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            stream_chunk_id = data.get("id") or stream_chunk_id
                            stream_created = data.get("created") or stream_created
                            if isinstance(data.get("usage"), dict):
                                stream_usage.update(data["usage"])
                            choice = (data.get("choices") or [{}])[0]
                            delta = choice.get("delta", {})
                            if choice.get("finish_reason") is not None:
                                stream_finish_reason = str(choice.get("finish_reason") or "")
                            if delta.get("tool_calls"):
                                tool_call_seen = True
                            text = delta.get("content")
                            if text:
                                collected_parts.append(text)
                                filtered = tag_filter.feed(text)
                                if filtered:
                                    data["choices"][0]["delta"]["content"] = filtered
                                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                                    visible_output_sent = visible_output_sent or bool(filtered.strip())
                                else:
                                    delta.pop("content", None)
                                    if delta or choice.get("finish_reason") is not None:
                                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                                continue
                            if choice.get("finish_reason") is not None and not visible_output_sent and not tool_call_seen:
                                fallback_applied = True
                                visible_output_sent = True
                                fallback_text, _ = private_capture_fallback_text(
                                    latest_user_text,
                                    private_capture_kinds(
                                        heartbeat_content=tag_filter.get_heartbeat(),
                                    ),
                                )
                                yield _stream_content_event(
                                    model,
                                    fallback_text,
                                    finish_reason=None,
                                    chunk_id=stream_chunk_id,
                                    created=stream_created,
                                )
                        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
                            pass
                    yield line + "\n\n"
            finally:
                await resp.aclose()
                if on_complete:
                    try:
                        full_text = "".join(collected_parts)
                        clean_text = clean_text_from_filter_source(full_text)
                        if fallback_applied and not clean_text.strip():
                            clean_text, _ = private_capture_fallback_text(
                                latest_user_text,
                                private_capture_kinds(
                                    heartbeat_content=tag_filter.get_heartbeat(),
                                ),
                            )
                        on_complete(
                            clean_text,
                            tag_filter.get_heartbeat(),
                            fallback_applied,
                            stream_usage or None,
                            stream_finish_reason or None,
                        )
                    except Exception:
                        logger.exception("流式回调执行失败")

        return _sse_response(generate())

    # Anthropic protocol
    async def generate():
        visible_output_sent = False
        tool_call_seen = False
        fallback_applied = False
        anthropic_stop_reason = ""
        anthropic_usage: dict[str, Any] = {}
        stream_chunk_id = _new_stream_chunk_id()
        stream_created = _now_ts()
        tool_index_by_block: dict[int, int] = {}
        try:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("event:"):
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "message_start":
                    usage = (data.get("message") or {}).get("usage")
                    if isinstance(usage, dict):
                        anthropic_usage.update(usage)
                elif data.get("type") == "content_block_delta":
                    delta = data.get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        collected_parts.append(text)
                        filtered = tag_filter.feed(text)
                        if filtered:
                            delta["text"] = filtered
                            visible_output_sent = visible_output_sent or bool(filtered.strip())
                        else:
                            continue
                elif data.get("type") == "content_block_start":
                    block = data.get("content_block", {})
                    if block.get("type") == "tool_use":
                        tool_call_seen = True
                elif data.get("type") == "message_delta":
                    anthropic_stop_reason = (
                        data.get("delta", {}).get("stop_reason")
                        or anthropic_stop_reason
                    )
                    usage = data.get("usage")
                    if isinstance(usage, dict):
                        anthropic_usage.update(usage)
                elif data.get("type") == "message_stop" and not visible_output_sent and not tool_call_seen:
                    fallback_applied = True
                    visible_output_sent = True
                    fallback_text, _ = private_capture_fallback_text(
                        latest_user_text,
                        private_capture_kinds(
                            heartbeat_content=tag_filter.get_heartbeat(),
                        ),
                    )
                    yield _stream_content_event(
                        model,
                        fallback_text,
                        finish_reason=None,
                        chunk_id=stream_chunk_id,
                        created=stream_created,
                    )
                finish_reason = _anthropic_stop_reason_to_openai(anthropic_stop_reason)
                if data.get("type") == "message_stop" and tool_call_seen and finish_reason is None:
                    finish_reason = "tool_calls"
                chunk = _anthropic_to_openai_chunk(
                    model,
                    data,
                    finish_reason_override=finish_reason,
                    tool_index_override=_anthropic_tool_index_override(data, tool_index_by_block),
                    chunk_id=stream_chunk_id,
                    created=stream_created,
                )
                if chunk:
                    if data.get("type") == "message_stop" and anthropic_usage:
                        try:
                            chunk_data = json.loads(chunk)
                            chunk_data["usage"] = _anthropic_usage_to_openai(anthropic_usage)
                            chunk = json.dumps(chunk_data, ensure_ascii=False)
                        except (TypeError, json.JSONDecodeError):
                            pass
                    yield f"data: {chunk}\n\n"
            remaining = tag_filter.flush()
            if remaining:
                yield _stream_content_event(
                    model,
                    remaining,
                    finish_reason=None,
                    chunk_id=stream_chunk_id,
                    created=stream_created,
                )
                visible_output_sent = visible_output_sent or bool(remaining.strip())
            if not visible_output_sent and not tool_call_seen:
                fallback_applied = True
                visible_output_sent = True
                fallback_text, _ = private_capture_fallback_text(
                    latest_user_text,
                    private_capture_kinds(
                        heartbeat_content=tag_filter.get_heartbeat(),
                    ),
                )
                yield _stream_content_event(
                    model,
                    fallback_text,
                    finish_reason=None,
                    chunk_id=stream_chunk_id,
                    created=stream_created,
                )
            yield "data: [DONE]\n\n"
        finally:
            await resp.aclose()
            if on_complete:
                try:
                    full_text = "".join(collected_parts)
                    clean_text = clean_text_from_filter_source(full_text)
                    if fallback_applied and not clean_text.strip():
                        clean_text, _ = private_capture_fallback_text(
                            latest_user_text,
                            private_capture_kinds(
                                heartbeat_content=tag_filter.get_heartbeat(),
                            ),
                        )
                    on_complete(
                        clean_text,
                        tag_filter.get_heartbeat(),
                        fallback_applied,
                        _anthropic_usage_to_openai(anthropic_usage) or None,
                        _anthropic_stop_reason_to_openai(anthropic_stop_reason),
                    )
                except Exception:
                    logger.exception("流式回调执行失败")

    return _sse_response(generate())
