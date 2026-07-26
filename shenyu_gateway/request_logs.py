from __future__ import annotations

import json
import os
import time as _time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from shenyu_gateway.utils import normalize_text
from shenyu_gateway.utils import shorten as _shorten


_request_logs: deque = deque(maxlen=30)
_http_request_events: deque = deque(maxlen=60)
_active_http_requests: dict[str, dict[str, Any]] = {}
_TOOL_STREAM_STALE_SECONDS = 30.0
_PERSISTED_REQUEST_LOG_SCHEMA_VERSION = 2
_PERSISTENT_LOG_MAX_DEPTH = 12
_PERSISTENT_LOG_MAX_DICT_ITEMS = 200
_PERSISTENT_LOG_MAX_LIST_ITEMS = 100
_PERSISTENT_LOG_MAX_STRING_CHARS = 4000

_LOG_SECRET_KEYS = {
    "authorization",
    "proxy_authorization",
    "x_api_key",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "client_secret",
    "webhook_secret",
    "password",
    "private_key",
}
_LOG_SECRET_KEY_SUFFIXES = (
    "_api_key",
    "_access_token",
    "_refresh_token",
    "_auth_token",
    "_client_secret",
    "_webhook_secret",
    "_private_key",
    "_password",
)
_PERSISTENT_LOG_EXCLUDED_KEYS = {
    "cookies",
    "headers",
    "image",
    "image_bytes",
    "image_url",
    "prepared_messages",
    "request_headers",
    "response_full",
    "signature",
    "system_additions_full",
    "upstream_payload",
}
_SAFE_THINKING_SUMMARY_KEYS = {"type", "display", "budget_tokens"}
_PERSISTENT_JSON_PREVIEW_KEYS = {"args_preview", "arguments_preview", "result_preview"}
_PERSISTENT_LOG_TAIL_LIST_KEYS = {"prepared_messages_preview", "messages_preview"}


def _normalized_log_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _is_log_secret_key(value: Any) -> bool:
    normalized = _normalized_log_key(value)
    return normalized in _LOG_SECRET_KEYS or normalized.endswith(_LOG_SECRET_KEY_SUFFIXES)


def _redact_log_url(value: str) -> str:
    if not value.startswith(("http://", "https://")):
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.query:
        return value
    query = [
        (key, "<redacted>" if _is_log_secret_key(key) else item_value)
        for key, item_value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _redact_log_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if _is_log_secret_key(key)
                else _redact_log_secrets(item_value)
            )
            for key, item_value in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_redact_log_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_log_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_log_url(value)
    return value


def _public_log_detail(item: dict[str, Any]) -> dict[str, Any]:
    return _redact_log_secrets(item)


def _persistent_log_value(
    value: Any,
    *,
    key: str = "",
    depth: int = 0,
    state: Optional[dict[str, bool]] = None,
) -> Any:
    state = state if state is not None else {"truncated": False}
    normalized_key = _normalized_log_key(key)
    if depth > _PERSISTENT_LOG_MAX_DEPTH:
        state["truncated"] = True
        return "<truncated:depth>"
    if _is_log_secret_key(normalized_key):
        return "<redacted>"
    if normalized_key in _PERSISTENT_LOG_EXCLUDED_KEYS:
        return None
    if normalized_key == "messages" and not isinstance(value, (int, float)):
        return None
    if normalized_key in {"redacted_thinking", "signature"}:
        return None
    if normalized_key == "thinking" and not (
        isinstance(value, dict)
        and set(_normalized_log_key(item) for item in value).issubset(_SAFE_THINKING_SUMMARY_KEYS)
    ):
        return None

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (item_key, item_value) in enumerate(value.items()):
            if index >= _PERSISTENT_LOG_MAX_DICT_ITEMS:
                state["truncated"] = True
                break
            item_key_text = str(item_key)
            normalized_item_key = _normalized_log_key(item_key_text)
            if item_key_text.startswith("_") or normalized_item_key in _PERSISTENT_LOG_EXCLUDED_KEYS:
                continue
            clean_value = _persistent_log_value(
                item_value,
                key=item_key_text,
                depth=depth + 1,
                state=state,
            )
            if clean_value is not None:
                result[item_key_text] = clean_value
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > _PERSISTENT_LOG_MAX_LIST_ITEMS:
            state["truncated"] = True
        if normalized_key in _PERSISTENT_LOG_TAIL_LIST_KEYS:
            # Chronological message previews keep the newest entries so the
            # Admin Messages tab still shows the turns closest to the reply.
            kept = value[-_PERSISTENT_LOG_MAX_LIST_ITEMS:]
        else:
            kept = value[:_PERSISTENT_LOG_MAX_LIST_ITEMS]
        return [
            _persistent_log_value(item, depth=depth + 1, state=state)
            for item in kept
        ]
    if isinstance(value, str):
        if normalized_key in _PERSISTENT_JSON_PREVIEW_KEYS:
            try:
                parsed_preview = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                state["truncated"] = True
                return "<omitted:truncated-json-preview>"
            else:
                clean_preview = _persistent_log_value(
                    parsed_preview,
                    depth=depth + 1,
                    state=state,
                )
                value = json.dumps(clean_preview, ensure_ascii=False)
        value = _redact_log_url(value)
        if len(value) > _PERSISTENT_LOG_MAX_STRING_CHARS:
            state["truncated"] = True
            return _shorten(value, _PERSISTENT_LOG_MAX_STRING_CHARS)
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    state["truncated"] = True
    return _shorten(str(value), _PERSISTENT_LOG_MAX_STRING_CHARS)


