<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NEmpty,
  NInput,
  NPopconfirm,
  NSelect,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  addMemoryEntityAlias,
  archiveMemoryEntityRelation,
  backfillMemoryGraph,
  createMemoryEntity,
  createMemoryEntityRelation,
  deleteMemoryEntityAlias,
  fetchMemoryGraph,
  fetchMemoryGraphNameCandidates,
  fetchSourceEntityMentions,
  previewMemoryGraphRecall,
  replaceSourceEntities,
  updateMemoryEntity,
  updateMemoryEntityAlias,
  updateMemoryEntityRelation,
  type MemoryEntity,
  type MemoryEntityRelation,
  type MemoryGraphNameCandidate,
  type MemoryGraphRecallPreviewItem,
  type MemoryEntityType,
  type MemoryRecallMatchGroup,
  type SourceEntityMention,
} from '@/api/memoryGraph'

const message = useMessage()
const tab = ref<'net' | 'recall'>('net')
const entities = ref<MemoryEntity[]>([])
const relations = ref<MemoryEntityRelation[]>([])
const anchorEntities = ref<MemoryEntity[]>([])
const available = ref(true)
const loadError = ref('')
const loading = ref(false)
const saving = ref(false)
const backfilling = ref(false)
const query = ref('')
const typeFilter = ref<MemoryEntityType | ''>('')
const selectedId = ref('')

const candidates = ref<MemoryGraphNameCandidate[]>([])
const drawerOpen = ref(false)
const drawerLoading = ref(false)
const archivedEntities = ref<MemoryEntity[]>([])

const createType = ref<MemoryEntityType>('person')
const createName = ref('')
const createAliases = ref('')

const editName = ref('')
const editDescription = ref('')
const aliasDraft = ref('')
const relationTarget = ref('')
const relationType = ref('')
const relationEvidence = ref('')

const recallQuery = ref('')
const recalling = ref(false)
const recallHasRun = ref(false)
const recallError = ref('')
const recallItems = ref<MemoryGraphRecallPreviewItem[]>([])
const recallManualAnchorIds = ref<Record<string, string[]>>({})
const recallSourceMentions = ref<Record<string, SourceEntityMention[]>>({})
const recallSourceMentionsLoaded = ref<Record<string, boolean>>({})
const savingRecallSourceKey = ref('')

const entityTypeOptions = [
  { label: '人物', value: 'person' },
  { label: '地点', value: 'place' },
  { label: '物件', value: 'object' },
  { label: '主题', value: 'topic' },
]
const filterTypeOptions = [{ label: '全部', value: '' }, ...entityTypeOptions]
const TYPE_COLOR: Record<string, string> = {
  person: '#2a78d6',
  place: '#1baf7a',
  object: '#eb6834',
  topic: '#4a3aa7',
}

const selected = computed(() => entities.value.find((item) => item.id === selectedId.value) || null)
const entityById = computed(() => Object.fromEntries(entities.value.map((item) => [item.id, item])))
const targetOptions = computed(() => anchorEntities.value
  .filter((item) => item.id !== selectedId.value && item.status === 'active')
  .map((item) => ({ label: `${item.canonical_name} · ${typeLabel(item.entity_type)}`, value: item.id })))
const recallAnchorOptions = computed(() => anchorEntities.value
  .filter((item) => item.status === 'active')
  .map((item) => ({ label: `${item.canonical_name} · ${typeLabel(item.entity_type)}`, value: item.id })))
const selectedRelations = computed(() => relations.value.filter((item) => (
  (item.source_entity_id === selectedId.value || item.target_entity_id === selectedId.value)
  && item.status !== 'archived'
)))
const confirmedRelationCount = computed(() => relations.value.filter((r) => r.status === 'confirmed').length)
const recallGroups = computed(() => [
  { key: 'direct', label: '直达', items: recallItems.value.filter((item) => item.recall_match?.group === 'direct') },
  { key: 'related', label: '顺着关系', items: recallItems.value.filter((item) => item.recall_match?.group === 'related') },
  { key: 'other', label: '联想', items: recallItems.value.filter((item) => item.recall_match?.group === 'other') },
].filter((group) => group.items.length))

// ---------- net layout (deterministic force simulation) ----------
const GRAPH_W = 880
const GRAPH_H = 600

interface GraphNode {
  entity: MemoryEntity
  x: number
  y: number
  r: number
  labelY: number
  subY: number
  dots: { x: number; y: number }[]
}
interface GraphEdge {
  relation: MemoryEntityRelation
  d: string
  lx: number
  ly: number
  dashed: boolean
}

