from __future__ import annotations

from typing import Any, Optional

import httpx


class EmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        expected_dim: int = 1024,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.expected_dim = int(expected_dim or 1024)
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def embed(self, text: str) -> tuple[Optional[list[float]], Optional[str]]:
        if not self.enabled:
            return None, "Embedding API is not configured."
        body = {"model": self.model, "input": text or ""}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(f"{self.base_url}/embeddings", headers=headers, json=body)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            return None, exc.response.text[:500]
        except Exception as exc:
            return None, str(exc)[:500]

        items = data.get("data") or []
        if not items or not isinstance(items[0], dict):
            return None, "Embedding API returned no data."
        embedding = items[0].get("embedding")
        if not isinstance(embedding, list):
            return None, "Embedding API returned invalid embedding."
        if len(embedding) != self.expected_dim:
            return None, f"Embedding dimension mismatch: got {len(embedding)}, expected {self.expected_dim}."
        try:
            vector = [float(value) for value in embedding]
        except (TypeError, ValueError):
            return None, "Embedding contains non-numeric values."
        return vector, None
