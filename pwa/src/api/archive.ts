import { apiUrl, requestHeaders, type RequestContext } from './client'

// 回看的数据层：全部读同一份逐字档案 shenyu_chat_archive，复用网关既有的
// /api/archive/* 端点，不新建存储。搜索是字面子串（后端 ilike + 复核），
// 不做语义——找原话要的是敲进去的那串字。

export type ArchiveMessage = {
  id: string
  session_tag: string
  role: 'user' | 'assistant'
  content: string
  event_at: string | null
  archived_at: string
}

export type ArchiveDay = { date: string; count: number }

export async function fetchArchiveDays(ctx: RequestContext, month?: string): Promise<ArchiveDay[]> {
  const query = month ? `?month=${encodeURIComponent(month)}` : ''
  const response = await fetch(apiUrl(ctx, `/api/archive/days${query}`), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('archive days unavailable')
  const data = await response.json()
  return Array.isArray(data.days) ? data.days : []
}

// around_days 让选日期变成「定位」而不是「框死」：跨过午夜的对话是一整段。
export async function fetchArchiveMessages(
  ctx: RequestContext,
  params: { date?: string; before?: string; limit?: number; aroundDays?: number },
): Promise<ArchiveMessage[]> {
  const search = new URLSearchParams()
  if (params.date) search.set('date', params.date)
  if (params.before) search.set('before', params.before)
  if (params.limit) search.set('limit', String(params.limit))
  if (params.aroundDays) search.set('around_days', String(params.aroundDays))
  const response = await fetch(apiUrl(ctx, `/api/archive/messages?${search.toString()}`), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('archive messages unavailable')
  const data = await response.json()
  return Array.isArray(data.messages) ? data.messages : []
}

export async function searchArchive(
  ctx: RequestContext,
  query: string,
  role?: 'user' | 'assistant',
): Promise<ArchiveMessage[]> {
  const needle = query.trim()
  if (!needle) return []
  const search = new URLSearchParams({ q: needle })
  if (role) search.set('role', role)
  const response = await fetch(apiUrl(ctx, `/api/archive/search?${search.toString()}`), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('archive search unavailable')
  const data = await response.json()
  return Array.isArray(data.results) ? data.results : []
}
