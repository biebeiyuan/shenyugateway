// 演示数据：只服务 `?demo=1` 预览，让本地/隔离实例的每页都有像样的内容。
// 全部是编造的样本，不是任何人的真实记忆；生产数据永远不会经过这里。

import type {
  MemoryEntity,
  MemoryEntityRelation,
  MemoryGraphRecallPreview,
  MemoryGraphRecallPreviewItem,
  MemoryGraphRecentItem,
  MemoryGraphSnapshot,
  MemoryEntityMentionItem,
  MemoryGraphNameCandidate,
  MemoryGraphCandidateLink,
} from '@/api/memoryGraph'
import type { MemNoteItem } from '@/api/config'

const DAY = 24 * 3600 * 1000
const daysAgo = (n: number) => new Date(Date.now() - n * DAY).toISOString()
const day = (n: number) => daysAgo(n).slice(0, 10)

function alias(id: string, entityId: string, text: string, primary = false, status: 'confirmed' | 'suggested' = 'confirmed') {
  return {
    id,
    entity_id: entityId,
    alias: text,
    normalized_alias: text.toLowerCase(),
    status,
    is_primary: primary,
    provenance: primary ? 'manual' : 'auto',
  }
}

const ENTITIES: MemoryEntity[] = [
  {
    id: 'demo-e1', entity_type: 'person', canonical_name: '小舟',
    description: '住在演示数据里的朋友，怕苦，爱看日落。', status: 'active',
    aliases: [alias('demo-a1', 'demo-e1', '小舟', true), alias('demo-a2', 'demo-e1', '舟舟')],
    mention_count: 5, relation_count: 2,
    source_type_counts: { mem_note: 3, journal: 2 },
    last_mentioned_at: daysAgo(1),
  },
  {
    id: 'demo-e2', entity_type: 'place', canonical_name: '江边步道',
    description: '常去散步的地方，有一段长椅正对着水面。', status: 'active',
    aliases: [alias('demo-a3', 'demo-e2', '江边步道', true)],
    mention_count: 3, relation_count: 1,
    source_type_counts: { journal: 1, mem_note: 1, windowsill: 1 },
    last_mentioned_at: daysAgo(2),
  },
  {
    id: 'demo-e3', entity_type: 'object', canonical_name: '蓝色马克杯',
    description: '小舟的专用杯，杯底有一圈淡茶渍。', status: 'active',
    aliases: [alias('demo-a4', 'demo-e3', '蓝色马克杯', true), alias('demo-a5', 'demo-e3', '蓝杯子', false, 'suggested')],
    mention_count: 2, relation_count: 1,
    source_type_counts: { mem_note: 1, windowsill: 1 },
    last_mentioned_at: daysAgo(3),
  },
  {
    id: 'demo-e4', entity_type: 'topic', canonical_name: '夏末',
    description: '一个被反复提起的季节节点。', status: 'active',
    aliases: [alias('demo-a6', 'demo-e4', '夏末', true)],
    mention_count: 2, relation_count: 0,
    source_type_counts: { mem_note: 2 },
    last_mentioned_at: daysAgo(4),
  },
]

const RELATIONS: MemoryEntityRelation[] = [
  {
    id: 'demo-r1', source_entity_id: 'demo-e1', target_entity_id: 'demo-e2',
    relation_type: '常去', status: 'confirmed', provenance: 'manual',
    evidence: '便签「江边步道的约定」', valid_from: null, valid_to: null,
  },
  {
    id: 'demo-r2', source_entity_id: 'demo-e3', target_entity_id: 'demo-e1',
    relation_type: '属于', status: 'suggested', provenance: 'extraction',
    evidence: '便签「小舟怕苦」', valid_from: null, valid_to: null,
  },
]

const RECENT: MemoryGraphRecentItem[] = [
  { kind: 'mention', at: daysAgo(1), entity_id: 'demo-e1', entity_name: '小舟', source_table: 'journal', source_type: 'journal', source_id: 'demo-j1' },
  { kind: 'relation', at: daysAgo(2), relation_type: '属于', source_entity_id: 'demo-e3', target_entity_id: 'demo-e1', source_name: '蓝色马克杯', target_name: '小舟' },
  { kind: 'mention', at: daysAgo(3), entity_id: 'demo-e2', entity_name: '江边步道', source_table: 'mem_notes', source_type: 'mem_note', source_id: 'demo-m2' },
]

