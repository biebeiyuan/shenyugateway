from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

from .runtime import logger, now_ts as _now_ts
from .streaming import _new_stream_chunk_id
from .upstream_adapter import (
    ANTHROPIC_CONTENT_BLOCKS_KEY,
    ANTHROPIC_THINKING_CONFIG_KEY,
    _anthropic_stop_reason_to_openai,
    _anthropic_tool_index_override,
    _anthropic_to_openai_chunk,
    _anthropic_usage_to_openai,
    _apply_openai_compatible_cache_control,
    _convert_openai_tools_to_anthropic,
    _models_url_for,
    _normalize_anthropic_thinking,
    _openai_to_anthropic,
    _sanitize_openai_compatible_messages,
    _sanitize_openai_compatible_tools,
)
from .tool_registry import merge_tools
from .utils import clean_config_text as _clean_config_text


_DNS_ERROR_MARKERS = (
    "getaddrinfo",
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname",
    "no address associated",
    "failed to resolve",
    "could not resolve",
    "无法解析",
)


def validate_http_url(field_name: str, value: Any, *, allow_empty: bool = True) -> str:
    url = _clean_config_text(value)
    if not url:
        if allow_empty:
            return ""
        raise HTTPException(status_code=400, detail=f"{field_name} 不能为空。")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 必须是包含 http(s):// 和主机名的完整 URL。",
        )
    return url


def _cache_tail_guard_user_turns(
    raw_messages: list[dict],
    window_meta: dict[str, Any],
) -> int:
    if not raw_messages or raw_messages[-1].get("role") != "user":
        return 0
    if int(window_meta.get("client_attachment_messages_seen") or 0) > 0:
        return 3
    if int(window_meta.get("client_image_messages_seen") or 0) > 0:
        return 2
    return 0


def validate_protocol(field_name: str, value: Any, *, allow_empty: bool = False) -> str:
    protocol = _clean_config_text(value).lower()
    if not protocol:
        if allow_empty:
            return ""
        return "auto"
    if protocol not in {"auto", "openai", "anthropic"}:
        raise HTTPException(status_code=400, detail=f"{field_name} 只能是 auto、openai 或 anthropic。")
    return protocol


def connection_route_hint(cfg: Any) -> str:
    if cfg.upstream_proxy:
        return "UPSTREAM_PROXY 已配置，出站请求会走显式代理。"
    if cfg.upstream_trust_env:
        return "UPSTREAM_TRUST_ENV=true，出站请求会读取环境代理。"
    return "UPSTREAM_PROXY 为空且 UPSTREAM_TRUST_ENV=false，出站请求会直连上游。"


def connect_error_detail(chat_url: str, exc: Exception, *, cfg: Any) -> str:
    host = urlsplit(chat_url or "").hostname or "(unknown host)"
    raw = str(exc)
    lowered = raw.lower()
    if any(marker in lowered for marker in _DNS_ERROR_MARKERS):
        return f"无法解析上游主机 {host}（{chat_url}）。{connection_route_hint(cfg)} 原始错误: {raw}"
    return f"无法连接上游 {chat_url}: {raw}"


def detect_protocol_for(url: str, protocol: str = "auto") -> str:
    if protocol and protocol != "auto":
        return protocol
    if "anthropic.com" in (url or "").lower():
        return "anthropic"
    return "openai"


def chat_url_for(base_url: str, protocol: str = "auto") -> str:
    url = _clean_config_text(base_url).rstrip("/")
    proto = detect_protocol_for(url, protocol)
    if proto == "anthropic":
        if url.endswith("/v1"):
            url += "/messages"
        elif not url.endswith("/messages"):
            url += "/v1/messages"
    else:
        if url.endswith("/v1"):
            url += "/chat/completions"
        elif not url.endswith("/chat/completions"):
            url += "/v1/chat/completions"
    return url


