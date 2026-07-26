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
    max_tokens: Optional[int] = Field(default=None, ge=1)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    tools: Optional[list[dict]] = None
    thinking: Optional[Any] = None
    output_config: Optional[dict[str, Any]] = None
    reasoning_effort: Optional[str] = None


class ConfigUpdate(BaseModel):
    gateway_key: Optional[str] = None
    upstream_url: Optional[str] = None
    upstream_api_key: Optional[str] = None
    upstream_protocol: Optional[str] = None
    upstream_proxy: Optional[str] = None
    upstream_trust_env: Optional[bool] = None
    enable_openai_cache_control: Optional[bool] = None
    enable_anthropic_cache_control: Optional[bool] = None
    openai_cache_ttl: Optional[str] = None
    anthropic_cache_ttl: Optional[str] = None
    enable_anthropic_auto_thinking: Optional[bool] = None
    anthropic_auto_thinking_effort: Optional[str] = None
    anthropic_default_max_tokens: Optional[int] = Field(default=None, ge=1)
    upstream_extra_body: Optional[dict[str, Any] | str] = None
    upstream_passthrough_headers: Optional[list[str] | str] = None
    calendar_upstream_url: Optional[str] = None
    calendar_api_key: Optional[str] = None
    calendar_protocol: Optional[str] = None
    calendar_model: Optional[str] = None
    wake_welcome_message: Optional[str] = None
    clear_wake_welcome_message: Optional[bool] = None
    inject_inline_memory_prompt: Optional[bool] = None
    enable_inline_memory_capture: Optional[bool] = None
    model_mapping: Optional[dict[str, str]] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    calendar_inject_day: Optional[bool] = None
    calendar_inject_week: Optional[bool] = None
    calendar_inject_month: Optional[bool] = None
    inject_mem_notes: Optional[bool] = None
    inject_stars: Optional[bool] = None
    inject_star_prompt: Optional[bool] = None
    enable_inline_star_capture: Optional[bool] = None
    enable_star_embeddings: Optional[bool] = None
    star_inject_limit: Optional[int] = None
    star_review_new_limit: Optional[int] = None
    star_review_candidates_per_star: Optional[int] = None
    star_review_total_candidate_limit: Optional[int] = None
    star_chat_explicit_fallback_limit: Optional[int] = None
    star_candidate_limit: Optional[int] = None
    star_shadow_candidate_limit: Optional[int] = None
    star_min_score: Optional[float] = None
    star_related_min_score: Optional[float] = None
    star_recent_fatigue_hours: Optional[int] = None
    star_recent_fatigue_penalty: Optional[float] = None
    star_soft_direct_cooldown_turns: Optional[int] = None
    star_rrf_ch_content: Optional[float] = None
    star_rrf_ch_keyword: Optional[float] = None
    star_rrf_ch_chord: Optional[float] = None
    star_rrf_ch_harmony: Optional[float] = None
    star_rrf_ch_scene: Optional[float] = None
    star_rrf_ch_explicit: Optional[float] = None
    star_rrf_k: Optional[int] = None
    star_rrf_actr_floor: Optional[float] = None
    star_rrf_constant_boost: Optional[float] = None
    star_rrf_date_boost_max: Optional[float] = None
    star_scene_llm_model: Optional[str] = None
    star_scene_llm_url: Optional[str] = None
    star_scene_llm_api_key: Optional[str] = None
    star_scene_llm_protocol: Optional[str] = None
    room_newspaper_qa_enabled: Optional[bool] = None
    room_newspaper_llm_model: Optional[str] = None
    room_newspaper_llm_url: Optional[str] = None
    room_newspaper_llm_api_key: Optional[str] = None
    room_newspaper_llm_protocol: Optional[str] = None
    weather_city: Optional[str] = None
    qweather_api_key: Optional[str] = None
    qweather_api_host: Optional[str] = None
    enable_cold_start: Optional[bool] = None
    enable_upstream_tools: Optional[bool] = None
    enable_gateway_tools: Optional[bool] = None
    enable_stream_duplicate_guard: Optional[bool] = None
    enable_mem0_management_tools: Optional[bool] = None
    expose_supabase_tools: Optional[bool] = None
    gateway_tool_mode: Optional[str] = None
    gateway_tool_surface: Optional[str] = None
    client_tool_surface: Optional[str] = None
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
    gateway_request_log_retention: Optional[int] = None
    gateway_log_full_payloads: Optional[bool] = None


class SessionDeleteRequest(BaseModel):
    confirm: str


class HeartbeatCreateRequest(BaseModel):
    content: str
    turn_number: Optional[int] = None


class HeartbeatDeleteRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    delete_all: bool = False
    confirm: Optional[str] = None


