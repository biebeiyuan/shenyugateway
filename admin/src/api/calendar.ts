import { api } from './http'

export type CalendarPeriodType = 'day' | 'week' | 'month'

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
  author?: string
  updated_at?: string
  created_at?: string
}

export async function fetchCalendarMonth(month: string): Promise<CalendarMonthResponse> {
  const { data } = await api.get('/api/calendar/month', { params: { month } })
  return data
}

export async function fetchCalendarPage(pageId: string): Promise<CalendarPageDetail> {
  const { data } = await api.get(`/api/calendar/page/${encodeURIComponent(pageId)}`)
  return data
}