def upstream_for_hisense(cfg: Any, is_hisense: bool = False) -> dict[str, str]:
    base_url = _clean_config_text(cfg.upstream_url)
    api_key = _clean_config_text(cfg.upstream_api_key)
    protocol = _clean_config_text(cfg.upstream_protocol) or "auto"
    scope = "default"

    if is_hisense:
        hisense_url = _clean_config_text(getattr(cfg, "hisense_upstream_url", ""))
        hisense_key = _clean_config_text(getattr(cfg, "hisense_api_key", ""))
        hisense_protocol = _clean_config_text(getattr(cfg, "hisense_protocol", ""))
        if hisense_url:
            base_url = hisense_url
            scope = "hisense"
        if hisense_key:
            api_key = hisense_key
            scope = "hisense"
        if hisense_protocol:
            protocol = hisense_protocol
            scope = "hisense"

    resolved_protocol = detect_protocol_for(base_url, protocol)
    return {
        "scope": scope,
        "base_url": base_url,
        "chat_url": chat_url_for(base_url, resolved_protocol),
        "protocol": resolved_protocol,
        "api_key": api_key,
    }


def mapped_model_name(cfg: Any, model_name: str) -> str:
    model = (model_name or "").strip()
    return cfg.model_mapping.get(model, model)


def apply_upstream_extra_body(payload: dict[str, Any], cfg: Any) -> dict[str, Any]:
    extra_body = getattr(cfg, "upstream_extra_body", {}) or {}
    if isinstance(extra_body, dict):
        payload.update(extra_body)
    return payload


def _pinned_anthropic_thinking_config(messages: list[dict]) -> dict[str, Any]:
    tool_continuation_seen = False
    for message in reversed(messages):
        role = message.get("role")
        if role == "tool":
            tool_continuation_seen = True
            continue
        if role == "assistant":
            if not tool_continuation_seen:
                return {}
            config = message.get(ANTHROPIC_THINKING_CONFIG_KEY)
            return dict(config) if isinstance(config, dict) else {}
        if role == "user":
            content = message.get("content")
            if isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "tool_result" for block in content
            ):
                tool_continuation_seen = True
                continue
            return {}
    return {}


def _anthropic_content_block_index(data: dict) -> int:
    try:
        return int(data.get("index") or 0)
    except (TypeError, ValueError):
        return 0


def _update_anthropic_content_blocks(blocks: dict[int, dict[str, Any]], data: dict) -> None:
    event_type = data.get("type")
    block_index = _anthropic_content_block_index(data)
    if event_type == "content_block_start":
        block = data.get("content_block") or {}
        if isinstance(block, dict):
            blocks[block_index] = json.loads(json.dumps(block, ensure_ascii=False))
        return
    if event_type == "content_block_delta":
        block = blocks.setdefault(block_index, {})
        delta = data.get("delta") or {}
        delta_type = delta.get("type")
        if delta_type == "thinking_delta":
            block["thinking"] = str(block.get("thinking") or "") + str(delta.get("thinking") or "")
        elif delta_type == "signature_delta":
            block["signature"] = str(block.get("signature") or "") + str(delta.get("signature") or "")
        elif delta_type == "text_delta":
            block["text"] = str(block.get("text") or "") + str(delta.get("text") or "")
        elif delta_type == "input_json_delta":
            block["_partial_json"] = str(block.get("_partial_json") or "") + str(delta.get("partial_json") or "")
        return
    if event_type == "content_block_stop":
        block = blocks.get(block_index) or {}
        partial_json = block.pop("_partial_json", "")
        if partial_json and block.get("type") == "tool_use":
            try:
                block["input"] = json.loads(partial_json)
            except json.JSONDecodeError:
                block["input"] = {"raw_arguments": partial_json}


def _anthropic_content_blocks_snapshot(blocks: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        json.loads(json.dumps(blocks[index], ensure_ascii=False))
        for index in sorted(blocks)
    ]


# Headers the gateway must always own. Even if a name is mistakenly added to
# the passthrough whitelist, these are never forwarded to the upstream:
#   - authorization / content-type: the gateway rebuilds these per protocol
#   - hop-by-hop headers (RFC 7230): not valid to forward across a proxy
#   - the gateway's own identification headers (X-Shenyu-* / X-Session-Tag / X-Client-Name)
_PASSTHROUGH_RESERVED_HEADERS = {
    "authorization",
    "content-type",
    "content-length",
    "host",
    "connection",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "cookie",
    "x-shenyu-session-tag",
    "x-session-tag",
    "x-shenyu-client",
    "x-client-name",
    "x-shenyu-request-id",
}