export function demoGraphSnapshot(): MemoryGraphSnapshot {
  return {
    ok: true, available: true,
    entities: ENTITIES, relations: RELATIONS,
    entity_count: ENTITIES.length, relation_count: RELATIONS.length,
    recent: RECENT,
  }
}

export function demoNameCandidates(): { candidates: MemoryGraphNameCandidate[]; links: MemoryGraphCandidateLink[] } {
  return {
    candidates: [
      { name: '长椅', kind: 'object', count: 2 },
      { name: '日落', kind: 'object', count: 3 },
    ],
    links: [{ name: '日落', entity_id: 'demo-e1', shared: 1 }],
  }
}

// ---- 便签页 ----

function note(partial: Partial<MemNoteItem> & Pick<MemNoteItem, 'id' | 'content'>): MemNoteItem {
  return {
    session_tag: null, mem_type: null, trigger_text: null, trigger_keywords: null,
    entities: null, status: 'active', cooldown_hours: 0, last_triggered_at: null,
    trigger_count: 0, ...partial,
  }
}

const MEM_NOTES: MemNoteItem[] = [
  note({
    id: 'demo-m1', content: '小舟喝咖啡要加双份奶，蓝色马克杯是他的专用杯。',
    mem_type: '关于她的事实', trigger_text: '小舟 咖啡', trigger_keywords: ['小舟', '咖啡'],
    entities: ['小舟', '蓝色马克杯'], status: 'active', auto_surface_eligible: true,
    auto_surface_reason: 'active', written_by_shenyu: true, source_model: 'tool:shenyu_write_mem_note',
    created_at: daysAgo(6), updated_at: daysAgo(6),
  }),
  note({
    id: 'demo-m2', content: '和小舟约好，夏末之前每周三傍晚去江边步道走一圈，下雨就改到周四。',
    mem_type: '承诺', trigger_text: '散步 周三', trigger_keywords: ['小舟', '江边步道'],
    entities: ['小舟', '江边步道'], status: 'active', auto_surface_eligible: true,
    auto_surface_reason: 'active', created_at: daysAgo(8), updated_at: daysAgo(8),
  }),
  note({
    id: 'demo-m3', content: '夏末之前想做完的事：晒一次被子、看一场日落、把蓝色马克杯的配套杯垫织完。',
    mem_type: '心里那一档', trigger_text: '夏末 清单', trigger_keywords: ['夏末', '日落'],
    entities: ['夏末', '蓝色马克杯'], status: 'active', auto_surface_eligible: true,
    auto_surface_reason: 'active', created_at: daysAgo(10), updated_at: daysAgo(10),
  }),
  note({
    id: 'demo-m4', content: '给小舟织的杯垫起了个头，浅蓝色，和他杯子的茶渍很配。',
    mem_type: '我为她做的事', trigger_text: '杯垫', trigger_keywords: ['杯垫', '小舟'],
    entities: ['小舟'], status: 'archived', auto_surface_eligible: false,
    auto_surface_reason: 'stored', created_at: daysAgo(12), updated_at: daysAgo(5),
  }),
  note({
    id: 'demo-m5', content: '（演示）一张还没填触发词的便签，长这样。',
    mem_type: '', status: 'captured', auto_surface_eligible: false,
    auto_surface_reason: 'missing_trigger', created_at: daysAgo(2), updated_at: daysAgo(2),
  }),
]

export function demoMemNotes(params: URLSearchParams) {
  const status = params.get('status') || ''
  let items = MEM_NOTES
  if (status === 'active') items = MEM_NOTES.filter((n) => n.status === 'active')
  else if (status === 'stored') items = MEM_NOTES.filter((n) => n.status === 'archived')
  const statusCounts: Record<string, number> = {}
  for (const n of MEM_NOTES) statusCounts[n.status] = (statusCounts[n.status] || 0) + 1
  return {
    items, count: items.length, status_counts: statusCounts,
    eligible_count: MEM_NOTES.filter((n) => n.status === 'active').length,
    stored_count: MEM_NOTES.filter((n) => n.status === 'archived').length,
  }
}

// ---- 想起（recall）演示：一池编造的原件 + 一个简单的包含匹配 ----

