from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .gateway_tools import GatewayToolService
from .mem_notes import MemNoteService
from .memory_graph import MemoryGraphService
from .recall import RecallIndexService
from .request_logs import (
    _finalize_stale_tool_stream_logs,
    _http_request_diagnostics,
    _public_log_detail,
    _retain_request_log_payloads,
)
from .room_newspaper import RoomNewspaperService, source_catalog
from .runtime import iso_now as _iso_now, logger
from .schemas import (
    ColdStartPreviewRequest,
    DrawerNoteCreateRequest,
    DrawerNoteMarkReadRequest,
    HeartbeatCreateRequest,
    HeartbeatDeleteRequest,
    MemNoteBulkPatch,
    MemNotePatch,
    MemoryGraphAliasCreate,
    MemoryGraphBackfillRequest,
    MemoryGraphEntityCreate,
    MemoryGraphEntityPatch,
    MemoryGraphRecallPreviewRequest,
    MemoryGraphRelationCreate,
    MemoryGraphRelationPatch,
    MemoryGraphSourceEntitiesPut,
    StarConnectRequest,
    StarConstantRequest,
    StarCreateRequest,
    StarFeedbackRequest,
    StarSceneBackfillRequest,
    StarScenesRequest,
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


def build_gateway_admin_router(deps: GatewayAdminRouteDeps) -> APIRouter:
    router = APIRouter()
    cfg = deps.cfg

    @router.get("/api/gateway/tools")
    async def gateway_tools():
        return {"tools": gateway_native_tools(cfg)}

    @router.get("/api/gateway/tool-errors")
    async def tool_errors(limit: int = 50, kind: Optional[str] = None):
        store = deps.require_session_store()
        return {"errors": store.list_tool_errors(limit=limit, kind=kind)}

    @router.get("/api/gateway/context/preview")
    async def context_preview(session_tag: Optional[str] = None):
        store = deps.require_session_store()
        builder = deps.context_builder(store, SessionManager(store, cfg), GatewayToolService())
        return await builder.preview(session_tag=session_tag)

    @router.get("/api/gateway/context/preview/room")
    async def context_preview_room(session_tag: Optional[str] = None):
        store = deps.require_session_store()
        builder = deps.context_builder(store, SessionManager(store, cfg), GatewayToolService())
        return await builder.preview_room(session_tag=session_tag)

    @router.get("/api/gateway/room/traces")
    async def room_traces(limit: int = 20):
        store = deps.require_session_store()
        traces = store.recent_room_traces(limit=min(limit, 100))
        import json as _json
        items = []
        for t in traces:
            detail = t.get("detail_json")
            if isinstance(detail, str):
                try:
                    detail = _json.loads(detail)
                except Exception:
                    pass
            items.append({
                "id": t.get("id"),
                "session_id": t.get("session_id"),
                "action": t.get("action"),
                "detail": detail,
                "scribble": t.get("scribble"),
                "created_at": t.get("created_at"),
            })
        return {"traces": items, "count": len(items)}

    @router.get("/api/gateway/room/drawer-notes")
    async def list_drawer_notes(limit: int = 20, unread_only: bool = False):
        store = deps.require_session_store()
        notes = store.list_drawer_notes(limit=min(limit, 100), unread_only=unread_only)
        return {"notes": notes, "count": len(notes), "unread": store.drawer_note_count_unread()}

    @router.post("/api/gateway/room/drawer-notes")
    async def create_drawer_note(body: DrawerNoteCreateRequest):
        store = deps.require_session_store()
        content = (body.content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="Content is required.")
        if len(content) > 2000:
            raise HTTPException(status_code=400, detail="Content is too long.")
        note_id = store.add_drawer_note(content)
        return {"ok": True, "id": note_id}

    @router.post("/api/gateway/room/drawer-notes/read")
    async def mark_drawer_notes_read(body: DrawerNoteMarkReadRequest):
        store = deps.require_session_store()
        if not body.ids:
            raise HTTPException(status_code=400, detail="No ids provided.")
        count = store.mark_drawer_notes_read(body.ids)
        return {"ok": True, "marked": count}

    @router.get("/api/gateway/room/scribbles")
    async def list_room_scribbles(limit: int = 20):
        store = deps.require_session_store()
        scribbles = store.recent_room_scribbles(limit=min(limit, 100))
        return {"scribbles": scribbles, "count": len(scribbles)}

    @router.get("/api/gateway/room/pins")
    async def list_room_pins(include_done: bool = False):
        store = deps.require_session_store()
        pins = store.list_room_pins(include_done=include_done)
        return {"pins": pins, "count": len(pins)}

    @router.get("/api/gateway/room/newspapers")
    async def list_room_newspapers(limit: int = 8):
        store = deps.require_session_store()
        issues = store.list_room_newspaper_issues(limit=min(max(limit, 1), 30))
        return {"issues": issues, "count": len(issues), "sources": source_catalog()}

    @router.post("/api/gateway/room/newspapers/generate")
    async def generate_room_newspaper():
        store = deps.require_session_store()
        service = RoomNewspaperService(cfg, store)
        try:
            issue = await service.generate_draft()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True, "issue": issue}

    @router.post("/api/gateway/room/newspapers/{issue_id}/publish")
    async def publish_room_newspaper(issue_id: str):
        store = deps.require_session_store()
        issue = store.publish_room_newspaper_issue(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="Draft newspaper issue not found.")
        return {"ok": True, "issue": issue}

    @router.post("/api/gateway/room/newspapers/{issue_id}/discard")
    async def discard_room_newspaper(issue_id: str):
        store = deps.require_session_store()
        if not store.discard_room_newspaper_issue(issue_id):
            raise HTTPException(status_code=404, detail="Draft newspaper issue not found.")
        return {"ok": True}

    @router.get("/api/gateway/overview")
    async def gateway_overview():
        store = deps.require_session_store()
        return {
            "overview": store.gateway_overview(),
            "retention": {
                "message_retention": cfg.gateway_message_retention,
                "context_snapshot_retention": cfg.gateway_context_snapshot_retention,
                "cold_start_retention": cfg.gateway_cold_start_retention,
                "request_log_retention": getattr(cfg, "gateway_request_log_retention", 200),
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
                "persistent_count": store.request_log_count(),
                "persistent_capacity": getattr(cfg, "gateway_request_log_retention", 200),
                "http_requests": _http_request_diagnostics(),
                "latest": {
                    "id": latest_log.get("id"),
                    "request_id": latest_log.get("request_id"),
                    "status": latest_log.get("status"),
                    "stage": latest_log.get("stage"),
                    "finish_reason": latest_log.get("finish_reason"),
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
            message_limit=body.message_limit,
            persist=body.persist,
        )

    async def _build_cold_start_preview(
        *,
        target_session_tag: Optional[str],
        source_session_tag: Optional[str],
        current_message_count: Optional[int],
        message_limit: Optional[int] = None,
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
        reason = "next_request" if target_is_next_request else "new_window"
        skip_reason = None
        if target_session:
            exclude_session_id = target_session["id"]
            if preview_current_message_count is None:
                latest_windows = store.get_recent_raw_request_windows(target_session["id"], limit=1)
                if latest_windows:
                    preview_current_message_count = int(latest_windows[0].get("message_count") or 0)
        sources = []
        target_messages = max(1, min(int(message_limit), 500)) if message_limit else (
            cfg.max_client_messages or cfg.cold_start_message_limit or 8
        )
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
                    since=None,
                )
                if resolved_source:
                    sources = store.latest_session_context(
                        resolved_source["session_tag"],
                        limit_messages=target_messages,
                        since=None,
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
                max_injections=1,
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
                "requested_message_limit": message_limit,
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
        all_rows: bool = False,
        session_tag: Optional[str] = None,
        q: str = "",
        mem_type: Optional[str] = None,
        memory_kind: Optional[str] = None,
    ):
        result = await MemNoteService(cfg, deps.get_supabase_client()).list_notes(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            mem_type=mem_type,
            memory_kind=memory_kind,
            all_rows=all_rows,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "mem note query failed")
        return result

    @router.patch("/api/gateway/mem-notes/bulk")
    async def bulk_update_mem_notes(body: MemNoteBulkPatch):
        return await GatewayToolService(
            runtime_config=cfg,
            supabase=deps.get_supabase_client(),
            store=None,
        ).bulk_update_mem_notes(
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
        result = await GatewayToolService(
            runtime_config=cfg,
            supabase=deps.get_supabase_client(),
            store=None,
        ).update_mem_note(note_id, patch)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "mem note update failed")
        return result

    @router.delete("/api/gateway/mem-notes/{note_id}")
    async def delete_mem_note(note_id: str):
        result = await GatewayToolService(
            runtime_config=cfg,
            supabase=deps.get_supabase_client(),
            store=None,
        ).delete_mem_note(note_id)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "mem note delete failed")
        return result

    def memory_graph_service() -> MemoryGraphService:
        return MemoryGraphService(deps.get_supabase_client())

    async def graph_mutation(awaitable):
        try:
            result = await awaitable
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"memory graph is not ready: {exc}") from exc
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "memory graph operation failed")
        return result

    @router.get("/api/gateway/memory-graph")
    async def get_memory_graph(
        q: str = "",
        entity_type: Optional[str] = None,
        include_archived: bool = False,
    ):
        return await memory_graph_service().snapshot(
            query=q,
            entity_type=entity_type,
            include_archived=include_archived,
        )

    @router.post("/api/gateway/memory-graph/entities")
    async def create_memory_graph_entity(body: MemoryGraphEntityCreate):
        return await graph_mutation(memory_graph_service().create_entity(**body.model_dump()))

    @router.patch("/api/gateway/memory-graph/entities/{entity_id}")
    async def update_memory_graph_entity(entity_id: str, body: MemoryGraphEntityPatch):
        return await graph_mutation(
            memory_graph_service().update_entity(entity_id, body.model_dump(exclude_unset=True))
        )

    @router.post("/api/gateway/memory-graph/entities/{entity_id}/aliases")
    async def create_memory_graph_alias(entity_id: str, body: MemoryGraphAliasCreate):
        return await graph_mutation(
            memory_graph_service().add_alias(entity_id, **body.model_dump())
        )

    @router.delete("/api/gateway/memory-graph/aliases/{alias_id}")
    async def delete_memory_graph_alias(alias_id: str):
        return await graph_mutation(memory_graph_service().delete_alias(alias_id))

    @router.post("/api/gateway/memory-graph/relations")
    async def create_memory_graph_relation(body: MemoryGraphRelationCreate):
        return await graph_mutation(memory_graph_service().create_relation(**body.model_dump()))

    @router.patch("/api/gateway/memory-graph/relations/{relation_id}")
    async def update_memory_graph_relation(relation_id: str, body: MemoryGraphRelationPatch):
        return await graph_mutation(
            memory_graph_service().update_relation(relation_id, body.model_dump(exclude_unset=True))
        )

    @router.get("/api/gateway/memory-graph/sources/{source_table}/{source_id}")
    async def get_memory_graph_source_entities(source_table: str, source_id: str):
        return await graph_mutation(memory_graph_service().source_entities(source_table, source_id))

    @router.put("/api/gateway/memory-graph/sources")
    async def replace_memory_graph_source_entities(body: MemoryGraphSourceEntitiesPut):
        return await graph_mutation(
            memory_graph_service().replace_manual_source_entities(**body.model_dump())
        )

    @router.post("/api/gateway/memory-graph/backfill")
    async def backfill_memory_graph(body: MemoryGraphBackfillRequest):
        return await graph_mutation(
            memory_graph_service().backfill_from_recall_index(max_sources=body.max_sources)
        )

    @router.post("/api/gateway/memory-graph/recall-preview")
    async def preview_memory_graph_recall(body: MemoryGraphRecallPreviewRequest):
        query = body.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail="query is required")
        # This intentionally bypasses GatewayToolService: no Mem counters,
        # context state, auto-sync, or graph backfill may change in preview.
        return await RecallIndexService(deps.get_supabase_client(), cfg=cfg).recall(
            query,
            limit=body.limit,
            auto_sync=False,
            include_trace=True,
        )

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
            chords=body.chords or None,
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

    @router.post("/api/gateway/stars/backfill-scenes")
    async def backfill_star_scenes(body: StarSceneBackfillRequest, request: Request):
        result = await StarService(cfg, deps.get_supabase_client()).backfill_scenes(
            limit=body.limit,
            http_client=request.app.state.http,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star scene backfill failed")
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

    @router.patch("/api/gateway/stars/{star_id}/scenes")
    async def set_star_scenes(star_id: str, body: StarScenesRequest):
        result = await StarService(cfg, deps.get_supabase_client()).set_scenes(star_id, body.scenes)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "star scenes update failed")
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
        return {
            "ok": True,
            "session_tag": session_tag,
            "scope": "local_sqlite_session",
            "external_archives_deleted": False,
            "deleted": deleted,
        }

    @router.get("/api/gateway/logs")
    async def gateway_logs(limit: int = 30):
        _finalize_stale_tool_stream_logs()
        retention = getattr(cfg, "gateway_request_log_retention", 200)
        limit = max(1, min(int(limit or 30), retention))
        live_logs = list(deps.request_logs)
        try:
            persisted_logs = deps.require_session_store().list_request_logs(limit=limit)
        except Exception:
            logger.warning("Failed to read persisted request logs", exc_info=True)
            persisted_logs = []
        merged_logs = {
            str(item.get("id") or item.get("request_id")): item
            for item in persisted_logs
            if item.get("id") or item.get("request_id")
        }
        for item in live_logs:
            key = str(item.get("id") or item.get("request_id") or "")
            if key:
                merged_logs[key] = item
        logs = sorted(
            merged_logs.values(),
            key=lambda item: str(item.get("timestamp") or ""),
            reverse=True,
        )[:limit]
        return {"logs": [
            {
                "id": item.get("id") or item.get("request_id") or "unknown",
                "request_id": item.get("request_id"),
                "timestamp": item.get("timestamp") or "",
                "last_activity_at": item.get("last_activity_at"),
                "stage": item.get("stage"),
                "model": item.get("model") or "unknown",
                "client_model": item.get("client_model") or item.get("model") or "unknown",
                "upstream_model": item.get("upstream_model") or item.get("model") or "unknown",
                "model_mapped": item.get("model_mapped", False),
                "stream": item.get("stream", False),
                "session_tag": item.get("session_tag"),
                "is_first_turn": item.get("is_first_turn", False),
                "is_room": item.get("is_room", False),
                "room_charge": item.get("room_charge"),
                "original_messages_count": item.get("original_messages_count", 0),
                "prepared_messages_count": item.get("prepared_messages_count", 0),
                "client_message_window": item.get("client_message_window"),
                "memory_island": item.get("memory_island"),
                "memory_island_version": item.get("memory_island_version"),
                "cold_start": item.get("cold_start"),
                "system_additions_preview": item.get("system_additions_preview", ""),
                "system_additions_chars": item.get("system_additions_chars"),
                "tools_count": item.get("tools_count", 0),
                "tool_names": item.get("tool_names") or [],
                "has_internal_tools": item.get("has_internal_tools", False),
                "upstream_url": item.get("upstream_url", ""),
                "upstream_scope": item.get("upstream_scope", "default"),
                "prompt_cache": item.get("prompt_cache"),
                "request_payloads_retained": item.get("request_payloads_retained", False),
                "upstream_payload_summary": item.get("upstream_payload_summary"),
                "usage": item.get("usage"),
                "cache_usage": item.get("cache_usage"),
                "finish_reason": item.get("finish_reason"),
                "internal_tool_rounds": [
                    {
                        key: value
                        for key, value in round_item.items()
                        if key in {
                            "round", "messages_count", "stream", "usage", "finish_reason", "final",
                            "response_preview", "upstream_duration_ms", "cache_usage", "tool_calls_count",
                            "gateway_tool_calls", "tools", "upstream_payload_summary", "prompt_cache",
                            "anthropic_thinking",
                        }
                    }
                    for round_item in (item.get("internal_tool_rounds") or [])
                ],
                "timeline_tail": item.get("timeline_tail") or (item.get("timeline") or [])[-8:],
                "slow_phases": item.get("slow_phases") or [],
                "empty_visible_response_fallback": item.get("empty_visible_response_fallback", False),
                "empty_visible_response_fallback_detail": item.get("empty_visible_response_fallback_detail"),
                "status": item.get("status", "unknown"),
                "duration_ms": item.get("duration_ms", 0),
                "error": item.get("error"),
                "response_preview": item.get("response_preview"),
            }
            for item in logs
        ]}

    @router.get("/api/gateway/logs/{log_id}")
    async def gateway_log_detail(log_id: str):
        _finalize_stale_tool_stream_logs()
        for item in deps.request_logs:
            if item["id"] == log_id or item.get("request_id") == log_id:
                return _public_log_detail(item)
        try:
            persisted = deps.require_session_store().get_request_log(log_id)
        except Exception:
            logger.warning("Failed to read persisted request log id=%s", log_id, exc_info=True)
            persisted = None
        if persisted:
            return _public_log_detail(persisted)
        raise HTTPException(status_code=404, detail="Log not found")

    return router
