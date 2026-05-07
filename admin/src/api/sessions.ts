import { api } from './http'

export interface GatewaySession {
  id: string
  session_tag: string
  client_name: string | null
  started_at: string
  last_active_at: string
  first_message_at: string
  message_count: number
  context_state_json: string
  stored_message_count: number
  last_message_at: string | null
  user_message_count: number
  assistant_message_count: number
  tool_message_count: number
}

export interface GatewayMessage {
  id: string
  session_id: string
  role: string
  content: string | null
  tool_name: string | null
  tool_args_json: string | null
  tool_result_summary: string | null
  source_table: string | null
  source_id: string | null
  created_at: string
}

export interface GatewaySessionStats {
  messages: number
  user_messages: number
  assistant_messages: number
  tool_messages: number
  surface_events: number
  heartbeats: number
  cold_start_snapshots: number
}

export interface GatewaySessionDetail {
  session: GatewaySession
  stats: GatewaySessionStats
  latest_cold_start_snapshot: Record<string, unknown> | null
  recent_messages: GatewayMessage[]
}

export async function fetchGatewaySessions(params: { limit?: number; q?: string } = {}) {
  const { data } = await api.get<{ sessions: GatewaySession[]; limit: number; query: string }>('/api/gateway/sessions', {
    params,
  })
  return data
}

export async function fetchGatewaySession(sessionTag: string): Promise<GatewaySessionDetail> {
  const { data } = await api.get(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}`)
  return data
}

export async function deleteGatewaySession(sessionTag: string) {
  const { data } = await api.delete(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}`, {
    data: { confirm: sessionTag },
  })
  return data
}
