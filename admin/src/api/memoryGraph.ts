import { api } from './http'

export type MemoryEntityType = 'person' | 'place' | 'object' | 'topic'
export type MemoryFactStatus = 'confirmed' | 'suggested' | 'rejected'

export interface MemoryEntityAlias {
  id: string
  entity_id: string
  alias: string
  normalized_alias: string
  status: MemoryFactStatus
  is_primary: boolean
  provenance: string
  evidence?: string
}

export interface MemoryEntity {
  id: string
  entity_type: MemoryEntityType
  canonical_name: string
  description: string
  status: 'active' | 'archived' | 'merged'
  aliases: MemoryEntityAlias[]
  mention_count: number
  relation_count: number
  source_type_counts: Record<string, number>
  last_mentioned_at?: string | null
}

export interface MemoryEntityRelation {
  id: string
  source_entity_id: string
  target_entity_id: string
  relation_type: string
  status: MemoryFactStatus | 'archived'
  evidence: string
  provenance: string
  valid_from?: string | null
  valid_to?: string | null
}

export interface MemoryGraphRecentItem {
  kind: 'mention' | 'relation'
  at: string
  entity_id?: string
  entity_name?: string
  source_table?: string
  source_type?: string
  source_id?: string
  relation_type?: string
  source_entity_id?: string
  target_entity_id?: string
  source_name?: string
  target_name?: string
}

export interface MemoryGraphSnapshot {
  ok: boolean
  available: boolean
  entities: MemoryEntity[]
  relations: MemoryEntityRelation[]
  entity_count?: number
  relation_count?: number
  recent?: MemoryGraphRecentItem[]
  error?: string
}

export interface SourceEntityMention {
  id: string
  entity_id: string
  source_table: string
  source_type: string
  source_id: string
  status: MemoryFactStatus
  origin: 'manual' | 'exact_alias' | 'structural' | 'suggestion'
  matched_alias?: string | null
  entity?: MemoryEntity | null
}

export type MemoryRecallMatchGroup = 'direct' | 'related' | 'other'

export interface MemoryRecallMatch {
  group: MemoryRecallMatchGroup
  label: string
  anchor?: { id?: string; name?: string; type?: string }
  path?: {
    from?: { id?: string; name?: string; type?: string }
    relation_type?: string
    to?: { id?: string; name?: string; type?: string }
  }
}

export interface MemoryGraphRecallPreviewItem {
  source_id: string
  source_type: string
  source_table: string
  content: string
  title?: string
  content_kind?: string
  event_date?: string
  content_complete?: boolean
  content_error?: string
  recall_match: MemoryRecallMatch
}

export interface MemoryGraphRecallPreview {
  ok: boolean
  count: number
  items: MemoryGraphRecallPreviewItem[]
  /** Query terms from the gateway tokenizer, used only to highlight matches in the original text. */
  tokens?: string[]
  error?: string
}

export async function fetchMemoryGraph(params: {
  q?: string
  entity_type?: MemoryEntityType | ''
  include_archived?: boolean
} = {}): Promise<MemoryGraphSnapshot> {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.entity_type) qs.set('entity_type', params.entity_type)
  if (params.include_archived) qs.set('include_archived', 'true')
  const { data } = await api.get(`/api/gateway/memory-graph?${qs.toString()}`)
  return data
}

export async function createMemoryEntity(payload: {
  entity_type: MemoryEntityType
  canonical_name: string
  description?: string
  aliases?: string[]
}): Promise<MemoryEntity> {
  const { data } = await api.post('/api/gateway/memory-graph/entities', payload)
  return data.entity
}

export async function updateMemoryEntity(
  entityId: string,
  patch: Partial<Pick<MemoryEntity, 'entity_type' | 'canonical_name' | 'description' | 'status'>>,
): Promise<void> {
  await api.patch(`/api/gateway/memory-graph/entities/${encodeURIComponent(entityId)}`, patch)
}

