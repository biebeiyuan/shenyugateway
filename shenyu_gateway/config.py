from __future__ import annotations

import os
import json
from typing import Any, Optional

from .runtime import mask, _env_bool


def _env_optional_int(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
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
        self.hisense_upstream_url: str = os.getenv("HISENSE_UPSTREAM_URL", "").strip()
        self.hisense_api_key: str = os.getenv("HISENSE_API_KEY", "").strip()
        self.hisense_protocol: str = os.getenv("HISENSE_PROTOCOL", "").strip().lower()
        self.calendar_upstream_url: str = os.getenv("CALENDAR_UPSTREAM_URL", "").strip()
        self.calendar_api_key: str = os.getenv("CALENDAR_API_KEY", "").strip()
        self.calendar_protocol: str = os.getenv("CALENDAR_PROTOCOL", "auto").strip().lower()
        self.calendar_model: str = os.getenv("CALENDAR_MODEL", "claude-opus-4-7").strip()
        self.wake_welcome_message: str = os.getenv("WAKE_WELCOME_MESSAGE", "").strip()
        self.enable_inline_memory_capture: bool = _env_bool("ENABLE_INLINE_MEMORY_CAPTURE", False)
        self.inject_inline_memory_prompt: bool = _env_bool(
            "INJECT_INLINE_MEMORY_PROMPT",
            self.enable_inline_memory_capture,
        )
        self.model_mapping: dict[str, str] = self._load_model_mapping()

        self.inject_meta_summaries: bool = _env_bool("INJECT_META_SUMMARIES", True)
        self.calendar_inject_day: bool = _env_bool("CALENDAR_INJECT_DAY", True)
        self.calendar_inject_week: bool = _env_bool("CALENDAR_INJECT_WEEK", True)
        self.calendar_inject_month: bool = _env_bool("CALENDAR_INJECT_MONTH", True)
        self.inject_mem_notes: bool = _env_bool("INJECT_MEM_NOTES", False)
        self.enable_cold_start: bool = _env_bool("ENABLE_COLD_START", True)
        self.enable_gateway_tools: bool = _env_bool("ENABLE_GATEWAY_TOOLS", False)
        self.enable_mem0_management_tools: bool = _env_bool("ENABLE_MEM0_MANAGEMENT_TOOLS", False)
        self.expose_supabase_tools: bool = _env_bool("EXPOSE_SUPABASE_TOOLS", True)
        self.gateway_tool_mode: str = self._normalize_tool_mode(os.getenv("GATEWAY_TOOL_MODE", "broker"))
        self.max_internal_tool_rounds: int = _env_int("MAX_INTERNAL_TOOL_ROUNDS", 4, 1)
        self.enable_recall_auto_sync: bool = _env_bool("ENABLE_RECALL_AUTO_SYNC", False)
        self.recall_candidate_limit: int = _env_int("RECALL_CANDIDATE_LIMIT", 160, 20, 1000)
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
        self.calendar_context_week_limit: int = _env_int("CALENDAR_CONTEXT_WEEK_LIMIT", 1, 1, 12)
        self.calendar_context_month_limit: int = _env_int("CALENDAR_CONTEXT_MONTH_LIMIT", 1, 1, 12)
        self.max_client_messages: Optional[int] = _env_optional_int("MAX_CLIENT_MESSAGES")
        self.cold_start_message_limit: Optional[int] = _env_optional_int("COLD_START_MESSAGE_LIMIT")
        self.cold_start_idle_minutes: int = _env_int("COLD_START_IDLE_MINUTES", 120, 1, 10080)
        self.default_surface_limit: int = _env_int("DEFAULT_SURFACE_LIMIT", 3, 1, 8)
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
        self.gateway_message_retention: int = _env_int("GATEWAY_MESSAGE_RETENTION", 1500, 50, 200000)
        self.gateway_context_snapshot_retention: int = _env_int("GATEWAY_CONTEXT_SNAPSHOT_RETENTION", 3, 1, 100)
        self.gateway_cold_start_retention: int = _env_int("GATEWAY_COLD_START_RETENTION", 20, 1, 1000)

        self.hisense_client_name: str = os.getenv("HISENSE_CLIENT_NAME", "hisense").strip()
        self.hisense_heartbeat_limit: int = _env_int("HISENSE_HEARTBEAT_LIMIT", 3, 1, 30)
        self.hisense_notebook_limit: int = _env_int("HISENSE_NOTEBOOK_LIMIT", 5, 1, 20)

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
            "hisense_upstream_url": self.hisense_upstream_url,
            "hisense_api_key": mask(self.hisense_api_key),
            "hisense_protocol": self.hisense_protocol,
            "calendar_upstream_url": self.calendar_upstream_url,
            "calendar_api_key": mask(self.calendar_api_key),
            "calendar_protocol": self.calendar_protocol,
            "calendar_model": self.calendar_model,
            "wake_welcome_message": self.wake_welcome_message,
            "inject_inline_memory_prompt": self.inject_inline_memory_prompt,
            "enable_inline_memory_capture": self.enable_inline_memory_capture,
            "model_mapping": self.model_mapping,
            "inject_meta_summaries": self.inject_meta_summaries,
            "calendar_inject_day": self.calendar_inject_day,
            "calendar_inject_week": self.calendar_inject_week,
            "calendar_inject_month": self.calendar_inject_month,
            "inject_mem_notes": self.inject_mem_notes,
            "enable_cold_start": self.enable_cold_start,
            "enable_gateway_tools": self.enable_gateway_tools,
            "enable_mem0_management_tools": self.enable_mem0_management_tools,
            "expose_supabase_tools": self.expose_supabase_tools,
            "gateway_tool_mode": self.gateway_tool_mode,
            "max_internal_tool_rounds": self.max_internal_tool_rounds,
            "enable_recall_auto_sync": self.enable_recall_auto_sync,
            "recall_candidate_limit": self.recall_candidate_limit,
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
            "calendar_context_week_limit": self.calendar_context_week_limit,
            "calendar_context_month_limit": self.calendar_context_month_limit,
            "max_client_messages": self.max_client_messages,
            "cold_start_message_limit": self.cold_start_message_limit,
            "cold_start_idle_minutes": self.cold_start_idle_minutes,
            "default_surface_limit": self.default_surface_limit,
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
            "gateway_message_retention": self.gateway_message_retention,
            "gateway_context_snapshot_retention": self.gateway_context_snapshot_retention,
            "gateway_cold_start_retention": self.gateway_cold_start_retention,
            "hisense_client_name": self.hisense_client_name,
            "hisense_heartbeat_limit": self.hisense_heartbeat_limit,
            "hisense_notebook_limit": self.hisense_notebook_limit,
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

    def _normalize_tool_mode(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        return raw if raw in {"full", "broker"} else "broker"
