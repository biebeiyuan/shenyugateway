from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .gateway_tools import GatewayToolService
from .mem_notes import MemNoteService
from .request_logs import _finalize_stale_tool_stream_logs, _http_request_diagnostics, _retain_request_log_payloads
from .runtime import iso_now as _iso_now
from .schemas import (
    ColdStartPreviewRequest,
    HeartbeatCreateRequest,
    HeartbeatDeleteRequest,
    MemNoteBulkPatch,
    MemNotePatch,
    StarConnectRequest,
    StarConstantRequest,
    StarCreateRequest,
    StarFeedbackRequest,
    SessionDeleteRequest,
)
from .sessions import SessionManager
from .stars import StarService
from .store import NEXT_REQUEST_COLD_START_TAG
from .tool_registry import gateway_native_tools


@dataclass(frozen=True)
class GatewayAdminRouteDeps:
    cfg: Any
    get_supabase_client: Callable[[], Any]
    get_session_store: Callable[[], Any]
    require_session_store: Callable[[], Any]
    context_builder: Callable[[Any, SessionManager, GatewayToolService], Any]
    upstream_for_hisense: Callable[[bool], dict[str, str]]
    prune_runtime_state: Callable[..., dict[str, int]]
    cold_start_idle_minutes: Callable[[dict], float]
    is_hisense_session: Callable[[Optional[dict]], bool]
    now: Callable[[], Any]
    request_logs: Any


def _public_log_detail(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not str(key).startswith("_")}


