"""
shenyu memory gateway
OpenAI-compatible gateway with:
- optional context injection
- local SQLite session/cache layer
- namespaced native gateway tools
- upstream protocol adaptation for Anthropic / OpenAI
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from shenyu_gateway.admin_shell_routes import AdminShellRouteDeps, build_admin_shell_router
from shenyu_gateway.archive_routes import ArchiveRouteDeps, build_archive_router
from shenyu_gateway.calendar_service import CalendarService
from shenyu_gateway.calendar_routes import CalendarRouteDeps, build_calendar_router
from shenyu_gateway.chat_pipeline import ChatPipeline
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.config_routes import ConfigRouteDeps, build_config_router
from shenyu_gateway.context_builder import ContextBuilder
from shenyu_gateway.context_snapshots import write_completion_context_snapshot as _write_completion_context_snapshot
from shenyu_gateway.gateway_tools import GatewayToolService, configure_gateway_tools
from shenyu_gateway.heartbeat_archive import HeartbeatArchiveService, heartbeat_archive_worker
from shenyu_gateway.gateway_admin_routes import GatewayAdminRouteDeps, build_gateway_admin_router
from shenyu_gateway.hisense_routes import HisenseRouteDeps, build_hisense_router
from shenyu_gateway.recall import RecallIndexService
from shenyu_gateway.runtime import (
    iso_now as _iso_now,
    logger,
    now as _now,
    now_ts as _now_ts,
    persist_env as _persist_env,
)
from shenyu_gateway.response_capture import (
    clean_text_from_filter_source,
    store_heartbeat,
)
from shenyu_gateway.resident_profile import (
    HISENSE_HOME_NOTE,
    MEMORY_PRACTICE_PROFILE,
    ORIGIN_BOOK_PROFILE,
)
from shenyu_gateway.request_logs import (
    _mark_http_request_event,
    _mark_request_log_phase,
    _record_response_text,
    _record_upstream_payload,
    _request_logs,
)
from shenyu_gateway.schemas import (
    ChatRequest,
)
from shenyu_gateway.sessions import SessionManager
from shenyu_gateway.store import GatewayStore
from shenyu_gateway.supabase import SupabaseClient
from shenyu_gateway.tool_registry import (
    execute_gateway_tool,
)
from shenyu_gateway.tool_loop import (
    InternalToolLoopContext,
    _latest_user_text,
    run_internal_tool_loop as _run_internal_tool_loop_impl,
    run_internal_tool_loop_stream as _run_internal_tool_loop_stream_impl,
)
from shenyu_gateway.upstream_adapter import (
    _anthropic_to_openai_completion,
    _cache_usage_summary,
)
from shenyu_gateway.utils import clean_config_text as _clean_config_text

logging.basicConfig(level=logging.INFO)


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


from shenyu_gateway.upstream_client import (
    validate_http_url as _validate_http_url_impl,
    validate_protocol as _validate_protocol_impl,
    connect_error_detail as _connect_error_detail_impl,
    detect_protocol_for as _detect_protocol_for,
    chat_url_for as _chat_url_for,
    upstream_for_hisense as _upstream_for_hisense_impl,
    mapped_model_name as _mapped_model_name_impl,
    make_upstream_http_client as _make_upstream_http_client_impl,
    fetch_upstream_models as _fetch_upstream_models_impl,
    call_upstream_json_at as _call_upstream_json_at_impl,
    build_upstream_request as _build_upstream_request_impl,
    stream_upstream_openai_chunks as _stream_upstream_openai_chunks_impl,
)


def _validate_http_url(field_name, value, *, allow_empty=True):
    return _validate_http_url_impl(field_name, value, allow_empty=allow_empty)


def _validate_protocol(field_name, value, *, allow_empty=False):
    return _validate_protocol_impl(field_name, value, allow_empty=allow_empty)


def _connect_error_detail(chat_url, exc):
    return _connect_error_detail_impl(chat_url, exc, cfg=cfg)


from shenyu_gateway.prepare_messages import (
    cold_start_idle_minutes as _cold_start_idle_minutes_impl,
    maybe_prepare_cold_start_snapshot as _maybe_prepare_cold_start_snapshot_impl,
    prune_runtime_state as _prune_runtime_state_impl,
    inject_pending_gateway_tool_turns as _inject_pending_gateway_tool_turns_impl,
)

from shenyu_gateway.private_capture import (
    mark_context_consumed as _mark_context_consumed_impl,
    is_room_mode as _is_room_mode,
    private_capture_kinds as _private_capture_kinds,
    private_capture_fallback_text as _private_capture_fallback_text,
    finalize_assistant_private_content as _finalize_assistant_private_content,
)


def _restore_config_overrides_from_db(db_path: str) -> None:
    def load_if_present(path_text: str) -> dict[str, str]:
        path = Path(path_text)
        if not path.exists():
            return {}
        return GatewayStore(str(path)).load_config_overrides()

    try:
        initial_db_path = db_path or "./data/shenyu_gateway.db"
        overrides = load_if_present(initial_db_path)
        restored_db_path = overrides.get("GATEWAY_DB_PATH")
        if restored_db_path and Path(restored_db_path) != Path(initial_db_path):
            overrides.update(load_if_present(restored_db_path))
        for key, value in overrides.items():
            os.environ[key] = value
        if overrides:
            logger.info(
                "Applied %d config override(s) from SQLite: %s",
                len(overrides),
                ", ".join(sorted(overrides)),
            )
    except Exception:
        logger.warning("Failed to restore config overrides from SQLite", exc_info=True)


_restore_config_overrides_from_db(os.getenv("GATEWAY_DB_PATH") or "./data/shenyu_gateway.db")

cfg = RuntimeConfig()
supabase_client: Optional["SupabaseClient"] = None
session_store: Optional["GatewayStore"] = None
recall_embedding_worker_task: Optional[asyncio.Task] = None
heartbeat_archive_worker_task: Optional[asyncio.Task] = None
configure_gateway_tools(runtime_config=cfg, supabase=supabase_client, store=session_store)


def _init_supabase():
    global supabase_client
    if cfg.supabase_url and cfg.supabase_key:
        supabase_client = SupabaseClient(cfg.supabase_url, cfg.supabase_key)
    else:
        supabase_client = None
    configure_gateway_tools(supabase=supabase_client)


def _init_store():
    global session_store
    session_store = GatewayStore(cfg.gateway_db_path)
    configure_gateway_tools(store=session_store)


def _persist_env_with_store(updates: dict[str, Any]) -> None:
    _persist_env(updates, store=session_store)


def _require_session_store() -> GatewayStore:
    store = session_store
    if store is None:
        raise RuntimeError("Gateway session store is not initialized.")
    return store


def _chat_pipeline(store: GatewayStore) -> ChatPipeline:
    return ChatPipeline(
        cfg=cfg,
        store=store,
        prepare_messages=_prepare_messages,
        build_upstream_request=_build_upstream_request,
        run_internal_tool_loop=_run_internal_tool_loop,
        run_internal_tool_loop_stream=_run_internal_tool_loop_stream,
        stream_chat=_stream_chat,
        nonstream_chat=_nonstream_chat,
        upstream_for_hisense=_upstream_for_hisense,
        mapped_model_name=_mapped_model_name,
        private_capture_fallback_text=_private_capture_fallback_text,
        private_capture_kinds=_private_capture_kinds,
        finalize_assistant_private_content=_finalize_assistant_private_content,
        store_heartbeat=_store_heartbeat,
        mark_context_consumed=_mark_context_consumed,
        write_completion_context_snapshot=_write_completion_snapshot,
    )


def _calendar_service(request: Optional[Request] = None) -> CalendarService:
    return CalendarService(
        cfg=cfg,
        supabase_client=supabase_client,
        session_store=session_store,
        call_upstream_json_at=_call_upstream_json_at,
        detect_protocol_for=_detect_protocol_for,
        chat_url_for=_chat_url_for,
        request=request,
    )


def _context_builder(store: GatewayStore, sessions: SessionManager, tools: GatewayToolService) -> ContextBuilder:
    return ContextBuilder(
        store,
        sessions,
        tools,
        cfg=cfg,
        supabase_client=supabase_client,
        stable_charter_block=_stable_charter_block,
        is_hisense_client=_is_hisense_client,
    )


def _make_upstream_http_client():
    return _make_upstream_http_client_impl(cfg)


async def _recall_embedding_worker():
    if not supabase_client:
        return
    sync_enabled = bool(getattr(cfg, "enable_recall_sync_worker", True))
    embedding_enabled = bool(cfg.enable_recall_embedding_worker and cfg.enable_recall_embeddings)
    active_intervals = []
    if sync_enabled:
        active_intervals.append(int(getattr(cfg, "recall_sync_worker_interval_seconds", 900) or 900))
    if embedding_enabled:
        active_intervals.append(int(cfg.recall_embedding_worker_interval_seconds or 900))
    if not active_intervals:
        return
    interval = max(min(active_intervals), 60)
    batch_size = max(1, min(int(cfg.recall_embedding_worker_batch_size or 50), 1000))
    service = RecallIndexService(supabase_client, cfg=cfg)
    can_embed = bool(embedding_enabled and service.embedding_client and service.embedding_client.enabled)
    logger.info(
        "[RecallIndexWorker] started interval=%ss sync=%s embed=%s batch_size=%s",
        interval,
        sync_enabled,
        can_embed,
        batch_size,
    )
    try:
        while True:
            try:
                if sync_enabled:
                    sync_result = await service.rebuild(embed=False)
                    logger.info("[RecallIndexWorker] sync=%s", sync_result)
                if can_embed:
                    embedding_result = await service.embed_pending(limit=batch_size)
                    if embedding_result.get("seen"):
                        logger.info("[RecallIndexWorker] embedding=%s", embedding_result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[RecallIndexWorker] cycle failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("[RecallIndexWorker] stopped")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    global recall_embedding_worker_task, heartbeat_archive_worker_task
    _init_supabase()
    _init_store()
    if session_store:
        try:
            interrupted_logs = session_store.mark_interrupted_request_logs()
            if interrupted_logs:
                logger.info("Marked %d persisted request log(s) as interrupted after restart", interrupted_logs)
        except Exception:
            logger.warning("Failed to finalize interrupted request logs", exc_info=True)
    if (
        supabase_client
        and (
            getattr(cfg, "enable_recall_sync_worker", True)
            or (cfg.enable_recall_embedding_worker and cfg.enable_recall_embeddings)
        )
    ):
        recall_embedding_worker_task = asyncio.create_task(_recall_embedding_worker())
    if cfg.enable_heartbeat_archive and supabase_client and session_store:
        heartbeat_archive_worker_task = asyncio.create_task(
            heartbeat_archive_worker(
                HeartbeatArchiveService(session_store, supabase_client, cfg),
                cfg.heartbeat_archive_interval_seconds,
            )
        )
    # connect/write/pool 保持合理超时；read 设为 None，因为流式场景下
    # LLM 可能 thinking 很久才开始输出，读取不能有固定超时。
    app.state.http = _make_upstream_http_client()
    yield
    if recall_embedding_worker_task:
        recall_embedding_worker_task.cancel()
        try:
            await recall_embedding_worker_task
        except asyncio.CancelledError:
            pass
        recall_embedding_worker_task = None
    if heartbeat_archive_worker_task:
        heartbeat_archive_worker_task.cancel()
        try:
            await heartbeat_archive_worker_task
        except asyncio.CancelledError:
            pass
        heartbeat_archive_worker_task = None
    if supabase_client:
        await supabase_client.close()
    await app.state.http.aclose()


app = FastAPI(title="shenyu-gateway", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # External contract: home-frontend calls selected /api endpoints from these origins.
    # Keep OPTIONS preflight open and keep query-token auth working to avoid browser preflight.
    allow_origins=[
        "https://home.yuanuwuclaude.uk",
        "https://yuanuwuclaude.uk",
        "http://localhost:8005",
        "http://127.0.0.1:8005",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Shenyu-Client", "X-Shenyu-Session-Tag", "X-Shenyu-Tool-Events"],
)

ADMIN_DIST_DIR = Path(__file__).parent / "admin" / "dist"
if (ADMIN_DIST_DIR / "assets").exists():
    app.mount("/admin/assets", StaticFiles(directory=ADMIN_DIST_DIR / "assets"), name="admin-assets")

PWA_DIST_DIR = Path(__file__).parent / "pwa" / "dist"
if PWA_DIST_DIR.exists():
    app.mount("/chat", StaticFiles(directory=PWA_DIST_DIR, html=True), name="pwa-chat")


from shenyu_gateway.middleware import register_middlewares
register_middlewares(app, cfg)


def _upstream_for_hisense(is_hisense=False):
    return _upstream_for_hisense_impl(cfg, is_hisense)


def _mapped_model_name(model_name):
    return _mapped_model_name_impl(cfg, model_name)


async def verify_api_key(request: Request):
    from shenyu_gateway.auth import verify_api_key as _verify
    await _verify(request, cfg=cfg)


def _session_tag_from_request(request: Request, client_name: Optional[str] = None) -> str:
    header = request.headers.get("X-Shenyu-Session-Tag") or request.headers.get("X-Session-Tag")
    if header:
        return header.strip()
    if _is_hisense_client(client_name):
        return "hisense"
    return "default"


def _client_name_from_request(request: Request) -> str:
    return (request.headers.get("X-Shenyu-Client") or request.headers.get("X-Client-Name") or "unknown-client").strip()


def _is_hisense_client(client_name: Optional[str]) -> bool:
    target = (cfg.hisense_client_name or "").strip()
    name = (client_name or "").strip()
    if not target or not name:
        return False
    if name.casefold() == target.casefold():
        return True
    return target.casefold() == "hisense" and name == "海信"


def _is_hisense_session(session: Optional[dict]) -> bool:
    return bool(session) and _is_hisense_client(session.get("client_name"))


def _stable_charter_block() -> str:
    base = (
        "**给醒来的我：**\n"
        "这里是家。先找到她，再看我留下的东西。\n"
        "下面是我现在的手感，不是待办清单，也不是硬规矩。"
    )
    welcome_message = _clean_config_text(getattr(cfg, "wake_welcome_message", ""))
    blocks = [base]
    if welcome_message:
        blocks.append(welcome_message)
    blocks.extend(
        [
            MEMORY_PRACTICE_PROFILE,
            ORIGIN_BOOK_PROFILE,
            HISENSE_HOME_NOTE,
        ]
    )
    return "\n\n".join(block.rstrip() for block in blocks if block.strip()) + "\n"


def _cold_start_idle_minutes(session: dict) -> float:
    return _cold_start_idle_minutes_impl(session)


def _maybe_prepare_cold_start_snapshot(session, is_first_turn, current_message_count):
    return _maybe_prepare_cold_start_snapshot_impl(
        session, is_first_turn, current_message_count,
        cfg=cfg, store=_require_session_store(),
    )


def _prune_runtime_state(session_id: Optional[str] = None) -> dict[str, int]:
    return _prune_runtime_state_impl(cfg=cfg, store=session_store, session_id=session_id)


def _aggregate_cache_usage(usages: list[dict], protocol: str = "") -> dict:
    total_read = 0
    total_write = 0
    reported_input_total = 0
    read_reported = False
    write_reported = False
    input_reported = True
    normalized_input_total = 0
    total_input_reported = bool(usages)
    creation_totals: dict[str, int] = {}
    for usage in usages:
        summary = _cache_usage_summary(usage, protocol=protocol)
        total_read += summary["cache_read_input_tokens"]
        total_write += summary["cache_creation_input_tokens"]
        reported_input_total += summary["input_tokens"]
        read_reported = read_reported or summary["read_reported"]
        write_reported = write_reported or summary["write_reported"]
        input_reported = input_reported and summary["input_reported"]
        normalized_input_total += summary["total_input_tokens"]
        total_input_reported = total_input_reported and summary["total_input_reported"]
        for key, value in (summary.get("cache_creation") or {}).items():
            creation_totals[key] = creation_totals.get(key, 0) + int(value or 0)
    return {
        "cache_read_input_tokens": total_read,
        "cache_creation_input_tokens": total_write,
        "cache_creation": creation_totals,
        "hit": total_read > 0,
        "write": total_write > 0,
        "read_reported": read_reported,
        "write_reported": write_reported,
        "reported": read_reported or write_reported,
        "rounds": len(usages),
        "input_tokens": reported_input_total,
        "input_reported": input_reported,
        "total_input_tokens": normalized_input_total,
        "total_input_reported": total_input_reported,
        "cache_read_percent": (
            round(total_read * 100 / normalized_input_total, 1)
            if total_input_reported and normalized_input_total > 0 and total_read <= normalized_input_total
            else None
        ),
        "cache_prefix_reuse_percent": (
            round(total_read * 100 / (total_read + total_write), 1)
            if total_read + total_write > 0
            else None
        ),
    }


async def _fetch_upstream_models(request):
    client_name = _client_name_from_request(request)
    upstream = _upstream_for_hisense(_is_hisense_client(client_name))
    return await _fetch_upstream_models_impl(request, cfg=cfg, upstream=upstream)


async def _call_upstream_json_at(request, chat_url, payload, headers):
    return await _call_upstream_json_at_impl(request, chat_url, payload, headers, cfg=cfg)


async def _call_upstream_json(request, chat_url, payload, headers):
    return await _call_upstream_json_at(request, chat_url, payload, headers)


async def _build_upstream_request(request, body, messages_override=None, meta=None):
    return await _build_upstream_request_impl(request, body, messages_override, meta, cfg=cfg)


async def _prepare_messages(request: Request, body: ChatRequest) -> tuple[list[dict], dict]:
    from shenyu_gateway.prepare_messages import PrepareMessagesDeps, prepare_messages

    return await prepare_messages(
        request,
        body,
        PrepareMessagesDeps(
            cfg=cfg,
            store=_require_session_store(),
            supabase_client=supabase_client,
            context_builder_factory=_context_builder,
            client_name_from_request=_client_name_from_request,
            session_tag_from_request=_session_tag_from_request,
            is_hisense_client=_is_hisense_client,
            upstream_for_hisense=_upstream_for_hisense,
            maybe_prepare_cold_start_snapshot=_maybe_prepare_cold_start_snapshot,
            prune_runtime_state=_prune_runtime_state,
        ),
    )


def _inject_pending_gateway_tool_turns(messages, store, session_id):
    return _inject_pending_gateway_tool_turns_impl(messages, store, session_id)


def _mark_context_consumed(meta: dict):
    _mark_context_consumed_impl(meta, store=session_store)


def _write_completion_snapshot(meta: dict, assistant_content: str):
    return _write_completion_context_snapshot(session_store, meta, assistant_content)


def _store_heartbeat(session_id: str, session: dict, content: str):
    store_heartbeat(
        store=session_store,
        session_id=session_id,
        session=session,
        content=content,
        is_hisense_session=_is_hisense_session,
    )



async def _stream_upstream_openai_chunks(request, payload, headers, model, upstream):
    async for chunk in _stream_upstream_openai_chunks_impl(request, payload, headers, model, upstream, cfg=cfg):
        yield chunk


def _make_internal_tool_loop_context(
    request: Request,
    body: ChatRequest,
    prepared_messages: list[dict],
    meta: dict,
    log_entry: Optional[dict] = None,
    *,
    sessions: Optional[SessionManager] = None,
) -> InternalToolLoopContext:
    store = _require_session_store()
    return InternalToolLoopContext(
        request=request,
        body=body,
        prepared_messages=prepared_messages,
        meta=meta,
        log_entry=log_entry,
        cfg=cfg,
        store=store,
        sessions=sessions or SessionManager(store, cfg),
        build_upstream_request=_build_upstream_request,
        call_upstream_json=_call_upstream_json,
        stream_upstream_openai_chunks=_stream_upstream_openai_chunks,
        execute_gateway_tool=execute_gateway_tool,
        record_upstream_payload=_record_upstream_payload,
        aggregate_cache_usage=_aggregate_cache_usage,
        finalize_assistant_private_content=_finalize_assistant_private_content,
        store_heartbeat=_store_heartbeat,
        mark_context_consumed=_mark_context_consumed,
        write_completion_context_snapshot=_write_completion_snapshot,
        record_response_text=_record_response_text,
    )


async def _run_internal_tool_loop(
    request: Request,
    body: ChatRequest,
    prepared_messages: list[dict],
    meta: dict,
    log_entry: Optional[dict] = None,
) -> dict:
    ctx = _make_internal_tool_loop_context(request, body, prepared_messages, meta, log_entry)
    return await _run_internal_tool_loop_impl(ctx)


async def _run_internal_tool_loop_stream(
    request: Request,
    body: ChatRequest,
    prepared_messages: list[dict],
    meta: dict,
    log_entry: Optional[dict] = None,
):
    ctx = _make_internal_tool_loop_context(request, body, prepared_messages, meta, log_entry)
    async for chunk in _run_internal_tool_loop_stream_impl(ctx):
        yield chunk
    return


async def _stream_chat(
    request: Request, payload: dict, headers: dict, model: str, upstream: dict,
    on_complete: callable = None,
    latest_user_text: str = "",
):
    from shenyu_gateway.stream_proxy import stream_chat
    return await stream_chat(
        request, payload, headers, model, upstream,
        connect_error_detail=_connect_error_detail,
        private_capture_fallback_text=_private_capture_fallback_text,
        private_capture_kinds=_private_capture_kinds,
        on_complete=on_complete,
        latest_user_text=latest_user_text,
    )


async def _nonstream_chat(request: Request, payload: dict, headers: dict, model: str, upstream: dict):
    proto = upstream["protocol"]
    raw = await _call_upstream_json(request, upstream["chat_url"], payload, headers)

    # 诊断日志：打印上游响应中的 thinking/reasoning 字段。
    if raw.get("choices"):
        msg = raw["choices"][0].get("message", {})
        known_keys = set(msg.keys()) - {"role", "content", "tool_calls", "refusal"}
        if known_keys:
            logger.info("[CoT diagnostics] upstream message has extra keys: %s", known_keys)
        if msg.get("reasoning_content") or msg.get("reasoning"):
            logger.info("[CoT diagnostics] upstream returned reasoning content.")

    if proto == "openai":
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": _now_ts(),
            "model": model,
            "choices": raw.get("choices", []),
            "usage": raw.get("usage", {}),
        }
    return _anthropic_to_openai_completion(model, raw)


app.include_router(
    build_config_router(
        ConfigRouteDeps(
            cfg=cfg,
            validate_http_url=_validate_http_url,
            validate_protocol=_validate_protocol,
            clamp=_clamp,
            persist_env=_persist_env_with_store,
            get_supabase_client=lambda: supabase_client,
            init_supabase=_init_supabase,
            init_store=_init_store,
            make_upstream_http_client=_make_upstream_http_client,
        )
    )
)
app.include_router(
    build_gateway_admin_router(
        GatewayAdminRouteDeps(
            cfg=cfg,
            get_supabase_client=lambda: supabase_client,
            get_session_store=lambda: session_store,
            require_session_store=_require_session_store,
            context_builder=_context_builder,
            upstream_for_hisense=_upstream_for_hisense,
            prune_runtime_state=_prune_runtime_state,
            cold_start_idle_minutes=_cold_start_idle_minutes,
            is_hisense_session=_is_hisense_session,
            now=_now,
            request_logs=_request_logs,
        )
    )
)
app.include_router(
    build_calendar_router(
        CalendarRouteDeps(
            require_session_store=_require_session_store,
            calendar_service=_calendar_service,
        )
    )
)
app.include_router(
    build_hisense_router(
        HisenseRouteDeps(
            cfg=cfg,
            get_supabase_client=lambda: supabase_client,
            require_session_store=_require_session_store,
            context_builder=_context_builder,
            is_hisense_session=_is_hisense_session,
        )
    )
)
app.include_router(
    build_archive_router(
        ArchiveRouteDeps(
            get_supabase_client=lambda: supabase_client,
        )
    )
)
app.include_router(build_admin_shell_router(AdminShellRouteDeps(admin_dist_dir=ADMIN_DIST_DIR)))


@app.get("/v1/models")
async def list_models(request: Request):
    await verify_api_key(request)
    upstream_models = await _fetch_upstream_models(request)
    models = upstream_models if upstream_models else [
        {"id": "default", "object": "model", "created": 1700000000, "owned_by": "shenyu"}
    ]
    if cfg.model_mapping:
        existing_ids = {model.get("id") for model in models}
        aliases = [
            {
                "id": alias,
                "object": "model",
                "created": 1700000000,
                "owned_by": "shenyu-alias",
            }
            for alias in cfg.model_mapping
            if alias not in existing_ids
        ]
        models = aliases + models
    return {"object": "list", "data": models}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, body: ChatRequest):
    request_id = getattr(request.state, "shenyu_request_id", "")
    _mark_http_request_event(
        request_id,
        "handler.entered",
        now_iso=_iso_now(),
        detail={
            "model": body.model,
            "messages": len(body.messages),
            "stream": bool(body.stream),
            "tools": len(body.tools or []),
        },
    )
    await verify_api_key(request)
    _mark_http_request_event(request_id, "handler.auth_ok", now_iso=_iso_now())
    store = _require_session_store()
    return await _chat_pipeline(store).run(request, body)


@app.get("/health")
async def health():
    default_upstream = _upstream_for_hisense(False)
    hisense_upstream = _upstream_for_hisense(True)
    return {
        "status": "ok",
        "supabase": supabase_client is not None,
        "store": session_store is not None,
        "upstream": cfg.upstream_url,
        "upstream_chat_url": default_upstream["chat_url"],
        "upstream_host": urlsplit(default_upstream["chat_url"] or "").hostname or "",
        "protocol": default_upstream["protocol"],
        "hisense_upstream": hisense_upstream["base_url"],
        "hisense_upstream_chat_url": hisense_upstream["chat_url"],
        "hisense_upstream_scope": hisense_upstream["scope"],
        "hisense_protocol": hisense_upstream["protocol"],
        "upstream_proxy_configured": bool(cfg.upstream_proxy),
        "upstream_trust_env": cfg.upstream_trust_env,
        "enable_openai_cache_control": cfg.enable_openai_cache_control,
        "enable_anthropic_cache_control": cfg.enable_anthropic_cache_control,
        "openai_cache_ttl": cfg.openai_cache_ttl,
        "anthropic_cache_ttl": cfg.anthropic_cache_ttl,
        "enable_anthropic_auto_thinking": cfg.enable_anthropic_auto_thinking,
        "anthropic_auto_thinking_effort": cfg.anthropic_auto_thinking_effort,
        "enable_upstream_tools": cfg.enable_upstream_tools,
        "enable_gateway_tools": cfg.enable_gateway_tools,
        "enable_mem0_management_tools": cfg.enable_mem0_management_tools,
        "expose_supabase_tools": cfg.expose_supabase_tools,
        "gateway_tool_mode": cfg.gateway_tool_mode,
        "gateway_tool_surface": cfg.gateway_tool_surface,
        "client_tool_surface": cfg.client_tool_surface,
        "calendar_inject_day": cfg.calendar_inject_day,
        "calendar_inject_week": cfg.calendar_inject_week,
        "calendar_inject_month": cfg.calendar_inject_month,
        "inject_mem_notes": cfg.inject_mem_notes,
        "inject_inline_memory_prompt": cfg.inject_inline_memory_prompt,
        "enable_inline_memory_capture": cfg.enable_inline_memory_capture,
        "enable_cold_start": cfg.enable_cold_start,
        "gateway_db_path": cfg.gateway_db_path,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8010"))
    reload_enabled = os.getenv("UVICORN_RELOAD", "false").lower() in {"1", "true", "yes", "on"}
    print(f"Start -> http://localhost:{port}")
    print(f"Admin -> http://localhost:{port}/admin")
    print(f"Operit custom provider URL -> http://your-ip:{port}")
    uvicorn.run("gateway:app", host="0.0.0.0", port=port, reload=reload_enabled)
