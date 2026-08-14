from __future__ import annotations

from typing import Any

from shenyu_gateway.runtime import logger

from ._runtime import (
    WINDOWSILL_ORIGIN_NORMAL,
    WINDOWSILL_ORIGINS,
    WINDOWSILL_TABLE,
)


class WindowsillToolsMixin:
    async def windowsill_write(
        self,
        content: Any,
        title: Any = "",
        mood: Any = "",
        *,
        origin: Any = WINDOWSILL_ORIGIN_NORMAL,
    ) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured.", "error_kind": "config"}
        body = str(content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required.", "error_kind": "validation"}
        origin_key = str(origin or WINDOWSILL_ORIGIN_NORMAL).strip() or WINDOWSILL_ORIGIN_NORMAL
        if origin_key not in WINDOWSILL_ORIGINS:
            return {"ok": False, "error": "unsupported windowsill origin.", "error_kind": "validation"}
        payload = {
            "content": body,
            "title": str(title or "").strip(),
            "mood": str(mood or "").strip(),
        }
        # Normal writes keep the original database-default path unchanged.
        if origin_key != WINDOWSILL_ORIGIN_NORMAL:
            payload["origin"] = origin_key
        try:
            row = await self.supabase.insert(WINDOWSILL_TABLE, payload)
            if isinstance(row, dict):
                try:
                    index_result = await self._recall_index().index_windowsill_row(row)
                    if not index_result.get("ok"):
                        logger.warning("[Windowsill] Recall indexing skipped: %s", index_result.get("error"))
                except Exception as exc:
                    logger.warning("[Windowsill] Recall indexing failed: %s", exc)
            return {"ok": True, "data": row}
        except Exception as exc:
            return {
                "ok": False,
                "error": self._friendly_supabase_error(WINDOWSILL_TABLE, exc),
                "error_kind": "exception",
            }

    async def windowsill_list(self, mood: Any = "", limit: int = 10, *, origin: Any = "") -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured.", "error_kind": "config"}
        params = {
            "select": "id,content,title,mood,origin,created_at",
            "order": "created_at.desc",
            "limit": str(max(1, min(int(limit or 10), 50))),
        }
        mood_key = str(mood or "").strip()
        if mood_key:
            params["mood"] = f"eq.{mood_key}"
        origin_key = str(origin or "").strip()
        if origin_key:
            if origin_key not in WINDOWSILL_ORIGINS:
                return {"ok": False, "error": "unsupported windowsill origin.", "error_kind": "validation"}
            params["origin"] = f"eq.{origin_key}"
        try:
            rows = await self.supabase.query(WINDOWSILL_TABLE, params)
            return {"ok": True, "count": len(rows or []), "data": rows or []}
        except Exception as exc:
            return {
                "ok": False,
                "error": self._friendly_supabase_error(WINDOWSILL_TABLE, exc),
                "error_kind": "exception",
            }