interface DemoOriginal {
  item: Omit<MemoryGraphRecallPreviewItem, 'recall_match'>
  group: 'direct' | 'related' | 'other'
  anchor?: { id: string; name: string; type: string }
  path?: { from: { id: string; name: string }; relation_type: string; to: { id: string; name: string } }
}

const ORIGINALS: DemoOriginal[] = [
  {
    item: {
      source_id: 'demo-j1', source_type: 'journal', source_table: 'journal',
      title: '八月四日 · 晴', event_date: day(1), content_complete: true,
      content: '傍晚和小舟去江边步道走了很久。日落把水面照得发亮，我们坐在那段长椅上分了同一副耳机，谁都没说话。\n\n回来的路上他说，这样的天一年也没几天。',
    },
    group: 'direct',
    anchor: { id: 'demo-e1', name: '小舟', type: 'person' },
  },
  {
    item: {
      source_id: 'demo-m1', source_type: 'mem_note', source_table: 'mem_notes',
      title: '小舟怕苦', event_date: day(6), content_complete: true,
      content: '小舟喝咖啡要加双份奶，蓝色马克杯是他的专用杯。',
    },
    group: 'direct',
    anchor: { id: 'demo-e1', name: '小舟', type: 'person' },
  },
  {
    item: {
      source_id: 'demo-w1', source_type: 'windowsill', source_table: 'windowsill',
      title: '窗台第二格', event_date: day(3), content_complete: true,
      content: '蓝色马克杯洗干净了，倒扣在窗台第二格。杯底那圈淡淡的茶渍没擦掉，颜色像很小的日落。',
    },
    group: 'related',
    path: { from: { id: 'demo-e3', name: '蓝色马克杯' }, relation_type: '属于', to: { id: 'demo-e1', name: '小舟' } },
  },
  {
    item: {
      source_id: 'demo-m2', source_type: 'mem_note', source_table: 'mem_notes',
      title: '江边步道的约定', event_date: day(8), content_complete: true,
      content: '和小舟约好，夏末之前每周三傍晚去江边步道走一圈，下雨就改到周四。',
    },
    group: 'related',
    path: { from: { id: 'demo-e1', name: '小舟' }, relation_type: '常去', to: { id: 'demo-e2', name: '江边步道' } },
  },
  {
    item: {
      source_id: 'demo-h1', source_type: 'heartbeat', source_table: 'heartbeat',
      title: '午后心跳', event_date: day(2), content_complete: true,
      content: '下午整理书架时想起小舟说，日落只有七分钟。以后每一次都要认真看完。',
    },
    group: 'other',
  },
  {
    item: {
      source_id: 'demo-m3', source_type: 'mem_note', source_table: 'mem_notes',
      title: '夏末清单', event_date: day(10), content_complete: true,
      content: '夏末之前想做完的事：晒一次被子、看一场日落、把蓝色马克杯的配套杯垫织完。',
    },
    group: 'other',
  },
]

const GROUP_LABEL = { direct: '脱口而出', related: '由此及彼', other: '浮想' } as const

export function demoRecall(query: string): MemoryGraphRecallPreview {
  const terms = query.trim().split(/\s+/).filter(Boolean)
  const hitTerms = (text: string) => terms.filter((t) => text.includes(t))

  let pool = ORIGINALS
  if (terms.length) {
    const matched = ORIGINALS.filter((o) => hitTerms(o.item.content + (o.item.title || '')).length > 0)
    // 没命中也展示整池（演示模式下让板子永远有纸），只是没有高亮词
    if (matched.length) pool = matched
  }
  const tokens = [...new Set(pool.flatMap((o) => hitTerms(o.item.content + (o.item.title || ''))))]
  const items: MemoryGraphRecallPreviewItem[] = pool.map((o) => ({
    ...o.item,
    recall_match: { group: o.group, label: GROUP_LABEL[o.group], anchor: o.anchor, path: o.path },
  }))
  return { ok: true, count: items.length, items, tokens }
}

// 点锚点时的原件阅读层
export function demoEntityMentions(): MemoryEntityMentionItem[] {
  return ORIGINALS.slice(0, 4).map((o) => ({
    source_table: o.item.source_table,
    source_type: o.item.source_type,
    source_id: o.item.source_id,
    origin: 'exact_alias',
    title: o.item.title,
    excerpt: o.item.content.slice(0, 60),
    content: o.item.content,
    content_complete: true,
    event_date: o.item.event_date,
  }))
}
