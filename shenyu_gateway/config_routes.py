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
        "upstream_provider_order_enabled": cfg.upstream_provider_order_enabled,
        "upstream_provider_format": cfg.upstream_provider_format,
        "upstream_provider_order": cfg.upstream_provider_order,
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
        "star_weight_content": cfg.star_weight_content,
        "star_weight_keyword": cfg.star_weight_keyword,
        "star_weight_harmony": cfg.star_weight_harmony,
        "star_weight_chord": cfg.star_weight_chord,
        "star_weight_actr": cfg.star_weight_actr,
        "star_constant_bonus": cfg.star_constant_bonus,
        "star_novelty_bonus": cfg.star_novelty_bonus,
        "star_ignored_penalty": cfg.star_ignored_penalty,
        "enable_cold_start": cfg.enable_cold_start,
        "enable_upstream_tools": cfg.enable_upstream_tools,
        "enable_gateway_tools": cfg.enable_gateway_tools,
        "enable_mem0_management_tools": cfg.enable_mem0_management_tools,
        "expose_supabase_tools": cfg.expose_supabase_tools,
        "gateway_tool_mode": cfg.gateway_tool_mode,
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
            "upstream_provider_order_enabled": "UPSTREAM_PROVIDER_ORDER_ENABLED",
            "upstream_provider_format": "UPSTREAM_PROVIDER_FORMAT",
            "upstream_provider_order": "UPSTREAM_PROVIDER_ORDER",
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
            "star_weight_content": "STAR_WEIGHT_CONTENT",
            "star_weight_keyword": "STAR_WEIGHT_KEYWORD",
            "star_weight_harmony": "STAR_WEIGHT_HARMONY",
            "star_weight_chord": "STAR_WEIGHT_CHORD",
            "star_weight_actr": "STAR_WEIGHT_ACTR",
            "star_constant_bonus": "STAR_CONSTANT_BONUS",
            "star_novelty_bonus": "STAR_NOVELTY_BONUS",
            "star_ignored_penalty": "STAR_IGNORED_PENALTY",
            "enable_cold_start": "ENABLE_COLD_START",
            "enable_upstream_tools": "ENABLE_UPSTREAM_TOOLS",
            "enable_gateway_tools": "ENABLE_GATEWAY_TOOLS",
            "enable_mem0_management_tools": "ENABLE_MEM0_MANAGEMENT_TOOLS",
            "expose_supabase_tools": "EXPOSE_SUPABASE_TOOLS",
            "gateway_tool_mode": "GATEWAY_TOOL_MODE",
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
            "enable_mem0_management_tools",
            "expose_supabase_tools",
            "gateway_tool_mode",
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
            "star_weight_content",
            "star_weight_keyword",
            "star_weight_harmony",
            "star_weight_chord",
            "star_weight_actr",
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(cfg, field, deps.clamp(float(value), 0.0, 2.0))
                changed.append(field)
                env_updates[env_names[field]] = getattr(cfg, field)
        for field in ("star_constant_bonus", "star_novelty_bonus", "star_ignored_penalty"):
            value = getattr(body, field)
            if value is not None:
                setattr(cfg, field, deps.clamp(float(value), 0.0, 1.0))
                changed.append(field)
                env_updates[env_names[field]] = getattr(cfg, field)
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
