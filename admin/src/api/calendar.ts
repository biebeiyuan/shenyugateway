import { api } from './http'

export type CalendarPeriodType = 'day' | 'week' | 'month'

export interface CalendarPrompt {
  id: string
  prompt_type: CalendarPeriodType
  name: string
  content: string
  version: number
  is_default: boolean
  is_active: boolean
  note: string
  updated_at: string
}

export interface CalendarPromptsResponse {
  items: Record<CalendarPeriodType, CalendarPrompt[]>
  active: Record<CalendarPeriodType, CalendarPrompt | null>
}

export interface CalendarPageListItem {
  id: string
  period_key: string
  title: string
  summary: string
  updated_at: string
}

export interface CalendarGridItem {
  date: string
  day: number
  in_month: boolean
  week_key: string
  month_key: string
  has_day: boolean
  has_week: boolean
  has_month: boolean
  day_page?: {
    id: string
    title: string
    summary: string
    status: string
  }
}

export interface CalendarMonthResponse {
  month_key: string
  grid: CalendarGridItem[]
  pages: Record<CalendarPeriodType, CalendarPageListItem[]>
}

export interface CalendarPageDetail {
  id: string
  period_type: CalendarPeriodType
  period_key: string
  title: string
  content: string
  summary: string
  digest: string
  status: string
  version: number
  updated_at?: string
  created_at?: string
}

export interface CalendarContextSnapshot {
  id: string
  session_tag: string
  client_name: string | null
  created_at: string
  last_active_at: string
  message_count: number
  stored_message_count: number
  latest_user_text: string
  messages: Array<{ role: string; content: string }>
}

export interface CalendarSendPreview {
  period_type: CalendarPeriodType
  period_key: string
  protocol: string
  model: string
  upstream_url: string
  prompt_name: string
  prompt_version: number
  system_prompt: string
  user_prompt: string
  source_block: string
  source_counts: Record<string, number>
}

export async function fetchCalendarPrompts(): Promise<CalendarPromptsResponse> {
  const { data } = await api.get('/api/calendar/prompts')
  return data
}

export async function saveCalendarPrompt(body: {
  prompt_type: CalendarPeriodType
  name: string
  content: string
  note?: string
  is_active?: boolean
}) {
  const { data } = await api.post('/api/calendar/prompts', body)
  return data
}

export async function fetchCalendarMonth(month: string): Promise<CalendarMonthResponse> {
  const { data } = await api.get('/api/calendar/month', { params: { month } })
  return data
}

export async function fetchCalendarPage(pageId: string): Promise<CalendarPageDetail> {
  const { data } = await api.get(`/api/calendar/page/${encodeURIComponent(pageId)}`)
  return data
}

export async function fetchCalendarContextSnapshots(params: { limit?: number; session_tag?: string } = {}) {
  const { data } = await api.get<{ items: CalendarContextSnapshot[] }>('/api/calendar/context-snapshots', { params })
  return data
}

export async function fetchCalendarSendPreview(params: {
  period_type: CalendarPeriodType
  period_key: string
  model?: string
  session_tag?: string
}): Promise<CalendarSendPreview> {
  const { data } = await api.get('/api/calendar/send-preview', { params })
  return data
}

export async function generateCalendarPage(body: {
  period_type: CalendarPeriodType
  period_key: string
  model?: string
  session_tag?: string
}) {
  const { data } = await api.post('/api/calendar/generate', body)
  return data
}