const graphLayout = computed<{ nodes: GraphNode[]; edges: GraphEdge[] }>(() => {
  const active = entities.value.filter((item) => item.status === 'active')
  const n = active.length
  if (!n) return { nodes: [], edges: [] }
  const indexById: Record<string, number> = Object.fromEntries(active.map((item, i) => [item.id, i]))
  const rs = active.map((item) => 13 + Math.min(13, Math.sqrt(item.mention_count || 0) * 3.6))
  const xs = active.map((_, i) => GRAPH_W / 2 + (170 + (i % 3) * 46) * Math.cos(i * 2.399963))
  const ys = active.map((_, i) => GRAPH_H / 2 - 14 + (120 + (i % 3) * 32) * Math.sin(i * 2.399963))
  const links: Array<[number, number]> = []
  for (const relation of relations.value) {
    if (relation.status !== 'confirmed' && relation.status !== 'suggested') continue
    const a = indexById[relation.source_entity_id]
    const b = indexById[relation.target_entity_id]
    if (a === undefined || b === undefined || a === b) continue
    links.push([a, b])
  }
  for (let iter = 0; iter < 260; iter++) {
    const fx = new Array(n).fill(0)
    const fy = new Array(n).fill(0)
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = xs[i] - xs[j]
        let dy = ys[i] - ys[j]
        let d2 = dx * dx + dy * dy
        if (d2 < 1) {
          dx = (((i * 37 + j * 13) % 7) - 3) || 1
          dy = (((i * 17 + j * 29) % 7) - 3) || 1
          d2 = dx * dx + dy * dy
        }
        const d = Math.sqrt(d2)
        const push = Math.min(26, 21000 / d2)
        fx[i] += (dx / d) * push
        fy[i] += (dy / d) * push
        fx[j] -= (dx / d) * push
        fy[j] -= (dy / d) * push
      }
      fx[i] += (GRAPH_W / 2 - xs[i]) * 0.012
      fy[i] += (GRAPH_H / 2 - 10 - ys[i]) * 0.014
    }
    for (const [a, b] of links) {
      const dx = xs[b] - xs[a]
      const dy = ys[b] - ys[a]
      const d = Math.sqrt(dx * dx + dy * dy) || 1
      const rest = rs[a] + rs[b] + 128
      const pull = (d - rest) * 0.016
      fx[a] += (dx / d) * pull
      fy[a] += (dy / d) * pull
      fx[b] -= (dx / d) * pull
      fy[b] -= (dy / d) * pull
    }
    for (let i = 0; i < n; i++) {
      xs[i] += Math.max(-13, Math.min(13, fx[i]))
      ys[i] += Math.max(-13, Math.min(13, fy[i]))
      xs[i] = Math.max(72, Math.min(GRAPH_W - 72, xs[i]))
      ys[i] = Math.max(78, Math.min(GRAPH_H - 96, ys[i]))
    }
  }
  const nodes: GraphNode[] = active.map((entity, i) => {
    const r = rs[i]
    const dotCount = Math.min(6, entity.mention_count || 0)
    const dots: { x: number; y: number }[] = []
    for (let k = 0; k < dotCount; k++) {
      const deg = dotCount === 1 ? -90 : -200 + k * (220 / (dotCount - 1))
      const ang = (deg * Math.PI) / 180
      const rr = r + 12 + (k % 2) * 6
      dots.push({ x: xs[i] + rr * Math.cos(ang), y: ys[i] + rr * Math.sin(ang) })
    }
    return { entity, x: xs[i], y: ys[i], r, labelY: ys[i] + r + 20, subY: ys[i] + r + 35, dots }
  })
  const nodeById: Record<string, GraphNode> = Object.fromEntries(nodes.map((node) => [node.entity.id, node]))
  const edges: GraphEdge[] = []
  for (const relation of relations.value) {
    if (relation.status !== 'confirmed' && relation.status !== 'suggested') continue
    const a = nodeById[relation.source_entity_id]
    const b = nodeById[relation.target_entity_id]
    if (!a || !b || a === b) continue
    const mx = (a.x + b.x) / 2
    const my = (a.y + b.y) / 2
    const dist = Math.hypot(b.x - a.x, b.y - a.y)
    const cy = my + Math.min(26, dist * 0.09)
    edges.push({
      relation,
      d: `M ${a.x.toFixed(1)} ${a.y.toFixed(1)} Q ${mx.toFixed(1)} ${cy.toFixed(1)} ${b.x.toFixed(1)} ${b.y.toFixed(1)}`,
      lx: mx,
      ly: (my + cy) / 2 - 5,
      dashed: relation.status === 'suggested',
    })
  }
  return { nodes, edges }
})

// ---------- recall ripple layout ----------
const RIPPLE_W = 880
const RIPPLE_H = 620

interface RippleNode {
  item: MemoryGraphRecallPreviewItem
  x: number
  y: number
  group: MemoryRecallMatchGroup
  color: string
  label: string
  threadLabel: string
}

const rippleLayout = computed<{ cx: number; cy: number; rings: number[]; nodes: RippleNode[] }>(() => {
  const cx = RIPPLE_W / 2
  const cy = 300
  const ringR: Record<MemoryRecallMatchGroup, number> = { direct: 120, related: 205, other: 285 }
  const nodes: RippleNode[] = []
  for (const group of ['direct', 'related', 'other'] as MemoryRecallMatchGroup[]) {
    const items = recallItems.value.filter((item) => item.recall_match?.group === group)
    items.forEach((item, i) => {
      const ang = ((-90 + (i * 360) / Math.max(items.length, 3)) * Math.PI) / 180
      const anchorType = group === 'related'
        ? item.recall_match?.path?.to?.type
        : item.recall_match?.anchor?.type
      nodes.push({
        item,
        x: cx + ringR[group] * Math.cos(ang),
        y: cy + ringR[group] * Math.sin(ang),
        group,
        color: TYPE_COLOR[anchorType || ''] || '#a4938d',
        label: (item.title || sourceLabel(item.source_type)).slice(0, 12),
        threadLabel: group === 'related'
          ? (item.recall_match?.path?.relation_type || '')
          : group === 'direct'
            ? (item.recall_match?.anchor?.name || '')
            : '',
      })
    })
  }
  return { cx, cy, rings: [120, 205, 285], nodes }
})

onMounted(async () => {
  await Promise.all([loadGraph(), loadAnchorEntities(), loadCandidates()])
})

function splitAliases(value: string): string[] {
  return [...new Set(value.split(/[,，、\n]+/).map((item) => item.trim()).filter(Boolean))]
}

function typeLabel(type: string): string {
  return ({ person: '人物', place: '地点', object: '物件', topic: '主题' } as Record<string, string>)[type] || type
}

function sourceLabel(type: string): string {
  return ({
    journal: '日记',
    windowsill: '窗台',
    heartbeat: '心跳',
    room: '房间',
    board: '留言',
    memory: '旧记忆',
    calendar: '日历',
    mem_note: 'Mem',
    notebook: '笔记',
  } as Record<string, string>)[type] || type
}

