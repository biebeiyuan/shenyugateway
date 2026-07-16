import { api } from './http'

export interface GatewayConfig {
  gateway_key: string
  gateway_key_configured?: boolean
  upstream_url: string
  upstream_api_key: string
  upstream_api_key_configured?: boolean
  upstream_protocol: string
  upstream_proxy?: string
  upstream_trust_env?: boolean
  enable_openai_cache_control?: boolean
  enable_anthropic_cache_control?: boolean
  openai_cache_ttl?: '5m' | '1h'
  anthropic_cache_ttl?: '5m' | '1h'
  enable_anthropic_auto_thinking?: boolean
  anthropic_auto_thinking_effort?: '' | 'max' | 'xhigh'
  upstream_extra_body?: Record<string, unknown>
  upstream_passthrough_headers?: string[]
  hisense_upstream_url?: string
  hisense_api_key?: string
  hisense_api_key_configured?: boolean
  hisense_protocol?: string
  supabase_url: string
  supabase_key: string
  supabase_key_configured?: boolean
  max_client_messages: number | null
  enable_cold_start: boolean
  cold_start_message_limit: number | null
  cold_start_idle_minutes: number
  model_mapping: Record<string, string>
  calendar_upstream_url?: string
  calendar_api_key?: string
  calendar_api_key_configured?: boolean
  calendar_protocol?: string
  calendar_model?: string
  wake_welcome_message?: string
  // mem notes
  inject_inline_memory_prompt?: boolean
  enable_inline_memory_capture?: boolean
  inject_mem_notes?: boolean
  mem_note_limit?: number
  mem_note_min_score?: number
  mem_note_context_keyword_min_score?: number
  mem_note_semantic_min_score?: number
  mem_note_semantic_min_vector_score?: number
  mem_note_anchored_semantic_min_score?: number
  mem_note_anchored_semantic_min_vector_score?: number
  mem_note_dedupe_turns?: number
  mem_note_soft_cooldown_hours?: number
  mem_note_default_cooldown_hours?: number
  // star memory
  inject_stars?: boolean
  inject_star_prompt?: boolean
  enable_inline_star_capture?: boolean
  enable_star_embeddings?: boolean
  star_inject_limit?: number
  star_review_new_limit?: number
  star_review_candidates_per_star?: number
  star_review_total_candidate_limit?: number
  star_chat_explicit_fallback_limit?: number
  star_candidate_limit?: number
  star_shadow_candidate_limit?: number
  star_min_score?: number
  star_related_min_score?: number
  star_recent_fatigue_hours?: number
  star_recent_fatigue_penalty?: number
  star_soft_direct_cooldown_turns?: number
  star_weight_content?: number
  star_weight_keyword?: number
  star_weight_harmony?: number
  star_weight_chord?: number
  star_weight_actr?: number
  star_constant_bonus?: number
  star_novelty_bonus?: number
  star_ignored_penalty?: number
  star_scene_llm_model?: string
  star_scene_llm_url?: string
  star_scene_llm_api_key?: string
  star_scene_llm_api_key_configured?: boolean
  star_scene_llm_protocol?: string
  // room newspaper optional quality check
  room_newspaper_qa_enabled?: boolean
  room_newspaper_llm_model?: string
  room_newspaper_llm_url?: string
  room_newspaper_llm_api_key?: string
  room_newspaper_llm_api_key_configured?: boolean
  room_newspaper_llm_protocol?: string
  // feature toggles
  enable_upstream_tools?: boolean
  calendar_inject_day?: boolean
  calendar_inject_week?: boolean
  calendar_inject_month?: boolean
  calendar_context_day_limit?: number
  calendar_context_week_limit?: number
  calendar_context_month_limit?: number

  enable_gateway_tools?: boolean
  enable_stream_duplicate_guard?: boolean
  enable_mem0_management_tools?: boolean
  expose_supabase_tools?: boolean
  gateway_tool_mode?: string
  gateway_tool_surface?: string
  client_tool_surface?: string
  max_internal_tool_rounds?: number
  default_surface_limit?: number
  heartbeat_inject_every?: number
  gateway_message_retention?: number
  gateway_context_snapshot_retention?: number
  gateway_cold_start_retention?: number
  gateway_request_log_retention?: number
  hisense_client_name?: string
  hisense_heartbeat_limit?: number
  hisense_notebook_limit?: number
  // stats
  gateway_db_path?: string
}

export interface HealthStatus {
  status: string
  supabase: boolean
  upstream: string
  upstream_chat_url?: string
  upstream_host?: string
  upstream_proxy_configured?: boolean
  upstream_trust_env?: boolean
  enable_openai_cache_control?: boolean
  enable_anthropic_cache_control?: boolean
  openai_cache_ttl?: '5m' | '1h'
  anthropic_cache_ttl?: '5m' | '1h'
  enable_anthropic_auto_thinking?: boolean
  anthropic_auto_thinking_effort?: '' | 'max' | 'xhigh'
  upstream_extra_body?: Record<string, unknown>
  hisense_upstream?: string
  hisense_upstream_chat_url?: string
  hisense_upstream_scope?: string
  hisense_protocol?: string
  models?: string[]
  protocol: string
  store?: boolean
  gateway_db_path?: string
  enable_upstream_tools?: boolean
  enable_gateway_tools?: boolean
  enable_stream_duplicate_guard?: boolean
  enable_mem0_management_tools?: boolean
  expose_supabase_tools?: boolean
  gateway_tool_mode?: string
  gateway_tool_surface?: string
  client_tool_surface?: string
  inject_mem_notes?: boolean
  enable_cold_start?: boolean
}

export interface SaveConfigResult {
  ok: boolean
  changed: string[]
  warnings?: string[]
  config: GatewayConfig
}

