from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shenyu_gateway.embeddings import EmbeddingClient

from ._base import RECALL_INDEX_TABLE
from ._text import _vector_literal


class EmbeddingMixin:
    def _embedding_client_from_config(self, cfg: Any) -> Optional[EmbeddingClient]:
        if not cfg or not getattr(cfg, "enable_recall_embeddings", False):
            return None
        return EmbeddingClient(
            base_url=getattr(cfg, "embedding_base_url", ""),
            api_key=getattr(cfg, "embedding_api_key", ""),
            model=getattr(cfg, "embedding_model", ""),
            expected_dim=int(getattr(cfg, "embedding_dim", 1024) or 1024),
        )

    async def embed_pending(self, limit: int = 200) -> dict[str, Any]:
        if not self.embedding_client or not self.embedding_client.enabled:
            return {"ok": False, "enabled": False, "embedded": 0, "error": "Embedding API is not configured."}
        if self._embed_pending_lock.locked():
            return {
                "ok": False,
                "enabled": True,
                "seen": 0,
                "embedded": 0,
                "failed": 0,
                "already_running": True,
                "error": "Embedding worker is already running.",
            }
        async with self._embed_pending_lock:
            return await self._embed_pending_unlocked(limit=limit)

    async def _embed_pending_unlocked(self, limit: int = 200) -> dict[str, Any]:
        rows = await self.supabase.query(
            RECALL_INDEX_TABLE,
            {
                "select": "id,embedding_text,embedding_status",
                "deleted_at": "is.null",
                "embedding_status": "in.(pending,failed)",
                "order": "indexed_at.asc",
                "limit": str(max(1, min(int(limit or 200), 1000))),
            },
        )
        embedded = 0
        failed = 0
        for row in rows:
            text = row.get("embedding_text") or ""
            if not text.strip():
                await self.supabase.update(
                    RECALL_INDEX_TABLE,
                    {"id": row.get("id")},
                    {"embedding_status": "skipped", "embedding_error": "empty embedding_text"},
                )
                continue
            vector, error = await self.embedding_client.embed(text)
            if error or vector is None:
                failed += 1
                await self.supabase.update(
                    RECALL_INDEX_TABLE,
                    {"id": row.get("id")},
                    {"embedding_status": "failed", "embedding_error": error or "embedding failed"},
                )
                continue
            embedded += 1
            await self.supabase.update(
                RECALL_INDEX_TABLE,
                {"id": row.get("id")},
                {
                    "embedding": _vector_literal(vector),
                    "embedding_model": self.embedding_client.model,
                    "embedding_status": "ready",
                    "embedding_error": None,
                    "embedded_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {"ok": failed == 0, "enabled": True, "seen": len(rows), "embedded": embedded, "failed": failed}