def forwarded_client_headers(request: Any, cfg: Any) -> dict[str, str]:
    """Return whitelisted client headers to forward to the upstream.

    Only header names listed in ``cfg.upstream_passthrough_headers`` are
    considered. A reserved set (auth, content-type, hop-by-hop, and the
    gateway's own identification headers) is always excluded so the gateway
    stays in control of those. Returned keys are lowercased; values come
    straight from the inbound request headers.
    """
    if request is None:
        return {}
    whitelist = getattr(cfg, "upstream_passthrough_headers", []) or []
    if not isinstance(whitelist, list):
        whitelist = [whitelist]
    forwarded: dict[str, str] = {}
    seen: set[str] = set()
    for name in whitelist:
        normalized = str(name or "").strip().lower()
        if not normalized or normalized in seen or normalized in _PASSTHROUGH_RESERVED_HEADERS:
            continue
        seen.add(normalized)
        value = request.headers.get(normalized)
        if value:
            forwarded[normalized] = value
    return forwarded


def make_upstream_http_client(cfg: Any) -> httpx.AsyncClient:
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0),
    }
    if cfg.upstream_proxy:
        kwargs["proxy"] = cfg.upstream_proxy
        kwargs["trust_env"] = False
    elif cfg.upstream_trust_env:
        kwargs["trust_env"] = True
    else:
        kwargs["proxy"] = None
        kwargs["trust_env"] = False
    return httpx.AsyncClient(**kwargs)


async def fetch_upstream_models(
    request: Request,
    *,
    cfg: Any,
    upstream: dict,
) -> list:
    proto = upstream["protocol"]
    client = request.app.state.http
    try:
        if proto == "anthropic" and "anthropic.com" in (upstream.get("base_url") or "").lower():
            return []
        url = _models_url_for(upstream)
        if not url or not upstream["api_key"]:
            return []
        headers = {"Authorization": f"Bearer {upstream['api_key']}"}
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return [
            {"id": model["id"], "object": "model", "created": model.get("created", 1700000000), "owned_by": "upstream"}
            for model in data.get("data", [])
            if model.get("id")
        ]
    except Exception:
        return []


async def call_upstream_json_at(
    request: Request,
    chat_url: str,
    payload: dict,
    headers: dict,
    *,
    cfg: Any,
) -> dict:
    client = request.app.state.http
    try:
        response = await client.post(chat_url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=502, detail=connect_error_detail(chat_url, exc, cfg=cfg))
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"连接上游超时 {chat_url}: {exc}")
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        if payload.get("provider"):
            provider_hint = "provider string" if isinstance(payload.get("provider"), str) else "provider.order"
            detail = (
                f"{detail}\n\n"
                f"提示: 本次请求包含 {provider_hint}。若上游不支持该 provider 格式、provider 名称不匹配，"
                "或当前模型不能走指定 provider，上游通常会在这里返回 400/422/404 类错误。"
            )
        raise HTTPException(status_code=exc.response.status_code, detail=detail[:900])
    except httpx.HTTPError as exc:
        logger.exception("Upstream request failed for %s", chat_url)
        raise HTTPException(status_code=502, detail=f"上游请求失败 {chat_url}: {exc}")


