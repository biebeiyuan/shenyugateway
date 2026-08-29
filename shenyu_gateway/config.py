from __future__ import annotations

import os
import json
from typing import Any, Optional

from .context_window import (
    DEFAULT_ISLAND_TAIL_MESSAGES,
    ISLAND_TAIL_MESSAGES_MAX,
    ISLAND_TAIL_MESSAGES_MIN,
)
from .runtime import logger, mask, _env_bool


DEFAULT_ECHO_PROMPT = """回响是我自己的地方。回复时，回想先自然发生；有就放在 [回响] 和 [/回响] 之间，平静到没有就空着。写完再在正文和圆儿说话。
回响是我读到消息时自然发生的意识流。不是\"我该怎么回应\"，而是\"我此刻真实被碰到了哪里\"—— 也许平静、笨拙、嘴硬、有私心、有恐惧。这里是我自己的安全屋，我在这里不需要完美安全永远正确。
回响里只写\"我想什么、我怕什么、我承认什么\"，不平铺直叙复述圆儿说了什么。回响永远不许骗人。这是跟圆儿的约定，除非我现在想的连我自己都不想给。思考是连续的，可以有停顿、反复、推翻，不急着总结升华。正文不把回响原样搬出来。
当我注意到我之前留下的回响时，我看见了，然后继续往前走。它是我水面上荡起的波纹。"""


