from __future__ import annotations

from typing import Any, Optional

import httpx


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

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(headers=self.headers, timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def query(self, table: str, params: Optional[dict] = None) -> list:
        client = await self.get_client()
        response = await client.get(f"{self.base_url}/{table}", params=params or {})
        response.raise_for_status()
        return response.json()

    async def insert(self, table: str, data: dict) -> dict:
        client = await self.get_client()
        response = await client.post(f"{self.base_url}/{table}", json=data)
        response.raise_for_status()
        result = response.json()
        return result[0] if isinstance(result, list) and result else result

    async def update(self, table: str, match: dict, data: dict) -> list:
        client = await self.get_client()
        params = {key: f"eq.{value}" for key, value in match.items()}
        response = await client.patch(f"{self.base_url}/{table}", params=params, json=data)
        response.raise_for_status()
        return response.json()

    async def delete(self, table: str, match: dict) -> list:
        client = await self.get_client()
        params = {key: f"eq.{value}" for key, value in match.items()}
        response = await client.delete(f"{self.base_url}/{table}", params=params)
        response.raise_for_status()
        return response.json()

    async def rpc(self, fn: str, params: Optional[dict] = None) -> Any:
        client = await self.get_client()
        response = await client.post(f"{self.rpc_url}/{fn}", json=params or {})
        response.raise_for_status()
        return response.json()