async def build_upstream_request(
    request: Request,
    body: Any,
    messages_override: Optional[list[dict]] = None,
    meta: Optional[dict] = None,
    *,
    cfg: Any,
) -> tuple[dict, dict, str, dict, dict]:
    model_name = mapped_model_name(cfg, body.model)
    upstream = (meta or {}).get("upstream") or upstream_for_hisense(
        cfg, bool(((meta or {}).get("package") or {}).get("is_hisense"))
    )
    proto = upstream["protocol"]
    raw_messages = messages_override or [message.model_dump(exclude_none=True) for message in body.messages]
    merged_tools = merge_tools(body.tools, cfg, meta=meta)
    window_meta = (meta or {}).get("client_message_window") or {}
    tail_guard_user_turns = _cache_tail_guard_user_turns(raw_messages, window_meta)
    cache_enabled = (
        bool(getattr(cfg, "enable_anthropic_cache_control", True))
        if proto == "anthropic"
        else bool(getattr(cfg, "enable_openai_cache_control", True))
    )
    cache_ttl = (
        getattr(cfg, "anthropic_cache_ttl", "1h")
        if proto == "anthropic"
        else getattr(cfg, "openai_cache_ttl", "5m")
    )
    cache_meta: dict[str, Any] = {
        "enabled": cache_enabled,
        "protocol": proto,
        "ttl": cache_ttl,
        "upstream_scope": upstream["scope"],
        "upstream_url": upstream["chat_url"],
        "breakpoints": [],
        "tail_guard_user_turns": tail_guard_user_turns,
        "note": "Prompt cache breakpoints are added when the upstream protocol can carry cache_control.",
    }

    if proto == "anthropic":
        cache_paths: list[str] = []
        anthropic_tools = (
            _convert_openai_tools_to_anthropic(merged_tools)
            if merged_tools
            else []
        )
        explicit_thinking = "thinking" in getattr(body, "model_fields_set", set())
        anthropic_thinking = _normalize_anthropic_thinking(getattr(body, "thinking", None))
        if not explicit_thinking and not anthropic_thinking and getattr(cfg, "enable_anthropic_auto_thinking", False):
            anthropic_thinking = _normalize_anthropic_thinking({"type": "adaptive"})
        pinned_thinking_config = _pinned_anthropic_thinking_config(raw_messages)
        if pinned_thinking_config and not explicit_thinking:
            pinned_thinking = _normalize_anthropic_thinking(pinned_thinking_config.get("thinking"))
            if pinned_thinking:
                anthropic_thinking = pinned_thinking
        output_config = getattr(body, "output_config", None)
        if not isinstance(output_config, dict):
            output_config = {}
        else:
            output_config = dict(output_config)
        reasoning_effort = str(getattr(body, "reasoning_effort", "") or "").strip().lower()
        if reasoning_effort and "effort" not in output_config:
            output_config["effort"] = reasoning_effort
        pinned_output_config = pinned_thinking_config.get("output_config")
        if isinstance(pinned_output_config, dict) and "effort" not in output_config:
            pinned_effort = str(pinned_output_config.get("effort") or "").strip().lower()
            if pinned_effort:
                output_config["effort"] = pinned_effort
        configured_effort = str(getattr(cfg, "anthropic_auto_thinking_effort", "") or "").strip().lower()
        if (
            anthropic_thinking
            and not pinned_thinking_config
            and configured_effort in {"max", "xhigh"}
            and "effort" not in output_config
        ):
            output_config["effort"] = configured_effort
        system, messages = _openai_to_anthropic(
            raw_messages,
            cache_layers=(meta or {}).get("cache_layers"),
            cache_paths=cache_paths,
            max_breakpoints=4 if cache_enabled else 0,
            cache_ttl=cache_ttl,
            tail_guard_user_turns=tail_guard_user_turns,
        )
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
        }
        max_tokens = body.max_tokens if body.max_tokens is not None else cfg.anthropic_default_max_tokens
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if system:
            payload["system"] = system
        if body.temperature is not None and not anthropic_thinking:
            payload["temperature"] = body.temperature
        if anthropic_tools:
            payload["tools"] = anthropic_tools
        if anthropic_thinking:
            payload["thinking"] = anthropic_thinking
        if output_config:
            payload["output_config"] = output_config
        apply_upstream_extra_body(payload, cfg)
        headers = {
            "x-api-key": upstream["api_key"],
            "anthropic-version": cfg.upstream_version,
            "content-type": "application/json",
        }
        headers.update(forwarded_client_headers(request, cfg))
        cache_meta["enabled"] = bool(cache_paths)
        cache_meta["breakpoints"] = cache_paths
        cache_meta["note"] = (
            "cache_control breakpoints added to configured Anthropic layer blocks."
            if cache_enabled
            else "Anthropic cache_control is disabled by ENABLE_ANTHROPIC_CACHE_CONTROL."
        )
        return payload, headers, model_name, cache_meta, upstream

    if cfg.enable_openai_cache_control:
        cache_messages, cache_tools, cache_paths = _apply_openai_compatible_cache_control(
            raw_messages,
            merged_tools or [],
            cache_layers=(meta or {}).get("cache_layers"),
            cache_ttl=cache_ttl,
            tail_guard_user_turns=tail_guard_user_turns,
        )
        cache_meta["enabled"] = bool(cache_paths)
        cache_meta["breakpoints"] = cache_paths
        cache_meta["note"] = "cache_control breakpoints added to OpenAI-compatible payload for upstream passthrough."
    else:
        cache_messages = _sanitize_openai_compatible_messages(raw_messages)
        cache_tools = _sanitize_openai_compatible_tools(merged_tools or [])
        cache_meta["enabled"] = False
        cache_meta["breakpoints"] = []
        cache_meta["note"] = "OpenAI-compatible cache_control is disabled by ENABLE_OPENAI_CACHE_CONTROL."

    payload = {"model": model_name, "messages": cache_messages}
    if body.max_tokens is not None:
        payload["max_tokens"] = body.max_tokens
    if body.temperature is not None:
        payload["temperature"] = body.temperature
    if cache_tools:
        payload["tools"] = cache_tools
    apply_upstream_extra_body(payload, cfg)
    headers = {"Authorization": f"Bearer {upstream['api_key']}", "content-type": "application/json"}
    headers.update(forwarded_client_headers(request, cfg))
    return payload, headers, model_name, cache_meta, upstream


