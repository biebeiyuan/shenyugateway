import { api } from './http'
import type { AtomicMemoryItem, AtomicMemoryReviewPatch, GatewayConfig, SaveConfigResult } from './config'

export interface AtomicPromptPreset {
  id: string
  name: string
  content: string
  note: string
  version: number
  is_default: boolean
  is_active: boolean
  updated_at: string
}

export interface AtomicPromptPresetResponse {
  items: AtomicPromptPreset[]
  active: AtomicPromptPreset | null
}

export async function fetchMem0Config(): Promise<GatewayConfig> {
  const { data } = await api.get('/api/config/full')
  return data
}

export async function saveMem0Config(patch: Partial<GatewayConfig>): Promise<SaveConfigResult> {
  const { data } = await api.post('/api/config', patch)
  return data
}

export async function fetchMem0PromptPresets(): Promise<AtomicPromptPresetResponse> {
  const { data } = await api.get('/api/mem0/prompt-presets')
  return data
}

export async function saveMem0PromptPreset(body: {
  name: string
  content: string
  note?: string
  is_active?: boolean
}) {
  const { data } = await api.post('/api/mem0/prompt-presets', body)
  return data
}

export async function activateMem0PromptPreset(presetId: string) {
  const { data } = await api.post(`/api/mem0/prompt-presets/${encodeURIComponent(presetId)}/activate`)
  return data
}

export async function fetchInlineMemoryPromptPresets(): Promise<AtomicPromptPresetResponse> {
  const { data } = await api.get('/api/inline-memory/prompt-presets')
  return data
}

export async function saveInlineMemoryPromptPreset(body: {
  name: string
  content: string
  note?: string
  is_active?: boolean
}) {
  const { data } = await api.post('/api/inline-memory/prompt-presets', body)
  return data
}

export async function activateInlineMemoryPromptPreset(presetId: string) {
  const { data } = await api.post(`/api/inline-memory/prompt-presets/${encodeURIComponent(presetId)}/activate`)
  return data
}

export async function extractMem0Now(body: {
  session_tag?: string
  model?: string
}): Promise<{ ok: boolean; run_id?: string; candidate_count?: number; inserted_count?: number; window_turns?: number; reason?: string; error?: string }> {
  const { data } = await api.post('/api/mem0/extract-now', body)
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