def _persistent_request_log_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    state = {"truncated": False}
    snapshot = _persistent_log_value(item, state=state)
    if not isinstance(snapshot, dict):
        snapshot = {}
    snapshot["persistence_schema_version"] = _PERSISTED_REQUEST_LOG_SCHEMA_VERSION
    snapshot["persisted"] = True
    snapshot["request_payloads_retained"] = False
    snapshot["prepared_messages"] = None
    snapshot["upstream_payload"] = None
    snapshot["response_full"] = None
    snapshot["system_additions_full"] = None
    if state["truncated"]:
        snapshot["persistence_truncated"] = True
    return snapshot


def _event_elapsed_ms(event: dict[str, Any], now_monotonic: float) -> int:
    started = event.get("_started_monotonic")
    if not isinstance(started, (int, float)):
        return int(event.get("duration_ms") or 0)
    return max(0, int((now_monotonic - float(started)) * 1000))


def _event_delta_ms(event: dict[str, Any], now_monotonic: float) -> int:
    previous = event.get("_last_phase_monotonic")
    if not isinstance(previous, (int, float)):
        previous = event.get("_started_monotonic")
    if not isinstance(previous, (int, float)):
        return 0
    return max(0, int((now_monotonic - float(previous)) * 1000))


def _append_timeline_event(
    event: dict[str, Any],
    phase: str,
    *,
    now_iso: str = "",
    now_monotonic: Optional[float] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    now_value = _time.monotonic() if now_monotonic is None else now_monotonic
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    item: dict[str, Any] = {
        "phase": phase,
        "at": now_iso,
        "elapsed_ms": _event_elapsed_ms(event, now_value),
        "delta_ms": _event_delta_ms(event, now_value),
    }
    if detail:
        item["detail"] = detail
    event.setdefault("timeline", []).append(item)
    event["_last_phase_monotonic"] = now_value
    if now_iso:
        event["last_activity_at"] = now_iso


def _public_http_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if not key.startswith("_")}


