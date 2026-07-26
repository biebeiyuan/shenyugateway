from __future__ import annotations

from typing import Any

from shenyu_gateway.conflict_books import ConflictBookService
from shenyu_gateway.mem_notes import MemNoteService
from shenyu_gateway.recall import RecallIndexService
from shenyu_gateway.resident_books import ResidentBooksService
from shenyu_gateway.stars import StarService

from ._runtime import _UNSET, _runtime


class GatewayToolServiceBase:
    def __init__(self, runtime_config: Any = _UNSET, supabase: Any = _UNSET, store: Any = _UNSET):
        self.cfg = (
            _runtime.cfg
            if runtime_config is _UNSET
            else runtime_config
        )
        self.supabase = (
            _runtime.supabase_client
            if supabase is _UNSET
            else supabase
        )
        self.store = (
            _runtime.session_store
            if store is _UNSET
            else store
        )

    def _mem_notes(self) -> MemNoteService:
        return MemNoteService(self.cfg, self.supabase)

    def _stars(self) -> StarService:
        return StarService(self.cfg, self.supabase)

    def _recall_index(self) -> RecallIndexService:
        return RecallIndexService(self.supabase, cfg=self.cfg)

    def _conflict_books(self) -> ConflictBookService:
        return ConflictBookService(self.supabase)

    def _resident_books(self) -> ResidentBooksService:
        return ResidentBooksService(self.supabase, runtime_config=self.cfg)

    async def _safe_query(self, table: str, params: dict) -> list:
        if not self.supabase:
            return []
        try:
            return await self.supabase.query(table, params)
        except Exception:
            return []
