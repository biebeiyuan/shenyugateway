from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from .schemas import ConfigUpdate


@dataclass(frozen=True)
class ConfigRouteDeps:
    cfg: Any
    validate_http_url: Callable[..., str]
    validate_protocol: Callable[..., str]
    clamp: Callable[[float, float, float], float]
    persist_env: Callable[[dict[str, Any]], None]
    get_supabase_client: Callable[[], Any]
    init_supabase: Callable[[], None]
    init_store: Callable[[], None]
    make_upstream_http_client: Callable[[], Any]


def _full_config(cfg: Any) -> dict[str, Any]:
    return {
        "gateway_key": cfg.gateway_key,
        "upstream_url": cfg.upstream_url,
        "upstream_api_key": cfg.upstream_api_key,
        "upstream_protocol": cfg.upstream_protocol,
        "upstream_proxy": cfg.upstream_proxy,
        "upstream_trust_env": cfg.upstream_trust_env,
        "enable_openai_cache_control": cfg.enable_openai_cache_control,
        "enable_anthropic_auto_thinking": cfg.enable_anthropic_auto_thinking,
        "anthropic_default_max_tokens": cfg.anthropic_default_max_tokens,
        "upstream_provider_order_enabled": cfg.upstream_provider_order_enabled,
        "upstream_provider_format": cfg.upstream_provider_format,
        "upstream_provider_order": cfg.upstream_provider_order,
        "upstream_extra_body": cfg.upstream_extra_body,
        "upstream_passthrough_headers": cfg.upstream_passthrough_headers,
        "hisense_upstream_url": cfg.hisense_upstream_url,
        "hisense_api_key": cfg.hisense_api_key,
        "hisense_protocol": cfg.hisense_protocol,
        "calendar_upstream_url": cfg.calendar_upstream_url,
        "calendar_api_key": cfg.calendar_api_key,
        "calendar_protocol": cfg.calendar_protocol,
        "calendar_model": cfg.calendar_model,
        "wake_welcome_message": cfg.wake_welcome_message,
        "inject_inline_memory_prompt": cfg.inject_inline_memory_prompt,
        "enable_inline_memory_capture": cfg.enable_inline_memory_capture,
        "model_mapping": cfg.model_mapping,
        "supabase_url": cfg.supabase_url,
        "supabase_key": cfg.supabase_key,
        "calendar_inject_day": cfg.calendar_inject_day,
        "calendar_inject_week": cfg.calendar_inject_week,
        "calendar_inject_month": cfg.calendar_inject_month,
        "inject_mem_notes": cfg.inject_mem_notes,
        "inject_stars": cfg.inject_stars,
        "inject_star_prompt": cfg.inject_star_prompt,
        "enable_inline_star_capture": cfg.enable_inline_star_capture,
        "enable_star_embeddings": cfg.enable_star_embeddings,
        "star_inject_limit": cfg.star_inject_limit,
        "star_review_new_limit": cfg.star_review_new_limit,
        "star_review_candidates_per_star": cfg.star_review_candidates_per_star,
        "star_review_total_candidate_limit": cfg.star_review_total_candidate_limit,
        "star_chat_explicit_fallback_limit": cfg.star_chat_explicit_fallback_limit,
        "star_candidate_limit": cfg.star_candidate_limit,
        "star_shadow_candidate_limit": cfg.star_shadow_candidate_limit,
        "star_min_score": cfg.star_min_score,
        "star_related_min_score": cfg.star_related_min_score,
        "star_recent_fatigue_hours": cfg.star_recent_fatigue_hours,
        "star_recent_fatigue_penalty": cfg.star_recent_fatigue_penalty,
        "star_rrf_ch_content": cfg.star_rrf_ch_content,
        "star_rrf_ch_keyword": cfg.star_rrf_ch_keyword,
        "star_rrf_ch_chord": cfg.star_rrf_ch_chord,
        "star_rrf_ch_harmony": cfg.star_rrf_ch_harmony,
        "star_rrf_ch_scene": cfg.star_rrf_ch_scene,
        "star_rrf_ch_explicit": cfg.star_rrf_ch_explicit,
        "star_rrf_k": cfg.star_rrf_k,
        "star_rrf_actr_floor": cfg.star_rrf_actr_floor,
        "star_rrf_constant_boost": cfg.star_rrf_constant_boost,
        "star_rrf_date_boost_max": cfg.star_rrf_date_boost_max,
        "enable_cold_start": cfg.enable_cold_start,
        "enable_upstream_tools": cfg.enable_upstream_tools,
        "enable_gateway_tools": cfg.enable_gateway_tools,
        "enable_stream_duplicate_guard": cfg.enable_stream_duplicate_guard,
        "enable_mem0_management_tools": cfg.enable_mem0_management_tools,
        "expose_supabase_tools": cfg.expose_supabase_tools,
        "gateway_tool_mode": cfg.gateway_tool_mode,
        "gateway_tool_surface": cfg.gateway_tool_surface,
        "client_tool_surface": cfg.client_tool_surface,
        "max_internal_tool_rounds": cfg.max_internal_tool_rounds,
        "gateway_db_path": cfg.gateway_db_path,
        "calendar_context_day_limit": cfg.calendar_context_day_limit,
        "calendar_context_week_limit": cfg.calendar_context_week_limit,
        "calendar_context_month_limit": cfg.calendar_context_month_limit,
        "max_client_messages": cfg.max_client_messages,
        "cold_start_message_limit": cfg.cold_start_message_limit,
        "cold_start_idle_minutes": cfg.cold_start_idle_minutes,
        "default_surface_limit": cfg.default_surface_limit,
        "mem_note_limit": cfg.mem_note_limit,
        "mem_note_min_score": cfg.mem_note_min_score,
        "mem_note_context_keyword_min_score": cfg.mem_note_context_keyword_min_score,
        "mem_note_semantic_min_score": cfg.mem_note_semantic_min_score,
        "mem_note_semantic_min_vector_score": cfg.mem_note_semantic_min_vector_score,
        "mem_note_anchored_semantic_min_score": cfg.mem_note_anchored_semantic_min_score,
        "mem_note_anchored_semantic_min_vector_score": cfg.mem_note_anchored_semantic_min_vector_score,
        "mem_note_dedupe_turns": cfg.mem_note_dedupe_turns,
        "mem_note_soft_cooldown_hours": cfg.mem_note_soft_cooldown_hours,
        "mem_note_default_cooldown_hours": cfg.mem_note_default_cooldown_hours,
        "hisense_client_name": cfg.hisense_client_name,
        "hisense_heartbeat_limit": cfg.hisense_heartbeat_limit,
        "hisense_notebook_limit": cfg.hisense_notebook_limit,
    }


