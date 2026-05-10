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


class RuntimeConfig:
    def __init__(self):
        self.supabase_url: str = os.getenv("SUPABASE_URL", "")
        self.supabase_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
        self.gateway_key: str = os.getenv("GATEWAY_API_KEY", "")
        self.upstream_url: str = os.getenv("UPSTREAM_URL", "https://api.anthropic.com/v1/messages")
        self.upstream_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.upstream_version: str = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
        self.upstream_protocol: str = os.getenv("UPSTREAM_PROTOCOL", "auto")
        self.upstream_proxy: str = os.getenv("UPSTREAM_PROXY", "").strip()
        self.upstream_trust_env: bool = _env_bool("UPSTREAM_TRUST_ENV", False)
        self.calendar_upstream_url: str = os.getenv("CALENDAR_UPSTREAM_URL", "")
        self.calendar_api_key: str = os.getenv("CALENDAR_API_KEY", "")
        self.calendar_protocol: str = os.getenv("CALENDAR_PROTOCOL", "auto")
        self.calendar_model: str = os.getenv("CALENDAR_MODEL", "claude-opus-4-7")
        self.atomic_memory_upstream_url: str = os.getenv("ATOMIC_MEMORY_UPSTREAM_URL", "")
        self.atomic_memory_api_key: str = os.getenv("ATOMIC_MEMORY_API_KEY", "")
        self.atomic_memory_protocol: str = os.getenv("ATOMIC_MEMORY_PROTOCOL", "auto")
        self.atomic_memory_model: str = os.getenv("ATOMIC_MEMORY_MODEL", "")
        self.atomic_memory_prompt: str = os.getenv("ATOMIC_MEMORY_PROMPT", "")
        self.enable_inline_memory_capture: bool = _env_bool("ENABLE_INLINE_MEMORY_CAPTURE", False)
        self.inline_memory_prompt: str = os.getenv("INLINE_MEMORY_PROMPT", "")
        self.model_mapping: dict[str, str] = self._load_model_mapping()

        self.inject_meta_summaries: bool = _env_bool("INJECT_META_SUMMARIES", True)
        self.inject_briefing: bool = _env_bool("INJECT_BRIEFING", True)
        self.calendar_inject_day: bool = _env_bool("CALENDAR_INJECT_DAY", True)
        self.calendar_inject_week: bool = _env_bool("CALENDAR_INJECT_WEEK", True)
        self.calendar_inject_month: bool = _env_bool("CALENDAR_INJECT_MONTH", True)
        self.inject_atomic_memories: bool = _env_bool("INJECT_ATOMIC_MEMORIES", False)
        self.extract_atomic_memories: bool = _env_bool("EXTRACT_ATOMIC_MEMORIES", False)
        self.enable_cold_start: bool = _env_bool("ENABLE_COLD_START", True)
        self.enable_gateway_tools: bool = _env_bool("ENABLE_GATEWAY_TOOLS", False)
        self.enable_mem0_management_tools: bool = _env_bool("ENABLE_MEM0_MANAGEMENT_TOOLS", False)
        self.expose_supabase_tools: bool = _env_bool("EXPOSE_SUPABASE_TOOLS", True)
        self.max_internal_tool_rounds: int = int(os.getenv("MAX_INTERNAL_TOOL_ROUNDS", "3"))

        self.gateway_db_path: str = os.getenv("GATEWAY_DB_PATH", "./data/shenyu_gateway.db")
        self.daily_briefing_ttl_minutes: int = int(os.getenv("DAILY_BRIEFING_TTL_MINUTES", "60"))
        self.calendar_context_day_limit: int = int(os.getenv("CALENDAR_CONTEXT_DAY_LIMIT", "3"))
        self.calendar_context_week_limit: int = int(os.getenv("CALENDAR_CONTEXT_WEEK_LIMIT", "1"))
        self.calendar_context_month_limit: int = int(os.getenv("CALENDAR_CONTEXT_MONTH_LIMIT", "1"))
        self.max_client_messages: Optional[int] = _env_optional_int("MAX_CLIENT_MESSAGES")
        self.cold_start_turns: int = int(os.getenv("COLD_START_TURNS", "3"))
        self.cold_start_message_limit: int = int(os.getenv("COLD_START_MESSAGE_LIMIT", "8"))
        self.cold_start_idle_minutes: int = int(os.getenv("COLD_START_IDLE_MINUTES", "120"))
        self.default_surface_limit: int = int(os.getenv("DEFAULT_SURFACE_LIMIT", "3"))
        self.default_atomic_memory_limit: int = int(os.getenv("DEFAULT_ATOMIC_MEMORY_LIMIT", "3"))
        self.atomic_memory_max_tokens: int = int(os.getenv("ATOMIC_MEMORY_MAX_TOKENS", "8192"))
        self.atomic_memory_extract_every_turns: int = int(os.getenv("ATOMIC_MEMORY_EXTRACT_EVERY_TURNS", "1"))
        self.atomic_memory_min_score: float = float(os.getenv("ATOMIC_MEMORY_MIN_SCORE", "0.42"))
        self.atomic_memory_auto_activate_min_confidence: float = float(os.getenv("ATOMIC_MEMORY_AUTO_ACTIVATE_MIN_CONFIDENCE", "0.92"))
        self.heartbeat_inject_every: int = int(os.getenv("HEARTBEAT_INJECT_EVERY", "5"))
        self.gateway_message_retention: int = int(os.getenv("GATEWAY_MESSAGE_RETENTION", "1500"))
        self.gateway_context_snapshot_retention: int = int(os.getenv("GATEWAY_CONTEXT_SNAPSHOT_RETENTION", "3"))
        self.gateway_cold_start_retention: int = int(os.getenv("GATEWAY_COLD_START_RETENTION", "20"))
        self.gateway_surface_event_retention: int = int(os.getenv("GATEWAY_SURFACE_EVENT_RETENTION", "500"))
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
            "calendar_upstream_url": self.calendar_upstream_url,
            "calendar_api_key": mask(self.calendar_api_key),
            "calendar_protocol": self.calendar_protocol,
            "calendar_model": self.calendar_model,
            "atomic_memory_upstream_url": self.atomic_memory_upstream_url,
            "atomic_memory_api_key": mask(self.atomic_memory_api_key),
            "atomic_memory_protocol": self.atomic_memory_protocol,
            "atomic_memory_model": self.atomic_memory_model,
            "atomic_memory_prompt": self.atomic_memory_prompt,
            "enable_inline_memory_capture": self.enable_inline_memory_capture,
            "inline_memory_prompt": self.inline_memory_prompt,
            "model_mapping": self.model_mapping,
            "inject_meta_summaries": self.inject_meta_summaries,
            "inject_briefing": self.inject_briefing,
            "calendar_inject_day": self.calendar_inject_day,
            "calendar_inject_week": self.calendar_inject_week,
            "calendar_inject_month": self.calendar_inject_month,
            "inject_atomic_memories": self.inject_atomic_memories,
            "extract_atomic_memories": self.extract_atomic_memories,
            "enable_cold_start": self.enable_cold_start,
            "enable_gateway_tools": self.enable_gateway_tools,
            "enable_mem0_management_tools": self.enable_mem0_management_tools,
            "expose_supabase_tools": self.expose_supabase_tools,
            "max_internal_tool_rounds": self.max_internal_tool_rounds,
            "gateway_db_path": self.gateway_db_path,
            "daily_briefing_ttl_minutes": self.daily_briefing_ttl_minutes,
            "calendar_context_day_limit": self.calendar_context_day_limit,
            "calendar_context_week_limit": self.calendar_context_week_limit,
            "calendar_context_month_limit": self.calendar_context_month_limit,
            "max_client_messages": self.max_client_messages,
            "cold_start_turns": self.cold_start_turns,
            "cold_start_message_limit": self.cold_start_message_limit,
            "cold_start_idle_minutes": self.cold_start_idle_minutes,
            "default_surface_limit": self.default_surface_limit,
            "default_atomic_memory_limit": self.default_atomic_memory_limit,
            "atomic_memory_max_tokens": self.atomic_memory_max_tokens,
            "atomic_memory_extract_every_turns": self.atomic_memory_extract_every_turns,
            "atomic_memory_min_score": self.atomic_memory_min_score,
            "atomic_memory_auto_activate_min_confidence": self.atomic_memory_auto_activate_min_confidence,
            "heartbeat_inject_every": self.heartbeat_inject_every,
            "gateway_message_retention": self.gateway_message_retention,
            "gateway_context_snapshot_retention": self.gateway_context_snapshot_retention,
            "gateway_cold_start_retention": self.gateway_cold_start_retention,
            "gateway_surface_event_retention": self.gateway_surface_event_retention,
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
