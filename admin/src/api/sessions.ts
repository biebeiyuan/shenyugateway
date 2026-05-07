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
  context_snapshot_count?: number
  cold_start_snapshot_count?: number
  heartbeat_count?: number
  latest_user_text?: string | null
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
  context_snapshots?: number
}

export interface GatewayHeartbeat {
  id: string
  session_id: string
  content: string
  turn_number: number
  created_at: string
  injected_at: string | null
}

export interface GatewayContextSnapshot {
  id: string
  session_id: string
  session_tag: string
  client_name: string | null
  messages_json: string
  message_count: number
  latest_user_text: string | null
  created_at: string
  messages: Array<{ role?: string; content?: unknown }>
}

export interface GatewayColdStartSnapshot {
  id: string
  session_id: string
  session_tag: string
  reason: string
  sources_json: string
  source_session_tags_json: string
  source_message_count: number
  trigger_last_active_at: string | null
  injected_count: number
  max_injections: number
  created_at: string
  sources: Array<{
    session_tag?: string
    client_name?: string
    snapshot_at?: string
    latest_user_text?: string
    messages?: Array<{ role?: string; content?: string }>
  }>
  source_session_tags: string[]
}

export interface GatewaySessionDetail {
  session: GatewaySession
  stats: GatewaySessionStats
  latest_cold_start_snapshot: GatewayColdStartSnapshot | null
  context_snapshots: GatewayContextSnapshot[]
  cold_start_snapshots: GatewayColdStartSnapshot[]
  recent_messages: GatewayMessage[]
  recent_heartbeats: GatewayHeartbeat[]
}

export async function fetchGatewaySessions(params: { limit?: number; q?: string } = {}) {
  const { data } = await api.get<{ sessions: GatewaySession[]; limit: number; query: string }>('/api/gateway/sessions', {
    params,
  })
  return data
}

export async function fetchGatewaySession(sessionTag: string, params: { messages_limit?: number } = {}): Promise<GatewaySessionDetail> {
  const { data } = await api.get(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}`, { params })
  return data
}

export async function deleteGatewaySession(sessionTag: string) {
  const { data } = await api.delete(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}`, {
    data: { confirm: sessionTag },
  })
  return data
}

export async function pruneGatewayRuntime() {
  const { data } = await api.post('/api/gateway/prune')
  return data
}

export async function dedupeGatewayMessages() {
  const { data } = await api.post('/api/gateway/dedupe-messages')
  return data
}

export async function exportGatewaySession(sessionTag: string) {
  const { data } = await api.get(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}/export`)
  return data
}

export async function createGatewayHeartbeat(sessionTag: string, content: string) {
  const { data } = await api.post(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}/heartbeats`, { content })
  return data
}

export async function deleteGatewayHeartbeats(sessionTag: string, payload: { ids?: string[]; delete_all?: boolean; confirm?: string }) {
  const { data } = await api.delete(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}/heartbeats`, { data: payload })
  return data
}
