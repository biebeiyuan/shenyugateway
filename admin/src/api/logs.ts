import { api } from './http'

export interface CacheUsage {
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
  hit: boolean
  write: boolean
  read_reported?: boolean
  write_reported?: boolean
  reported?: boolean
  rounds?: number
  input_tokens?: number
  input_reported?: boolean
  total_input_tokens?: number
  total_input_reported?: boolean
  cache_read_percent?: number | null
  cache_prefix_reuse_percent?: number | null
}

export interface MemoryIslandItem {
  id?: string
  text?: string
  label?: string
  change?: 'retained' | 'added' | 'updated'
}

export interface MemoryIslandLane {
  current?: MemoryIslandItem[]
  removed?: MemoryIslandItem[]
  updated?: Array<{
    id?: string
    before?: MemoryIslandItem
    after?: MemoryIslandItem
  }>
  added_count?: number
  removed_count?: number
  updated_count?: number
}

export interface PromptCache {
  enabled?: boolean
  protocol?: string | null
  ttl?: string | null
  breakpoints?: string[]
  prefix_fingerprints?: Array<{ path?: string, sha256?: string }>
  cache_control_marker_count?: number
  tail_guard_user_turns?: number
}

export interface ResponseEvidenceLayer {
  events?: number
  text_blocks?: number
  thinking_blocks?: number
  redacted_thinking_blocks?: number
  tool_call_blocks?: number
  text_deltas?: number
  thinking_deltas?: number
  signature_deltas?: number
  tool_call_deltas?: number
  other_events?: number
  other_blocks?: number
  other_deltas?: number
  other_fields?: number
  thinking_content_seen?: boolean
  usage_seen?: boolean
  usage_values_seen?: boolean
  finish_seen?: boolean
}

export interface UpstreamResponseEvidence {
  version?: number
  protocol?: string
  mode?: 'stream' | 'nonstream' | string
  thinking_requested?: boolean
  upstream_format?: string
  normalized_format?: string
  upstream?: ResponseEvidenceLayer
  normalized?: ResponseEvidenceLayer
}

export interface LogEntry {
  id: string
  request_id?: string | null
  timestamp: string
  session_tag: string | null
  model: string
  client_model: string | null
  upstream_model: string | null
  model_mapped: boolean
  upstream_url: string
  upstream_scope?: string
  status: string
  duration_ms: number
  stream: boolean
  tools_count: number | null
  tool_names: string[] | null
  has_internal_tools: boolean | null
  is_first_turn: boolean
  original_messages_count: number
  prepared_messages_count: number
  client_message_window?: Record<string, any> | null
  memory_island?: Record<string, any> | null
  memory_island_version?: string | null
  cold_start?: Record<string, any> | null
  finish_reason?: string | null
  internal_tool_rounds?: number | ToolRoundEntry[] | null
  timeline_tail?: Array<Record<string, any>> | null
  slow_phases?: Array<Record<string, any>> | null
  error: string | null
  response_preview: string | null
  response_full?: string | null
  request_payloads_retained?: boolean
  persisted?: boolean
  persistence_schema_version?: number
  persistence_truncated?: boolean
  upstream_payload_summary?: Record<string, any> | null
  upstream_response_evidence?: UpstreamResponseEvidence | null
  system_additions_chars?: number | null
  usage?: Record<string, any> | null
  cache_usage?: CacheUsage | null
  prompt_cache?: PromptCache | null
}

export interface ToolRoundEntry {
  round: number
  messages_count: number
  stream?: boolean
  usage?: Record<string, any>
  cache_usage?: CacheUsage | null
  finish_reason?: string | null
  final?: boolean
  response_full?: string
  response_preview?: string
  upstream_duration_ms?: number
  messages?: any[]
  messages_preview?: any[]
  upstream_payload?: Record<string, any> | null
  upstream_payload_summary?: Record<string, any> | null
  upstream_response_evidence?: UpstreamResponseEvidence | null
  prompt_cache?: PromptCache | null
  anthropic_thinking?: {
    preserved?: boolean
    blocks?: number
    signature_present?: boolean
    redacted_present?: boolean
  } | null
  tool_calls_count?: number
  gateway_tool_calls?: Array<{
    id?: string
    name?: string
    arguments_preview?: string
  }> | null
  tools: Array<{
    name: string
    cached_duplicate: boolean
    args_preview: string
    result_preview?: string
    ok?: boolean | null
    target_tool?: string | null
    duration_ms?: number
  }>
}

export interface LogDetail extends LogEntry {
  system_additions_full: string | null
  system_additions_preview: string | null
  prepared_messages: any[] | null
  prepared_messages_preview?: any[] | null
  upstream_payload: Record<string, any> | null
  tool_names_all?: string[] | null
  memory_island_content?: {
    version?: string | null
    star_count?: number
    mem_count?: number
    rendered_text?: string
    stars?: MemoryIslandLane
    mem_notes?: MemoryIslandLane
    bumps?: string[]
  } | null
  internal_tool_rounds?: ToolRoundEntry[] | null
}

export interface LogsResponse {
  logs: LogEntry[]
}

export async function fetchLogs(limit = 30): Promise<LogsResponse> {
  const { data } = await api.get(`/api/gateway/logs?limit=${limit}`)
  return data
}

export async function fetchLogDetail(id: string): Promise<LogDetail> {
  const { data } = await api.get(`/api/gateway/logs/${id}`)
  return data
}
