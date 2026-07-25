from __future__ import annotations

from types import SimpleNamespace

from starlette.datastructures import Headers

from shenyu_gateway.upstream_client import forwarded_client_headers


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
            "x-shenyu-client": "hisense",
            "x-shenyu-tool-events": "1",
            "x-client-name": "hisense",
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
