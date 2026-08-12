from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from shenyu_gateway.upstream_client import forwarded_client_headers, validated_custom_upstream_headers


def _request(headers: dict[str, str]) -> SimpleNamespace:
    """Minimal request stand-in: forwarded_client_headers only reads request.headers.get."""
    return SimpleNamespace(headers=Headers(headers))


def test_default_whitelist_forwards_x_api_key():
    cfg = SimpleNamespace(upstream_passthrough_headers=["x-api-key"])
    req = _request({"x-api-key": "yep_sk_123", "authorization": "Bearer gatewaykey"})
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "yep_sk_123"}


def test_reserved_authorization_not_forwarded_even_if_whitelisted():
    # Even if someone mistakenly whitelists authorization/content-type, the reserved
    # set must keep the gateway in control of those (and never leak the inbound gateway key).
    cfg = SimpleNamespace(upstream_passthrough_headers=["authorization", "x-api-key", "content-type"])
    req = _request(
        {
            "authorization": "Bearer gatewaykey",
            "x-api-key": "k",
            "content-type": "application/json",
        }
    )
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "k"}


def test_gateway_identification_headers_isolated():
    # The thread/client identification headers must never reach the upstream.
    cfg = SimpleNamespace(
        upstream_passthrough_headers=[
            "x-shenyu-session-tag",
            "x-session-tag",
            "x-shenyu-client",
            "x-shenyu-tool-events",
            "x-client-name",
            "x-api-key",
        ]
    )
    req = _request(
        {
            "x-shenyu-session-tag": "6.20",
            "x-session-tag": "6.20",
            "x-shenyu-client": "shenyu-pwa",
            "x-shenyu-tool-events": "1",
            "x-client-name": "shenyu-pwa",
            "x-api-key": "k",
        }
    )
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "k"}


def test_hop_by_hop_headers_isolated():
    cfg = SimpleNamespace(
        upstream_passthrough_headers=["host", "connection", "transfer-encoding", "x-api-key"]
    )
    req = _request({"host": "api.example", "connection": "keep-alive", "x-api-key": "k"})
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "k"}


def test_unsent_whitelisted_header_omitted():
    cfg = SimpleNamespace(upstream_passthrough_headers=["x-api-key", "x-trace-id"])
    req = _request({"x-api-key": "k"})
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "k"}


def test_empty_whitelist_returns_empty():
    cfg = SimpleNamespace(upstream_passthrough_headers=[])
    req = _request({"x-api-key": "k"})
    assert forwarded_client_headers(req, cfg) == {}


def test_missing_attribute_returns_empty():
    # A cfg that never configured the whitelist should behave as "forward nothing".
    cfg = SimpleNamespace()
    req = _request({"x-api-key": "k"})
    assert forwarded_client_headers(req, cfg) == {}


def test_case_insensitive_whitelist():
    cfg = SimpleNamespace(upstream_passthrough_headers=["X-Api-Key"])
    req = _request({"x-api-key": "k"})
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "k"}


def test_duplicate_whitelist_entries_deduped():
    cfg = SimpleNamespace(upstream_passthrough_headers=["x-api-key", "X-API-KEY", "x-api-key"])
    req = _request({"x-api-key": "k"})
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "k"}


def test_custom_header_forwarded():
    cfg = SimpleNamespace(upstream_passthrough_headers=["x-api-key", "x-trace-id"])
    req = _request({"x-api-key": "k", "x-trace-id": "abc"})
    assert forwarded_client_headers(req, cfg) == {"x-api-key": "k", "x-trace-id": "abc"}


def test_per_request_headers_accept_claude_code_preset():
    assert validated_custom_upstream_headers(
        {
            "User-Agent": "claude-cli/2.1.201 (external, sdk-cli)",
            "Accept": "application/json",
            "Anthropic-Beta": "claude-code-20250219,interleaved-thinking-2025-05-14,effort-2025-11-24,prompt-caching-scope-2026-01-05",
            "Anthropic-Dangerous-Direct-Browser-Access": "true",
            "X-App": "cli",
            "X-Claude-Code-Session-Id": "550e8400-e29b-41d4-a716-446655440000",
            "X-Stainless-Lang": "js",
            "X-Stainless-Runtime": "node",
        }
    ) == {
        "user-agent": "claude-cli/2.1.201 (external, sdk-cli)",
        "accept": "application/json",
        "anthropic-beta": "claude-code-20250219,interleaved-thinking-2025-05-14,effort-2025-11-24,prompt-caching-scope-2026-01-05",
        "anthropic-dangerous-direct-browser-access": "true",
        "x-app": "cli",
        "x-claude-code-session-id": "550e8400-e29b-41d4-a716-446655440000",
        "x-stainless-lang": "js",
        "x-stainless-runtime": "node",
    }


@pytest.mark.parametrize(
    "name",
    ["Authorization", "X-Api-Key", "Anthropic-Version", "Cookie", "X-Shenyu-Client"],
)
def test_per_request_headers_reject_gateway_owned_names(name):
    with pytest.raises(HTTPException, match="由网关管理"):
        validated_custom_upstream_headers({name: "override"})


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"Bad Header": "value"}, "无效的上游请求头名称"),
        ({"X-Trace": "one\r\ntwo"}, "包含非法换行"),
        ({"X-Trace": "中文"}, "只支持 ASCII"),
    ],
)
def test_per_request_headers_reject_invalid_wire_values(headers, message):
    with pytest.raises(HTTPException, match=message):
        validated_custom_upstream_headers(headers)