function sourceKey(item: Pick<MemoryGraphRecallPreviewItem, 'source_table' | 'source_id'>): string {
  return `${item.source_table} ${item.source_id}`
}

function sourceMentions(item: MemoryGraphRecallPreviewItem): SourceEntityMention[] {
  return recallSourceMentions.value[sourceKey(item)] || []
}

function sourceDate(item: MemoryGraphRecallPreviewItem): string {
  return (item.event_date || '').replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}

function selectEntity(entity: MemoryEntity) {
  selectedId.value = entity.id
  editName.value = entity.canonical_name
  editDescription.value = entity.description || ''
  aliasDraft.value = ''
  relationTarget.value = ''
  relationType.value = ''
  relationEvidence.value = ''
}

async function loadGraph(keepSelection = true) {
  loading.value = true
  try {
    const result = await fetchMemoryGraph({
      q: query.value.trim() || undefined,
      entity_type: typeFilter.value || undefined,
    })
    available.value = result.available
    loadError.value = result.error || ''
    entities.value = result.entities || []
    relations.value = result.relations || []
    if (!keepSelection || !entities.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = ''
    } else if (selected.value) {
      selectEntity(selected.value)
    }
  } catch {
    message.error('读取记忆网络失败')
  } finally {
    loading.value = false
  }
}

async function loadAnchorEntities() {
  try {
    const result = await fetchMemoryGraph()
    anchorEntities.value = result.entities || []
  } catch {
    anchorEntities.value = []
  }
}

async function loadCandidates() {
  try {
    candidates.value = await fetchMemoryGraphNameCandidates(20)
  } catch {
    candidates.value = []
  }
}

async function loadArchived() {
  drawerLoading.value = true
  try {
    const result = await fetchMemoryGraph({ include_archived: true })
    archivedEntities.value = (result.entities || []).filter((item) => item.status === 'archived')
  } catch {
    archivedEntities.value = []
  } finally {
    drawerLoading.value = false
  }
}

function toggleDrawer() {
  drawerOpen.value = !drawerOpen.value
  if (drawerOpen.value) void loadArchived()
}

function useCandidate(candidate: MemoryGraphNameCandidate) {
  createName.value = candidate.name
  createType.value = candidate.kind
}

async function createEntity() {
  if (!createName.value.trim()) return
  saving.value = true
  try {
    const entity = await createMemoryEntity({
      entity_type: createType.value,
      canonical_name: createName.value.trim(),
      description: '',
      aliases: splitAliases(createAliases.value),
    })
    createName.value = ''
    createAliases.value = ''
    await Promise.all([loadGraph(false), loadAnchorEntities(), loadCandidates()])
    const created = entities.value.find((item) => item.id === entity.id)
    if (created) selectEntity(created)
    message.success('锚点已钉住')
  } catch {
    message.error('建立锚点失败')
  } finally {
    saving.value = false
  }
}

async function saveEntity() {
  if (!selected.value || !editName.value.trim()) return
  saving.value = true
  try {
    await updateMemoryEntity(selected.value.id, {
      canonical_name: editName.value.trim(),
      description: editDescription.value.trim(),
    })
    await Promise.all([loadGraph(), loadAnchorEntities()])
    message.success('锚点已保存')
  } catch {
    message.error('保存锚点失败')
  } finally {
    saving.value = false
  }
}

async function archiveEntity() {
  if (!selected.value) return
  saving.value = true
  try {
    await updateMemoryEntity(selected.value.id, { status: 'archived' })
    await Promise.all([loadGraph(false), loadAnchorEntities()])
    if (drawerOpen.value) await loadArchived()
    message.success('已收进抽屉')
  } catch {
    message.error('归档失败')
  } finally {
    saving.value = false
  }
}

async function restoreEntity(entityId: string) {
  saving.value = true
  try {
    await updateMemoryEntity(entityId, { status: 'active' })
    await Promise.all([loadGraph(), loadAnchorEntities(), loadArchived()])
    message.success('已放回网里')
  } catch {
    message.error('放回失败')
  } finally {
    saving.value = false
  }
}

async function addAlias() {
  if (!selected.value || !aliasDraft.value.trim()) return
  saving.value = true
  try {
    await addMemoryEntityAlias(selected.value.id, aliasDraft.value.trim())
    aliasDraft.value = ''
    await Promise.all([loadGraph(), loadAnchorEntities(), loadCandidates()])
    message.success('别名已确认')
  } catch {
    message.error('添加别名失败')
  } finally {
    saving.value = false
  }
}

async function confirmAlias(aliasId: string) {
  saving.value = true
  try {
    await updateMemoryEntityAlias(aliasId, { status: 'confirmed' })
    await Promise.all([loadGraph(), loadAnchorEntities()])
    message.success('别名已确认')
  } catch {
    message.error('确认别名失败')
  } finally {
    saving.value = false
  }
}

async function removeAlias(aliasId: string) {
  saving.value = true
  try {
    await deleteMemoryEntityAlias(aliasId)
    await Promise.all([loadGraph(), loadAnchorEntities()])
    message.success('别名已移除')
  } catch {
    message.error('移除别名失败')
  } finally {
    saving.value = false
  }
}

async function addRelation() {
  if (!selected.value || !relationTarget.value || !relationType.value.trim()) return
  saving.value = true
  try {
    await createMemoryEntityRelation({
      source_entity_id: selected.value.id,
      target_entity_id: relationTarget.value,
      relation_type: relationType.value.trim(),
      evidence: relationEvidence.value.trim(),
    })
    relationTarget.value = ''
    relationType.value = ''
    relationEvidence.value = ''
    await loadGraph()
    message.success('红线已牵好')
  } catch {
    message.error('建立关系失败')
  } finally {
    saving.value = false
  }
}

