import { api } from './http'

export interface GatewayConfig {
  gateway_key: string
  upstream_url: string
  upstream_api_key: string
  upstream_protocol: string
  upstream_proxy?: string
  upstream_trust_env?: boolean
  supabase_url: string
  supabase_key: string
  max_client_messages: number | null
  enable_cold_start: boolean
  cold_start_turns: number
  cold_start_message_limit: number
  cold_start_idle_minutes: number
  model_mapping: Record<string, string>
  calendar_upstream_url?: string
  calendar_api_key?: string
  calendar_protocol?: string
  calendar_model?: string
  // atomic memory
  inject_inline_memory_prompt?: boolean
  enable_inline_memory_capture?: boolean
  inject_atomic_memories?: boolean
  default_atomic_memory_limit?: number
  atomic_memory_min_score?: number
  // feature toggles
  inject_briefing?: boolean
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
  max_internal_tool_rounds?: number
  default_surface_limit?: number
  heartbeat_inject_every?: number
  gateway_message_retention?: number
  gateway_context_snapshot_retention?: number
  gateway_cold_start_retention?: number
  gateway_surface_event_retention?: number
  daily_briefing_ttl_minutes?: number
  // stats
  gateway_db_path?: string
}

export interface HealthStatus {
  status: string
  supabase: boolean
  upstream: string
  models?: string[]
  protocol: string
  store?: boolean
  gateway_db_path?: string
  enable_gateway_tools?: boolean
  enable_mem0_management_tools?: boolean
  expose_supabase_tools?: boolean
  inject_meta_summaries?: boolean
  inject_briefing?: boolean

  inject_atomic_memories?: boolean
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
  surface_events?: number
  heartbeats?: number
  cache_entries?: number
  earliest_message_at: string | null
  latest_message_at: string | null
}

export interface AtomicMemoryItem {
  id: string
  subject: string | null
  content_surface: string | null
  quote: string | null
  time_hint: string | null
  status: string
  owner: string | null
  memory_type: string
  tier: number
  importance: number
  session_tag: string | null
  tags_json: string[] | null
  entities_json: string[] | null
  source_excerpt: string | null
  source_model?: string | null
  supersedes_id?: string | null
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

export type AtomicMemoryReviewPatch = Partial<
  Pick<
    AtomicMemoryItem,
    | 'content_surface'
    | 'quote'
    | 'time_hint'
    | 'subject'
    | 'owner'
    | 'memory_type'
    | 'tier'
    | 'importance'
  >
> & { status: string }
