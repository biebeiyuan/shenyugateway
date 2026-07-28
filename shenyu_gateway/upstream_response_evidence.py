from __future__ import annotations

from copy import deepcopy
from typing import Any


UPSTREAM_RESPONSE_EVIDENCE_KEY = "_shenyu_upstream_response_evidence"

_ANTHROPIC_EVENT_TYPES = {
    "message_start",
    "content_block_start",
    "content_block_delta",
    "content_block_stop",
    "message_delta",
    "message_stop",
}


def _new_layer() -> dict[str, Any]:
    return {
        "events": 0,
        "text_blocks": 0,
        "thinking_blocks": 0,
        "redacted_thinking_blocks": 0,
        "tool_call_blocks": 0,
        "text_deltas": 0,
        "thinking_deltas": 0,
        "signature_deltas": 0,
        "tool_call_deltas": 0,
        "other_events": 0,
        "other_blocks": 0,
        "other_deltas": 0,
        "other_fields": 0,
        "thinking_content_seen": False,
        "usage_seen": False,
        "usage_values_seen": False,
        "finish_seen": False,
    }


def _thinking_requested(payload: dict) -> bool:
    thinking = payload.get("thinking")
    if isinstance(thinking, dict):
        return str(thinking.get("type") or "").strip().lower() not in {"", "disabled", "off", "none"}
    if thinking not in (None, False, "", "disabled", "off", "none"):
        return True
    effort = str(payload.get("reasoning_effort") or "").strip().lower()
    return effort not in {"", "none", "off", "disabled"}


def ensure_upstream_response_evidence(
    upstream: dict,
    payload: dict,
    mode: str,
    *,
    reset: bool = False,
) -> dict[str, Any]:
    existing = upstream.get(UPSTREAM_RESPONSE_EVIDENCE_KEY)
    if not reset and isinstance(existing, dict) and existing.get("mode") == mode:
        existing["thinking_requested"] = bool(existing.get("thinking_requested") or _thinking_requested(payload))
        return existing
    evidence = {
        "version": 1,
        "protocol": str(upstream.get("protocol") or "unknown"),
        "mode": mode,
        "thinking_requested": _thinking_requested(payload),
        "upstream_format": "unknown",
        "normalized_format": "unknown",
        "upstream": _new_layer(),
        "normalized": _new_layer(),
    }
    upstream[UPSTREAM_RESPONSE_EVIDENCE_KEY] = evidence
    return evidence


def _has_payload(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (list, dict, tuple)):
        return bool(value)
    return value is not None


