// 原件 ↔ 锚点关联的唯一实现（阅读卡与想起木板共用）。
// 手动确认的 evidence 字串是跨模块字面契约，只能在这里改。

import { fetchSourceEntityMentions, replaceSourceEntities } from '@/api/memoryGraph'

export const MANUAL_ANCHOR_EVIDENCE = '记忆网络手动确认'

export function sourceKey(item: Pick<{ source_table: string; source_id: string }, 'source_table' | 'source_id'>): string {
  return `${item.source_table} ${item.source_id}`
}

export interface SourceAnchorState {
  manualIds: string[]
  autoNames: string[]
}

// 翻页/翻纸时同一张原件不重复拉取；保存后强制刷新。
const cache = new Map<string, SourceAnchorState>()

export async function loadSourceAnchors(
  sourceTable: string,
  sourceId: string,
  force = false,
): Promise<SourceAnchorState> {
  const key = `${sourceTable} ${sourceId}`
  if (!force && cache.has(key)) return cache.get(key) as SourceAnchorState
  const mentions = await fetchSourceEntityMentions(sourceTable, sourceId)
  const state: SourceAnchorState = {
    manualIds: mentions.filter((mention) => mention.origin === 'manual').map((mention) => mention.entity_id),
    autoNames: mentions
      .filter((mention) => mention.origin !== 'manual')
      .map((mention) => mention.entity?.canonical_name || mention.matched_alias || '')
      .filter(Boolean),
  }
  cache.set(key, state)
  return state
}

export async function saveSourceAnchors(payload: {
  source_table: string
  source_type: string
  source_id: string
  manualIds: string[]
}): Promise<SourceAnchorState> {
  await replaceSourceEntities({
    source_table: payload.source_table,
    source_type: payload.source_type,
    source_id: payload.source_id,
    entity_ids: payload.manualIds,
    evidence: MANUAL_ANCHOR_EVIDENCE,
  })
  return loadSourceAnchors(payload.source_table, payload.source_id, true)
}
