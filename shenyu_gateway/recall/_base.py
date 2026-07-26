from __future__ import annotations

import asyncio
from typing import Any, Optional

from shenyu_gateway.embeddings import EmbeddingClient


RECALL_INDEX_TABLE = "shenyu_recall_index"


DEFAULT_RECALL_CANDIDATE_LIMIT = 160


DEFAULT_RECALL_LIMIT = 4


MAX_RECALL_LIMIT = 8


RECALL_SYNC_PAGE_SIZE = 1000


PUBLIC_RECALL_SOURCE_TYPES = [
    "memory",
    "journal",
    "windowsill",
    "heartbeat",
    "room",
    "board",
    "calendar",
    "mem_note",
    "notebook",
]


class RecallServiceBase:
    def __init__(self, supabase: Any, cfg: Any = None, embedding_client: Optional[EmbeddingClient] = None):
        self.supabase = supabase
        self.cfg = cfg
        self.embedding_client = embedding_client or self._embedding_client_from_config(cfg)
        self._embed_pending_lock = asyncio.Lock()

    def _candidate_limit(self) -> int:
        raw_limit = getattr(self.cfg, "recall_candidate_limit", DEFAULT_RECALL_CANDIDATE_LIMIT)
        try:
            limit = int(raw_limit or DEFAULT_RECALL_CANDIDATE_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_RECALL_CANDIDATE_LIMIT
        return max(20, min(limit, 1000))

    def _vector_min_score(self) -> float:
        try:
            value = float(getattr(self.cfg, "recall_vector_min_score", 0.42) or 0.42)
        except (TypeError, ValueError):
            value = 0.42
        return max(0.0, min(value, 1.0))

    async def _query_all_rows(
        self,
        table: str,
        params: Optional[dict[str, str]] = None,
        *,
        page_size: int = RECALL_SYNC_PAGE_SIZE,
    ) -> list[dict]:
        base_params = dict(params or {})
        base_params.pop("limit", None)
        base_params.pop("offset", None)
        size = max(1, min(int(page_size or RECALL_SYNC_PAGE_SIZE), RECALL_SYNC_PAGE_SIZE))
        rows: list[dict] = []
        offset = 0
        while True:
            page_params = {
                **base_params,
                "limit": str(size),
                "offset": str(offset),
            }
            page = await self.supabase.query(table, page_params)
            if not isinstance(page, list) or not page:
                break
            rows.extend(page)
            if len(page) < size:
                break
            offset += len(page)
        return rows

    def _requested_source_types(self, source_types: Optional[list[str]]) -> list[str]:
        types = []
        for item in source_types or []:
            if item is None:
                continue
            source_type = str(item).strip()
            if source_type and source_type != "all":
                types.append(source_type)
        return types

    def _source_type_filter(self, source_types: Optional[list[str]], *, allow_mem_note: bool = False) -> list[str]:
        if not self._requested_source_types(source_types):
            return list(PUBLIC_RECALL_SOURCE_TYPES)
        types = []
        for source_type in self._requested_source_types(source_types):
            if source_type in {"note", "mem"}:
                source_type = "mem_note"
            if source_type in {"atomic", "meta"}:
                continue
            aliases = {"memories": "memory", "message_board": "board"}
            public_type = aliases.get(source_type, source_type)
            if public_type in PUBLIC_RECALL_SOURCE_TYPES and public_type not in types:
                types.append(public_type)
        return types

    def _auto_sync_enabled(self, auto_sync: Optional[bool]) -> bool:
        if auto_sync is not None:
            return bool(auto_sync)
        return bool(getattr(self.cfg, "enable_recall_auto_sync", False))
