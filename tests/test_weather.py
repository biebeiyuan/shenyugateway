from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import gateway
from shenyu_gateway import weather as weather_module
from shenyu_gateway.weather import QWeatherService, normalize_qweather_host


UNAVAILABLE = {
    "available": False,
    "city": None,
    "text": None,
    "temp_c": None,
    "updated_at": None,
    "source": "qweather",
}


@pytest.fixture(autouse=True)
def _clean_weather_caches():
    weather_module._reset_weather_caches()
    yield
    weather_module._reset_weather_caches()


def _cfg(**overrides):
    base = {
        "weather_city": "邵阳",
        "qweather_api_key": "test-key",
        "qweather_api_host": "https://abc123.qweatherapi.com",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _mock_client(calls: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["X-QW-Api-Key"] == "test-key"
        assert request.url.host == "abc123.qweatherapi.com"
        if request.url.path == "/geo/v2/city/lookup":
            assert request.url.params["location"] == "邵阳"
            return httpx.Response(
                200,
                json={"code": "200", "location": [{"id": "101250901", "name": "邵阳"}]},
            )
        if request.url.path == "/v7/weather/now":
            assert request.url.params["location"] == "101250901"
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "updateTime": "2026-07-26T14:35+08:00",
                    "now": {"obsTime": "2026-07-26T14:30+08:00", "temp": "25", "text": "霾"},
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run(coro):
    return asyncio.run(coro)


def test_normalize_qweather_host_tolerates_scheme_prefix_and_slash():
    assert normalize_qweather_host("abc123.qweatherapi.com") == "abc123.qweatherapi.com"
    assert normalize_qweather_host("https://abc123.qweatherapi.com/") == "abc123.qweatherapi.com"
    assert normalize_qweather_host("HTTP://abc123.qweatherapi.com") == "abc123.qweatherapi.com"
    assert normalize_qweather_host("") == ""
    assert normalize_qweather_host(None) == ""


def test_weather_normal_payload_and_host_normalization():
    calls: list[str] = []
    client = _mock_client(calls)

    async def run():
        try:
            return await QWeatherService(_cfg()).current(client=client)
        finally:
            await client.aclose()

    payload = _run(run())

    assert payload == {
        "available": True,
        "city": "邵阳",
        "text": "霾",
        "temp_c": 25,
        "updated_at": "2026-07-26T14:30+08:00",
        "source": "qweather",
    }
    assert calls == ["/geo/v2/city/lookup", "/v7/weather/now"]


def test_weather_unconfigured_key_short_circuits_without_http():
    calls: list[str] = []
    client = _mock_client(calls)

    async def run():
        try:
            return await QWeatherService(_cfg(qweather_api_key="")).current(client=client)
        finally:
            await client.aclose()

    payload = _run(run())

    assert payload == UNAVAILABLE
    assert calls == []


def test_weather_upstream_timeout_degrades_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("upstream timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run():
        try:
            return await QWeatherService(_cfg()).current(client=client)
        finally:
            await client.aclose()

    assert _run(run()) == UNAVAILABLE


def test_weather_upstream_error_code_degrades_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "401"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run():
        try:
            return await QWeatherService(_cfg()).current(client=client)
        finally:
            await client.aclose()

    assert _run(run()) == UNAVAILABLE


def test_weather_cache_hit_skips_second_fetch():
    calls: list[str] = []
    client = _mock_client(calls)
    service = QWeatherService(_cfg())

    async def run():
        try:
            first = await service.current(client=client)
            second = await service.current(client=client)
            return first, second
        finally:
            await client.aclose()

    first, second = _run(run())

    assert first["available"] is True
    assert second == first
    assert calls == ["/geo/v2/city/lookup", "/v7/weather/now"]


def test_weather_endpoint_unconfigured_returns_available_false(monkeypatch):
    monkeypatch.setattr(gateway.cfg, "gateway_key", "")
    monkeypatch.setattr(gateway.cfg, "weather_city", "邵阳")
    monkeypatch.setattr(gateway.cfg, "qweather_api_key", "")
    monkeypatch.setattr(gateway.cfg, "qweather_api_host", "")

    client = TestClient(gateway.app)
    try:
        response = client.get("/api/gateway/weather")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == UNAVAILABLE
