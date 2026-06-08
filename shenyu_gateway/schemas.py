from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: Optional[Any] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict]] = None


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: Optional[int] = Field(default=4096, ge=1, le=8192)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    tools: Optional[list[dict]] = None


class ConfigUpdate(BaseModel):
    gateway_key: Optional[str] = None
    upstream_url: Optional[str] = None
    upstream_api_key: Optional[str] = None
    upstream_protocol: Optional[str] = None
    upstream_proxy: Optional[str] = None
    upstream_trust_env: Optional[bool] = None
    enable_openai_cache_control: Optional[bool] = None
    hisense_upstream_url: Optional[str] = None
    hisense_api_key: Optional[str] = None
    hisense_protocol: Optional[str] = None
    calendar_upstream_url: Optional[str] = None
    calendar_api_key: Optional[str] = None
    calendar_protocol: Optional[str] = None
    calendar_model: Optional[str] = None
    wake_welcome_message: Optional[str] = None
    inject_inline_memory_prompt: Optional[bool] = None
    enable_inline_memory_capture: Optional[bool] = None
    model_mapping: Optional[dict[str, str]] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    calendar_inject_day: Optional[bool] = None
    calendar_inject_week: Optional[bool] = None
    calendar_inject_month: Optional[bool] = None
    inject_mem_notes: Optional[bool] = None
    enable_cold_start: Optional[bool] = None
    enable_upstream_tools: Optional[bool] = None
    enable_gateway_tools: Optional[bool] = None
    enable_mem0_management_tools: Optional[bool] = None
    expose_supabase_tools: Optional[bool] = None
    gateway_tool_mode: Optional[str] = None
    max_internal_tool_rounds: Optional[int] = None
    gateway_db_path: Optional[str] = None
    calendar_context_day_limit: Optional[int] = None
    calendar_context_week_limit: Optional[int] = None
    calendar_context_month_limit: Optional[int] = None
    max_client_messages: Optional[int] = None
    cold_start_message_limit: Optional[int] = None
    cold_start_idle_minutes: Optional[int] = None
    default_surface_limit: Optional[int] = None
    mem_note_limit: Optional[int] = None
    mem_note_min_score: Optional[float] = None
    mem_note_context_keyword_min_score: Optional[float] = None
    mem_note_semantic_min_score: Optional[float] = None
    mem_note_semantic_min_vector_score: Optional[float] = None
    mem_note_anchored_semantic_min_score: Optional[float] = None
    mem_note_anchored_semantic_min_vector_score: Optional[float] = None
    mem_note_dedupe_turns: Optional[int] = None
    mem_note_soft_cooldown_hours: Optional[int] = None
    mem_note_default_cooldown_hours: Optional[int] = None
    heartbeat_inject_every: Optional[int] = None
    gateway_message_retention: Optional[int] = None
    gateway_context_snapshot_retention: Optional[int] = None
    gateway_cold_start_retention: Optional[int] = None
    hisense_client_name: Optional[str] = None
    hisense_heartbeat_limit: Optional[int] = None
    hisense_notebook_limit: Optional[int] = None


class SessionDeleteRequest(BaseModel):
    confirm: str


class HeartbeatCreateRequest(BaseModel):
    content: str
    turn_number: Optional[int] = None


class HeartbeatDeleteRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    delete_all: bool = False
    confirm: Optional[str] = None


class CalendarPromptUpdate(BaseModel):
    prompt_type: str
    name: Optional[str] = None
    content: str
    note: Optional[str] = None
    is_active: bool = True


class CalendarGenerateRequest(BaseModel):
    period_type: str
    period_key: Optional[str] = None
    model: Optional[str] = None
    session_tag: Optional[str] = None


class MemNotePatch(BaseModel):
    content: Optional[str] = None
    mem_type: Optional[str] = None
    trigger_text: Optional[str] = None
    trigger_keywords: Optional[list[str] | str] = None
    status: Optional[str] = None
    cooldown_hours: Optional[int] = None
    review_note: Optional[str] = None


class MemNoteBulkPatch(BaseModel):
    ids: list[str] = Field(default_factory=list)
    patch: dict[str, Any] = Field(default_factory=dict)
    updates: list[dict[str, Any]] = Field(default_factory=list)
    use_suggestions: bool = False