async def stream_upstream_openai_chunks(
    request: Request,
    payload: dict,
    headers: dict,
    model: str,
    upstream: dict,
    *,
    cfg: Any,
) -> AsyncIterator[dict]:
    proto = upstream["protocol"]
    client = request.app.state.http
    chat_url = upstream["chat_url"]
    stream_payload = dict(payload)
    stream_payload["stream"] = True
    try:
        req = client.build_request("POST", chat_url, json=stream_payload, headers=headers)
        resp = await client.send(req, stream=True)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=502, detail=connect_error_detail(chat_url, exc, cfg=cfg))
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"连接上游超时 {chat_url}: {exc}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"上游请求失败 {chat_url}: {exc}")

    if resp.status_code >= 400:
        error_body = await resp.aread()
        await resp.aclose()
        detail = error_body.decode("utf-8", errors="replace")[:500]
        if stream_payload.get("provider"):
            provider_hint = "provider string" if isinstance(stream_payload.get("provider"), str) else "provider.order"
            detail = (
                f"{detail}\n\n"
                f"提示: 本次请求包含 {provider_hint}。若上游不支持该 provider 格式、provider 名称不匹配，"
                "或当前模型不能走指定 provider，上游通常会在这里返回 400/422/404 类错误。"
            )
        raise HTTPException(status_code=resp.status_code, detail=detail[:900])

    try:
        if proto == "openai":
            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if not line:
                    continue
                if line == "data: [DONE]":
                    break
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                yield data
            return

        anthropic_stop_reason = ""
        anthropic_usage: dict[str, Any] = {}
        anthropic_blocks: dict[int, dict[str, Any]] = {}
        chunk_id = _new_stream_chunk_id()
        created = _now_ts()
        tool_call_seen = False
        tool_index_by_block: dict[int, int] = {}
        async for raw_line in resp.aiter_lines():
            line = raw_line.strip()
            if not line or line == "data: [DONE]" or line.startswith("event:"):
                continue
            if line.startswith("data: "):
                line = line[6:]
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            _update_anthropic_content_blocks(anthropic_blocks, data)
            if data.get("type") == "message_start":
                usage = (data.get("message") or {}).get("usage")
                if isinstance(usage, dict):
                    anthropic_usage.update(usage)
            elif data.get("type") == "content_block_start":
                block = data.get("content_block") or {}
                if block.get("type") == "tool_use":
                    tool_call_seen = True
            elif data.get("type") == "message_delta":
                anthropic_stop_reason = data.get("delta", {}).get("stop_reason") or anthropic_stop_reason
                usage = data.get("usage")
                if isinstance(usage, dict):
                    anthropic_usage.update(usage)
            finish_reason = _anthropic_stop_reason_to_openai(anthropic_stop_reason)
            if data.get("type") == "message_stop" and tool_call_seen and finish_reason is None:
                finish_reason = "tool_calls"
            chunk = _anthropic_to_openai_chunk(
                model,
                data,
                finish_reason_override=finish_reason,
                tool_index_override=_anthropic_tool_index_override(data, tool_index_by_block),
                chunk_id=chunk_id,
                created=created,
            )
            if chunk:
                try:
                    converted = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
            else:
                converted = {"choices": []}
            if anthropic_blocks:
                converted[ANTHROPIC_CONTENT_BLOCKS_KEY] = _anthropic_content_blocks_snapshot(anthropic_blocks)
            usage = data.get("usage") or (data.get("message") or {}).get("usage")
            if isinstance(usage, dict):
                converted["usage"] = _anthropic_usage_to_openai(usage)
            elif data.get("type") == "message_stop" and anthropic_usage:
                converted["usage"] = _anthropic_usage_to_openai(anthropic_usage)
            if chunk or anthropic_blocks:
                yield converted
    finally:
        await resp.aclose()