def build_config_router(deps: ConfigRouteDeps) -> APIRouter:
    router = APIRouter()
    cfg = deps.cfg

    @router.get("/api/config")
    async def get_config():
        return cfg.to_dict()

    @router.get("/api/config/full")
    async def get_config_full():
        return _full_config(cfg)

    @router.post("/api/config")
    async def update_config(request: Request, body: ConfigUpdate):
        changed = []
        env_updates: dict[str, Any] = {}

        env_names = {
            "gateway_key": "GATEWAY_API_KEY",
            "upstream_url": "UPSTREAM_URL",
            "upstream_api_key": "ANTHROPIC_API_KEY",
            "upstream_protocol": "UPSTREAM_PROTOCOL",
            "upstream_proxy": "UPSTREAM_PROXY",
            "upstream_trust_env": "UPSTREAM_TRUST_ENV",
            "enable_openai_cache_control": "ENABLE_OPENAI_CACHE_CONTROL",
            "enable_anthropic_auto_thinking": "ENABLE_ANTHROPIC_AUTO_THINKING",
            "anthropic_default_max_tokens": "ANTHROPIC_DEFAULT_MAX_TOKENS",
            "upstream_provider_order_enabled": "UPSTREAM_PROVIDER_ORDER_ENABLED",
            "upstream_provider_format": "UPSTREAM_PROVIDER_FORMAT",
            "upstream_provider_order": "UPSTREAM_PROVIDER_ORDER",
            "upstream_extra_body": "UPSTREAM_EXTRA_BODY",
            "upstream_passthrough_headers": "UPSTREAM_PASSTHROUGH_HEADERS",
            "hisense_upstream_url": "HISENSE_UPSTREAM_URL",
            "hisense_api_key": "HISENSE_API_KEY",
            "hisense_protocol": "HISENSE_PROTOCOL",
            "calendar_upstream_url": "CALENDAR_UPSTREAM_URL",
            "calendar_api_key": "CALENDAR_API_KEY",
            "calendar_protocol": "CALENDAR_PROTOCOL",
            "calendar_model": "CALENDAR_MODEL",
            "wake_welcome_message": "WAKE_WELCOME_MESSAGE",
            "inject_inline_memory_prompt": "INJECT_INLINE_MEMORY_PROMPT",
            "enable_inline_memory_capture": "ENABLE_INLINE_MEMORY_CAPTURE",
            "model_mapping": "MODEL_MAPPING",
            "supabase_url": "SUPABASE_URL",
            "supabase_key": "SUPABASE_SERVICE_KEY",
            "calendar_inject_day": "CALENDAR_INJECT_DAY",
            "calendar_inject_week": "CALENDAR_INJECT_WEEK",
            "calendar_inject_month": "CALENDAR_INJECT_MONTH",
            "inject_mem_notes": "INJECT_MEM_NOTES",
            "inject_stars": "INJECT_STARS",
            "inject_star_prompt": "INJECT_STAR_PROMPT",
            "enable_inline_star_capture": "ENABLE_INLINE_STAR_CAPTURE",
            "enable_star_embeddings": "ENABLE_STAR_EMBEDDINGS",
            "star_inject_limit": "STAR_INJECT_LIMIT",
            "star_review_new_limit": "STAR_REVIEW_NEW_LIMIT",
            "star_review_candidates_per_star": "STAR_REVIEW_CANDIDATES_PER_STAR",
            "star_review_total_candidate_limit": "STAR_REVIEW_TOTAL_CANDIDATE_LIMIT",
            "star_chat_explicit_fallback_limit": "STAR_CHAT_EXPLICIT_FALLBACK_LIMIT",
            "star_candidate_limit": "STAR_CANDIDATE_LIMIT",
            "star_shadow_candidate_limit": "STAR_SHADOW_CANDIDATE_LIMIT",
            "star_min_score": "STAR_MIN_SCORE",
            "star_related_min_score": "STAR_RELATED_MIN_SCORE",
            "star_recent_fatigue_hours": "STAR_RECENT_FATIGUE_HOURS",
            "star_recent_fatigue_penalty": "STAR_RECENT_FATIGUE_PENALTY",
            "star_rrf_ch_content": "STAR_RRF_CH_CONTENT",
            "star_rrf_ch_keyword": "STAR_RRF_CH_KEYWORD",
            "star_rrf_ch_chord": "STAR_RRF_CH_CHORD",
            "star_rrf_ch_harmony": "STAR_RRF_CH_HARMONY",
            "star_rrf_ch_scene": "STAR_RRF_CH_SCENE",
            "star_rrf_ch_explicit": "STAR_RRF_CH_EXPLICIT",
            "star_rrf_k": "STAR_RRF_K",
            "star_rrf_actr_floor": "STAR_RRF_ACTR_FLOOR",
            "star_rrf_constant_boost": "STAR_RRF_CONSTANT_BOOST",
            "star_rrf_date_boost_max": "STAR_RRF_DATE_BOOST_MAX",
            "enable_cold_start": "ENABLE_COLD_START",
            "enable_upstream_tools": "ENABLE_UPSTREAM_TOOLS",
            "enable_gateway_tools": "ENABLE_GATEWAY_TOOLS",
            "enable_stream_duplicate_guard": "ENABLE_STREAM_DUPLICATE_GUARD",
            "enable_mem0_management_tools": "ENABLE_MEM0_MANAGEMENT_TOOLS",
            "expose_supabase_tools": "EXPOSE_SUPABASE_TOOLS",
            "gateway_tool_mode": "GATEWAY_TOOL_MODE",
            "gateway_tool_surface": "GATEWAY_TOOL_SURFACE",
            "client_tool_surface": "CLIENT_TOOL_SURFACE",
            "gateway_db_path": "GATEWAY_DB_PATH",
            "max_internal_tool_rounds": "MAX_INTERNAL_TOOL_ROUNDS",
            "calendar_context_day_limit": "CALENDAR_CONTEXT_DAY_LIMIT",
            "calendar_context_week_limit": "CALENDAR_CONTEXT_WEEK_LIMIT",
            "calendar_context_month_limit": "CALENDAR_CONTEXT_MONTH_LIMIT",
            "heartbeat_inject_every": "HEARTBEAT_INJECT_EVERY",
            "gateway_message_retention": "GATEWAY_MESSAGE_RETENTION",
            "gateway_context_snapshot_retention": "GATEWAY_CONTEXT_SNAPSHOT_RETENTION",
            "gateway_cold_start_retention": "GATEWAY_COLD_START_RETENTION",
            "max_client_messages": "MAX_CLIENT_MESSAGES",
            "cold_start_message_limit": "COLD_START_MESSAGE_LIMIT",
            "cold_start_idle_minutes": "COLD_START_IDLE_MINUTES",
            "default_surface_limit": "DEFAULT_SURFACE_LIMIT",
            "mem_note_limit": "MEM_NOTE_LIMIT",
            "mem_note_min_score": "MEM_NOTE_MIN_SCORE",
            "mem_note_context_keyword_min_score": "MEM_NOTE_CONTEXT_KEYWORD_MIN_SCORE",
            "mem_note_semantic_min_score": "MEM_NOTE_SEMANTIC_MIN_SCORE",
            "mem_note_semantic_min_vector_score": "MEM_NOTE_SEMANTIC_MIN_VECTOR_SCORE",
            "mem_note_anchored_semantic_min_score": "MEM_NOTE_ANCHORED_SEMANTIC_MIN_SCORE",
            "mem_note_anchored_semantic_min_vector_score": "MEM_NOTE_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE",
            "mem_note_dedupe_turns": "MEM_NOTE_DEDUPE_TURNS",
            "mem_note_soft_cooldown_hours": "MEM_NOTE_SOFT_COOLDOWN_HOURS",
            "mem_note_default_cooldown_hours": "MEM_NOTE_DEFAULT_COOLDOWN_HOURS",
            "hisense_client_name": "HISENSE_CLIENT_NAME",
            "hisense_heartbeat_limit": "HISENSE_HEARTBEAT_LIMIT",
            "hisense_notebook_limit": "HISENSE_NOTEBOOK_LIMIT",
        }

        simple_fields = [
            "gateway_key",
            "upstream_url",
            "upstream_api_key",
            "upstream_protocol",
            "upstream_proxy",
            "upstream_trust_env",
            "enable_openai_cache_control",
            "enable_anthropic_auto_thinking",
            "anthropic_default_max_tokens",
            "upstream_provider_order_enabled",
            "upstream_provider_format",
            "hisense_upstream_url",
            "hisense_api_key",
            "hisense_protocol",
            "calendar_upstream_url",
            "calendar_api_key",
            "calendar_protocol",
            "calendar_model",
            "wake_welcome_message",
            "inject_inline_memory_prompt",
            "enable_inline_memory_capture",
            "supabase_url",
            "supabase_key",
            "calendar_inject_day",
            "calendar_inject_week",
            "calendar_inject_month",
            "inject_mem_notes",
            "inject_stars",
            "inject_star_prompt",
            "enable_inline_star_capture",
            "enable_star_embeddings",
            "enable_cold_start",
            "enable_upstream_tools",
            "enable_gateway_tools",
            "enable_stream_duplicate_guard",
            "enable_mem0_management_tools",
            "expose_supabase_tools",
            "gateway_tool_mode",
            "gateway_tool_surface",
            "client_tool_surface",
            "gateway_db_path",
            "hisense_client_name",
        ]
        if body.clear_wake_welcome_message:
            cfg.wake_welcome_message = ""
            changed.append("wake_welcome_message")
            env_updates[env_names["wake_welcome_message"]] = ""

        for field in simple_fields:
            value = getattr(body, field)
            if value is not None:
                if field == "wake_welcome_message":
                    if body.clear_wake_welcome_message:
                        continue
                    value = value.strip() if isinstance(value, str) else value
                    if not value:
                        continue
                if field in {"upstream_url", "hisense_upstream_url", "calendar_upstream_url"}:
                    value = deps.validate_http_url(env_names[field], value, allow_empty=(field != "upstream_url"))
                elif field == "upstream_proxy":
                    value = deps.validate_http_url(env_names[field], value, allow_empty=True)
                elif field in {"upstream_protocol", "hisense_protocol", "calendar_protocol"}:
                    value = deps.validate_protocol(env_names[field], value, allow_empty=(field == "hisense_protocol"))
                elif field == "gateway_tool_mode":
                    value = str(value or "").strip().lower()
                    if value not in {"full", "broker"}:
                        raise HTTPException(status_code=400, detail="GATEWAY_TOOL_MODE must be full or broker.")
                elif field == "gateway_tool_surface":
                    value = str(value or "").strip().lower()
                    if value not in {"full", "daily"}:
                        raise HTTPException(status_code=400, detail="GATEWAY_TOOL_SURFACE must be full or daily.")
                elif field == "client_tool_surface":
                    value = str(value or "").strip().lower()
                    if value not in {"all", "daily", "none"}:
                        raise HTTPException(status_code=400, detail="CLIENT_TOOL_SURFACE must be all, daily, or none.")
                elif field == "upstream_provider_format":
                    value = str(value or "").strip().lower().replace("-", "_")
                    if value not in {"string", "order_object"}:
                        raise HTTPException(
                            status_code=400,
                            detail="UPSTREAM_PROVIDER_FORMAT must be string or order_object.",
                        )
                elif isinstance(value, str):
                    value = value.strip()
                setattr(cfg, field, value)
                changed.append(field)
                env_updates[env_names[field]] = str(value).lower() if isinstance(value, bool) else value

        if body.upstream_provider_order is not None:
            raw_order = body.upstream_provider_order
            if isinstance(raw_order, str):
                raw_items = raw_order.split(",")
            elif isinstance(raw_order, list):
                raw_items = raw_order
            else:
                raw_items = []
            seen: set[str] = set()
            provider_order: list[str] = []
            for item in raw_items:
                provider = str(item or "").strip()
                if not provider or provider in seen:
                    continue
                seen.add(provider)
                provider_order.append(provider)
            cfg.upstream_provider_order = provider_order
            changed.append("upstream_provider_order")
            env_updates[env_names["upstream_provider_order"]] = json.dumps(provider_order, ensure_ascii=False)

        if "upstream_extra_body" in body.model_fields_set:
            raw_extra_body = body.upstream_extra_body
            if raw_extra_body is None or raw_extra_body == "":
                extra_body: dict[str, Any] = {}
            elif isinstance(raw_extra_body, str):
                try:
                    parsed_extra_body = json.loads(raw_extra_body)
                except json.JSONDecodeError as exc:
                    raise HTTPException(status_code=400, detail="UPSTREAM_EXTRA_BODY 必须是 JSON object。") from exc
                if not isinstance(parsed_extra_body, dict):
                    raise HTTPException(status_code=400, detail="UPSTREAM_EXTRA_BODY 必须是 JSON object。")
                extra_body = parsed_extra_body
            elif isinstance(raw_extra_body, dict):
                extra_body = raw_extra_body
            else:
                raise HTTPException(status_code=400, detail="UPSTREAM_EXTRA_BODY 必须是 JSON object。")
            cfg.upstream_extra_body = {
                str(key): value
                for key, value in extra_body.items()
                if str(key)
            }
            changed.append("upstream_extra_body")
            env_updates[env_names["upstream_extra_body"]] = json.dumps(cfg.upstream_extra_body, ensure_ascii=False)

        if "upstream_passthrough_headers" in body.model_fields_set:
            raw_headers = body.upstream_passthrough_headers
            if raw_headers is None or raw_headers == "":
                raw_items = []
            elif isinstance(raw_headers, str):
                raw_items = raw_headers.split(",")
            elif isinstance(raw_headers, list):
                raw_items = raw_headers
            else:
                raise HTTPException(
                    status_code=400,
                    detail="UPSTREAM_PASSTHROUGH_HEADERS 必须是字符串数组或逗号分隔的字符串。",
                )
            seen_names: set[str] = set()
            passthrough_names: list[str] = []
            for item in raw_items:
                name = str(item or "").strip().lower()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                passthrough_names.append(name)
            cfg.upstream_passthrough_headers = passthrough_names
            changed.append("upstream_passthrough_headers")
            env_updates[env_names["upstream_passthrough_headers"]] = json.dumps(passthrough_names, ensure_ascii=False)

        if body.max_internal_tool_rounds is not None:
            cfg.max_internal_tool_rounds = max(1, body.max_internal_tool_rounds)
            changed.append("max_internal_tool_rounds")
            env_updates[env_names["max_internal_tool_rounds"]] = cfg.max_internal_tool_rounds
        if body.calendar_context_day_limit is not None:
            cfg.calendar_context_day_limit = max(1, min(body.calendar_context_day_limit, 30))
            changed.append("calendar_context_day_limit")
            env_updates[env_names["calendar_context_day_limit"]] = cfg.calendar_context_day_limit
        if body.calendar_context_week_limit is not None:
            cfg.calendar_context_week_limit = max(1, min(body.calendar_context_week_limit, 12))
            changed.append("calendar_context_week_limit")
            env_updates[env_names["calendar_context_week_limit"]] = cfg.calendar_context_week_limit
        if body.calendar_context_month_limit is not None:
            cfg.calendar_context_month_limit = max(1, min(body.calendar_context_month_limit, 12))
            changed.append("calendar_context_month_limit")
            env_updates[env_names["calendar_context_month_limit"]] = cfg.calendar_context_month_limit
        if body.heartbeat_inject_every is not None:
            cfg.heartbeat_inject_every = max(1, min(body.heartbeat_inject_every, 50))
            changed.append("heartbeat_inject_every")
            env_updates[env_names["heartbeat_inject_every"]] = cfg.heartbeat_inject_every
        if body.gateway_message_retention is not None:
            cfg.gateway_message_retention = max(50, min(body.gateway_message_retention, 200000))
            changed.append("gateway_message_retention")
            env_updates[env_names["gateway_message_retention"]] = cfg.gateway_message_retention
        if body.gateway_context_snapshot_retention is not None:
            cfg.gateway_context_snapshot_retention = max(1, min(body.gateway_context_snapshot_retention, 100))
            changed.append("gateway_context_snapshot_retention")
            env_updates[env_names["gateway_context_snapshot_retention"]] = cfg.gateway_context_snapshot_retention
        if body.gateway_cold_start_retention is not None:
            cfg.gateway_cold_start_retention = max(1, min(body.gateway_cold_start_retention, 1000))
            changed.append("gateway_cold_start_retention")
            env_updates[env_names["gateway_cold_start_retention"]] = cfg.gateway_cold_start_retention
        if "max_client_messages" in body.model_fields_set:
            value = body.max_client_messages
            cfg.max_client_messages = max(1, min(int(value), 500)) if value and int(value) > 0 else None
            changed.append("max_client_messages")
            env_updates[env_names["max_client_messages"]] = cfg.max_client_messages
        if "cold_start_message_limit" in body.model_fields_set:
            value = body.cold_start_message_limit
            cfg.cold_start_message_limit = max(1, min(int(value), 500)) if value and int(value) > 0 else None
            changed.append("cold_start_message_limit")
            env_updates[env_names["cold_start_message_limit"]] = cfg.cold_start_message_limit
        if body.cold_start_idle_minutes is not None:
            cfg.cold_start_idle_minutes = max(1, min(body.cold_start_idle_minutes, 10080))
            changed.append("cold_start_idle_minutes")
            env_updates[env_names["cold_start_idle_minutes"]] = cfg.cold_start_idle_minutes
        if body.default_surface_limit is not None:
            cfg.default_surface_limit = max(1, min(body.default_surface_limit, 8))
            changed.append("default_surface_limit")
            env_updates[env_names["default_surface_limit"]] = cfg.default_surface_limit
        if body.mem_note_limit is not None:
            cfg.mem_note_limit = max(1, min(body.mem_note_limit, 5))
            changed.append("mem_note_limit")
            env_updates[env_names["mem_note_limit"]] = cfg.mem_note_limit
        if body.mem_note_min_score is not None:
            cfg.mem_note_min_score = deps.clamp(float(body.mem_note_min_score), 0.0, 1.0)
            changed.append("mem_note_min_score")
            env_updates[env_names["mem_note_min_score"]] = cfg.mem_note_min_score
        if body.mem_note_context_keyword_min_score is not None:
            cfg.mem_note_context_keyword_min_score = deps.clamp(
                float(body.mem_note_context_keyword_min_score), 0.05, 0.9
            )
            changed.append("mem_note_context_keyword_min_score")
            env_updates[env_names["mem_note_context_keyword_min_score"]] = cfg.mem_note_context_keyword_min_score
        if body.mem_note_semantic_min_score is not None:
            cfg.mem_note_semantic_min_score = deps.clamp(float(body.mem_note_semantic_min_score), 0.0, 1.0)
            changed.append("mem_note_semantic_min_score")
            env_updates[env_names["mem_note_semantic_min_score"]] = cfg.mem_note_semantic_min_score
        if body.mem_note_semantic_min_vector_score is not None:
            cfg.mem_note_semantic_min_vector_score = deps.clamp(
                float(body.mem_note_semantic_min_vector_score), 0.0, 1.0
            )
            changed.append("mem_note_semantic_min_vector_score")
            env_updates[env_names["mem_note_semantic_min_vector_score"]] = cfg.mem_note_semantic_min_vector_score
        if body.mem_note_anchored_semantic_min_score is not None:
            cfg.mem_note_anchored_semantic_min_score = deps.clamp(
                float(body.mem_note_anchored_semantic_min_score), 0.0, 1.0
            )
            changed.append("mem_note_anchored_semantic_min_score")
            env_updates[env_names["mem_note_anchored_semantic_min_score"]] = cfg.mem_note_anchored_semantic_min_score
        if body.mem_note_anchored_semantic_min_vector_score is not None:
            cfg.mem_note_anchored_semantic_min_vector_score = deps.clamp(
                float(body.mem_note_anchored_semantic_min_vector_score),
                0.0,
                1.0,
            )
            changed.append("mem_note_anchored_semantic_min_vector_score")
            env_updates[env_names["mem_note_anchored_semantic_min_vector_score"]] = (
                cfg.mem_note_anchored_semantic_min_vector_score
            )
        if body.mem_note_dedupe_turns is not None:
            cfg.mem_note_dedupe_turns = max(0, min(body.mem_note_dedupe_turns, 50))
            changed.append("mem_note_dedupe_turns")
            env_updates[env_names["mem_note_dedupe_turns"]] = cfg.mem_note_dedupe_turns
        if body.mem_note_soft_cooldown_hours is not None:
            cfg.mem_note_soft_cooldown_hours = max(0, min(body.mem_note_soft_cooldown_hours, 8760))
            changed.append("mem_note_soft_cooldown_hours")
            env_updates[env_names["mem_note_soft_cooldown_hours"]] = cfg.mem_note_soft_cooldown_hours
        if body.mem_note_default_cooldown_hours is not None:
            cfg.mem_note_default_cooldown_hours = max(0, min(body.mem_note_default_cooldown_hours, 8760))
            changed.append("mem_note_default_cooldown_hours")
            env_updates[env_names["mem_note_default_cooldown_hours"]] = cfg.mem_note_default_cooldown_hours
        if body.star_inject_limit is not None:
            cfg.star_inject_limit = max(1, min(body.star_inject_limit, 5))
            changed.append("star_inject_limit")
            env_updates[env_names["star_inject_limit"]] = cfg.star_inject_limit
        if body.star_review_new_limit is not None:
            cfg.star_review_new_limit = max(1, min(body.star_review_new_limit, 10))
            changed.append("star_review_new_limit")
            env_updates[env_names["star_review_new_limit"]] = cfg.star_review_new_limit
        if body.star_review_candidates_per_star is not None:
            cfg.star_review_candidates_per_star = max(1, min(body.star_review_candidates_per_star, 5))
            changed.append("star_review_candidates_per_star")
            env_updates[env_names["star_review_candidates_per_star"]] = cfg.star_review_candidates_per_star
        if body.star_review_total_candidate_limit is not None:
            cfg.star_review_total_candidate_limit = max(1, min(body.star_review_total_candidate_limit, 30))
            changed.append("star_review_total_candidate_limit")
            env_updates[env_names["star_review_total_candidate_limit"]] = cfg.star_review_total_candidate_limit
        if body.star_chat_explicit_fallback_limit is not None:
            cfg.star_chat_explicit_fallback_limit = max(0, min(body.star_chat_explicit_fallback_limit, 3))
            changed.append("star_chat_explicit_fallback_limit")
            env_updates[env_names["star_chat_explicit_fallback_limit"]] = cfg.star_chat_explicit_fallback_limit
        if body.star_candidate_limit is not None:
            cfg.star_candidate_limit = max(50, min(body.star_candidate_limit, 5000))
            changed.append("star_candidate_limit")
            env_updates[env_names["star_candidate_limit"]] = cfg.star_candidate_limit
        if body.star_shadow_candidate_limit is not None:
            cfg.star_shadow_candidate_limit = max(3, min(body.star_shadow_candidate_limit, 100))
            changed.append("star_shadow_candidate_limit")
            env_updates[env_names["star_shadow_candidate_limit"]] = cfg.star_shadow_candidate_limit
        if body.star_min_score is not None:
            cfg.star_min_score = deps.clamp(float(body.star_min_score), 0.0, 1.0)
            changed.append("star_min_score")
            env_updates[env_names["star_min_score"]] = cfg.star_min_score
        if body.star_related_min_score is not None:
            cfg.star_related_min_score = deps.clamp(float(body.star_related_min_score), 0.0, 1.0)
            changed.append("star_related_min_score")
            env_updates[env_names["star_related_min_score"]] = cfg.star_related_min_score
        if body.star_recent_fatigue_hours is not None:
            cfg.star_recent_fatigue_hours = max(0, min(body.star_recent_fatigue_hours, 168))
            changed.append("star_recent_fatigue_hours")
            env_updates[env_names["star_recent_fatigue_hours"]] = cfg.star_recent_fatigue_hours
        if body.star_recent_fatigue_penalty is not None:
            cfg.star_recent_fatigue_penalty = deps.clamp(float(body.star_recent_fatigue_penalty), 0.0, 1.0)
            changed.append("star_recent_fatigue_penalty")
            env_updates[env_names["star_recent_fatigue_penalty"]] = cfg.star_recent_fatigue_penalty
        for field in (
            "star_rrf_ch_content",
            "star_rrf_ch_keyword",
            "star_rrf_ch_chord",
            "star_rrf_ch_harmony",
            "star_rrf_ch_scene",
            "star_rrf_ch_explicit",
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(cfg, field, deps.clamp(float(value), 0.0, 5.0))
                changed.append(field)
                env_updates[env_names[field]] = getattr(cfg, field)
        if body.star_rrf_k is not None:
            cfg.star_rrf_k = max(1, min(body.star_rrf_k, 1000))
            changed.append("star_rrf_k")
            env_updates[env_names["star_rrf_k"]] = cfg.star_rrf_k
        for field in ("star_rrf_actr_floor", "star_rrf_date_boost_max"):
            value = getattr(body, field)
            if value is not None:
                setattr(cfg, field, deps.clamp(float(value), 0.0, 2.0))
                changed.append(field)
                env_updates[env_names[field]] = getattr(cfg, field)
        if body.star_rrf_constant_boost is not None:
            cfg.star_rrf_constant_boost = deps.clamp(float(body.star_rrf_constant_boost), 1.0, 3.0)
            changed.append("star_rrf_constant_boost")
            env_updates[env_names["star_rrf_constant_boost"]] = cfg.star_rrf_constant_boost
        if body.hisense_heartbeat_limit is not None:
            cfg.hisense_heartbeat_limit = max(1, min(body.hisense_heartbeat_limit, 30))
            changed.append("hisense_heartbeat_limit")
            env_updates[env_names["hisense_heartbeat_limit"]] = cfg.hisense_heartbeat_limit
        if body.hisense_notebook_limit is not None:
            cfg.hisense_notebook_limit = max(1, min(body.hisense_notebook_limit, 20))
            changed.append("hisense_notebook_limit")
            env_updates[env_names["hisense_notebook_limit"]] = cfg.hisense_notebook_limit
        if body.model_mapping is not None:
            cfg.model_mapping = {
                str(key).strip(): str(value).strip()
                for key, value in body.model_mapping.items()
                if str(key).strip() and str(value).strip()
            }
            changed.append("model_mapping")
            env_updates[env_names["model_mapping"]] = json.dumps(cfg.model_mapping, ensure_ascii=False)

        deps.persist_env(env_updates)

        if "supabase_url" in changed or "supabase_key" in changed:
            supabase_client = deps.get_supabase_client()
            if supabase_client:
                await supabase_client.close()
            deps.init_supabase()

        if "gateway_db_path" in changed:
            deps.init_store()
        if "upstream_proxy" in changed or "upstream_trust_env" in changed:
            old_client = request.app.state.http
            request.app.state.http = deps.make_upstream_http_client()
            await old_client.aclose()

        return {"ok": True, "changed": changed, "config": _full_config(cfg)}

    return router
