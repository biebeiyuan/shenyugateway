import { api } from './http'
import type {
  GatewayConfig,
  LegacyAtomicMemoryItem,
  MemNoteBulkPatch,
  MemNoteItem,
  MemNotePatch,
  SaveConfigResult,
} from './config'

export async function fetchMem0Config(): Promise<GatewayConfig> {
  const { data } = await api.get('/api/config/full')
  return data
}

export async function saveMem0Config(patch: Partial<GatewayConfig>): Promise<SaveConfigResult> {
  const { data } = await api.post('/api/config', patch)
  return data
}

export async function fetchMemNotes(params: {
  status?: string
  limit?: number
  all_rows?: boolean
  session_tag?: string
  q?: string
  mem_type?: string
  memory_kind?: string
}): Promise<{
  items: MemNoteItem[]
  count: number
  eligible_count?: number
  stored_count?: number
  status_counts?: Record<string, number>
}> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.all_rows) qs.set('all_rows', 'true')
  if (params.session_tag) qs.set('session_tag', params.session_tag)
  if (params.q) qs.set('q', params.q)
  if (params.mem_type) qs.set('mem_type', params.mem_type)
  if (params.memory_kind) qs.set('memory_kind', params.memory_kind)
  const { data } = await api.get(`/api/gateway/mem-notes?${qs.toString()}`)
  return data
}

export async function updateMemNote(noteId: string, patch: MemNotePatch): Promise<void> {
  await api.patch(`/api/gateway/mem-notes/${encodeURIComponent(noteId)}`, patch)
}

export async function bulkUpdateMemNotes(patch: MemNoteBulkPatch): Promise<{
  ok: boolean
  error?: string
  requested_count: number
  max_count?: number
  updated_count: number
  failed_count: number
  updated_ids: string[]
  failures: Array<{ id: string; error: string }>
}> {
  const { data } = await api.patch('/api/gateway/mem-notes/bulk', patch)
  return data
}

export async function deleteMemNote(noteId: string): Promise<void> {
  await api.delete(`/api/gateway/mem-notes/${encodeURIComponent(noteId)}`)
}

export async function fetchLegacyAtomicMemories(params: {
  limit?: number
  session_tag?: string
  q?: string
}): Promise<{ items: LegacyAtomicMemoryItem[]; count: number }> {
  const qs = new URLSearchParams()
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.session_tag) qs.set('session_tag', params.session_tag)
  if (params.q) qs.set('q', params.q)
  const { data } = await api.get(`/api/gateway/legacy-atomic-memories?${qs.toString()}`)
  return data
}