class DrawerNoteCreateRequest(BaseModel):
    content: str


class DrawerNoteMarkReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class ColdStartPreviewRequest(BaseModel):
    target_session_tag: Optional[str] = None
    source_session_tag: Optional[str] = None
    current_message_count: Optional[int] = None
    message_limit: Optional[int] = Field(default=None, ge=1, le=500)
    persist: bool = True


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
    entities: Optional[list[str] | str] = None
    status: Optional[str] = None
    cooldown_hours: Optional[int] = None
    review_note: Optional[str] = None
    # v2 structured fields
    summary: Optional[str] = None
    memory_kind: Optional[str] = None
    people: Optional[list[str] | str] = None
    places: Optional[list[str] | str] = None
    objects: Optional[list[str] | str] = None
    keywords: Optional[list[str] | str] = None
    event_time: Optional[str] = None
    importance: Optional[int] = None
    mention_count: Optional[int] = None
    promotion_score: Optional[float] = None
    decay_after: Optional[str] = None
    # promise
    promise_text: Optional[str] = None
    trigger_scenarios: Optional[list[str] | str] = None
    due_hint: Optional[str] = None
    resolved: Optional[bool] = None
    resolved_at: Optional[str] = None
    next_action: Optional[str] = None
    privacy_level: Optional[str] = None
    # running_joke
    joke_text: Optional[str] = None
    scene_tags: Optional[list[str] | str] = None
    last_used_at: Optional[str] = None
    # routine
    routine_domain: Optional[str] = None
    pattern: Optional[str] = None
    phase: Optional[str] = None
    constraints: Optional[list[str] | str] = None
    last_confirmed_at: Optional[str] = None
    # thread
    topic: Optional[str] = None
    last_position: Optional[str] = None
    open_questions: Optional[list[str] | str] = None
    next_prompt: Optional[str] = None
    thread_resolved: Optional[bool] = None


class MemNoteBulkPatch(BaseModel):
    ids: list[str] = Field(default_factory=list)
    patch: dict[str, Any] = Field(default_factory=dict)
    updates: list[dict[str, Any]] = Field(default_factory=list)
    use_suggestions: bool = False


class MemoryGraphEntityCreate(BaseModel):
    entity_type: str
    canonical_name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryGraphEntityPatch(BaseModel):
    entity_type: Optional[str] = None
    canonical_name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    merged_into: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class MemoryGraphAliasCreate(BaseModel):
    alias: str
    status: str = "confirmed"
    evidence: str = ""
    provenance: str = "manual"


class MemoryGraphRelationCreate(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    status: str = "confirmed"
    evidence: str = ""
    provenance: str = "manual"
    evidence_source_table: Optional[str] = None
    evidence_source_type: Optional[str] = None
    evidence_source_id: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None


class MemoryGraphRelationPatch(BaseModel):
    relation_type: Optional[str] = None
    status: Optional[str] = None
    evidence: Optional[str] = None
    provenance: Optional[str] = None
    evidence_source_table: Optional[str] = None
    evidence_source_type: Optional[str] = None
    evidence_source_id: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None


class MemoryGraphSourceEntitiesPut(BaseModel):
    source_table: str
    source_type: str
    source_id: str
    entity_ids: list[str] = Field(default_factory=list)
    evidence: str = ""


class MemoryGraphBackfillRequest(BaseModel):
    max_sources: Optional[int] = Field(default=None, ge=1, le=100000)


class MemoryGraphRecallPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=8)


class StarCreateRequest(BaseModel):
    content: str
    chord: Optional[str] = None
    chords: list[str] = Field(default_factory=list)
    session_tag: Optional[str] = None
    status: str = "active"
    is_constant: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class StarFeedbackItem(BaseModel):
    feedback: str
    run_id: Optional[str] = None
    candidate_id: Optional[str] = None
    candidate_star_id: Optional[str] = None
    expected_star_id: Optional[str] = None
    scored_by: str = "圆圆"
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class StarFeedbackRequest(BaseModel):
    feedback: Optional[str] = None
    run_id: Optional[str] = None
    candidate_id: Optional[str] = None
    candidate_star_id: Optional[str] = None
    expected_star_id: Optional[str] = None
    scored_by: str = "圆圆"
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    items: list[StarFeedbackItem] = Field(default_factory=list)


class StarConnectRequest(BaseModel):
    star_ids: list[str]
    name: Optional[str] = None
    relation_type: str = "constellation"
    scored_by: str = "圆圆"
    note: str = ""


class StarConstantRequest(BaseModel):
    is_constant: bool = True


class StarSceneBackfillRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)


class StarScenesRequest(BaseModel):
    scenes: list[str] = Field(default_factory=list)
