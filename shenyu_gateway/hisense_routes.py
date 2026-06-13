from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from .gateway_tools import GatewayToolService
from .runtime import iso_now as _iso_now
from .sessions import SessionManager


@dataclass(frozen=True)
class HisenseRouteDeps:
    cfg: Any
    get_supabase_client: Callable[[], Any]
    require_session_store: Callable[[], Any]
    context_builder: Callable[[Any, SessionManager, GatewayToolService], Any]
    is_hisense_session: Callable[[Optional[dict]], bool]


def build_hisense_router(deps: HisenseRouteDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/hisense/preview")
    async def hisense_preview():
        store = deps.require_session_store()
        sessions_mgr = SessionManager(store, deps.cfg)
        tools = GatewayToolService()
        builder = deps.context_builder(store, sessions_mgr, tools)
        fake_session = {
            "id": "hisense-preview",
            "session_tag": "hisense-preview",
            "client_name": deps.cfg.hisense_client_name,
            "message_count": 0,
        }
        package = await builder.build_context_package(
            fake_session,
            current_user_text="",
            is_first_turn=True,
            cold_start_snapshot=None,
            client_name=deps.cfg.hisense_client_name,
            consume_heartbeat_pending=False,
        )
        layers = builder.render_layered_additions(package)
        return {
            "config": {
                "hisense_client_name": deps.cfg.hisense_client_name,
                "hisense_heartbeat_limit": deps.cfg.hisense_heartbeat_limit,
                "hisense_notebook_limit": deps.cfg.hisense_notebook_limit,
            },
            "package": {
                "heartbeat_digest": package.get("heartbeat_digest", ""),
                "hisense_heartbeat_digest": package.get("hisense_heartbeat_digest", ""),
                "calendar_context": package.get("calendar_context", {}),
                "notebook_items": package.get("notebook_items", []),
                "last_wake_recap": package.get("last_wake_recap", ""),
            },
            "rendered_slow_layer": layers.get("slow", ""),
            "rendered_heartbeat_layer": layers.get("heartbeat", ""),
        }

    @router.get("/api/hisense/notebook")
    async def hisense_notebook_list(type: Optional[str] = None, status: str = "active", limit: int = 50):
        supabase_client = deps.get_supabase_client()
        if not supabase_client:
            raise HTTPException(status_code=503, detail="Supabase not configured")
        params: dict[str, str] = {
            "order": "pinned.desc,updated_at.desc",
            "limit": str(max(1, min(int(limit or 50), 100))),
            "status": f"eq.{status}",
            "select": "id,type,content,tags,status,pinned,metadata,session_tag,created_at,updated_at",
        }
        if type:
            params["type"] = f"eq.{type}"
        rows = await supabase_client.query("shenyu_notebook", params)
        return {"ok": True, "count": len(rows or []), "data": rows or []}

    @router.post("/api/hisense/notebook")
    async def hisense_notebook_create(request: Request):
        supabase_client = deps.get_supabase_client()
        if not supabase_client:
            raise HTTPException(status_code=503, detail="Supabase not configured")
        body = await request.json()
        content = (body.get("content") or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="content is required")
        data: dict[str, Any] = {
            "type": body.get("type", "note"),
            "content": content,
            "status": body.get("status", "active"),
        }
        if body.get("tags"):
            data["tags"] = body["tags"]
        if body.get("metadata"):
            data["metadata"] = body["metadata"]
        result = await supabase_client.insert("shenyu_notebook", data)
        return {"ok": True, "data": result}

    @router.patch("/api/hisense/notebook/{item_id}")
    async def hisense_notebook_update(item_id: str, request: Request):
        supabase_client = deps.get_supabase_client()
        if not supabase_client:
            raise HTTPException(status_code=503, detail="Supabase not configured")
        body = await request.json()
        update_data: dict[str, Any] = {}
        for field in ("content", "status", "type", "tags", "metadata", "pinned"):
            if field in body:
                update_data[field] = body[field]
        if not update_data:
            raise HTTPException(status_code=400, detail="Nothing to update")
        update_data["updated_at"] = _iso_now()
        result = await supabase_client.update("shenyu_notebook", match={"id": item_id}, data=update_data)
        return {"ok": True, "data": result}

    @router.delete("/api/hisense/notebook/{item_id}")
    async def hisense_notebook_delete(item_id: str):
        supabase_client = deps.get_supabase_client()
        if not supabase_client:
            raise HTTPException(status_code=503, detail="Supabase not configured")
        result = await supabase_client.delete("shenyu_notebook", match={"id": item_id})
        return {"ok": True, "data": result}

    @router.get("/api/hisense/sessions")
    async def hisense_sessions(limit: int = 20):
        store = deps.require_session_store()
        all_sessions = store.list_sessions(limit=200)
        hisense_sessions = [
            session for session in all_sessions
            if deps.is_hisense_session(session)
        ][:max(1, min(int(limit or 20), 50))]
        for item in hisense_sessions:
            item["heartbeat_count"] = item.get("hisense_heartbeat_count", 0)
        return {"sessions": hisense_sessions, "count": len(hisense_sessions)}

    return router
