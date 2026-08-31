import { apiUrl, requestHeaders, type RequestContext } from './client'
import { demoRead } from '../demo'

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
  const params = new URLSearchParams()
  if (month) params.set('month', month)
  const demo = demoRead('/api/archive/days', params) as { days?: ArchiveDay[] } | undefined
  if (demo) return Array.isArray(demo.days) ? demo.days : []
  const query = month ? `?month=${encodeURIComponent(month)}` : ''
  const response = await fetch(apiUrl(ctx, `/api/archive/days${query}`), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('archive days unavailable')
  const data = await response.json()
  return Array.isArray(data.days) ? data.days : []
}

// around_days 让选日期变成「定位」而不是「框死」：跨过午夜的对话是一整段。
// before 往过去翻、after 往当下翻，两头都返回升序，直接 prepend / append。
export async function fetchArchiveMessages(
  ctx: RequestContext,
  params: { date?: string; before?: string; after?: string; limit?: number; aroundDays?: number },
): Promise<ArchiveMessage[]> {
  const search = new URLSearchParams()
  if (params.date) search.set('date', params.date)
  if (params.before) search.set('before', params.before)
  if (params.after) search.set('after', params.after)
  if (params.limit) search.set('limit', String(params.limit))
  if (params.aroundDays) search.set('around_days', String(params.aroundDays))
  const demo = demoRead('/api/archive/messages', search) as { messages?: ArchiveMessage[] } | undefined
  if (demo) return Array.isArray(demo.messages) ? demo.messages : []
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
  const demo = demoRead('/api/archive/search', search) as { results?: ArchiveMessage[] } | undefined
  if (demo) return Array.isArray(demo.results) ? demo.results : []
  const response = await fetch(apiUrl(ctx, `/api/archive/search?${search.toString()}`), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('archive search unavailable')
  const data = await response.json()
  return Array.isArray(data.results) ? data.results : []
}
