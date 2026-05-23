import { api } from './http'

export interface GatewayConfig {
  gateway_key: string
  upstream_url: string
  upstream_api_key: string
  upstream_protocol: string
  upstream_proxy?: string
  upstream_trust_env?: boolean
  hisense_upstream_url?: string
  hisense_api_key?: string
  hisense_protocol?: string
  supabase_url: string
  supabase_key: string
  max_client_messages: number | null
  enable_cold_start: boolean
  cold_start_message_limit: number | null
  cold_start_idle_minutes: number
  model_mapping: Record<string, string>
  calendar_upstream_url?: string
  calendar_api_key?: string
  calendar_protocol?: string
  calendar_model?: string
  wake_welcome_message?: string
  // mem notes
  inject_inline_memory_prompt?: boolean
  enable_inline_memory_capture?: boolean
  inject_mem_notes?: boolean
  mem_note_limit?: number
  mem_note_min_score?: number
  mem_note_default_cooldown_hours?: number
  // feature toggles
  inject_meta_summaries?: boolean
  calendar_inject_day?: boolean
  calendar_inject_week?: boolean
  calendar_inject_month?: boolean
  calendar_context_day_limit?: number
  calendar_context_week_limit?: number
  calendar_context_month_limit?: number

  enable_gateway_tools?: boolean
  enable_mem0_management_tools?: boolean
  expose_supabase_tools?: boolean
  gateway_tool_mode?: string
  max_internal_tool_rounds?: number
  default_surface_limit?: number
  heartbeat_inject_every?: number
  gateway_message_retention?: number
  gateway_context_snapshot_retention?: number
  gateway_cold_start_retention?: number
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
  hisense_upstream?: string
  hisense_upstream_chat_url?: string
  hisense_upstream_scope?: string
  hisense_protocol?: string
  models?: string[]
  protocol: string
  store?: boolean
  gateway_db_path?: string
  enable_gateway_tools?: boolean
  enable_mem0_management_tools?: boolean
  expose_supabase_tools?: boolean
  gateway_tool_mode?: string
  inject_meta_summaries?: boolean

  inject_mem_notes?: boolean
  enable_cold_start?: boolean
}

export interface SaveConfigResult {
  ok: boolean
  changed: string[]
  config: GatewayConfig
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

export type MemNoteType = '她为我做的事' | '关于她的事实' | '心里那一档' | '承诺'
export type MemNoteStatus = 'captured' | 'active' | 'paused' | 'archived'

export interface MemNoteItem {
  id: string
  session_tag: string | null
  content: string
  mem_type: MemNoteType | '' | null
  trigger_text: string | null
  trigger_keywords: string[] | null
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
}

export type MemNotePatch = Partial<
  Pick<
    MemNoteItem,
    | 'content'
    | 'mem_type'
    | 'trigger_text'
    | 'trigger_keywords'
    | 'status'
    | 'cooldown_hours'
    | 'review_note'
  >
>

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
  would_inject: boolean
  reason: string | null
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

export async function saveConfig(patch: Partial<GatewayConfig>): Promise<SaveConfigResult> {
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

export async function fetchColdStartPreview(): Promise<ColdStartPreview> {
  const { data } = await api.get('/api/gateway/cold-start/preview')
  return data
}