async function confirmRelation(relationId: string) {
  saving.value = true
  try {
    await updateMemoryEntityRelation(relationId, { status: 'confirmed' })
    await loadGraph()
    message.success('关系已确认')
  } catch {
    message.error('确认关系失败')
  } finally {
    saving.value = false
  }
}

async function archiveRelation(relationId: string) {
  saving.value = true
  try {
    await archiveMemoryEntityRelation(relationId)
    await loadGraph()
    message.success('关系已收起')
  } catch {
    message.error('收起关系失败')
  } finally {
    saving.value = false
  }
}

async function runBackfill() {
  backfilling.value = true
  try {
    const result = await backfillMemoryGraph()
    await loadGraph()
    message.success(`扫描 ${result.scanned_sources} 个原件，连上 ${result.matched_sources} 个`)
  } catch {
    message.error('历史关联扫描失败')
  } finally {
    backfilling.value = false
  }
}

async function loadRecallSourceMentions(items: MemoryGraphRecallPreviewItem[]) {
  const manual: Record<string, string[]> = Object.fromEntries(items.map((item) => [sourceKey(item), []]))
  const mentionsBySource: Record<string, SourceEntityMention[]> = {}
  const loaded: Record<string, boolean> = Object.fromEntries(items.map((item) => [sourceKey(item), false]))
  recallManualAnchorIds.value = manual
  recallSourceMentions.value = mentionsBySource
  recallSourceMentionsLoaded.value = loaded
  if (!available.value) return
  await Promise.all(items.map(async (item) => {
    try {
      const mentions = await fetchSourceEntityMentions(item.source_table, item.source_id)
      const key = sourceKey(item)
      mentionsBySource[key] = mentions
      loaded[key] = true
      manual[key] = mentions
        .filter((mention) => mention.origin === 'manual')
        .map((mention) => mention.entity_id)
    } catch {
      // A preview result remains usable even if its optional anchor lookup fails.
    }
  }))
  recallSourceMentions.value = { ...mentionsBySource }
  recallManualAnchorIds.value = { ...manual }
  recallSourceMentionsLoaded.value = { ...loaded }
}

async function runRecallPreview() {
  const text = recallQuery.value.trim()
  if (!text) return
  recalling.value = true
  recallHasRun.value = true
  recallError.value = ''
  try {
    const result = await previewMemoryGraphRecall(text)
    if (!result.ok) {
      recallItems.value = []
      recallError.value = result.error || '这次没有读到 recall 结果'
      return
    }
    recallItems.value = result.items || []
    await loadRecallSourceMentions(recallItems.value)
  } catch {
    recallItems.value = []
    recallError.value = '试着想起时没有读到结果'
  } finally {
    recalling.value = false
  }
}

function recallEntity(entity: MemoryEntity) {
  tab.value = 'recall'
  recallQuery.value = entity.canonical_name
  void runRecallPreview()
}

async function saveRecallAnchors(item: MemoryGraphRecallPreviewItem) {
  const key = sourceKey(item)
  if (savingRecallSourceKey.value || !recallSourceMentionsLoaded.value[key]) return
  savingRecallSourceKey.value = key
  try {
    await replaceSourceEntities({
      source_table: item.source_table,
      source_type: item.source_type,
      source_id: item.source_id,
      entity_ids: recallManualAnchorIds.value[key] || [],
      evidence: '记忆网络想起页手动确认',
    })
    const mentions = await fetchSourceEntityMentions(item.source_table, item.source_id)
    recallSourceMentions.value = { ...recallSourceMentions.value, [key]: mentions }
    recallSourceMentionsLoaded.value = { ...recallSourceMentionsLoaded.value, [key]: true }
    recallManualAnchorIds.value = {
      ...recallManualAnchorIds.value,
      [key]: mentions.filter((mention) => mention.origin === 'manual').map((mention) => mention.entity_id),
    }
    message.success('关联已保存')
  } catch {
    message.error('保存关联失败')
  } finally {
    savingRecallSourceKey.value = ''
  }
}

function otherEntity(relation: MemoryEntityRelation): MemoryEntity | undefined {
  const otherId = relation.source_entity_id === selectedId.value
    ? relation.target_entity_id
    : relation.source_entity_id
  return entityById.value[otherId]
}
</script>

