import { api } from './http'

export type StarStatus = 'active' | 'paused' | 'archived'
export type StarReviewedFilter = 'all' | 'reviewed' | 'unreviewed'
export type StarFeedbackValue = 'positive' | 'negative' | 'missed' | 'skipped' | 'connected' | 'should_surface'

export interface StarItem {
  id: string
  session_tag: string | null
  content: string
  chord: string
  chord_sequence?: string[]
  chord_root?: string | null
  chord_quality?: string | null
  scenes?: string[]
  status: StarStatus | string
  is_constant: boolean
  reviewed_at?: string | null
  activation_count?: number
  last_activated_at?: string | null
  source_model?: string | null
  source_session_id?: string | null
  source_excerpt?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface StarCandidate extends StarItem {
  run_id?: string | null
  candidate_id?: string | null
  score?: number
  scores?: Record<string, number>
  keyword_hits?: string[]
}

export interface StarReviewItem {
  star: StarItem
  run_id?: string | null
  candidates: StarCandidate[]
}

export interface StarReviewResult {
  ok: boolean
  count: number
  new_star_limit: number
  candidates_per_star: number
  total_candidate_limit: number
  items: StarReviewItem[]
}

export interface StarFeedbackRequest {
  feedback?: StarFeedbackValue
  run_id?: string | null
  candidate_id?: string | null
  candidate_star_id?: string | null
  expected_star_id?: string | null
  scored_by?: string
  note?: string
  metadata?: Record<string, unknown>
  items?: StarFeedbackItem[]
}

export interface StarFeedbackItem {
  feedback: StarFeedbackValue
  run_id?: string | null
  candidate_id?: string | null
  candidate_star_id?: string | null
  expected_star_id?: string | null
  scored_by?: string
  note?: string
  metadata?: Record<string, unknown>
}

export interface StarCreateRequest {
  content: string
  chord?: string
  chords?: string[]
  session_tag?: string
  status?: StarStatus
  is_constant?: boolean
  metadata?: Record<string, unknown>
}

export interface StarConnectRequest {
  star_ids: string[]
  name?: string
  relation_type?: 'constellation' | 'harmony' | 'keyword' | 'manual' | 'heartbeat'
  scored_by?: string
  note?: string
}

export interface StarGraphLink {
  id?: string | null
  source: string
  target: string
  relation_type: string
  confidence?: number
  weight?: number
  position?: number | null
  bidirectional?: boolean
  times_confirmed?: number
  last_confirmed_at?: string | null
  name?: string
  note?: string
  scored_by?: string
}

export interface StarGraphResult {
  ok: boolean
  stars: StarItem[]
  links: StarGraphLink[]
}

export async function fetchStars(params: {
  status?: StarStatus | 'all'
  reviewed?: StarReviewedFilter
  session_tag?: string
  q?: string
  limit?: number
}): Promise<{ ok: boolean; count: number; items: StarItem[] }> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.reviewed) qs.set('reviewed', params.reviewed)
  if (params.session_tag) qs.set('session_tag', params.session_tag)
  if (params.q) qs.set('q', params.q)
  if (params.limit) qs.set('limit', String(params.limit))
  const { data } = await api.get(`/api/gateway/stars?${qs.toString()}`)
  return data
}

export async function searchStars(params: {
  q: string
  session_tag?: string
  limit?: number
  log_run?: boolean
}): Promise<{ ok: boolean; count: number; items: StarCandidate[]; run_id?: string | null }> {
  const qs = new URLSearchParams()
  qs.set('q', params.q)
  if (params.session_tag) qs.set('session_tag', params.session_tag)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.log_run !== undefined) qs.set('log_run', String(params.log_run))
  const { data } = await api.get(`/api/gateway/stars/search?${qs.toString()}`)
  return data
}

export async function fetchStarGraph(params: {
  status?: StarStatus | 'all'
  session_tag?: string
  limit?: number
} = {}): Promise<StarGraphResult> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.session_tag) qs.set('session_tag', params.session_tag)
  if (params.limit) qs.set('limit', String(params.limit))
  const { data } = await api.get(`/api/gateway/stars/graph?${qs.toString()}`)
  return data
}

export async function createStar(body: StarCreateRequest): Promise<{ ok: boolean; star_id?: string; star?: StarItem }> {
  const { data } = await api.post('/api/gateway/stars', body)
  return data
}

export async function reviewStars(params: {
  limit_new?: number
  candidates_per_star?: number
  total_candidate_limit?: number
  session_tag?: string
}): Promise<StarReviewResult> {
  const qs = new URLSearchParams()
  if (params.limit_new) qs.set('limit_new', String(params.limit_new))
  if (params.candidates_per_star) qs.set('candidates_per_star', String(params.candidates_per_star))
  if (params.total_candidate_limit) qs.set('total_candidate_limit', String(params.total_candidate_limit))
  if (params.session_tag) qs.set('session_tag', params.session_tag)
  const { data } = await api.post(`/api/gateway/stars/review?${qs.toString()}`)
  return data
}

export async function sendStarFeedback(body: StarFeedbackRequest): Promise<{ ok: boolean }> {
  const { data } = await api.post('/api/gateway/stars/feedback', body)
  return data
}

export async function connectStars(body: StarConnectRequest): Promise<{ ok: boolean; edge_count?: number }> {
  const { data } = await api.post('/api/gateway/stars/connect', body)
  return data
}

export async function markConstantStar(starId: string, isConstant: boolean): Promise<{ ok: boolean }> {
  const { data } = await api.patch(`/api/gateway/stars/${encodeURIComponent(starId)}/constant`, {
    is_constant: isConstant,
  })
  return data
}

export interface StarSceneBackfillResult {
  ok: boolean
  requested: number
  selected: number
  updated: number
  failed: number
  remaining_unlabeled: number
  by_scene: Record<string, number>
  items: Array<{ star: StarItem; ok: boolean; scenes?: string[]; skipped?: boolean; error?: string }>
}

export async function backfillStarScenes(limit: number): Promise<StarSceneBackfillResult> {
  const { data } = await api.post('/api/gateway/stars/backfill-scenes', { limit })
  return data
}

export async function setStarScenes(starId: string, scenes: string[]): Promise<{ ok: boolean; star: StarItem }> {
  const { data } = await api.patch(`/api/gateway/stars/${encodeURIComponent(starId)}/scenes`, { scenes })
  return data
}