def _observe_usage(layer: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    layer["usage_seen"] = True
    layer["usage_values_seen"] = bool(layer.get("usage_values_seen") or value)


def _observe_content_block(layer: dict[str, Any], block: Any) -> None:
    if isinstance(block, str):
        if block:
            layer["text_blocks"] += 1
        return
    if not isinstance(block, dict):
        layer["other_blocks"] += 1
        return
    block_type = str(block.get("type") or "")
    if block_type in {"text", "output_text"}:
        layer["text_blocks"] += 1
    elif block_type == "thinking":
        layer["thinking_blocks"] += 1
        layer["thinking_content_seen"] = bool(
            layer.get("thinking_content_seen") or _has_payload(block.get("thinking"))
        )
    elif block_type == "redacted_thinking":
        layer["redacted_thinking_blocks"] += 1
    elif block_type in {"tool_use", "function_call"}:
        layer["tool_call_blocks"] += 1
    else:
        layer["other_blocks"] += 1


def _observe_openai_message(layer: dict[str, Any], message: Any) -> None:
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            _observe_content_block(layer, block)
    elif _has_payload(content):
        layer["text_blocks"] += 1
    for key in ("reasoning_content", "reasoning"):
        if _has_payload(message.get(key)):
            layer["thinking_blocks"] += 1
            layer["thinking_content_seen"] = True
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        layer["tool_call_blocks"] += len(tool_calls)
    known_keys = {
        "role",
        "content",
        "reasoning_content",
        "reasoning",
        "tool_calls",
        "function_call",
        "refusal",
        "audio",
        "name",
    }
    layer["other_fields"] += sum(1 for key in message if key not in known_keys)


def _observe_openai_completion(layer: dict[str, Any], response: dict) -> None:
    layer["events"] += 1
    choices = response.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            _observe_openai_message(layer, choice.get("message"))
            if choice.get("finish_reason") is not None:
                layer["finish_seen"] = True
    _observe_usage(layer, response.get("usage"))


def observe_upstream_nonstream_response(evidence: dict[str, Any], response: Any) -> None:
    layer = evidence["upstream"]
    if not isinstance(response, dict):
        layer["other_events"] += 1
        return
    if isinstance(response.get("content"), list):
        evidence["upstream_format"] = "anthropic_message"
        layer["events"] += 1
        for block in response["content"]:
            _observe_content_block(layer, block)
        _observe_usage(layer, response.get("usage"))
        if response.get("stop_reason") is not None:
            layer["finish_seen"] = True
        return
    if isinstance(response.get("choices"), list):
        evidence["upstream_format"] = "openai_completion"
        _observe_openai_completion(layer, response)
        return
    layer["events"] += 1
    layer["other_events"] += 1
    _observe_usage(layer, response.get("usage"))


def observe_normalized_completion(evidence: dict[str, Any], completion: Any) -> None:
    layer = evidence["normalized"]
    if not isinstance(completion, dict):
        layer["other_events"] += 1
        return
    evidence["normalized_format"] = "openai_completion"
    _observe_openai_completion(layer, completion)


def _observe_openai_chunk(layer: dict[str, Any], chunk: dict) -> None:
    layer["events"] += 1
    choices = chunk.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                if _has_payload(delta.get("content")):
                    layer["text_deltas"] += 1
                for key in ("reasoning_content", "reasoning"):
                    if _has_payload(delta.get(key)):
                        layer["thinking_deltas"] += 1
                        layer["thinking_content_seen"] = True
                tool_calls = delta.get("tool_calls")
                if isinstance(tool_calls, list):
                    layer["tool_call_deltas"] += len(tool_calls)
                known_keys = {
                    "role",
                    "content",
                    "reasoning_content",
                    "reasoning",
                    "tool_calls",
                    "function_call",
                    "refusal",
                    "audio",
                }
                layer["other_fields"] += sum(1 for key in delta if key not in known_keys)
            if choice.get("finish_reason") is not None:
                layer["finish_seen"] = True
    _observe_usage(layer, chunk.get("usage"))


def _observe_anthropic_event(layer: dict[str, Any], event: dict) -> None:
    layer["events"] += 1
    event_type = str(event.get("type") or "")
    if event_type not in _ANTHROPIC_EVENT_TYPES:
        layer["other_events"] += 1
    if event_type == "content_block_start":
        _observe_content_block(layer, event.get("content_block"))
    elif event_type == "content_block_delta":
        delta = event.get("delta")
        if not isinstance(delta, dict):
            layer["other_deltas"] += 1
        else:
            delta_type = str(delta.get("type") or "")
            if delta_type == "text_delta":
                layer["text_deltas"] += 1
            elif delta_type == "thinking_delta":
                layer["thinking_deltas"] += 1
                layer["thinking_content_seen"] = bool(
                    layer.get("thinking_content_seen") or _has_payload(delta.get("thinking"))
                )
            elif delta_type == "signature_delta":
                layer["signature_deltas"] += 1
            elif delta_type == "input_json_delta":
                layer["tool_call_deltas"] += 1
            else:
                layer["other_deltas"] += 1
    if event_type == "message_start":
        message = event.get("message")
        if isinstance(message, dict):
            _observe_usage(layer, message.get("usage"))
    elif event_type == "message_delta":
        _observe_usage(layer, event.get("usage"))
        delta = event.get("delta")
        if isinstance(delta, dict) and delta.get("stop_reason") is not None:
            layer["finish_seen"] = True
    elif event_type == "message_stop":
        layer["finish_seen"] = True


def observe_upstream_stream_event(evidence: dict[str, Any], event: Any) -> None:
    layer = evidence["upstream"]
    if not isinstance(event, dict):
        layer["other_events"] += 1
        return
    if isinstance(event.get("choices"), list):
        evidence["upstream_format"] = "openai_chunks"
        _observe_openai_chunk(layer, event)
        return
    evidence["upstream_format"] = "anthropic_events"
    _observe_anthropic_event(layer, event)


def observe_normalized_stream_chunk(evidence: dict[str, Any], chunk: Any) -> None:
    layer = evidence["normalized"]
    if not isinstance(chunk, dict):
        layer["other_events"] += 1
        return
    evidence["normalized_format"] = "openai_chunks"
    _observe_openai_chunk(layer, chunk)


def upstream_response_evidence_snapshot(upstream: dict) -> dict[str, Any] | None:
    evidence = upstream.get(UPSTREAM_RESPONSE_EVIDENCE_KEY)
    return deepcopy(evidence) if isinstance(evidence, dict) else None
