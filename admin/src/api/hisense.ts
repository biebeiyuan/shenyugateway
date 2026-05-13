import { api } from './http'

export interface NotebookItem {
  id: string
  type: string
  content: string
  tags: string[]
  status: string
  pinned: boolean
  metadata: Record<string, unknown>
  session_tag: string | null
  created_at: string
  updated_at: string
}

export interface HisensePreview {
  config: {
    hisense_client_name: string
    hisense_heartbeat_limit: number
    hisense_notebook_limit: number
  }
  package: {
    heartbeat_digest: string
    calendar_context: Record<string, unknown[]>
    notebook_items: NotebookItem[]
    last_wake_recap: string
  }
  rendered_slow_layer: string
}

export async function fetchHisensePreview(): Promise<HisensePreview> {
  const r = await api.get('/api/hisense/preview')
  return r.data
}

export async function fetchNotebook(params?: { type?: string; status?: string; limit?: number }): Promise<{ data: NotebookItem[]; count: number }> {
  const r = await api.get('/api/hisense/notebook', { params })
  return r.data
}

export async function createNotebookItem(data: { type?: string; content: string; tags?: string[]; metadata?: Record<string, unknown> }): Promise<NotebookItem> {
  const r = await api.post('/api/hisense/notebook', data)
  return r.data.data
}

export async function updateNotebookItem(id: string, data: Partial<{ content: string; status: string; type: string; tags: string[]; pinned: boolean; metadata: Record<string, unknown> }>): Promise<unknown> {
  const r = await api.patch(`/api/hisense/notebook/${id}`, data)
  return r.data
}

export async function deleteNotebookItem(id: string): Promise<unknown> {
  const r = await api.delete(`/api/hisense/notebook/${id}`)
  return r.data
}

export async function fetchHisenseSessions(limit = 20): Promise<{ sessions: unknown[]; count: number }> {
  const r = await api.get('/api/hisense/sessions', { params: { limit } })
  return r.data
}
