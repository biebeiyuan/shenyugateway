from __future__ import annotations

import json
import os
import time as _time
from collections import deque
from typing import Any, Optional

from shenyu_gateway.context_layers import trim_client_image_blocks
from shenyu_gateway.tool_loop import _tool_call_arguments, _tool_call_name
from shenyu_gateway.utils import normalize_text
from shenyu_gateway.utils import shorten as _shorten


_request_logs: deque = deque(maxlen=30)
_TOOL_STREAM_STALE_SECONDS = 30.0


def _retain_request_log_payloads() -> bool:
    raw = os.getenv("GATEWAY_LOG_FULL_PAYLOADS", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _tool_stream_stale_seconds() -> float:
    raw = os.getenv("GATEWAY_TOOL_STREAM_STALE_SECONDS", "").strip()
    if not raw:
        return _TOOL_STREAM_STALE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _TOOL_STREAM_STALE_SECONDS
    return max(5.0, value)


def _mark_tool_stream_activity(log_entry: Optional[dict]) -> None:
    if log_entry is not None:
        now_value = _time.monotonic()
        log_entry.setdefault("_tool_stream_started_monotonic", now_value)
        log_entry["_tool_stream_last_activity_monotonic"] = now_value


def _finalize_stale_tool_stream_log(
    log_entry: dict,
    *,
    now_monotonic: Optional[float] = None,
    stale_seconds: Optional[float] = None,
) -> bool:
    if log_entry.get("status") != "streaming_tools":
        return False
    last_activity = log_entry.get("_tool_stream_last_activity_monotonic")
    if not isinstance(last_activity, (int, float)):
        return False
    now_value = _time.monotonic() if now_monotonic is None else now_monotonic
    threshold = _tool_stream_stale_seconds() if stale_seconds is None else stale_seconds
    if now_value - float(last_activity) < threshold:
        return False
    started_at = log_entry.get("_tool_stream_started_monotonic")
    duration_source = float(started_at) if isinstance(started_at, (int, float)) else float(last_activity)
    duration_ms = max(int(log_entry.get("duration_ms") or 0), int((now_value - duration_source) * 1000))
    _finalize_tool_stream_log(log_entry, duration_ms)
    return True


def _finalize_stale_tool_stream_logs() -> None:
    now_value = _time.monotonic()
    threshold = _tool_stream_stale_seconds()
    for log_entry in list(_request_logs):
        _finalize_stale_tool_stream_log(
            log_entry,
            now_monotonic=now_value,
            stale_seconds=threshold,
        )


def _message_log_preview(msg: dict) -> dict[str, Any]:
    content = normalize_text(msg.get("content"))
    item: dict[str, Any] = {
        "role": msg.get("role", ""),
        "content_preview": _shorten(content, 500),
        "content_chars": len(content),
    }
    if msg.get("name"):
        item["name"] = msg.get("name")
    if msg.get("tool_call_id"):
        item["tool_call_id"] = msg.get("tool_call_id")
    tool_calls = msg.get("tool_calls") or []
    if tool_calls:
        item["tool_calls"] = [
            {
                "id": call.get("id"),
                "name": _tool_call_name(call),
                "arguments_preview": _shorten(json.dumps(_tool_call_arguments(call), ensure_ascii=False), 240),
            }
            for call in tool_calls[:8]
        ]
        item["tool_calls_count"] = len(tool_calls)
    return item


def _upstream_payload_summary(payload: Optional[dict]) -> Optional[dict[str, Any]]:
    if not payload:
        return None
    messages = payload.get("messages") or []
    tools = payload.get("tools") or []
    summary: dict[str, Any] = {
        "model": payload.get("model"),
        "messages_count": len(messages) if isinstance(messages, list) else 0,
        "tools_count": len(tools) if isinstance(tools, list) else 0,
        "max_tokens": payload.get("max_tokens"),
        "temperature": payload.get("temperature"),
        "stream": payload.get("stream", False),
    }
    system = payload.get("system")
    if isinstance(system, list):
        summary["system_blocks_count"] = len(system)
        summary["system_chars"] = sum(len(normalize_text(block.get("text") if isinstance(block, dict) else block)) for block in system)
    elif system:
        summary["system_blocks_count"] = 1
        summary["system_chars"] = len(normalize_text(system))
    return summary


def _record_upstream_payload(log_entry: Optional[dict], payload: dict) -> None:
    if log_entry is None:
        return
    log_entry["upstream_payload_summary"] = _upstream_payload_summary(payload)
    if log_entry.get("request_payloads_retained"):
        log_entry["upstream_payload"] = _payload_without_image_blocks(payload)


def _payload_without_image_blocks(payload: dict) -> dict:
    clean = dict(payload)
    messages = clean.get("messages")
    if isinstance(messages, list):
        clean["messages"] = trim_client_image_blocks(messages, keep_recent_messages=0)[0]
    system = clean.get("system")
    if isinstance(system, list):
        clean["system"] = trim_client_image_blocks(
            [{"role": "system", "content": system}],
            keep_recent_messages=0,
        )[0][0]["content"]
    return clean


def _record_response_text(log_entry: dict, text: str, preview_limit: int = 200) -> None:
    text = text or ""
    log_entry["response_preview"] = _shorten(text, preview_limit)
    if log_entry.get("request_payloads_retained"):
        log_entry["response_full"] = text


def _finalize_tool_stream_log(log_entry: dict, duration_ms: int) -> None:
    if log_entry.get("status") == "streaming_tools":
        log_entry["status"] = "client_disconnected"
        log_entry["error"] = (
            log_entry.get("error")
            or "Client disconnected before native internal gateway tool stream completed."
        )
    log_entry.pop("_tool_stream_started_monotonic", None)
    log_entry.pop("_tool_stream_last_activity_monotonic", None)
    log_entry["duration_ms"] = duration_ms