export async function addMemoryEntityAlias(entityId: string, alias: string): Promise<void> {
  await api.post(`/api/gateway/memory-graph/entities/${encodeURIComponent(entityId)}/aliases`, {
    alias,
    status: 'confirmed',
    provenance: 'manual',
  })
}

export async function deleteMemoryEntityAlias(aliasId: string): Promise<void> {
  await api.delete(`/api/gateway/memory-graph/aliases/${encodeURIComponent(aliasId)}`)
}

export async function updateMemoryEntityAlias(
  aliasId: string,
  patch: { status?: MemoryFactStatus; evidence?: string },
): Promise<void> {
  await api.patch(`/api/gateway/memory-graph/aliases/${encodeURIComponent(aliasId)}`, patch)
}

export interface MemoryEntityMentionItem {
  source_table: string
  source_type: string
  source_id: string
  origin: string
  title?: string
  excerpt?: string
  event_date?: string
}

export async function fetchMemoryEntityMentions(entityId: string, limit = 24): Promise<MemoryEntityMentionItem[]> {
  const { data } = await api.get(
    `/api/gateway/memory-graph/entities/${encodeURIComponent(entityId)}/mentions?limit=${limit}`,
  )
  return data.items || []
}

export interface MemoryGraphNameCandidate {
  name: string
  kind: 'person' | 'place' | 'object'
  count: number
}

export interface MemoryGraphCandidateLink {
  name: string
  entity_id: string
  shared: number
}

export interface MemoryCandidateMention {
  id: string
  mem_type: string
  content: string
  kind: string
  event_date?: string
}

export async function fetchMemoryCandidateMentions(name: string, limit = 12): Promise<MemoryCandidateMention[]> {
  const { data } = await api.get(
    `/api/gateway/memory-graph/candidate-mentions?name=${encodeURIComponent(name)}&limit=${limit}`,
  )
  return data.items || []
}

export async function fetchMemoryGraphNameCandidates(
  limit = 30,
): Promise<{ candidates: MemoryGraphNameCandidate[]; links: MemoryGraphCandidateLink[] }> {
  const { data } = await api.get(`/api/gateway/memory-graph/name-candidates?limit=${limit}`)
  return { candidates: data.candidates || [], links: data.links || [] }
}

export async function createMemoryEntityRelation(payload: {
  source_entity_id: string
  target_entity_id: string
  relation_type: string
  evidence?: string
}): Promise<void> {
  await api.post('/api/gateway/memory-graph/relations', {
    ...payload,
    status: 'confirmed',
    provenance: 'manual',
  })
}

export async function updateMemoryEntityRelation(
  relationId: string,
  patch: { status?: MemoryFactStatus | 'archived'; relation_type?: string; evidence?: string },
): Promise<void> {
  await api.patch(`/api/gateway/memory-graph/relations/${encodeURIComponent(relationId)}`, patch)
}

export async function archiveMemoryEntityRelation(relationId: string): Promise<void> {
  await updateMemoryEntityRelation(relationId, { status: 'archived' })
}

export async function fetchSourceEntityMentions(
  sourceTable: string,
  sourceId: string,
): Promise<SourceEntityMention[]> {
  const { data } = await api.get(
    `/api/gateway/memory-graph/sources/${encodeURIComponent(sourceTable)}/${encodeURIComponent(sourceId)}`,
  )
  return data.mentions || []
}

export async function replaceSourceEntities(payload: {
  source_table: string
  source_type: string
  source_id: string
  entity_ids: string[]
  evidence?: string
}): Promise<void> {
  await api.put('/api/gateway/memory-graph/sources', payload)
}

export async function backfillMemoryGraph(): Promise<{
  scanned_sources: number
  matched_sources: number
  linked_mentions: number
}> {
  const { data } = await api.post('/api/gateway/memory-graph/backfill', {})
  return data
}

export async function previewMemoryGraphRecall(query: string, limit = 8): Promise<MemoryGraphRecallPreview> {
  const { data } = await api.post('/api/gateway/memory-graph/recall-preview', { query, limit })
  return data
}