export type GatewayConfigPatch = Partial<GatewayConfig> & {
  clear_wake_welcome_message?: boolean
}

export interface GatewayOverview {
  messages_total: number
  messages_today: number
  sessions_total: number
  cold_start_snapshots: number
  context_snapshots?: number
  heartbeats?: number
  cache_entries?: number
  earliest_message_at: string | null
  latest_message_at: string | null
}

export type MemNoteType = '她为我做的事' | '我为她做的事' | '关于她的事实' | '关于我的事' | '心里那一档' | '承诺'
export type MemNoteStatus = 'captured' | 'active' | 'paused' | 'archived'
export type MemoryKind = 'event' | 'person_fact' | 'social' | 'trip' | 'object' | 'preference' | 'routine' | 'promise' | 'running_joke' | 'thread'

export interface MemNoteItem {
  id: string
  session_tag: string | null
  content: string
  mem_type: MemNoteType | '' | null
  trigger_text: string | null
  trigger_keywords: string[] | null
  entities: string[] | null
  status: MemNoteStatus
  cooldown_hours: number
  last_triggered_at: string | null
  trigger_count: number
  source_model?: string | null
  source_session_id?: string | null
  source_excerpt?: string | null
  review_note?: string | null
  reviewed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  suggested_mem_type?: MemNoteType | ''
  suggested_trigger_text?: string
  suggested_trigger_keywords?: string[]
  suggestion_reason?: string
  // v2 structured fields
  summary?: string | null
  memory_kind?: MemoryKind | null
  people?: string[] | null
  places?: string[] | null
  objects?: string[] | null
  keywords?: string[] | null
  event_time?: string | null
  importance?: number | null
  mention_count?: number | null
  promotion_score?: number | null
  decay_after?: string | null
  // promise
  promise_text?: string | null
  trigger_scenarios?: string[] | null
  due_hint?: string | null
  resolved?: boolean | null
  resolved_at?: string | null
  next_action?: string | null
  privacy_level?: string | null
  // running_joke
  joke_text?: string | null
  scene_tags?: string[] | null
  last_used_at?: string | null
  // routine
  routine_domain?: string | null
  pattern?: string | null
  phase?: string | null
  constraints?: string[] | null
  last_confirmed_at?: string | null
  // thread
  topic?: string | null
  last_position?: string | null
  open_questions?: string[] | null
  next_prompt?: string | null
  thread_resolved?: boolean | null
}

export interface MemNotePatch {
  content?: string | null
  mem_type?: string | null
  trigger_text?: string | null
  trigger_keywords?: string[] | null
  entities?: string[] | null
  status?: string | null
  cooldown_hours?: number | null
  review_note?: string | null
  // v2
  summary?: string | null
  memory_kind?: string | null
  people?: string[] | null
  places?: string[] | null
  objects?: string[] | null
  keywords?: string[] | null
  event_time?: string | null
  importance?: number | null
  promise_text?: string | null
  trigger_scenarios?: string[] | null
  due_hint?: string | null
  resolved?: boolean | null
  next_action?: string | null
  privacy_level?: string | null
  joke_text?: string | null
  scene_tags?: string[] | null
  routine_domain?: string | null
  pattern?: string | null
  phase?: string | null
  constraints?: string[] | null
  topic?: string | null
  last_position?: string | null
  open_questions?: string[] | null
  next_prompt?: string | null
  thread_resolved?: boolean | null
}

export interface MemNoteBulkPatch {
  ids?: string[]
  patch?: MemNotePatch
  updates?: Array<{ id: string; patch: MemNotePatch }>
  use_suggestions?: boolean
}

export interface LegacyAtomicMemoryItem {
  id: string
  session_tag: string | null
  subject: string | null
  owner: string | null
  content_surface: string | null
  quote: string | null
  time_hint: string | null
  status: string
  memory_type: string
  tier: number | null
  importance: number | null
  tags_json: string[] | null
  entities_json: string[] | null
  source_excerpt: string | null
  source_model?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface ColdStartPreview {
  enabled?: boolean
  would_inject: boolean
  reason: string | null
  persisted?: boolean
  skip_reason?: string | null
  target_session_tag?: string | null
  source_session_tag?: string | null
  source_mode?: 'auto_latest' | 'same' | 'explicit' | string
  snapshot?: {
    id: string
    created_at: string
    source_message_count: number
    source_session_tags: string[]
  } | null
  resolved_source?: {
    session_tag?: string
    client_name?: string | null
    snapshot_at?: string
    latest_user_text?: string | null
  } | null
  config?: {
    message_limit?: number | null
    effective_message_limit?: number
    current_message_count?: number | null
    preview_fill_count?: number
    source_snapshot_limit?: number
    requested_message_limit?: number | null
  }
  sources: Array<{
    session_tag: string
    client_name: string
    snapshot_at: string
    messages: Array<{ role: string; content: string }>
  }>
}

export async function fetchConfig(): Promise<GatewayConfig> {
  const { data } = await api.get('/api/config/full')
  return data
}

export async function saveConfig(patch: GatewayConfigPatch): Promise<SaveConfigResult> {
  const { data } = await api.post('/api/config', patch)
  return data
}

export async function fetchHealth(): Promise<HealthStatus> {
  const { data } = await api.get('/health')
  return data
}

export async function fetchGatewayOverview(): Promise<GatewayOverview> {
  const { data } = await api.get('/api/gateway/overview')
  return data.overview || data
}

export async function fetchColdStartPreview(params: {
  target_session_tag?: string
  source_session_tag?: string
  current_message_count?: number
  message_limit?: number
  persist?: boolean
} = {}): Promise<ColdStartPreview> {
  const { data } = await api.post('/api/gateway/cold-start/preview', params)
  return data
}
