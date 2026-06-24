import { api } from './http'

export interface CacheUsage {
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
  hit: boolean
  write: boolean
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
  error: string | null
  response_preview: string | null
  response_full?: string | null
  request_payloads_retained?: boolean
  upstream_payload_summary?: Record<string, any> | null
  system_additions_chars?: number | null
  usage?: Record<string, any> | null
  cache_usage?: CacheUsage | null
}

export interface ToolRoundEntry {
  round: number
  messages_count: number
  stream?: boolean
  usage?: Record<string, any>
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
