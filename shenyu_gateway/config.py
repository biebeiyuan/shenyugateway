from __future__ import annotations

import os
from typing import Any

from .runtime import mask, _env_bool


class RuntimeConfig:
    def __init__(self):
        self.supabase_url: str = os.getenv("SUPABASE_URL", "")
        self.supabase_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
        self.gateway_key: str = os.getenv("GATEWAY_API_KEY", "")
        self.upstream_url: str = os.getenv("UPSTREAM_URL", "https://api.anthropic.com/v1/messages")
        self.upstream_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.upstream_version: str = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
        self.upstream_protocol: str = os.getenv("UPSTREAM_PROTOCOL", "auto")
        self.calendar_upstream_url: str = os.getenv("CALENDAR_UPSTREAM_URL", "")
        self.calendar_api_key: str = os.getenv("CALENDAR_API_KEY", "")
        self.calendar_protocol: str = os.getenv("CALENDAR_PROTOCOL", "auto")
        self.calendar_model: str = os.getenv("CALENDAR_MODEL", "claude-opus-4-7")

        self.inject_meta_summaries: bool = _env_bool("INJECT_META_SUMMARIES", True)
        self.inject_briefing: bool = _env_bool("INJECT_BRIEFING", True)
        self.inject_surface_passages: bool = _env_bool("INJECT_SURFACE_PASSAGES", True)
        self.enable_gateway_tools: bool = _env_bool("ENABLE_GATEWAY_TOOLS", False)
        self.expose_supabase_tools: bool = _env_bool("EXPOSE_SUPABASE_TOOLS", True)
        self.max_internal_tool_rounds: int = int(os.getenv("MAX_INTERNAL_TOOL_ROUNDS", "3"))

        self.gateway_db_path: str = os.getenv("GATEWAY_DB_PATH", "./data/shenyu_gateway.db")
        self.daily_briefing_ttl_minutes: int = int(os.getenv("DAILY_BRIEFING_TTL_MINUTES", "60"))
        self.summary_update_every_messages: int = int(os.getenv("SUMMARY_UPDATE_EVERY_MESSAGES", "6"))
        self.freeze_every_messages: int = int(os.getenv("FREEZE_EVERY_MESSAGES", "8"))
        self.freeze_tail_messages: int = int(os.getenv("FREEZE_TAIL_MESSAGES", "6"))
        self.default_surface_limit: int = int(os.getenv("DEFAULT_SURFACE_LIMIT", "3"))
        self.heartbeat_inject_every: int = int(os.getenv("HEARTBEAT_INJECT_EVERY", "10"))
    def to_dict(self) -> dict[str, Any]:
        return {
            "supabase_url": mask(self.supabase_url, 30),
            "supabase_key": mask(self.supabase_key),
            "gateway_key": mask(self.gateway_key),
            "upstream_url": self.upstream_url,
            "upstream_api_key": mask(self.upstream_api_key),
            "upstream_protocol": self.upstream_protocol,
            "calendar_upstream_url": self.calendar_upstream_url,
            "calendar_api_key": mask(self.calendar_api_key),
            "calendar_protocol": self.calendar_protocol,
            "calendar_model": self.calendar_model,
            "inject_meta_summaries": self.inject_meta_summaries,
            "inject_briefing": self.inject_briefing,
            "inject_surface_passages": self.inject_surface_passages,
            "enable_gateway_tools": self.enable_gateway_tools,
            "expose_supabase_tools": self.expose_supabase_tools,
            "max_internal_tool_rounds": self.max_internal_tool_rounds,
            "gateway_db_path": self.gateway_db_path,
            "daily_briefing_ttl_minutes": self.daily_briefing_ttl_minutes,
            "summary_update_every_messages": self.summary_update_every_messages,
            "freeze_every_messages": self.freeze_every_messages,
            "freeze_tail_messages": self.freeze_tail_messages,
            "default_surface_limit": self.default_surface_limit,
            "heartbeat_inject_every": self.heartbeat_inject_every,
        }