def _timeline_slow_phases(timeline: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(timeline, list):
        return []
    phases = [item for item in timeline if isinstance(item, dict)]
    phases.sort(key=lambda item: int(item.get("delta_ms") or 0), reverse=True)
    return phases[:limit]


def _mark_request_log_phase(
    log_entry: Optional[dict],
    phase: str,
    *,
    now_iso: str = "",
    detail: Optional[dict[str, Any]] = None,
) -> None:
    if log_entry is None:
        return
    now_value = _time.monotonic()
    if "_started_monotonic" not in log_entry:
        log_entry["_started_monotonic"] = now_value
    if "_last_phase_monotonic" not in log_entry:
        log_entry["_last_phase_monotonic"] = log_entry.get("_started_monotonic", now_value)
    _append_timeline_event(
        log_entry,
        phase,
        now_iso=now_iso,
        now_monotonic=now_value,
        detail=detail,
    )
    log_entry["timeline_tail"] = log_entry.get("timeline", [])[-8:]
    log_entry["slow_phases"] = _timeline_slow_phases(log_entry.get("timeline"))


def _retain_request_log_payloads(cfg: Any = None) -> bool:
    if cfg is not None and hasattr(cfg, "gateway_log_full_payloads"):
        return bool(cfg.gateway_log_full_payloads)
    raw = os.getenv("GATEWAY_LOG_FULL_PAYLOADS", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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


def _start_http_request_event(
    *,
    request_id: str,
    method: str,
    path: str,
    client: str = "",
    session_tag: str = "",
    client_name: str = "",
    now_iso: str = "",
) -> None:
    now_value = _time.monotonic()
    event = {
        "request_id": request_id,
        "method": method,
        "path": path,
        "client": client,
        "session_tag": session_tag,
        "client_name": client_name,
        "started_at": now_iso,
        "last_activity_at": now_iso,
        "status": "active",
        "duration_ms": 0,
        "http_status": None,
        "error": None,
        "timeline": [],
        "_started_monotonic": now_value,
        "_last_phase_monotonic": now_value,
    }
    _append_timeline_event(event, "http.entry", now_iso=now_iso, now_monotonic=now_value)
    _active_http_requests[request_id] = event
    _http_request_events.appendleft(event)


def _mark_http_request_event(
    request_id: str,
    phase: str,
    *,
    now_iso: str = "",
    detail: Optional[dict[str, Any]] = None,
) -> None:
    event = _active_http_requests.get(request_id)
    if event is None:
        return
    _append_timeline_event(event, phase, now_iso=now_iso, detail=detail)


def _finish_http_request_event(
    *,
    request_id: str,
    now_iso: str = "",
    duration_ms: int = 0,
    http_status: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    event = _active_http_requests.pop(request_id, None)
    if event is None:
        return
    _append_timeline_event(
        event,
        "http.response_returned",
        now_iso=now_iso,
        detail={"http_status": http_status, **({"error": error[:500]} if error else {})},
    )
    event["last_activity_at"] = now_iso
    event["duration_ms"] = duration_ms
    event["http_status"] = http_status
    if error:
        event["status"] = "error"
        event["error"] = error[:500]
    else:
        event["status"] = "complete"


def _http_request_diagnostics(limit: int = 20) -> dict[str, Any]:
    return {
        "active": [_public_http_event(item) for item in _active_http_requests.values()],
        "recent": [_public_http_event(item) for item in list(_http_request_events)[:limit]],
        "capacity": getattr(_http_request_events, "maxlen", None),
    }


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
    from shenyu_gateway.tool_loop import _tool_call_arguments, _tool_call_name

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
    provider = payload.get("provider")
    if isinstance(provider, dict):
        summary["provider_format"] = "order_object"
        summary["provider_order"] = provider.get("order") or []
    elif isinstance(provider, str):
        summary["provider_format"] = "string"
        summary["provider"] = provider
    thinking = payload.get("thinking")
    if isinstance(thinking, dict):
        summary["thinking"] = {
            key: thinking.get(key)
            for key in ("type", "display", "budget_tokens")
            if thinking.get(key) is not None
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
    from shenyu_gateway.context_layers import trim_client_image_blocks

    def redact_anthropic_thinking(value: Any) -> Any:
        if isinstance(value, list):
            return [redact_anthropic_thinking(item) for item in value]
        if not isinstance(value, dict):
            return value
        clean_value = {key: redact_anthropic_thinking(item) for key, item in value.items()}
        block_type = clean_value.get("type")
        if block_type == "thinking":
            thinking = str(value.get("thinking") or "")
            signature = str(value.get("signature") or "")
            clean_value["thinking"] = f"<redacted:{len(thinking)} chars>"
            if "signature" in clean_value:
                clean_value["signature"] = f"<opaque:{len(signature)} chars>"
        elif block_type == "redacted_thinking":
            opaque = str(value.get("data") or "")
            clean_value["data"] = f"<opaque:{len(opaque)} chars>"
        clean_value.pop("_partial_json", None)
        clean_value.pop("_shenyu_anthropic_content_blocks", None)
        return clean_value

    clean = redact_anthropic_thinking(payload)
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


def _completion_finish_reason(completion: Optional[dict]) -> Optional[str]:
    if not isinstance(completion, dict):
        return None
    choices = completion.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return None
    reason = choices[0].get("finish_reason")
    if reason is None:
        return None
    text = str(reason).strip()
    return text or None


def _record_finish_reason(
    log_entry: Optional[dict],
    finish_reason: Any,
    *,
    round_log: Optional[dict] = None,
) -> Optional[str]:
    if finish_reason is None:
        return None
    reason = str(finish_reason).strip()
    if not reason:
        return None
    if log_entry is not None:
        log_entry["finish_reason"] = reason
    if round_log is not None:
        round_log["finish_reason"] = reason
    return reason


def _record_completion_finish_reason(
    log_entry: Optional[dict],
    completion: Optional[dict],
    *,
    round_log: Optional[dict] = None,
) -> Optional[str]:
    return _record_finish_reason(
        log_entry,
        _completion_finish_reason(completion),
        round_log=round_log,
    )


def _finalize_tool_stream_log(log_entry: dict, duration_ms: int) -> None:
    if log_entry.get("status") == "streaming_tools":
        log_entry["status"] = "client_disconnected"
        log_entry["error"] = (
            log_entry.get("error")
            or "Client disconnected before native internal gateway tool stream completed."
        )
    log_entry.pop("_tool_stream_started_monotonic", None)
    log_entry.pop("_tool_stream_last_activity_monotonic", None)
    _mark_request_log_phase(log_entry, "stream.finalized")
    log_entry["duration_ms"] = duration_ms
