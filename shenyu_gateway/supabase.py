from __future__ import annotations

from typing import Any, Optional

import httpx


def _raise_for_status(response: httpx.Response):
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text[:1000]
        raise httpx.HTTPStatusError(
            f"{exc} | response: {detail}",
            request=exc.request,
            response=exc.response,
        ) from exc


class SupabaseClient:
    def __init__(self, url: str, key: str):
        self.base_url = url.rstrip("/") + "/rest/v1"
        self.rpc_url = url.rstrip("/") + "/rest/v1/rpc"
        self.headers = {
            "apikey": key,
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client: Optional[httpx.AsyncClient] = None
        self._fallback_client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(headers=self.headers, timeout=30.0, proxy=None, trust_env=False)
        return self._client

    async def get_fallback_client(self) -> httpx.AsyncClient:
        if self._fallback_client is None or self._fallback_client.is_closed:
            self._fallback_client = httpx.AsyncClient(headers=self.headers, timeout=30.0, trust_env=True)
        return self._fallback_client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        if self._fallback_client and not self._fallback_client.is_closed:
            await self._fallback_client.aclose()
            self._fallback_client = None

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        client = await self.get_client()
        try:
            return await client.request(method, url, **kwargs)
        except httpx.ConnectError:
            fallback = await self.get_fallback_client()
            return await fallback.request(method, url, **kwargs)

    async def query(self, table: str, params: Optional[dict] = None) -> list:
        response = await self._request("GET", f"{self.base_url}/{table}", params=params or {})
        _raise_for_status(response)
        return response.json()

    async def insert(self, table: str, data: dict) -> dict:
        response = await self._request("POST", f"{self.base_url}/{table}", json=data)
        _raise_for_status(response)
        result = response.json()
        return result[0] if isinstance(result, list) and result else result

    async def update(self, table: str, match: dict, data: dict) -> list:
        params = {key: f"eq.{value}" for key, value in match.items()}
        response = await self._request("PATCH", f"{self.base_url}/{table}", params=params, json=data)
        _raise_for_status(response)
        return response.json()

    async def delete(self, table: str, match: dict) -> list:
        params = {key: f"eq.{value}" for key, value in match.items()}
        response = await self._request("DELETE", f"{self.base_url}/{table}", params=params)
        _raise_for_status(response)
        return response.json()

    async def rpc(self, fn: str, params: Optional[dict] = None) -> Any:
        response = await self._request("POST", f"{self.rpc_url}/{fn}", json=params or {})
        _raise_for_status(response)
        return response.json()