def build_gateway_admin_router(deps: GatewayAdminRouteDeps) -> APIRouter:
    router = APIRouter()
    cfg = deps.cfg

    @router.get("/api/gateway/tools")
    async def gateway_tools():
        return {"tools": gateway_native_tools(cfg)}

    @router.get("/api/gateway/tool-errors")
    async def tool_errors(limit: int = 50):
        store = deps.require_session_store()
        return {"errors": store.list_tool_errors(limit=limit)}

    @router.get("/api/gateway/context/preview")
    async def context_preview(session_tag: Optional[str] = None):
        store = deps.require_session_store()
        builder = deps.context_builder(store, SessionManager(store, cfg), GatewayToolService())
        return await builder.preview(session_tag=session_tag)

    @router.get("/api/gateway/overview")
    async def gateway_overview():
        store = deps.require_session_store()
        return {
            "overview": store.gateway_overview(),
            "retention": {
                "message_retention": cfg.gateway_message_retention,
                "context_snapshot_retention": cfg.gateway_context_snapshot_retention,
                "cold_start_retention": cfg.gateway_cold_start_retention,
                "heartbeat_retention": "keep",
            },
            "cold_start": {
                "enabled": cfg.enable_cold_start,
                "message_limit": cfg.cold_start_message_limit,
                "idle_minutes": cfg.cold_start_idle_minutes,
            },
        }

    @router.get("/api/gateway/debug")
    async def gateway_debug():
        store = deps.require_session_store()
        default_upstream = deps.upstream_for_hisense(False)
        hisense_upstream = deps.upstream_for_hisense(True)
        tools = gateway_native_tools(cfg)
        logs = list(deps.request_logs)
        latest_log = logs[0] if logs else None
        latest_error = next((item for item in logs if item.get("status") == "error"), None)
        return {
            "ok": True,
            "generated_at": _iso_now(),
            "runtime": {
                "config": cfg.to_dict(),
                "store_ready": deps.get_session_store() is not None,
                "supabase_ready": deps.get_supabase_client() is not None,
                "request_payloads_retained": _retain_request_log_payloads(),
            },
            "upstream": {
                "default": {
                    "scope": default_upstream["scope"],
                    "chat_url": default_upstream["chat_url"],
                    "protocol": default_upstream["protocol"],
                    "api_key_configured": bool(default_upstream["api_key"]),
                },
                "hisense": {
                    "scope": hisense_upstream["scope"],
                    "chat_url": hisense_upstream["chat_url"],
                    "protocol": hisense_upstream["protocol"],
                    "api_key_configured": bool(hisense_upstream["api_key"]),
                },
            },
            "tools": {
                "mode": cfg.gateway_tool_mode,
                "count": len(tools),
                "names": [tool.get("function", {}).get("name", "") for tool in tools],
                "upstream_tools_enabled": cfg.enable_upstream_tools,
                "gateway_tools_enabled": cfg.enable_gateway_tools,
                "supabase_tools_enabled": cfg.expose_supabase_tools,
                "mem0_tools_enabled": cfg.enable_mem0_management_tools,
            },
            "store": {
                "overview": store.gateway_overview(),
                "db_path": cfg.gateway_db_path,
                "retention": {
                    "message_retention": cfg.gateway_message_retention,
                    "context_snapshot_retention": cfg.gateway_context_snapshot_retention,
                    "cold_start_retention": cfg.gateway_cold_start_retention,
                },
            },
            "logs": {
                "count": len(logs),
                "capacity": getattr(deps.request_logs, "maxlen", None),
                "http_requests": _http_request_diagnostics(),
                "latest": {
                    "id": latest_log.get("id"),
                    "request_id": latest_log.get("request_id"),
                    "status": latest_log.get("status"),
                    "stage": latest_log.get("stage"),
                    "timestamp": latest_log.get("timestamp"),
                    "last_activity_at": latest_log.get("last_activity_at"),
                    "tools_count": latest_log.get("tools_count"),
                    "duration_ms": latest_log.get("duration_ms"),
                } if latest_log else None,
                "latest_error": {
                    "id": latest_error.get("id"),
                    "request_id": latest_error.get("request_id"),
                    "timestamp": latest_error.get("timestamp"),
                    "error": latest_error.get("error"),
                } if latest_error else None,
            },
        }

    @router.post("/api/gateway/prune")
    async def prune_gateway_runtime():
        store = deps.require_session_store()
        deleted = deps.prune_runtime_state()
        return {"ok": True, "deleted": deleted, "overview": store.gateway_overview()}

    @router.post("/api/gateway/dedupe-messages")
    async def dedupe_gateway_messages():
        store = deps.require_session_store()
        deleted = store.dedupe_messages()
        return {"ok": True, "deleted": deleted, "overview": store.gateway_overview()}

    @router.get("/api/gateway/cold-start/preview")
    async def cold_start_preview(
        session_tag: Optional[str] = None,
        source_session_tag: Optional[str] = None,
        current_message_count: Optional[int] = None,
        persist: bool = True,
    ):
        return await _build_cold_start_preview(
            target_session_tag=session_tag,
            source_session_tag=source_session_tag,
            current_message_count=current_message_count,
            persist=persist,
        )

    @router.post("/api/gateway/cold-start/preview")
    async def cold_start_preview_post(body: ColdStartPreviewRequest):
        return await _build_cold_start_preview(
            target_session_tag=body.target_session_tag,
            source_session_tag=body.source_session_tag,
            current_message_count=body.current_message_count,
            persist=body.persist,
        )

    async def _build_cold_start_preview(
        *,
        target_session_tag: Optional[str],
        source_session_tag: Optional[str],
        current_message_count: Optional[int],
        persist: bool,
    ):
        store = deps.require_session_store()
        preview_current_message_count = None if current_message_count is None else max(0, int(current_message_count or 0))
        target_tag = (target_session_tag or NEXT_REQUEST_COLD_START_TAG).strip() or NEXT_REQUEST_COLD_START_TAG
        target_is_next_request = target_tag == NEXT_REQUEST_COLD_START_TAG
        explicit_source_tag = (source_session_tag or "").strip()
        same_source = explicit_source_tag == "__same__"
        auto_source = not explicit_source_tag or explicit_source_tag == "__auto__"
        source_tag = target_tag if same_source else ("" if auto_source else explicit_source_tag)
        target_session = None if target_is_next_request else store.get_session_by_tag(target_tag)
        exclude_session_id = None
        since = None
        reason = "next_request" if target_is_next_request else "new_window"
        idle_minutes = None
        skip_reason = None
        if target_session:
            exclude_session_id = target_session["id"]
            idle_minutes = deps.cold_start_idle_minutes(target_session)
            if idle_minutes >= max(cfg.cold_start_idle_minutes, 1):
                since = target_session.get("last_active_at")
                reason = "stale_window_cross_activity"
            if preview_current_message_count is None:
                latest_windows = store.get_recent_raw_request_windows(target_session["id"], limit=1)
                if latest_windows:
                    preview_current_message_count = int(latest_windows[0].get("message_count") or 0)
        sources = []
        target_messages = cfg.cold_start_message_limit or cfg.max_client_messages or 8
        preview_fill_count = (
            max(int(target_messages) - preview_current_message_count, 0)
            if preview_current_message_count is not None
            else int(target_messages)
        )
        resolved_source = None
        if not cfg.enable_cold_start:
            skip_reason = "冷启动注入未启用"
        else:
            if source_tag:
                sources = store.latest_session_context(
                    source_tag,
                    limit_messages=target_messages,
                    since=None,
                )
                if sources:
                    resolved_source = {
                        "session_id": sources[0].get("session_id"),
                        "session_tag": sources[0].get("session_tag"),
                        "client_name": sources[0].get("client_name"),
                        "snapshot_at": sources[0].get("snapshot_at"),
                        "latest_user_text": sources[0].get("latest_user_text"),
                    }
            elif auto_source:
                resolved_source = store.latest_context_source_session(
                    exclude_session_id=exclude_session_id,
                    since=since,
                )
                if resolved_source:
                    sources = store.latest_session_context(
                        resolved_source["session_tag"],
                        limit_messages=target_messages,
                        since=since,
                    )
            if not sources:
                source_label = "最新老线程" if auto_source else source_tag
                skip_reason = f"没有找到可用于补足的来源快照：{source_label or '-'}"
        snapshot = None
        if persist and cfg.enable_cold_start and sources:
            if not target_session:
                target_session = store.get_or_create_session(
                    target_tag,
                    "cold-start-next-request" if target_is_next_request else "preview",
                )
            snapshot = store.write_cold_start_snapshot(
                session_id=target_session["id"],
                session_tag=target_session["session_tag"],
                reason=f"manual_preview:{reason}",
                sources=sources,
                trigger_last_active_at=(target_session or {}).get("last_active_at"),
                max_injections=max(int(target_messages or 8), 1),
            )
        return {
            "enabled": cfg.enable_cold_start,
            "reason": reason,
            "would_inject": bool(sources),
            "persisted": bool(snapshot),
            "skip_reason": None if sources else skip_reason,
            "snapshot": snapshot,
            "target_session_tag": target_tag,
            "source_session_tag": (sources[0].get("session_tag") if sources else source_tag) or None,
            "source_mode": "same" if same_source else ("auto_latest" if auto_source else "explicit"),
            "resolved_source": resolved_source,
            "sources": sources,
            "config": {
                "message_limit": cfg.cold_start_message_limit,
                "effective_message_limit": target_messages,
                "current_message_count": preview_current_message_count,
                "preview_fill_count": preview_fill_count,
                "source_snapshot_limit": int(target_messages),
                "idle_minutes": cfg.cold_start_idle_minutes,
                "target_idle_minutes": idle_minutes,
            },
        }

    @router.get("/api/gateway/mem-notes/search")
    async def mem_note_search(q: str, session_tag: Optional[str] = None, limit: int = 3):
        return await MemNoteService(cfg, deps.get_supabase_client()).search_notes(
            q,
            session_tag=session_tag,
            limit=limit,
            mark_triggered=False,
        )

    @router.get("/api/gateway/mem-notes")
    async def list_mem_notes(
        status: str = "captured",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        mem_type: Optional[str] = None,
    ):
        result = await MemNoteService(cfg, deps.get_supabase_client()).list_notes(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            mem_type=mem_type,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "mem note query failed")
        return result

    @router.patch("/api/gateway/mem-notes/bulk")
    async def bulk_update_mem_notes(body: MemNoteBulkPatch):
        return await MemNoteService(cfg, deps.get_supabase_client()).bulk_update_notes(
            ids=body.ids,
            patch=body.patch,
            updates=body.updates,
            use_suggestions=body.use_suggestions,
        )

    @router.patch("/api/gateway/mem-notes/{note_id}")
    async def update_mem_note(note_id: str, body: MemNotePatch):
        patch = {
            key: getattr(body, key)
            for key in body.model_fields_set
        }
        result = await MemNoteService(cfg, deps.get_supabase_client()).update_note(note_id, patch)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "mem note update failed")
        return result

    @router.delete("/api/gateway/mem-notes/{note_id}")
    async def delete_mem_note(note_id: str):
        result = await MemNoteService(cfg, deps.get_supabase_client()).delete_note(note_id)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "mem note delete failed")
        return result

    @router.get("/api/gateway/stars")
    async def list_stars(
        status: str = "active",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        reviewed: str = "all",
    ):
        result = await StarService(cfg, deps.get_supabase_client()).list_stars(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            reviewed=reviewed,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star query failed")
        return result

    @router.get("/api/gateway/stars/search")
    async def search_stars(q: str, session_tag: Optional[str] = None, limit: int = 10, log_run: bool = False):
        result = await StarService(cfg, deps.get_supabase_client()).search_stars(
            q,
            session_tag=session_tag,
            limit=limit,
            log_run=log_run,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star search failed")
        return result

    @router.get("/api/gateway/stars/graph")
    async def graph_stars(status: str = "active", limit: int = 250, session_tag: Optional[str] = None):
        result = await StarService(cfg, deps.get_supabase_client()).graph(
            status=status,
            limit=limit,
            session_tag=session_tag,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star graph failed")
        return result

    @router.post("/api/gateway/stars")
    async def create_star(body: StarCreateRequest):
        result = await StarService(cfg, deps.get_supabase_client()).create_star(
            body.content,
            chord=body.chord or "",
            session_tag=body.session_tag,
            status=body.status,
            is_constant=body.is_constant,
            source_model="admin:star-create",
            metadata=body.metadata,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star create failed")
        return result

    @router.post("/api/gateway/stars/review")
    async def review_stars(limit_new: int = 4, candidates_per_star: int = 2, total_candidate_limit: int = 8, session_tag: Optional[str] = None):
        result = await StarService(cfg, deps.get_supabase_client()).review(
            limit_new=limit_new,
            candidates_per_star=candidates_per_star,
            total_candidate_limit=total_candidate_limit,
            session_tag=session_tag,
            review_scope="admin",
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star review failed")
        return result

    @router.post("/api/gateway/stars/feedback")
    async def star_feedback(body: StarFeedbackRequest):
        result = await StarService(cfg, deps.get_supabase_client()).feedback(
            feedback=body.feedback,
            run_id=body.run_id,
            candidate_id=body.candidate_id,
            candidate_star_id=body.candidate_star_id,
            expected_star_id=body.expected_star_id,
            scored_by=body.scored_by,
            note=body.note,
            metadata=body.metadata,
            items=[item.model_dump() for item in body.items] if body.items else None,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star feedback failed")
        return result

    @router.post("/api/gateway/stars/connect")
    async def connect_stars(body: StarConnectRequest):
        result = await StarService(cfg, deps.get_supabase_client()).connect_constellation(
            body.star_ids,
            name=body.name or "",
            relation_type=body.relation_type,
            scored_by=body.scored_by,
            note=body.note,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star connect failed")
        return result

    @router.patch("/api/gateway/stars/{star_id}/constant")
    async def mark_constant_star(star_id: str, body: StarConstantRequest):
        result = await StarService(cfg, deps.get_supabase_client()).mark_constant(star_id, body.is_constant)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star constant update failed")
        return result

    @router.get("/api/gateway/legacy-atomic-memories")
    async def legacy_atomic_memories(limit: int = 30, session_tag: Optional[str] = None, q: str = ""):
        result = await MemNoteService(cfg, deps.get_supabase_client()).legacy_atomic_memories(
            limit=limit,
            session_tag=session_tag,
            q=q,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "legacy atomic query failed")
        return result

    @router.get("/api/gateway/sessions")
    async def list_gateway_sessions(limit: int = 100, q: str = ""):
        store = deps.require_session_store()
        sessions = store.list_sessions(limit=limit, query=q)
        return {"sessions": sessions, "limit": max(1, min(int(limit or 100), 500)), "query": q}

    @router.get("/api/gateway/sessions/{session_tag}")
    async def session_detail(session_tag: str, messages_limit: Optional[int] = None, heartbeat_limit: int = 500):
        store = deps.require_session_store()
        session = store.get_session_by_tag(session_tag)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        window_limit = messages_limit if messages_limit is not None else 50
        messages = store.get_recent_messages(
            session["id"],
            limit=max(1, min(int(window_limit or cfg.gateway_message_retention), cfg.gateway_message_retention)),
        )
        raw_request_windows = store.get_recent_raw_request_windows(
            session["id"],
            limit=max(1, min(int(window_limit or cfg.gateway_message_retention), cfg.gateway_message_retention)),
        )
        context_snapshots = store.get_recent_context_snapshots(session["id"], limit=5)
        cold_start = store.latest_cold_start_snapshot(session["id"])
        cold_start_snapshots = store.recent_cold_start_snapshots(session["id"], limit=8)
        is_hisense = deps.is_hisense_session(session)
        heartbeats = store.read_heartbeats(
            None,
            state="all",
            limit=max(1, min(int(heartbeat_limit or 500), 500)),
            order="desc",
            hisense=is_hisense,
        )
        stats = store.get_session_stats(session["id"])
        if is_hisense:
            stats["heartbeats"] = stats.get("hisense_heartbeats", 0)
        return {
            "session": session,
            "stats": stats,
            "latest_cold_start_snapshot": cold_start,
            "context_snapshots": context_snapshots,
            "raw_request_windows": raw_request_windows,
            "cold_start_snapshots": cold_start_snapshots,
            "recent_messages": messages,
            "heartbeats": heartbeats,
            "hisense_heartbeats": heartbeats if is_hisense else [],
        }

    @router.post("/api/gateway/sessions/{session_tag}/heartbeats")
    async def create_gateway_heartbeat(session_tag: str, body: HeartbeatCreateRequest):
        store = deps.require_session_store()
        session = store.get_session_by_tag(session_tag)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        content = (body.content or "").strip()
        content = content.replace("<heartbeat>", "").replace("</heartbeat>", "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="Heartbeat content is required.")
        if len(content) > 4000:
            raise HTTPException(status_code=400, detail="Heartbeat content is too long.")
        turn_number = body.turn_number if body.turn_number is not None else int(session.get("message_count") or 0)
        item = store.append_heartbeat(
            session["id"],
            content,
            turn_number=max(0, int(turn_number or 0)),
            hisense=deps.is_hisense_session(session),
        )
        return {"ok": True, "heartbeat": item}

    @router.delete("/api/gateway/sessions/{session_tag}/heartbeats")
    async def delete_gateway_heartbeats(session_tag: str, body: HeartbeatDeleteRequest):
        store = deps.require_session_store()
        session = store.get_session_by_tag(session_tag)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        if body.delete_all and body.confirm != "GLOBAL":
            raise HTTPException(status_code=400, detail="Confirmation must be GLOBAL for delete_all.")
        deleted = store.delete_heartbeats(
            None,
            heartbeat_ids=body.ids,
            delete_all=body.delete_all,
            hisense=deps.is_hisense_session(session),
        )
        return {"ok": True, "deleted": deleted}

    @router.get("/api/gateway/heartbeats")
    async def list_gateway_heartbeats(limit: int = 500, order: str = "asc", scope: str = "normal"):
        # External contract: home-frontend reads
        # /api/gateway/heartbeats?token=...&limit=2000&order=asc&scope=normal|hisense.
        # Preserve query-token auth, limit/order/scope, and heartbeats[].content/created_at.
        store = deps.require_session_store()
        order_key = "desc" if str(order or "").lower() == "desc" else "asc"
        max_limit = max(1, min(int(limit or 500), 2000))
        scope_key = (scope or "normal").strip().lower()
        hisense = scope_key in {"hisense", "海信"}
        scope_key = "hisense" if hisense else "normal"
        heartbeats = store.get_all_heartbeats(hisense=hisense)
        if order_key == "desc":
            heartbeats = list(reversed(heartbeats))
        return {
            "ok": True,
            "scope": scope_key,
            "count": len(heartbeats),
            "limit": max_limit,
            "order": order_key,
            "heartbeats": heartbeats[:max_limit],
        }

    @router.get("/api/gateway/sessions/{session_tag}/export")
    async def export_gateway_session(session_tag: str):
        store = deps.require_session_store()
        bundle = store.export_session_bundle(session_tag)
        if not bundle:
            raise HTTPException(status_code=404, detail="Session not found.")
        filename = f"shenyu-session-{session_tag}-{deps.now().strftime('%Y%m%d-%H%M%S')}.json"
        return JSONResponse(
            content=bundle,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.delete("/api/gateway/sessions/{session_tag}")
    async def delete_gateway_session(session_tag: str, body: SessionDeleteRequest):
        store = deps.require_session_store()
        if body.confirm != session_tag:
            raise HTTPException(status_code=400, detail="Confirmation must match session_tag.")
        session = store.get_session_by_tag(session_tag)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        deleted = store.delete_session(session["id"])
        return {"ok": True, "session_tag": session_tag, "deleted": deleted}

    @router.get("/api/gateway/logs")
    async def gateway_logs(limit: int = 30):
        _finalize_stale_tool_stream_logs()
        logs = list(deps.request_logs)[:limit]
        return {"logs": [
            {
                "id": item["id"],
                "request_id": item.get("request_id"),
                "timestamp": item["timestamp"],
                "last_activity_at": item.get("last_activity_at"),
                "stage": item.get("stage"),
                "model": item["model"],
                "client_model": item.get("client_model", item["model"]),
                "upstream_model": item.get("upstream_model", item["model"]),
                "model_mapped": item.get("model_mapped", False),
                "stream": item["stream"],
                "session_tag": item["session_tag"],
                "is_first_turn": item["is_first_turn"],
                "original_messages_count": item["original_messages_count"],
                "prepared_messages_count": item["prepared_messages_count"],
                "client_message_window": item.get("client_message_window"),
                "cold_start": item.get("cold_start"),
                "system_additions_preview": item["system_additions_preview"],
                "system_additions_chars": item.get("system_additions_chars"),
                "tools_count": item["tools_count"],
                "tool_names": item["tool_names"],
                "has_internal_tools": item["has_internal_tools"],
                "upstream_url": item["upstream_url"],
                "upstream_scope": item.get("upstream_scope", "default"),
                "prompt_cache": item.get("prompt_cache"),
                "request_payloads_retained": item.get("request_payloads_retained", False),
                "upstream_payload_summary": item.get("upstream_payload_summary"),
                "usage": item.get("usage"),
                "cache_usage": item.get("cache_usage"),
                "internal_tool_rounds": len(item.get("internal_tool_rounds") or []),
                "timeline_tail": item.get("timeline_tail") or (item.get("timeline") or [])[-8:],
                "slow_phases": item.get("slow_phases") or [],
                "empty_visible_response_fallback": item.get("empty_visible_response_fallback", False),
                "empty_visible_response_fallback_detail": item.get("empty_visible_response_fallback_detail"),
                "status": item["status"],
                "duration_ms": item["duration_ms"],
                "error": item["error"],
                "response_preview": item["response_preview"],
            }
            for item in logs
        ]}

    @router.get("/api/gateway/logs/{log_id}")
    async def gateway_log_detail(log_id: str):
        _finalize_stale_tool_stream_logs()
        for item in deps.request_logs:
            if item["id"] == log_id or item.get("request_id") == log_id:
                return _public_log_detail(item)
        raise HTTPException(status_code=404, detail="Log not found")

    return router
