from types import SimpleNamespace

import httpx
import pytest

from shenyu_gateway.upstream_client import (
    _default_upstream_auth,
    build_upstream_request,
    fetch_upstream_models,
    validated_upstream_auth,
)


def _request_with_client(client: httpx.AsyncClient) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http=client)))


@pytest.mark.asyncio
async def test_fetch_upstream_models_accepts_model_field_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api-gateway.merge.dev/v1/models"
        assert request.headers["Authorization"] == "Bearer merge-key"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "model": "anthropic/claude-opus-4-6",
                        "display_name": "Claude Opus 4.6",
                    },
                    {"id": "canonical-id", "model": "fallback-id", "created": 123},
                    {"provider": "missing-identifier"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = await fetch_upstream_models(
            _request_with_client(client),
            cfg=SimpleNamespace(),
            upstream={
                "protocol": "openai",
                "base_url": "https://api-gateway.merge.dev",
                "api_key": "merge-key",
            },
        )

    assert models == [
        {
            "id": "anthropic/claude-opus-4-6",
            "object": "model",
            "created": 1700000000,
            "owned_by": "upstream",
        },
        {
            "id": "canonical-id",
            "object": "model",
            "created": 123,
            "owned_by": "upstream",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_headers", "expected"),
    [
        ({"x-shenyu-upstream-x-api-key": "merge-key"}, {"x-api-key": "merge-key"}),
        ({"x-shenyu-upstream-authorization": "Token merge-token"}, {"authorization": "Token merge-token"}),
    ],
)
async def test_fetch_upstream_models_prefers_pwa_auth_override(request_headers, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        if "x-api-key" in expected:
            assert request.headers["x-api-key"] == expected["x-api-key"]
            assert "authorization" not in request.headers
        else:
            assert request.headers["authorization"] == expected["authorization"]
            assert "x-api-key" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "model-a"}]})

    request = _request_with_client(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    request.headers = httpx.Headers(request_headers)
    try:
        models = await fetch_upstream_models(
            request,
            cfg=SimpleNamespace(),
            upstream={"protocol": "openai", "base_url": "https://upstream.example", "api_key": "default-key"},
        )
    finally:
        await request.app.state.http.aclose()

    assert models[0]["id"] == "model-a"


def test_upstream_auth_validation_is_mutually_exclusive_and_defaults_by_protocol():
    assert validated_upstream_auth({"x-api-key": " k "}) == {"x-api-key": "k"}
    assert validated_upstream_auth({"authorization": " Bearer k "}) == {"authorization": "Bearer k"}
    assert _default_upstream_auth({"protocol": "openai", "api_key": "k"}) == {"authorization": "Bearer k"}
    assert _default_upstream_auth({"protocol": "anthropic", "api_key": "k"}) == {"x-api-key": "k"}


@pytest.mark.asyncio
async def test_build_upstream_request_uses_explicit_auth_without_claude_header_conflict():
    body = SimpleNamespace(
        model="test-model",
        messages=[SimpleNamespace(model_dump=lambda exclude_none=True: {"role": "user", "content": "hello"})],
        upstream_headers={"User-Agent": "claude-cli/2.1.201"},
        upstream_auth={"x-api-key": "special-key"},
        max_tokens=None,
        temperature=None,
        tools=None,
        model_fields_set=set(),
        thinking=None,
        output_config=None,
        reasoning_effort=None,
        metadata=None,
    )
    cfg = SimpleNamespace(
        upstream_url="https://upstream.example",
        upstream_api_key="default-key",
        upstream_protocol="openai",
        enable_openai_cache_control=False,
        enable_anthropic_cache_control=False,
        openai_cache_ttl="5m",
        anthropic_cache_ttl="1h",
        enable_anthropic_auto_thinking=False,
        anthropic_auto_thinking_effort="",
        anthropic_default_max_tokens=None,
        model_mapping={},
        upstream_extra_body={},
    )
    payload, headers, *_ = await build_upstream_request(None, body, cfg=cfg)
    assert payload["model"] == "test-model"
    assert headers["x-api-key"] == "special-key"
    assert "authorization" not in headers
    assert headers["user-agent"] == "claude-cli/2.1.201"
