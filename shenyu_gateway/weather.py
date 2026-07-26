from __future__ import annotations

"""QWeather client for the window weather the PWA shows.

Configuration is read at call time so Admin console changes apply on the next
request. The city→locationId lookup is cached for ~24h and the observed
weather for ~15min per (host, key, city) in process memory. Every failure
degrades to ``{"available": False}`` — this service must never raise into a
request path.
"""

import time
from typing import Any, Optional

import httpx

from .runtime import iso_now, logger

CITY_CACHE_TTL_SECONDS = 24 * 3600
WEATHER_CACHE_TTL_SECONDS = 15 * 60
# Failed fetches are cached briefly so a broken upstream cannot add a 5s
# timeout to every poll, while a config fix still applies quickly.
FAILURE_CACHE_TTL_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 5.0

_city_cache: dict[tuple[str, str, str], tuple[float, str]] = {}
_weather_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}


def _reset_weather_caches() -> None:
    _city_cache.clear()
    _weather_cache.clear()


def _unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "city": None,
        "text": None,
        "temp_c": None,
        "updated_at": None,
        "source": "qweather",
    }


def normalize_qweather_host(raw: Any) -> str:
    """Accept the per-account API host with or without an https:// prefix."""
    host = str(raw or "").strip()
    lowered = host.lower()
    for prefix in ("https://", "http://"):
        if lowered.startswith(prefix):
            host = host[len(prefix):]
            break
    return host.strip().strip("/")


class QWeatherService:
    def __init__(self, cfg: Any):
        self.cfg = cfg

    def _settings(self) -> tuple[str, str, str]:
        city = str(getattr(self.cfg, "weather_city", "") or "").strip()
        key = str(getattr(self.cfg, "qweather_api_key", "") or "").strip()
        host = normalize_qweather_host(getattr(self.cfg, "qweather_api_host", ""))
        return city, key, host

    async def current(self, client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
        city, key, host = self._settings()
        if not city or not key or not host:
            return _unavailable()

        cache_key = (host, key, city)
        now = time.monotonic()
        cached = _weather_cache.get(cache_key)
        if cached and cached[0] > now:
            return dict(cached[1])

        payload = await self._fetch(city, key, host, client)
        ttl = WEATHER_CACHE_TTL_SECONDS if payload.get("available") else FAILURE_CACHE_TTL_SECONDS
        _weather_cache[cache_key] = (now + ttl, dict(payload))
        return payload

    async def _fetch(
        self,
        city: str,
        key: str,
        host: str,
        client: Optional[httpx.AsyncClient],
    ) -> dict[str, Any]:
        own_client = client is None
        http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        try:
            location_id = await self._location_id(http, city, key, host)
            if not location_id:
                return _unavailable()
            resp = await http.get(
                f"https://{host}/v7/weather/now",
                params={"location": location_id},
                headers={"X-QW-Api-Key": key},
            )
            data = resp.json() if resp.status_code == 200 else {}
            now_block = data.get("now") if isinstance(data, dict) else None
            if str((data or {}).get("code") or "") != "200" or not isinstance(now_block, dict):
                return _unavailable()
            try:
                temp_c: Optional[int] = int(round(float(now_block.get("temp"))))
            except (TypeError, ValueError):
                temp_c = None
            text = str(now_block.get("text") or "").strip() or None
            if text is None and temp_c is None:
                return _unavailable()
            return {
                "available": True,
                "city": city,
                "text": text,
                "temp_c": temp_c,
                "updated_at": str(now_block.get("obsTime") or data.get("updateTime") or iso_now()),
                "source": "qweather",
            }
        except Exception as exc:
            logger.warning("[Weather] qweather fetch failed: %s", exc)
            return _unavailable()
        finally:
            if own_client:
                await http.aclose()

    async def _location_id(
        self,
        http: httpx.AsyncClient,
        city: str,
        key: str,
        host: str,
    ) -> str:
        cache_key = (host, key, city)
        now = time.monotonic()
        cached = _city_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        resp = await http.get(
            f"https://{host}/geo/v2/city/lookup",
            params={"location": city},
            headers={"X-QW-Api-Key": key},
        )
        data = resp.json() if resp.status_code == 200 else {}
        locations = data.get("location") if isinstance(data, dict) else None
        if str((data or {}).get("code") or "") != "200" or not locations:
            return ""
        location_id = str((locations[0] or {}).get("id") or "").strip()
        if location_id:
            _city_cache[cache_key] = (now + CITY_CACHE_TTL_SECONDS, location_id)
        return location_id