<template>
  <div class="graph-page" data-testid="page-memory-graph">
    <header class="page-head">
      <div>
        <h2>记忆网络</h2>
        <span>{{ entities.length }} 个锚点 · {{ confirmedRelationCount }} 条红线</span>
      </div>
      <nav class="tab-rail" role="tablist">
        <button role="tab" :aria-selected="tab === 'net'" data-testid="memory-graph-tab-net" @click="tab = 'net'">记忆之网</button>
        <button role="tab" :aria-selected="tab === 'recall'" data-testid="memory-graph-tab-recall" @click="tab = 'recall'">想起的一瞬间</button>
      </nav>
    </header>

    <div v-if="!available" class="unavailable">
      <b>记忆网络尚未启用</b>
      <span>{{ loadError }}</span>
    </div>

    <!-- ============ 记忆之网 ============ -->
    <section v-show="tab === 'net'">
      <div class="toolbar">
        <NInput v-model:value="query" clearable placeholder="搜索名称或别名" data-testid="memory-graph-search" @keyup.enter="loadGraph(false)" @clear="loadGraph(false)" />
        <NSelect v-model:value="typeFilter" :options="filterTypeOptions" @update:value="loadGraph(false)" />
        <NButton :loading="backfilling" :disabled="!available" @click="runBackfill">扫描历史关联</NButton>
        <NButton quaternary :type="drawerOpen ? 'primary' : 'default'" @click="toggleDrawer">抽屉</NButton>
      </div>

      <div v-if="drawerOpen" class="drawer">
        <NSpin :show="drawerLoading">
          <div v-if="archivedEntities.length" class="drawer-list">
            <div v-for="entity in archivedEntities" :key="entity.id" class="drawer-row">
              <span class="drawer-name">{{ entity.canonical_name }}</span>
              <span class="drawer-meta">{{ typeLabel(entity.entity_type) }}</span>
              <NButton size="tiny" :loading="saving" @click="restoreEntity(entity.id)">放回</NButton>
            </div>
          </div>
          <p v-else class="drawer-empty">抽屉是空的</p>
        </NSpin>
      </div>

      <NSpin :show="loading">
        <div class="canvas-card">
          <svg :viewBox="`0 0 ${GRAPH_W} ${GRAPH_H}`" role="img" aria-label="记忆网络星图">
            <defs>
              <filter id="mg-blur" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="7" />
              </filter>
              <radialGradient id="mg-spec" cx="0.35" cy="0.28" r="0.8">
                <stop offset="0%" stop-color="#ffffff" stop-opacity="0.85" />
                <stop offset="45%" stop-color="#ffffff" stop-opacity="0.2" />
                <stop offset="100%" stop-color="#ffffff" stop-opacity="0" />
              </radialGradient>
            </defs>
            <g v-for="edge in graphLayout.edges" :key="edge.relation.id">
              <path class="thread" :class="{ dashed: edge.dashed }" :d="edge.d" />
              <text class="thread-label" :x="edge.lx" :y="edge.ly">{{ edge.relation.relation_type }}</text>
            </g>
            <g
              v-for="node in graphLayout.nodes"
              :key="node.entity.id"
              class="star"
              :class="{ selected: node.entity.id === selectedId }"
              role="button"
              tabindex="0"
              :aria-label="`锚点：${node.entity.canonical_name}`"
              @click="selectEntity(node.entity)"
              @keydown.enter.prevent="selectEntity(node.entity)"
              @keydown.space.prevent="selectEntity(node.entity)"
            >
              <circle class="halo" :cx="node.x" :cy="node.y" :r="node.r + 14" :fill="TYPE_COLOR[node.entity.entity_type]" filter="url(#mg-blur)" />
              <circle class="orb-body" :cx="node.x" :cy="node.y" :r="node.r" :fill="TYPE_COLOR[node.entity.entity_type]" />
              <circle :cx="node.x" :cy="node.y" :r="node.r" fill="url(#mg-spec)" />
              <circle class="orb-rim" :cx="node.x" :cy="node.y" :r="node.r" :stroke="TYPE_COLOR[node.entity.entity_type]" />
              <circle v-for="(dot, i) in node.dots" :key="i" class="mention-dot" :cx="dot.x" :cy="dot.y" r="3.5" />
              <text class="star-label" :x="node.x" :y="node.labelY">{{ node.entity.canonical_name }}</text>
              <text class="star-sub" :x="node.x" :y="node.subY">{{ typeLabel(node.entity.entity_type) }} · {{ node.entity.mention_count }}</text>
            </g>
            <text v-if="!graphLayout.nodes.length" class="canvas-empty" :x="GRAPH_W / 2" :y="GRAPH_H / 2">还没有锚点，先钉一个名字</text>
          </svg>
          <div class="legend">
            <span v-for="option in entityTypeOptions" :key="option.value" class="legend-item">
              <span class="legend-dot" :style="{ borderColor: TYPE_COLOR[option.value], background: TYPE_COLOR[option.value] + '4d' }"></span>{{ option.label }}
            </span>
            <span class="legend-item"><span class="legend-line"></span>红线</span>
            <span class="legend-item"><span class="legend-line dashed"></span>候选</span>
          </div>
        </div>
      </NSpin>

      <div class="create-band">
        <NSelect v-model:value="createType" :options="entityTypeOptions" aria-label="锚点类型" />
        <NInput v-model:value="createName" placeholder="名称" @keyup.enter="createEntity" />
        <NInput v-model:value="createAliases" placeholder="小名、外号，用逗号分开" />
        <NButton type="primary" :loading="saving" :disabled="!available || !createName.trim()" @click="createEntity">建立锚点</NButton>
      </div>
      <div v-if="candidates.length" class="candidate-band">
        <span class="candidate-label">沈予提过：</span>
        <button v-for="candidate in candidates" :key="candidate.kind + candidate.name" class="candidate-chip" @click="useCandidate(candidate)">
          {{ candidate.name }} <small>{{ typeLabel(candidate.kind) }} · {{ candidate.count }}</small>
        </button>
      </div>

      <div v-if="selected" class="detail">
        <div class="detail-title">
          <div>
            <h3>{{ selected.canonical_name }}</h3>
            <span class="type-chip" :style="{ background: TYPE_COLOR[selected.entity_type] }">{{ typeLabel(selected.entity_type) }}</span>
            <span class="detail-meta">{{ selected.mention_count }} 个原件 · {{ selected.relation_count }} 条红线</span>
          </div>
          <div class="detail-title-actions">
            <NButton size="small" quaternary @click="recallEntity(selected)">让沈予想起 →</NButton>
            <NPopconfirm positive-text="收进抽屉" negative-text="取消" @positive-click="archiveEntity">
              <template #trigger><NButton size="small">归档</NButton></template>
              收进抽屉，随时可以放回。
            </NPopconfirm>
          </div>
        </div>

        <div class="edit-row">
          <NInput v-model:value="editName" placeholder="名称" />
          <NInput v-model:value="editDescription" placeholder="备注（可空）" />
          <NButton size="small" :loading="saving" @click="saveEntity">保存</NButton>
        </div>

        <div class="detail-block">
          <h4>别名</h4>
          <div class="tag-list">
            <NTag v-for="alias in selected.aliases" :key="alias.id" :bordered="false" size="small">
              {{ alias.alias }}
              <button v-if="alias.status !== 'confirmed'" class="tag-action confirm" title="确认这个候选" @click="confirmAlias(alias.id)">✓ 候选</button>
              <button v-if="!alias.is_primary" class="tag-action" title="移除别名" @click="removeAlias(alias.id)">×</button>
            </NTag>
            <span class="inline-add">
              <NInput v-model:value="aliasDraft" size="small" placeholder="新增" @keyup.enter="addAlias" />
              <NButton size="small" :loading="saving" :disabled="!aliasDraft.trim()" @click="addAlias">＋</NButton>
            </span>
          </div>
        </div>

        <div class="detail-block">
          <h4>原件</h4>
          <div class="source-counts">
            <span v-for="(count, source) in selected.source_type_counts" :key="source">{{ sourceLabel(String(source)) }} <b>{{ count }}</b></span>
            <span v-if="!Object.keys(selected.source_type_counts).length" class="muted">还没有</span>
          </div>
        </div>

        <div class="detail-block">
          <h4>红线</h4>
          <div v-if="selectedRelations.length" class="relation-list">
            <div v-for="relation in selectedRelations" :key="relation.id" class="relation-row">
              <div>
                <b>{{ relation.relation_type }}</b>
                <span>{{ otherEntity(relation)?.canonical_name || '未知锚点' }}</span>
                <small v-if="relation.evidence">{{ relation.evidence }}</small>
              </div>
              <div class="relation-actions">
                <NButton v-if="relation.status === 'suggested'" size="tiny" type="primary" @click="confirmRelation(relation.id)">✓ 候选</NButton>
                <NButton size="tiny" quaternary @click="archiveRelation(relation.id)">收起</NButton>
              </div>
            </div>
          </div>
          <div class="relation-form">
            <NSelect v-model:value="relationTarget" filterable :options="targetOptions" placeholder="连到谁" />
            <NInput v-model:value="relationType" placeholder="关系" @keyup.enter="addRelation" />
            <NInput v-model:value="relationEvidence" placeholder="备注（可空）" />
            <NButton :loading="saving" :disabled="!relationTarget || !relationType.trim()" @click="addRelation">牵红线</NButton>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 想起的一瞬间 ============ -->
    <section v-show="tab === 'recall'" data-testid="memory-graph-recall-preview">
      <div class="recall-bar">
        <NInput
          v-model:value="recallQuery"
          clearable
          placeholder="人、地点、一段话或心情"
          data-testid="memory-graph-recall-input"
          @keyup.enter="runRecallPreview"
        />
        <NButton type="primary" :loading="recalling" :disabled="!recallQuery.trim()" @click="runRecallPreview">想起</NButton>
      </div>

      <p v-if="recallError" class="recall-error">{{ recallError }}</p>
      <NEmpty v-else-if="recallHasRun && !recalling && !recallItems.length" description="还没有找到相连的原件" />

      <div v-if="recallItems.length" class="canvas-card">
        <svg :viewBox="`0 0 ${RIPPLE_W} ${RIPPLE_H}`" role="img" aria-label="这次想起的涟漪">
          <defs>
            <radialGradient id="mg-spec-r" cx="0.35" cy="0.28" r="0.8">
              <stop offset="0%" stop-color="#ffffff" stop-opacity="0.85" />
              <stop offset="45%" stop-color="#ffffff" stop-opacity="0.2" />
              <stop offset="100%" stop-color="#ffffff" stop-opacity="0" />
            </radialGradient>
          </defs>
          <circle v-for="r in rippleLayout.rings" :key="r" class="ripple-ring" :cx="rippleLayout.cx" :cy="rippleLayout.cy" :r="r" />
          <text class="ring-tag" :x="rippleLayout.cx" :y="rippleLayout.cy - 128">直达</text>
          <text class="ring-tag" :x="rippleLayout.cx" :y="rippleLayout.cy - 213">顺着关系</text>
          <text class="ring-tag" :x="rippleLayout.cx" :y="rippleLayout.cy - 293">联想</text>
          <g v-for="(node, i) in rippleLayout.nodes" :key="i">
            <template v-if="node.group !== 'other'">
              <path class="thread" :d="`M ${rippleLayout.cx} ${rippleLayout.cy} Q ${(rippleLayout.cx + node.x) / 2} ${(rippleLayout.cy + node.y) / 2 + 14} ${node.x} ${node.y}`" />
              <text v-if="node.threadLabel" class="thread-label" :x="(rippleLayout.cx + node.x) / 2" :y="(rippleLayout.cy + node.y) / 2 + 2">{{ node.threadLabel }}</text>
            </template>
            <circle v-if="node.group === 'other'" class="echo-ring" :cx="node.x" :cy="node.y" r="9" />
            <template v-else>
              <circle class="orb-body" :cx="node.x" :cy="node.y" r="11" :fill="node.color" />
              <circle :cx="node.x" :cy="node.y" r="11" fill="url(#mg-spec-r)" />
              <circle class="orb-rim" :cx="node.x" :cy="node.y" r="11" :stroke="node.color" />
            </template>
            <text class="star-sub" :x="node.x" :y="node.y + 26">{{ node.label }}</text>
          </g>
          <circle class="q-glow" :cx="rippleLayout.cx" :cy="rippleLayout.cy" r="42" />
          <circle class="orb-body" :cx="rippleLayout.cx" :cy="rippleLayout.cy" r="13" fill="#aa3c60" />
          <circle :cx="rippleLayout.cx" :cy="rippleLayout.cy" r="13" fill="url(#mg-spec-r)" />
          <circle class="orb-rim" :cx="rippleLayout.cx" :cy="rippleLayout.cy" r="13" stroke="#aa3c60" />
          <text class="q-label" :x="rippleLayout.cx" :y="rippleLayout.cy + 40">「{{ recallQuery.trim().slice(0, 20) }}」</text>
        </svg>
      </div>

      <div v-if="recallGroups.length" class="recall-groups">
        <section v-for="group in recallGroups" :key="group.key" class="recall-group">
          <h4>{{ group.label }}</h4>
          <article v-for="item in group.items" :key="sourceKey(item)" class="recall-item">
            <header class="recall-item-head">
              <div>
                <b>{{ item.title || sourceLabel(item.source_type) }}</b>
                <span>{{ sourceLabel(item.source_type) }}<template v-if="sourceDate(item)"> · {{ sourceDate(item) }}</template></span>
              </div>
              <NTag size="small" :bordered="false">{{ item.recall_match.label }}</NTag>
            </header>
            <pre class="recall-content">{{ item.content }}</pre>
            <p v-if="item.content_complete === false" class="recall-incomplete">原文暂时无法完整读取：{{ item.content_error }}</p>
            <div v-if="available" class="recall-anchor-editor">
              <NSelect
                v-model:value="recallManualAnchorIds[sourceKey(item)]"
                multiple
                filterable
                clearable
                :options="recallAnchorOptions"
                placeholder="关联锚点"
              />
              <NButton
                size="small"
                :disabled="!recallSourceMentionsLoaded[sourceKey(item)]"
                :loading="savingRecallSourceKey === sourceKey(item)"
                @click="saveRecallAnchors(item)"
              >保存关联</NButton>
              <div v-if="sourceMentions(item).filter(m => m.origin !== 'manual').length" class="recall-auto-anchors">
                <NTag
                  v-for="mention in sourceMentions(item).filter(m => m.origin !== 'manual')"
                  :key="mention.id"
                  size="small"
                  :bordered="false"
                >{{ mention.entity?.canonical_name || mention.matched_alias }}</NTag>
              </div>
            </div>
          </article>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.graph-page {
  --mg-ink: #231a19;
  --mg-ink-2: #6e615f;
  --mg-ink-3: #a3928f;
  --mg-hairline: #e7dbd6;
  --mg-panel: #fbf8f6;
  --mg-thread: #c25573;
  --mg-rose: #aa3c60;
  --mg-mention: #a4938d;
  --mg-halo: #f9f1ee;
  width: min(1180px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 20px 0 40px;
  color: var(--mg-ink);
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.page-head h2 {
  font-size: 22px;
  font-weight: 600;
}

.page-head > div > span {
  color: var(--mg-ink-3);
  font-size: 12px;
}

.tab-rail {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--mg-hairline);
  border-radius: 999px;
  background: #f1e9e6;
}

.tab-rail button {
  border: 0;
  border-radius: 999px;
  background: none;
  color: var(--mg-ink-3);
  font-size: 13px;
  padding: 6px 16px;
  cursor: pointer;
}

.tab-rail button[aria-selected='true'] {
  background: var(--mg-panel);
  color: var(--mg-ink);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(35, 26, 25, 0.08);
}

.unavailable {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 16px;
  padding: 12px 14px;
  border-left: 3px solid #c8956a;
  background: #fff8f1;
  color: #76594a;
}

.toolbar {
  display: grid;
  grid-template-columns: minmax(180px, 300px) 110px auto auto;
  gap: 8px;
  margin: 16px 0 12px;
}

.drawer {
  margin: 0 0 12px;
  padding: 10px 14px;
  border: 1px dashed var(--mg-hairline);
  border-radius: 12px;
  background: var(--mg-panel);
}

.drawer-list {
  display: grid;
  gap: 6px;
}

.drawer-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.drawer-name {
  font-weight: 600;
  font-size: 13px;
}

.drawer-meta {
  color: var(--mg-ink-3);
  font-size: 12px;
}

.drawer-empty {
  margin: 0;
  color: var(--mg-ink-3);
  font-size: 13px;
}

.canvas-card {
  border: 1px solid var(--mg-hairline);
  border-radius: 16px;
  background: radial-gradient(ellipse 100% 85% at 50% 112%, #f6dfe3 0%, #f7ece9 45%, #fbf7f5 80%);
  overflow: hidden;
}

.canvas-card svg {
  display: block;
  width: 100%;
  height: auto;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  padding: 0 14px 10px;
  font-size: 12px;
  color: var(--mg-ink-2);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid;
  box-sizing: border-box;
}

.legend-line {
  width: 16px;
  border-top: 2px solid var(--mg-thread);
}

.legend-line.dashed {
  border-top-style: dashed;
}

.thread {
  fill: none;
  stroke: var(--mg-thread);
  stroke-width: 1.6;
  opacity: 0.6;
}

.thread.dashed {
  stroke-dasharray: 5 4;
}

.thread-label {
  font-size: 11px;
  fill: var(--mg-ink-2);
  text-anchor: middle;
  paint-order: stroke;
  stroke: var(--mg-halo);
  stroke-width: 4px;
  stroke-linejoin: round;
}

.star {
  cursor: pointer;
}

.star:focus {
  outline: none;
}

.halo {
  opacity: 0.16;
  transition: opacity 0.3s;
}

.star.selected .halo {
  opacity: 0.5;
}

.orb-body {
  fill-opacity: 0.3;
}

.orb-rim {
  fill: none;
  stroke-width: 1.6;
  stroke-opacity: 0.85;
  transition: stroke-width 0.15s;
}

.star:hover .orb-rim,
.star:focus-visible .orb-rim,
.star.selected .orb-rim {
  stroke-width: 3;
}

.mention-dot {
  fill: var(--mg-mention);
  opacity: 0.85;
}

.star-label {
  font-size: 14px;
  font-weight: 600;
  fill: var(--mg-ink);
  text-anchor: middle;
  pointer-events: none;
  paint-order: stroke;
  stroke: var(--mg-halo);
  stroke-width: 3px;
  stroke-linejoin: round;
}

.star-sub {
  font-size: 10.5px;
  fill: var(--mg-ink-3);
  text-anchor: middle;
  pointer-events: none;
  font-variant-numeric: tabular-nums;
}

.canvas-empty {
  fill: var(--mg-ink-3);
  font-size: 14px;
  text-anchor: middle;
}

.create-band {
  display: grid;
  grid-template-columns: 110px minmax(140px, 1fr) minmax(200px, 1.4fr) auto;
  gap: 8px;
  margin: 14px 0 0;
}

.candidate-band {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.candidate-label {
  color: var(--mg-ink-3);
  font-size: 12px;
}

.candidate-chip {
  border: 1px dashed var(--mg-ink-3);
  border-radius: 999px;
  background: none;
  color: var(--mg-ink-2);
  font-size: 12.5px;
  padding: 3px 12px;
  cursor: pointer;
}

.candidate-chip:hover {
  border-color: var(--mg-rose);
  color: var(--mg-rose);
}

.candidate-chip small {
  color: var(--mg-ink-3);
}

.detail {
  margin-top: 16px;
  padding: 18px 20px;
  border: 1px solid var(--mg-hairline);
  border-radius: 16px;
  background: var(--mg-panel);
}

.detail-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.detail-title > div {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.detail-title h3 {
  font-size: 19px;
  font-weight: 600;
  margin: 0;
}

.type-chip {
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  border-radius: 999px;
  padding: 1px 10px;
  letter-spacing: 0.08em;
}

.detail-meta {
  color: var(--mg-ink-3);
  font-size: 12px;
}

.detail-title-actions {
  display: flex;
  gap: 8px;
}

.edit-row {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(180px, 1.5fr) auto;
  gap: 8px;
  margin: 14px 0 4px;
}

.detail-block {
  padding: 14px 0 0;
}

.detail-block h4 {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.18em;
  color: var(--mg-ink-3);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.tag-action {
  margin-left: 6px;
  border: 0;
  background: transparent;
  color: var(--mg-ink-3);
  cursor: pointer;
  font-size: 12px;
}

.tag-action.confirm {
  color: var(--mg-rose);
  font-weight: 600;
}

.inline-add {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  width: 180px;
}

.source-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.source-counts span {
  padding: 4px 9px;
  border: 1px solid var(--mg-hairline);
  border-radius: 8px;
  font-size: 12px;
  color: var(--mg-ink-2);
}

.muted {
  color: var(--mg-ink-3);
}

.relation-list {
  display: grid;
  gap: 2px;
  margin-bottom: 10px;
}

.relation-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 2px;
  border-bottom: 1px solid #f1e7e3;
}

.relation-row > div:first-child {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
}

.relation-row b {
  font-size: 13.5px;
}

.relation-row span {
  font-size: 13px;
  color: var(--mg-ink-2);
}

.relation-row small {
  color: var(--mg-ink-3);
  font-size: 12px;
}

.relation-actions {
  display: flex;
  gap: 6px;
}

.relation-form {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(120px, 1fr) minmax(160px, 1.2fr) auto;
  gap: 8px;
}

.recall-bar {
  display: grid;
  grid-template-columns: minmax(220px, 480px) auto;
  gap: 8px;
  margin: 16px 0 12px;
}

.recall-error,
.recall-incomplete {
  margin: 0 0 12px;
  padding: 10px 14px;
  color: #8d4c25;
  background: #fff7ed;
  border-radius: 10px;
  font-size: 12px;
}

.ripple-ring {
  fill: none;
  stroke: var(--mg-hairline);
  stroke-width: 1;
}

.ring-tag {
  font-size: 11px;
  fill: var(--mg-ink-3);
  letter-spacing: 0.24em;
  text-anchor: middle;
}

.echo-ring {
  fill: none;
  stroke: var(--mg-ink-3);
  stroke-width: 1.5;
  stroke-dasharray: 4 3;
  opacity: 0.8;
}

.q-glow {
  fill: rgba(194, 85, 115, 0.16);
}

.q-label {
  font-size: 13px;
  font-weight: 600;
  fill: var(--mg-ink);
  text-anchor: middle;
  paint-order: stroke;
  stroke: var(--mg-halo);
  stroke-width: 3px;
  stroke-linejoin: round;
}

.recall-groups {
  display: grid;
  gap: 14px;
  margin-top: 14px;
}

.recall-group {
  border: 1px solid var(--mg-hairline);
  border-radius: 16px;
  background: var(--mg-panel);
  padding: 14px 18px;
}

.recall-group h4 {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.22em;
  color: var(--mg-ink-2);
}

.recall-item {
  padding: 12px 0;
  border-top: 1px solid #f1e7e3;
}

.recall-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.recall-item-head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.recall-item-head b {
  color: var(--mg-ink);
  font-size: 14px;
  overflow-wrap: anywhere;
}

.recall-item-head span {
  color: var(--mg-ink-3);
  font-size: 12px;
}

.recall-item-head :deep(.n-tag) {
  max-width: min(48vw, 360px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recall-content {
  margin: 10px 0;
  color: var(--mg-ink);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
}

.recall-anchor-editor {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px dashed var(--mg-hairline);
}

.recall-auto-anchors {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 820px) {
  .toolbar,
  .create-band,
  .edit-row,
  .relation-form,
  .recall-anchor-editor {
    grid-template-columns: 1fr;
  }

  .recall-bar {
    grid-template-columns: 1fr auto;
  }

  .detail-title,
  .recall-item-head {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