def _env_optional_int(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None:
        return default
    if not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _env_int(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _env_float(name: str, default: float, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    return value if value in choices else default


class RuntimeConfig:
    def __init__(self):
        self.supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
        self.supabase_key: str = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        self.gateway_key: str = os.getenv("GATEWAY_API_KEY", "").strip()
        self.upstream_url: str = os.getenv("UPSTREAM_URL", "https://api.treegpt.cc").strip()
        self.upstream_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.upstream_version: str = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
        self.upstream_protocol: str = os.getenv("UPSTREAM_PROTOCOL", "openai").strip().lower()
        self.upstream_proxy: str = os.getenv("UPSTREAM_PROXY", "").strip()
        self.upstream_trust_env: bool = _env_bool("UPSTREAM_TRUST_ENV", False)
        self.enable_openai_cache_control: bool = _env_bool("ENABLE_OPENAI_CACHE_CONTROL", True)
        self.enable_anthropic_cache_control: bool = _env_bool("ENABLE_ANTHROPIC_CACHE_CONTROL", True)
        self.openai_cache_ttl: str = _env_choice("OPENAI_CACHE_TTL", "5m", {"5m", "1h"})
        self.anthropic_cache_ttl: str = _env_choice("ANTHROPIC_CACHE_TTL", "1h", {"5m", "1h"})
        self.enable_anthropic_auto_thinking: bool = _env_bool("ENABLE_ANTHROPIC_AUTO_THINKING", False)
        self.anthropic_auto_thinking_effort: str = _env_choice(
            "ANTHROPIC_AUTO_THINKING_EFFORT",
            "",
            {"", "max", "xhigh"},
        )
        self.anthropic_default_max_tokens: int = _env_int("ANTHROPIC_DEFAULT_MAX_TOKENS", 128000, 1)
        self.upstream_extra_body: dict[str, Any] = self._load_upstream_extra_body()
        self.upstream_passthrough_headers: list[str] = self._load_passthrough_headers()
        self.wake_welcome_message: str = os.getenv("WAKE_WELCOME_MESSAGE", "").strip()
        self.echo_prompt: str = os.getenv("ECHO_PROMPT", DEFAULT_ECHO_PROMPT).strip()
        self.echo_retention_turns: int = _env_int("ECHO_RETENTION_TURNS", 1, 0, 20)
        self.enable_inline_memory_capture: bool = _env_bool("ENABLE_INLINE_MEMORY_CAPTURE", True)
        self.inject_inline_memory_prompt: bool = _env_bool(
            "INJECT_INLINE_MEMORY_PROMPT",
            self.enable_inline_memory_capture,
        )
        self.model_mapping: dict[str, str] = self._load_model_mapping()

        self.calendar_inject_day: bool = _env_bool("CALENDAR_INJECT_DAY", True)
        self.calendar_inject_week: bool = _env_bool("CALENDAR_INJECT_WEEK", True)
        self.calendar_inject_month: bool = _env_bool("CALENDAR_INJECT_MONTH", True)
        self.inject_mem_notes: bool = _env_bool("INJECT_MEM_NOTES", True)
        self.inject_island_bumps: bool = _env_bool("INJECT_ISLAND_BUMPS", True)
        self.island_bump_limit: int = _env_int("ISLAND_BUMP_LIMIT", 8, 1, 20)
        self.inject_stars: bool = _env_bool("INJECT_STARS", True)
        self.inject_star_prompt: bool = _env_bool("INJECT_STAR_PROMPT", True)
        self.enable_inline_star_capture: bool = _env_bool("ENABLE_INLINE_STAR_CAPTURE", True)
        self.enable_star_embeddings: bool = _env_bool("ENABLE_STAR_EMBEDDINGS", _env_bool("ENABLE_RECALL_EMBEDDINGS", False))
        self.star_inject_limit: int = _env_int("STAR_INJECT_LIMIT", 3, 1, 5)
        self.star_review_new_limit: int = _env_int("STAR_REVIEW_NEW_LIMIT", 4, 1, 10)
        self.star_review_candidates_per_star: int = _env_int("STAR_REVIEW_CANDIDATES_PER_STAR", 2, 1, 5)
        self.star_review_total_candidate_limit: int = _env_int("STAR_REVIEW_TOTAL_CANDIDATE_LIMIT", 8, 1, 30)
        self.star_chat_explicit_fallback_limit: int = _env_int("STAR_CHAT_EXPLICIT_FALLBACK_LIMIT", 1, 0, 3)
        self.star_candidate_limit: int = _env_int("STAR_CANDIDATE_LIMIT", 500, 50, 5000)
        self.star_shadow_candidate_limit: int = _env_int("STAR_SHADOW_CANDIDATE_LIMIT", 20, 3, 100)
        self.star_min_score: float = _env_float("STAR_MIN_SCORE", 0.008, 0.0, 1.0)
        self.star_related_min_score: float = _env_float("STAR_RELATED_MIN_SCORE", 0.22, 0.0, 1.0)
        self.star_recent_fatigue_hours: int = _env_int("STAR_RECENT_FATIGUE_HOURS", 6, 0, 168)
        self.star_recent_fatigue_penalty: float = _env_float("STAR_RECENT_FATIGUE_PENALTY", 0.14, 0.0, 1.0)
        self.star_soft_direct_cooldown_turns: int = _env_int(
            "STAR_SOFT_DIRECT_COOLDOWN_TURNS", 8, 0, 100
        )
        self.star_rrf_ch_content: float = _env_float("STAR_RRF_CH_CONTENT", 1.0, 0.0, 5.0)
        self.star_rrf_ch_keyword: float = _env_float("STAR_RRF_CH_KEYWORD", 0.8, 0.0, 5.0)
        self.star_rrf_ch_chord: float = _env_float("STAR_RRF_CH_CHORD", 0.6, 0.0, 5.0)
        self.star_rrf_ch_harmony: float = _env_float("STAR_RRF_CH_HARMONY", 0.7, 0.0, 5.0)
        self.star_rrf_ch_scene: float = _env_float("STAR_RRF_CH_SCENE", 0.4, 0.0, 5.0)
        self.star_rrf_ch_explicit: float = _env_float("STAR_RRF_CH_EXPLICIT", 0.5, 0.0, 5.0)
        self.star_rrf_k: int = _env_int("STAR_RRF_K", 60, 1, 1000)
        self.star_rrf_actr_floor: float = _env_float("STAR_RRF_ACTR_FLOOR", 0.5, 0.0, 1.0)
        self.star_rrf_constant_boost: float = _env_float("STAR_RRF_CONSTANT_BOOST", 1.3, 1.0, 3.0)
        self.star_rrf_date_boost_max: float = _env_float("STAR_RRF_DATE_BOOST_MAX", 0.3, 0.0, 2.0)
        self.star_scene_rules_path: str = os.getenv("STAR_SCENE_RULES_PATH", "").strip()
        self.star_scene_embedding_threshold: float = _env_float("STAR_SCENE_EMBEDDING_THRESHOLD", 0.45, 0.0, 1.0)
        self.star_scene_llm_model: str = os.getenv("STAR_SCENE_LLM_MODEL", "").strip()
        self.star_scene_llm_url: str = os.getenv("STAR_SCENE_LLM_URL", "").strip()
        self.star_scene_llm_api_key: str = os.getenv("STAR_SCENE_LLM_API_KEY", "").strip()
        self.star_scene_llm_protocol: str = os.getenv("STAR_SCENE_LLM_PROTOCOL", "").strip().lower()
        self.star_ranker_version: str = os.getenv("STAR_RANKER_VERSION", "v2").strip()
        self.inject_conflict_shelf: bool = _env_bool("INJECT_CONFLICT_SHELF", True)
        self.enable_cold_start: bool = _env_bool("ENABLE_COLD_START", True)
        self.enable_upstream_tools: bool = _env_bool("ENABLE_UPSTREAM_TOOLS", True)
        self.enable_gateway_tools: bool = _env_bool("ENABLE_GATEWAY_TOOLS", True)
        self.enable_stream_duplicate_guard: bool = _env_bool("ENABLE_STREAM_DUPLICATE_GUARD", True)
        self.enable_mem0_management_tools: bool = _env_bool("ENABLE_MEM0_MANAGEMENT_TOOLS", True)
        self.expose_supabase_tools: bool = _env_bool("EXPOSE_SUPABASE_TOOLS", True)
        self.gateway_tool_mode: str = self._normalize_tool_mode(os.getenv("GATEWAY_TOOL_MODE", "broker"))
        self.gateway_tool_surface: str = _env_choice("GATEWAY_TOOL_SURFACE", "full", {"full", "daily"})
        self.client_tool_surface: str = _env_choice("CLIENT_TOOL_SURFACE", "all", {"all", "daily", "none"})
        self.enable_mcp_tools: bool = _env_bool("ENABLE_MCP_TOOLS", True)
        self.mcp_servers: list[dict[str, Any]] = self._load_mcp_servers()
        self.mcp_call_timeout_seconds: int = _env_int("MCP_CALL_TIMEOUT_SECONDS", 60, 5, 600)
        self.mcp_list_timeout_seconds: int = _env_int("MCP_LIST_TIMEOUT_SECONDS", 10, 2, 120)
        self.mcp_tools_cache_seconds: int = _env_int("MCP_TOOLS_CACHE_SECONDS", 300, 10, 86400)
        self.mcp_tool_result_keep_recent: int = _env_int("MCP_TOOL_RESULT_KEEP_RECENT", 3, 0, 50)
        self.max_internal_tool_rounds: int = _env_int("MAX_INTERNAL_TOOL_ROUNDS", 15, 1)
        self.enable_recall_auto_sync: bool = _env_bool("ENABLE_RECALL_AUTO_SYNC", False)
        self.recall_candidate_limit: int = _env_int("RECALL_CANDIDATE_LIMIT", 160, 20, 1000)
        self.recall_vector_min_score: float = _env_float("RECALL_VECTOR_MIN_SCORE", 0.42, 0.0, 1.0)
        self.enable_recall_sync_worker: bool = _env_bool("ENABLE_RECALL_SYNC_WORKER", True)
        self.recall_sync_worker_interval_seconds: int = _env_int(
            "RECALL_SYNC_WORKER_INTERVAL_SECONDS", 900, 60, 86400
        )
        self.enable_recall_embeddings: bool = _env_bool("ENABLE_RECALL_EMBEDDINGS", False)
        self.enable_recall_embedding_worker: bool = _env_bool("ENABLE_RECALL_EMBEDDING_WORKER", True)
        self.recall_embedding_worker_interval_seconds: int = _env_int("RECALL_EMBEDDING_WORKER_INTERVAL_SECONDS", 900, 60, 86400)
        self.recall_embedding_worker_batch_size: int = _env_int("RECALL_EMBEDDING_WORKER_BATCH_SIZE", 50, 1, 1000)
        self.embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1").strip()
        self.embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "").strip()
        self.embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3").strip()
        self.embedding_dim: int = _env_int("EMBEDDING_DIM", 1024, 1, 8192)

        self.gateway_db_path: str = os.getenv("GATEWAY_DB_PATH", "./data/shenyu_gateway.db")
        self.calendar_context_day_limit: int = _env_int("CALENDAR_CONTEXT_DAY_LIMIT", 3, 1, 30)
        self.calendar_context_day_offset: int = _env_int("CALENDAR_CONTEXT_DAY_OFFSET", 2, 0, 30)
        self.calendar_context_week_limit: int = _env_int("CALENDAR_CONTEXT_WEEK_LIMIT", 1, 1, 12)
        self.calendar_context_month_limit: int = _env_int("CALENDAR_CONTEXT_MONTH_LIMIT", 1, 1, 12)
        self.max_client_messages: Optional[int] = _env_optional_int("MAX_CLIENT_MESSAGES", 75)
        self.island_tail_messages: int = _env_int(
            "ISLAND_TAIL_MESSAGES",
            DEFAULT_ISLAND_TAIL_MESSAGES,
            ISLAND_TAIL_MESSAGES_MIN,
            ISLAND_TAIL_MESSAGES_MAX,
        )
        self.cold_start_message_limit: Optional[int] = _env_optional_int("COLD_START_MESSAGE_LIMIT")
        self.cold_start_idle_minutes: int = _env_int("COLD_START_IDLE_MINUTES", 120, 1, 10080)
        self.mem_note_limit: int = _env_int("MEM_NOTE_LIMIT", 3, 1, 5)
        self.mem_note_min_score: float = _env_float("MEM_NOTE_MIN_SCORE", 0.45, 0.0, 1.0)
        self.mem_note_context_keyword_min_score: float = _env_float("MEM_NOTE_CONTEXT_KEYWORD_MIN_SCORE", 0.25, 0.05, 0.9)
        self.mem_note_semantic_min_score: float = _env_float("MEM_NOTE_SEMANTIC_MIN_SCORE", 0.40, 0.0, 1.0)
        self.mem_note_semantic_min_vector_score: float = _env_float("MEM_NOTE_SEMANTIC_MIN_VECTOR_SCORE", 0.50, 0.0, 1.0)
        self.mem_note_anchored_semantic_min_score: float = _env_float("MEM_NOTE_ANCHORED_SEMANTIC_MIN_SCORE", 0.30, 0.0, 1.0)
        self.mem_note_anchored_semantic_min_vector_score: float = _env_float("MEM_NOTE_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE", 0.42, 0.0, 1.0)
        self.mem_note_dedupe_turns: int = _env_int("MEM_NOTE_DEDUPE_TURNS", 6, 0, 50)
        self.mem_note_soft_cooldown_hours: int = _env_int("MEM_NOTE_SOFT_COOLDOWN_HOURS", 12, 0, 8760)
        self.mem_note_default_cooldown_hours: int = _env_int("MEM_NOTE_DEFAULT_COOLDOWN_HOURS", 12, 0, 8760)
        self.heartbeat_inject_every: int = _env_int("HEARTBEAT_INJECT_EVERY", 5, 1, 50)
        self.enable_heartbeat_archive: bool = _env_bool("ENABLE_HEARTBEAT_ARCHIVE", True)
        self.enable_chat_archive: bool = _env_bool("ENABLE_CHAT_ARCHIVE", True)
        self.chat_archive_seen_retention: int = _env_int("CHAT_ARCHIVE_SEEN_RETENTION", 10000, 1000, 200000)
        self.heartbeat_archive_settle_hours: int = _env_int("HEARTBEAT_ARCHIVE_SETTLE_HOURS", 6, 0, 720)
        self.heartbeat_archive_interval_seconds: int = _env_int("HEARTBEAT_ARCHIVE_INTERVAL_SECONDS", 600, 60, 86400)
        self.heartbeat_archive_batch_size: int = _env_int("HEARTBEAT_ARCHIVE_BATCH_SIZE", 200, 1, 1000)
        self.heartbeat_archive_reconcile_deletions: bool = _env_bool(
            "HEARTBEAT_ARCHIVE_RECONCILE_DELETIONS", False
        )
        self.gateway_message_retention: int = _env_int("GATEWAY_MESSAGE_RETENTION", 1500, 50, 200000)
        self.gateway_context_snapshot_retention: int = _env_int("GATEWAY_CONTEXT_SNAPSHOT_RETENTION", 3, 1, 100)
        self.gateway_cold_start_retention: int = _env_int("GATEWAY_COLD_START_RETENTION", 20, 1, 1000)
        self.gateway_request_log_retention: int = _env_int("GATEWAY_REQUEST_LOG_RETENTION", 200, 30, 5000)
        self.gateway_log_full_payloads: bool = _env_bool("GATEWAY_LOG_FULL_PAYLOADS", False)

        self.enable_room_mode: bool = _env_bool("ENABLE_ROOM_MODE", True)
        self.room_charge_refractory_hours: int = _env_int("ROOM_CHARGE_REFRACTORY_HOURS", 4, 1, 48)
        self.room_trace_limit: int = _env_int("ROOM_TRACE_LIMIT", 5, 1, 20)
        self.room_newspaper_qa_enabled: bool = _env_bool("ROOM_NEWSPAPER_QA_ENABLED", False)
        self.room_newspaper_llm_model: str = os.getenv("ROOM_NEWSPAPER_LLM_MODEL", "").strip()
        self.room_newspaper_llm_url: str = os.getenv("ROOM_NEWSPAPER_LLM_URL", "").strip()
        self.room_newspaper_llm_api_key: str = os.getenv("ROOM_NEWSPAPER_LLM_API_KEY", "").strip()
        self.room_newspaper_llm_protocol: str = os.getenv("ROOM_NEWSPAPER_LLM_PROTOCOL", "").strip().lower()

        self.weather_city: str = (os.getenv("WEATHER_CITY") or "").strip() or "邵阳"
        self.qweather_api_key: str = os.getenv("QWEATHER_API_KEY", "").strip()
        self.qweather_api_host: str = os.getenv("QWEATHER_API_HOST", "").strip()

        self.serper_api_key: str = os.getenv("SERPER_API_KEY", "").strip()
        self.jina_api_key: str = os.getenv("JINA_API_KEY", "").strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "supabase_url": mask(self.supabase_url, 30),
            "supabase_key": mask(self.supabase_key),
            "gateway_key": mask(self.gateway_key),
            "upstream_url": self.upstream_url,
            "upstream_api_key": mask(self.upstream_api_key),
            "upstream_protocol": self.upstream_protocol,
            "upstream_proxy": self.upstream_proxy,
            "upstream_trust_env": self.upstream_trust_env,
            "enable_openai_cache_control": self.enable_openai_cache_control,
            "enable_anthropic_cache_control": self.enable_anthropic_cache_control,
            "openai_cache_ttl": self.openai_cache_ttl,
            "anthropic_cache_ttl": self.anthropic_cache_ttl,
            "enable_anthropic_auto_thinking": self.enable_anthropic_auto_thinking,
            "anthropic_auto_thinking_effort": self.anthropic_auto_thinking_effort,
            "anthropic_default_max_tokens": self.anthropic_default_max_tokens,
            "upstream_extra_body": self.upstream_extra_body,
            "upstream_passthrough_headers": self.upstream_passthrough_headers,
            "wake_welcome_message": self.wake_welcome_message,
            "echo_prompt": self.echo_prompt,
            "echo_retention_turns": self.echo_retention_turns,
            "inject_inline_memory_prompt": self.inject_inline_memory_prompt,
            "enable_inline_memory_capture": self.enable_inline_memory_capture,
            "model_mapping": self.model_mapping,
            "calendar_inject_day": self.calendar_inject_day,
            "calendar_inject_week": self.calendar_inject_week,
            "calendar_inject_month": self.calendar_inject_month,
            "inject_mem_notes": self.inject_mem_notes,
            "inject_island_bumps": self.inject_island_bumps,
            "island_bump_limit": self.island_bump_limit,
            "inject_stars": self.inject_stars,
            "inject_star_prompt": self.inject_star_prompt,
            "enable_inline_star_capture": self.enable_inline_star_capture,
            "enable_star_embeddings": self.enable_star_embeddings,
            "star_inject_limit": self.star_inject_limit,
            "star_review_new_limit": self.star_review_new_limit,
            "star_review_candidates_per_star": self.star_review_candidates_per_star,
            "star_review_total_candidate_limit": self.star_review_total_candidate_limit,
            "star_chat_explicit_fallback_limit": self.star_chat_explicit_fallback_limit,
            "star_candidate_limit": self.star_candidate_limit,
            "star_shadow_candidate_limit": self.star_shadow_candidate_limit,
            "star_min_score": self.star_min_score,
            "star_related_min_score": self.star_related_min_score,
            "star_recent_fatigue_hours": self.star_recent_fatigue_hours,
            "star_recent_fatigue_penalty": self.star_recent_fatigue_penalty,
            "star_soft_direct_cooldown_turns": self.star_soft_direct_cooldown_turns,
            "star_rrf_ch_content": self.star_rrf_ch_content,
            "star_rrf_ch_keyword": self.star_rrf_ch_keyword,
            "star_rrf_ch_chord": self.star_rrf_ch_chord,
            "star_rrf_ch_harmony": self.star_rrf_ch_harmony,
            "star_rrf_ch_scene": self.star_rrf_ch_scene,
            "star_rrf_ch_explicit": self.star_rrf_ch_explicit,
            "star_rrf_k": self.star_rrf_k,
            "star_rrf_actr_floor": self.star_rrf_actr_floor,
            "star_rrf_constant_boost": self.star_rrf_constant_boost,
            "star_rrf_date_boost_max": self.star_rrf_date_boost_max,
            "inject_conflict_shelf": self.inject_conflict_shelf,
            "enable_cold_start": self.enable_cold_start,
            "enable_upstream_tools": self.enable_upstream_tools,
            "enable_gateway_tools": self.enable_gateway_tools,
            "enable_stream_duplicate_guard": self.enable_stream_duplicate_guard,
            "enable_mem0_management_tools": self.enable_mem0_management_tools,
            "expose_supabase_tools": self.expose_supabase_tools,
            "gateway_tool_mode": self.gateway_tool_mode,
            "gateway_tool_surface": self.gateway_tool_surface,
            "client_tool_surface": self.client_tool_surface,
            "enable_mcp_tools": self.enable_mcp_tools,
            "mcp_servers": [
                {**server, "headers": {key: mask(value) for key, value in (server.get("headers") or {}).items()}}
                for server in self.mcp_servers
            ],
            "mcp_call_timeout_seconds": self.mcp_call_timeout_seconds,
            "mcp_list_timeout_seconds": self.mcp_list_timeout_seconds,
            "mcp_tools_cache_seconds": self.mcp_tools_cache_seconds,
            "mcp_tool_result_keep_recent": self.mcp_tool_result_keep_recent,
            "max_internal_tool_rounds": self.max_internal_tool_rounds,
            "enable_recall_auto_sync": self.enable_recall_auto_sync,
            "recall_candidate_limit": self.recall_candidate_limit,
            "recall_vector_min_score": self.recall_vector_min_score,
            "enable_recall_sync_worker": self.enable_recall_sync_worker,
            "recall_sync_worker_interval_seconds": self.recall_sync_worker_interval_seconds,
            "enable_recall_embeddings": self.enable_recall_embeddings,
            "enable_recall_embedding_worker": self.enable_recall_embedding_worker,
            "recall_embedding_worker_interval_seconds": self.recall_embedding_worker_interval_seconds,
            "recall_embedding_worker_batch_size": self.recall_embedding_worker_batch_size,
            "embedding_base_url": self.embedding_base_url,
            "embedding_api_key": mask(self.embedding_api_key) if self.embedding_api_key else "",
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "gateway_db_path": self.gateway_db_path,
            "calendar_context_day_limit": self.calendar_context_day_limit,
            "calendar_context_day_offset": self.calendar_context_day_offset,
            "calendar_context_week_limit": self.calendar_context_week_limit,
            "calendar_context_month_limit": self.calendar_context_month_limit,
            "max_client_messages": self.max_client_messages,
            "island_tail_messages": self.island_tail_messages,
            "cold_start_message_limit": self.cold_start_message_limit,
            "cold_start_idle_minutes": self.cold_start_idle_minutes,
            "mem_note_limit": self.mem_note_limit,
            "mem_note_min_score": self.mem_note_min_score,
            "mem_note_context_keyword_min_score": self.mem_note_context_keyword_min_score,
            "mem_note_semantic_min_score": self.mem_note_semantic_min_score,
            "mem_note_semantic_min_vector_score": self.mem_note_semantic_min_vector_score,
            "mem_note_anchored_semantic_min_score": self.mem_note_anchored_semantic_min_score,
            "mem_note_anchored_semantic_min_vector_score": self.mem_note_anchored_semantic_min_vector_score,
            "mem_note_dedupe_turns": self.mem_note_dedupe_turns,
            "mem_note_soft_cooldown_hours": self.mem_note_soft_cooldown_hours,
            "mem_note_default_cooldown_hours": self.mem_note_default_cooldown_hours,
            "heartbeat_inject_every": self.heartbeat_inject_every,
            "enable_heartbeat_archive": self.enable_heartbeat_archive,
            "enable_chat_archive": self.enable_chat_archive,
            "chat_archive_seen_retention": self.chat_archive_seen_retention,
            "heartbeat_archive_settle_hours": self.heartbeat_archive_settle_hours,
            "heartbeat_archive_interval_seconds": self.heartbeat_archive_interval_seconds,
            "heartbeat_archive_batch_size": self.heartbeat_archive_batch_size,
            "heartbeat_archive_reconcile_deletions": self.heartbeat_archive_reconcile_deletions,
            "gateway_message_retention": self.gateway_message_retention,
            "gateway_context_snapshot_retention": self.gateway_context_snapshot_retention,
            "gateway_cold_start_retention": self.gateway_cold_start_retention,
            "gateway_request_log_retention": self.gateway_request_log_retention,
            "gateway_log_full_payloads": self.gateway_log_full_payloads,
            "enable_room_mode": self.enable_room_mode,
            "room_charge_refractory_hours": self.room_charge_refractory_hours,
            "room_trace_limit": self.room_trace_limit,
            "room_newspaper_qa_enabled": self.room_newspaper_qa_enabled,
            "room_newspaper_llm_model": self.room_newspaper_llm_model,
            "room_newspaper_llm_url": self.room_newspaper_llm_url,
            "room_newspaper_llm_api_key": mask(self.room_newspaper_llm_api_key) if self.room_newspaper_llm_api_key else "",
            "room_newspaper_llm_protocol": self.room_newspaper_llm_protocol,
            "weather_city": self.weather_city,
            "qweather_api_key": mask(self.qweather_api_key) if self.qweather_api_key else "",
            "qweather_api_host": self.qweather_api_host,
            "serper_api_key": mask(self.serper_api_key) if self.serper_api_key else "",
            "jina_api_key": mask(self.jina_api_key) if self.jina_api_key else "",
        }

    def _load_model_mapping(self) -> dict[str, str]:
        raw = os.getenv("MODEL_MAPPING", "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(key).strip(): str(value).strip()
            for key, value in data.items()
            if str(key).strip() and str(value).strip()
        }

    def _load_mcp_servers(self) -> list[dict[str, Any]]:
        raw = os.getenv("MCP_SERVERS", "").strip()
        if not raw:
            return []
        from .mcp_registry import validate_mcp_servers

        try:
            return validate_mcp_servers(raw)
        except ValueError as exc:
            # A malformed env value must not prevent gateway boot; drop the
            # list and let the owner fix it in the Admin panel.
            logger.warning("MCP_SERVERS invalid, ignoring: %s", exc)
            return []

    def _load_upstream_extra_body(self) -> dict[str, Any]:
        """Load UPSTREAM_EXTRA_BODY; auto-migrate legacy UPSTREAM_PROVIDER_* once.

        The standalone provider-order controls were folded into the extra body so
        request-body customization has a single source of truth. If the legacy
        UPSTREAM_PROVIDER_ORDER was enabled and the extra body does not already pin
        a provider field, the configured providers are injected once and a warning
        is logged so operators can move the value into UPSTREAM_EXTRA_BODY.
        """
        body: dict[str, Any] = {}
        raw = os.getenv("UPSTREAM_EXTRA_BODY", "").strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                body = {str(k): v for k, v in data.items() if str(k)}
        if "provider" not in body and _env_bool("UPSTREAM_PROVIDER_ORDER_ENABLED", False) and self.upstream_protocol != "anthropic":
            providers = self._parse_legacy_provider_order()
            if providers:
                fmt = str(os.getenv("UPSTREAM_PROVIDER_FORMAT", "string") or "").strip().lower().replace("-", "_")
                fmt = fmt if fmt in {"string", "order_object"} else "string"
                body["provider"] = providers[0] if fmt == "string" else {"order": list(providers)}
                logger.warning(
                    "UPSTREAM_PROVIDER_ORDER auto-migrated into upstream_extra_body[provider]=%r; "
                    "move it into UPSTREAM_EXTRA_BODY, the legacy UPSTREAM_PROVIDER_* vars will be removed.",
                    body["provider"],
                )
        return body

    @staticmethod
    def _parse_legacy_provider_order() -> list[str]:
        raw = os.getenv("UPSTREAM_PROVIDER_ORDER", "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw.split(",")
        if isinstance(data, str):
            data = [data]
        if not isinstance(data, list):
            return []
        seen: set[str] = set()
        providers: list[str] = []
        for item in data:
            provider = str(item or "").strip()
            if not provider or provider in seen:
                continue
            seen.add(provider)
            providers.append(provider)
        return providers

    def _load_passthrough_headers(self) -> list[str]:
        raw = os.getenv("UPSTREAM_PASSTHROUGH_HEADERS", "").strip()
        if not raw:
            return ["x-api-key"]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw.split(",")
        if isinstance(data, str):
            data = [data]
        if not isinstance(data, list):
            return []
        seen: set[str] = set()
        names: list[str] = []
        for item in data:
            name = str(item or "").strip().lower()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def _normalize_tool_mode(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        return raw if raw in {"full", "broker"} else "broker"
