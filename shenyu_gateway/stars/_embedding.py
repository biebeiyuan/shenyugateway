from __future__ import annotations

from typing import Any, Optional

from ..embeddings import EmbeddingClient
from ..runtime import iso_now, logger
from ..utils import shorten as _shorten
from ._helpers import _safe_float, _safe_int, _vector_literal
from ..request_logs import _mark_request_log_phase


class EmbeddingMixin:
    def _embedding_client(self) -> Optional[EmbeddingClient]:
        star_enabled = bool(getattr(self.cfg, "enable_star_embeddings", getattr(self.cfg, "enable_recall_embeddings", False)))
        if not star_enabled:
            return None
        client = EmbeddingClient(
            base_url=getattr(self.cfg, "embedding_base_url", ""),
            api_key=getattr(self.cfg, "embedding_api_key", ""),
            model=getattr(self.cfg, "embedding_model", ""),
            expected_dim=int(getattr(self.cfg, "embedding_dim", 1024) or 1024),
        )
        return client if client.enabled else None

    async def _vector_rows(self, query: str, *, trace_log: Optional[dict] = None) -> list[dict[str, Any]]:
        client = self._embedding_client()
        if not client or not query.strip() or not hasattr(self.supabase, "rpc"):
            _mark_request_log_phase(
                trace_log,
                "stars.vector_skipped",
                detail={
                    "embedding_client": bool(client),
                    "has_query": bool(query.strip()),
                    "has_rpc": hasattr(self.supabase, "rpc"),
                },
            )
            return []
        _mark_request_log_phase(
            trace_log,
            "stars.embedding_start",
            detail={"model": client.model, "query_chars": min(len(query), 1600)},
        )
        vector, error = await client.embed(query[:1600])
        if error or vector is None:
            _mark_request_log_phase(
                trace_log,
                "stars.embedding_failed",
                detail={"error": _shorten(error or "embedding failed", 240)},
            )
            return []
        _mark_request_log_phase(trace_log, "stars.embedding_done", detail={"dimensions": len(vector)})
        try:
            _mark_request_log_phase(
                trace_log,
                "stars.vector_rpc_start",
                detail={"match_count": min(self._candidate_limit(), 120)},
            )
            rows = await self.supabase.rpc(
                "match_shenyu_stars",
                {
                    "query_embedding": _vector_literal(vector),
                    "match_count": min(self._candidate_limit(), 120),
                    "include_status": "active",
                },
            )
        except Exception as exc:
            logger.warning("[Star] vector search failed: %s", exc)
            _mark_request_log_phase(
                trace_log,
                "stars.vector_rpc_failed",
                detail={"error": _shorten(str(exc), 240)},
            )
            return []
        _mark_request_log_phase(
            trace_log,
            "stars.vector_rpc_done",
            detail={"rows": len(rows) if isinstance(rows, list) else 0},
        )
        return rows if isinstance(rows, list) else []

    async def _attach_embedding(self, payload: dict[str, Any], chord: str, content: str) -> None:
        client = self._embedding_client()
        if not client:
            payload["embedding_status"] = "skipped"
            return
        text = "\n".join(part for part in [chord, content] if part).strip()[:1600]
        if not text:
            payload["embedding_status"] = "skipped"
            return
        vector, error = await client.embed(text)
        if error or vector is None:
            payload["embedding_status"] = "failed"
            payload["embedding_error"] = error or "embedding failed"
            return
        payload["embedding"] = _vector_literal(vector)
        payload["embedding_model"] = client.model
        payload["embedding_status"] = "ready"
        payload["embedding_error"] = None
        payload["embedded_at"] = iso_now()
