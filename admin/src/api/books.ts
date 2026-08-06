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

export interface ProjectMapComponent {
  id: string
  title: string
  status: 'ok' | 'review_required' | 'error'
  summary: string
  resident_effect: string
  core: string[]
  files: string[]
  reviewed: {
    reviewed_at?: string
    reviewed_by?: string
    revision?: string
  }
  zone_ids: string[]
}

export interface ProjectMapZone {
  id: string
  number: string
  title: string
  summary: string
  responsibilities: string[]
  core_files: string[]
  component_ids: string[]
}

export interface ProjectMapFlowStage {
  id: string
  label: string
  meaning: string
  zone_ids: string[]
  details: string[]
}

export interface ProjectMapComponentBridge {
  id: string
  left_id: string
  right_id: string
  via_files: string[]
  meaning: string
}

export interface ProjectMapDelivery {
  id: string
  completed_at: string
  title: string
  product: string
  kind: 'feature' | 'fix' | 'experience' | 'operations' | 'architecture'
  summary: string
  touchpoint: string
  why: string
  status: 'verified_local' | 'pushed' | 'deployed' | 'device_verified'
  verification: string[]
  paths: string[]
  docs: string[]
  commit: string
  lesson: string
  debug_ref: string
  recorded_by: string
  product_map: Record<string, string>
  zone_ids: string[]
}

export interface ProjectMapSnapshot {
  ok: boolean
  live: {
    commit: string
    revision: string
    worktree_dirty: boolean
    observed_at: string
    last_confirmed_at: string
  }
  summary: {
    status: 'confirmed' | 'attention'
    component_count: number
    confirmed_count: number
    pending_count: number
    error_count: number
    zone_count: number
    bridge_count: number
    document_count: number
    delivery_count: number
    delivery_product_count: number
  }
  components: ProjectMapComponent[]
  zones: ProjectMapZone[]
  request_flow: ProjectMapFlowStage[]
  bridges: Array<Record<string, string>>
  component_bridges: ProjectMapComponentBridge[]
  documents: Array<Record<string, string>>
  products: Array<Record<string, string>>
  deliveries: ProjectMapDelivery[]
  changes: ResidentHomeChange[]
  warnings: string[]
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

export async function fetchProjectMap() {
  const { data } = await api.get<ProjectMapSnapshot>('/api/project-map')
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
