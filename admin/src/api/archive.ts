import { api } from './http'

export interface ArchiveDay {
  date: string
  count: number
}

export interface ArchiveMessage {
  id: string
  session_tag: string
  role: 'user' | 'assistant'
  content: string
  event_at: string | null
  archived_at: string
}

export interface ConflictBookSummary {
  id: string
  title: string
  thread: string | null
  span_start: string | null
  span_end: string | null
  status: 'open' | 'settled'
  read_count: number
  last_read_at: string | null
  created_at: string
  updated_at: string | null
}

export interface ConflictAnnotation {
  id: string
  content: string
  created_at: string
}

export interface ConflictBookDetail extends ConflictBookSummary {
  original_text: string
  epilogue: string | null
  user_notes: string | null
  message_refs: unknown[]
  annotations: ConflictAnnotation[]
}

export async function fetchArchiveDays(month?: string) {
  const { data } = await api.get<{ days: ArchiveDay[] }>('/api/archive/days', { params: { month } })
  return data.days
}

// around_days 让选日期变成「定位」而不是「框死」：跨过午夜的对话是一整段，
// 单日硬筛会把它切断，来历书就截不全。
export async function fetchArchiveMessages(params: { date?: string; before?: string; limit?: number; around_days?: number }) {
  const { data } = await api.get<{ messages: ArchiveMessage[]; count: number }>('/api/archive/messages', { params })
  return data.messages
}

export async function softDeleteArchiveMessage(messageId: string) {
  const { data } = await api.delete(`/api/archive/messages/${encodeURIComponent(messageId)}`)
  return data
}

export async function fetchConflictBooks() {
  const { data } = await api.get<{ ok: boolean; books: ConflictBookSummary[] }>('/api/conflict-books')
  return data.books ?? []
}

export async function fetchConflictBook(bookId: string) {
  const { data } = await api.get<{ ok: boolean; book: ConflictBookDetail }>(`/api/conflict-books/${encodeURIComponent(bookId)}`)
  return data.book
}

export async function createConflictBook(payload: {
  title: string
  original_text: string
  thread?: string
  span_start?: string
  span_end?: string
  message_refs?: unknown[]
  user_notes?: string
  epilogue?: string
}) {
  const { data } = await api.post('/api/conflict-books', payload)
  return data
}

export async function patchConflictBook(
  bookId: string,
  payload: { title?: string; thread?: string; epilogue?: string; user_notes?: string; status?: string },
) {
  const { data } = await api.patch(`/api/conflict-books/${encodeURIComponent(bookId)}`, payload)
  return data
}

export async function deleteConflictBook(bookId: string) {
  const { data } = await api.delete(`/api/conflict-books/${encodeURIComponent(bookId)}`)
  return data
}
