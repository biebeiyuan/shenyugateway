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
    calendar_upstream_url: Optional[str] = None
    calendar_api_key: Optional[str] = None
    calendar_protocol: Optional[str] = None
    calendar_model: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    inject_meta_summaries: Optional[bool] = None
    inject_briefing: Optional[bool] = None
    inject_surface_passages: Optional[bool] = None
    enable_gateway_tools: Optional[bool] = None
    expose_supabase_tools: Optional[bool] = None
    max_internal_tool_rounds: Optional[int] = None
    gateway_db_path: Optional[str] = None
    daily_briefing_ttl_minutes: Optional[int] = None
    summary_update_every_messages: Optional[int] = None
    freeze_every_messages: Optional[int] = None
    freeze_tail_messages: Optional[int] = None
    default_surface_limit: Optional[int] = None


class SessionDeleteRequest(BaseModel):
    confirm: str


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
