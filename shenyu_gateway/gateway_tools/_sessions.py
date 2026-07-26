from __future__ import annotations

from typing import Any, Optional

from ._helpers import _date_range_bounds
from ._runtime import _is_hisense_session


class SessionToolsMixin:
    async def read_heartbeat(
        self,
        session_tag: Optional[str],
        limit: int = 10,
        state: str = "all",
        order: str = "desc",
        scope: str = "auto",
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
    ) -> dict:
        if self.store is None:
            return {"ok": False, "items": [], "note": "Gateway store is not configured."}
        resolved_tag = (session_tag or "default").strip() or "default"

        state = (state or "all").strip().lower()
        if state not in {"all", "pending", "injected"}:
            state = "all"
        order = "asc" if (order or "").strip().lower() == "asc" else "desc"
        if date:
            date_from = date_to = date
        created_from = date_from or created_from
        created_to = date_to or created_to
        created_start, created_end = _date_range_bounds(created_from, created_to)
        target_session = self.store.get_session_by_tag(resolved_tag)
        scope_key = (scope or "auto").strip().lower()
        if scope_key in {"hisense", "海信"}:
            read_hisense = True
            resolved_scope = "hisense"
        elif scope_key in {"normal", "global", "default", "普通", "默认"}:
            read_hisense = False
            resolved_scope = "normal"
        else:
            read_hisense = _is_hisense_session(target_session, runtime_config=self.cfg)
            resolved_scope = "hisense" if read_hisense else "normal"
        items = self.store.read_heartbeats(
            None,
            state=state,
            limit=max(1, min(int(limit or 10), 100)),
            order=order,
            created_from=created_start,
            created_to=created_end,
            hisense=read_hisense,
        )
        for item in items:
            item["state"] = "injected" if item.get("injected_at") else "pending"
        latest_digest = "\n".join(reversed([item.get("content") or "" for item in items[:5]])) if order == "desc" else "\n".join(item.get("content") or "" for item in items[:5])
        return {
            "ok": True,
            "session_tag": resolved_tag,
            "scope": resolved_scope,
            "scope_requested": scope_key,
            "state": state,
            "order": order,
            "date": date,
            "date_from": date_from,
            "date_to": date_to,
            "count": len(items),
            "items": items,
            "latest_digest": latest_digest,
        }

    async def last_seen(self) -> Any:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        try:
            return await self.supabase.rpc("last_seen")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def recall_main_thread(self, since: Optional[str], until: Optional[str], query: Optional[str], limit: int) -> dict:
        if not self.store:
            return {"ok": False, "error": "Store not available"}
        limit = max(1, min(int(limit or 10), 30))
        all_sessions = self.store.list_sessions(limit=50)
        non_hisense = [s for s in all_sessions if not _is_hisense_session(s, runtime_config=self.cfg)]
        if not non_hisense:
            return {"ok": True, "count": 0, "data": []}
        target = non_hisense[0]
        msgs = self.store.get_recent_dialogue_messages(target["id"], limit=limit * 3)
        if since:
            msgs = [m for m in msgs if (m.get("created_at") or "") >= since]
        if until:
            msgs = [m for m in msgs if (m.get("created_at") or "") <= until]
        if query and query.strip():
            keyword = query.strip().lower()
            msgs = [m for m in msgs if keyword in (m.get("content") or "").lower()]
        msgs = msgs[-limit:]
        data = [{"role": m["role"], "content": (m.get("content") or "")[:500], "at": m.get("created_at")} for m in msgs]
        return {"ok": True, "session_tag": target.get("session_tag"), "count": len(data), "data": data}
