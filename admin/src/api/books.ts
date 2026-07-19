import { api } from './http'

export interface LivingBookSummary {
  kind: 'living'
  id: string
  slug: 'identity'
  title: string
  status: 'active'
  revision: number
  updated_at: string | null
  updated_by: string | null
}

export interface HomeOverview {
  current_week: string
  current_week_changes: number
  last_confirmed_at: string
}

export interface ResidentShelfResponse {
  ok: boolean
  home: HomeOverview
  identity: LivingBookSummary | null
  origin_books: Array<Record<string, unknown>>
  warnings: string[]
}

export interface BookAnnotation {
  id: string
  target_revision: number
  content: string
  actor: string
  created_at: string
}

export interface LivingBookRevision {
  id: string
  revision: number
  body: string
  summary: string | null
  actor: string
  created_at: string
}

export interface LivingBookDetail extends LivingBookSummary {
  body: string
  created_at: string
  annotations: BookAnnotation[]
}

export interface ResidentHomeChange {
  week: string
  title: string
  summary: string
  impact: string
  created_at: string
}

export interface ResidentHomeComponent {
  id: string
  title: string
  status: 'ok' | 'review_required' | 'error'
  summary: string
  core: string[]
  resident_effect: string
}

export interface ResidentHomeSnapshot {
  live: {
    commit: string
    revision: string
    worktree_dirty: boolean
    observed_at: string
    last_confirmed_at: string
    current_week: string
    current_week_changes: number
  }
  components: ResidentHomeComponent[]
  changes: Record<string, ResidentHomeChange[]>
}

export interface LivingBookReadResponse {
  ok: boolean
  error?: string
  kind?: 'living'
  book?: LivingBookDetail
  revisions?: LivingBookRevision[]
}

export interface HomeBookReadResponse {
  ok: boolean
  error?: string
  kind?: 'snapshot'
  book?: {
    id: string | null
    slug: 'home'
    title: '家现在'
    kind: 'snapshot'
    annotations: BookAnnotation[]
  }
  snapshot?: ResidentHomeSnapshot
  warnings?: string[]
}

export async function fetchResidentOverview() {
  const { data } = await api.get<ResidentShelfResponse>('/api/books')
  return data
}

export async function fetchIdentityBook(view: 'current' | 'history' = 'history') {
  const { data } = await api.get<LivingBookReadResponse>('/api/books/identity', { params: { view } })
  return data
}

export async function fetchHomeBook() {
  const { data } = await api.get<HomeBookReadResponse>('/api/books/home')
  return data
}

export async function updateIdentityBook(
  payload: { content: string; expected_revision: number; summary?: string },
) {
  const { data } = await api.patch<LivingBookReadResponse>('/api/books/identity', payload)
  return data
}

export async function annotateBook(
  book: 'identity' | 'home',
  payload: { content: string; target_revision?: number },
) {
  const { data } = await api.post<LivingBookReadResponse | HomeBookReadResponse>(
    `/api/books/${book}/annotations`,
    payload,
  )
  return data
}
