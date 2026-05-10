import { api } from './http'
import type { AtomicMemoryItem, AtomicMemoryReviewPatch, GatewayConfig, SaveConfigResult } from './config'

export async function fetchMem0Config(): Promise<GatewayConfig> {
  const { data } = await api.get('/api/config/full')
  return data
}

export async function saveMem0Config(patch: Partial<GatewayConfig>): Promise<SaveConfigResult> {
  const { data } = await api.post('/api/config', patch)
  return data
}

export async function fetchAtomicMemories(params: {
  status?: string
  limit?: number
  session_tag?: string
}): Promise<{ items: AtomicMemoryItem[] }> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.session_tag) qs.set('session_tag', params.session_tag)
  const { data } = await api.get(`/api/gateway/atomic-memories?${qs.toString()}`)
  return data
}

export async function reviewAtomicMemory(memoryId: string, patch: AtomicMemoryReviewPatch): Promise<void> {
  await api.post(`/api/gateway/atomic-memories/${encodeURIComponent(memoryId)}/review`, patch)
}
