import { api } from './http'

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
  request_payloads_retained?: boolean
  upstream_payload_summary?: Record<string, any> | null
  system_additions_chars?: number | null
}

export interface LogDetail extends LogEntry {
  system_additions_full: string | null
  system_additions_preview: string | null
  prepared_messages: any[] | null
  prepared_messages_preview?: any[] | null
  upstream_payload: Record<string, any> | null
  tool_names_all?: string[] | null
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
