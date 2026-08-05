<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
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
  fetchMemoryCandidateMentions,
  fetchMemoryEntityMentions,
  fetchMemoryGraph,
  fetchMemoryGraphNameCandidates,
  previewMemoryGraphRecall,
  updateMemoryEntity,
  updateMemoryEntityAlias,
  updateMemoryEntityRelation,
  type MemoryCandidateMention,
  type MemoryCandidateTextHit,
  type MemoryEntity,
  type MemoryEntityMentionItem,
  type MemoryEntityRelation,
  type MemoryGraphCandidateLink,
  type MemoryGraphNameCandidate,
  type MemoryGraphRecallPreviewItem,
  type MemoryGraphRecentItem,
  type MemoryEntityType,
} from '@/api/memoryGraph'
import AnchorOriginalsOverlay, { type OverlayPaper } from './memory-graph/AnchorOriginalsOverlay.vue'
import RecallBoard from './memory-graph/RecallBoard.vue'
import { sourceLabel } from './memory-graph/sourceDisplay'

const message = useMessage()
const tab = ref<'net' | 'recall'>('net')
const entities = ref<MemoryEntity[]>([])
const relations = ref<MemoryEntityRelation[]>([])
const anchorEntities = ref<MemoryEntity[]>([])
const recentActivity = ref<MemoryGraphRecentItem[]>([])
const available = ref(true)
const loadError = ref('')
const loading = ref(false)
const saving = ref(false)
const backfilling = ref(false)
const query = ref('')
const typeFilter = ref<MemoryEntityType | ''>('')
const selectedId = ref('')
const selectedMentions = ref<MemoryEntityMentionItem[]>([])
const mentionsLoading = ref(false)
const manageOpen = ref(false)

const candidates = ref<MemoryGraphNameCandidate[]>([])
const candidateLinks = ref<MemoryGraphCandidateLink[]>([])
const ghostCard = ref<MemoryGraphNameCandidate | null>(null)
const ghostMentions = ref<MemoryCandidateMention[]>([])
const ghostTextHits = ref<MemoryCandidateTextHit[]>([])
const ghostLoading = ref(false)
const overlayOpen = ref(false)
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
const recallTokens = ref<string[]>([])
const recallRunId = ref(0)

const entityTypeOptions = [
  { label: '人物', value: 'person' },
  { label: '地点', value: 'place' },
  { label: '物件', value: 'object' },
  { label: '主题', value: 'topic' },
]
const filterTypeOptions = [{ label: '全部', value: '' }, ...entityTypeOptions]
// 类别色全部取自设计 token（CSS 变量，随昼夜换）：人 = 松绿，地 = 古金，物 = 玫瑰，题 = 鼠尾草。
const TYPE_COLOR: Record<string, string> = {
  person: 'var(--sy-resident)',
  place: 'var(--sy-gilt-d)',
  object: 'var(--sy-self-d)',
  topic: 'var(--sy-sage)',
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
// 当前想起的词若正好是一个确认过的锚点，木板板签就露出「管理这个名字」。
const recallMatchedAnchor = computed(() => {
  const q = recallQuery.value.trim().toLowerCase()
  if (!q) return null
  return anchorEntities.value.find(
    (item) => item.status === 'active' && item.canonical_name.trim().toLowerCase() === q,
  ) || null
})

function openAnchorManage() {
  const anchor = recallMatchedAnchor.value
  if (!anchor) return
  selectEntity(anchor)
  overlayOpen.value = true
}

// ---------- net layout (deterministic force simulation, typographic nodes) ----------
const GRAPH_W = 880
const GRAPH_H = 600

interface GraphNode {
  entity: MemoryEntity
  x: number
  y: number
  size: number
  warm: '' | 'warm' | 'fresh'
}
interface GraphEdge {
  relation: MemoryEntityRelation
  d: string
  lx: number
  ly: number
  dashed: boolean
}
interface GhostNode {
  candidate: MemoryGraphNameCandidate
  x: number
  y: number
  anchor: GraphNode
}

function warmTier(entity: MemoryEntity): '' | 'warm' | 'fresh' {
  const at = entity.last_mentioned_at
  if (!at) return ''
  const time = new Date(at).getTime()
  if (!time) return ''
  const days = (Date.now() - time) / 86400000
  if (days <= 2) return 'fresh'
  if (days <= 7) return 'warm'
  return ''
}

const graphLayout = computed<{ nodes: GraphNode[]; edges: GraphEdge[]; ghosts: GhostNode[] }>(() => {
  // 同一份数据必须排出同一张网：按 id 定序，刷新/改名后不再整网重排。
  const active = entities.value
    .filter((item) => item.status === 'active')
    .slice()
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  const n = active.length
  if (!n) return { nodes: [], edges: [], ghosts: [] }
  const indexById: Record<string, number> = Object.fromEntries(active.map((item, i) => [item.id, i]))
  const sizes = active.map((item) => 15 + Math.min(10, Math.sqrt(item.mention_count || 0) * 2.6))
  const rs = active.map((item, i) => Math.min(112, Math.max(38, item.canonical_name.length * sizes[i] * 0.62)))

  // 连通分量：confirmed/suggested 红线当绑定，把相连的锚点划进同一座小岛。
  const parent = active.map((_, i) => i)
  const find = (x: number): number => (parent[x] === x ? x : (parent[x] = find(parent[x])))
  const links: Array<[number, number]> = []
  for (const relation of relations.value) {
    if (relation.status !== 'confirmed' && relation.status !== 'suggested') continue
    const a = indexById[relation.source_entity_id]
    const b = indexById[relation.target_entity_id]
    if (a === undefined || b === undefined || a === b) continue
    links.push([a, b])
    parent[find(a)] = find(b)
  }
  const clusterOf = active.map((_, i) => find(i))
  const clusterIds = [...new Set(clusterOf)]
  // 多成员的簇按热度排前面，单成员的「孤岛」排最后、贴板底。
  const multi = clusterIds.filter((c) => clusterOf.filter((x) => x === c).length > 1)
  const singles = clusterIds.filter((c) => clusterOf.filter((x) => x === c).length === 1)
  // 热度相同的小岛按成员最小 id 定先后，布局才稳。
  const clusterMinId = new Map<number, string>()
  active.forEach((item, i) => {
    const c = clusterOf[i]
    if (!clusterMinId.has(c) || item.id < (clusterMinId.get(c) as string)) clusterMinId.set(c, item.id)
  })
  multi.sort((a, b) => clusterHeat(b) - clusterHeat(a) || ((clusterMinId.get(a) || '') < (clusterMinId.get(b) || '') ? -1 : 1))
  const orderedClusters = [...multi, ...singles]
  function clusterHeat(c: number): number {
    return active.reduce((sum, item, i) => (clusterOf[i] === c ? sum + (item.mention_count || 0) : sum), 0)
  }
  const clusterIndex = new Map(orderedClusters.map((c, i) => [c, i]))

  // 每座小岛一个岛心：多成员簇散布在画布中上部，孤岛沿底部一字排开。
  const centerX = new Map<number, number>()
  const centerY = new Map<number, number>()
  const multiCount = multi.length
  multi.forEach((c, k) => {
    const cols = Math.ceil(Math.sqrt(multiCount))
    const rows = Math.ceil(multiCount / cols)
    const col = k % cols
    const row = Math.floor(k / cols)
    const gx = cols === 1 ? 0.5 : 0.22 + (col / (cols - 1)) * 0.56
    const gy = rows === 1 ? 0.42 : 0.24 + (row / (rows - 1)) * 0.36
    centerX.set(c, GRAPH_W * gx)
    centerY.set(c, GRAPH_H * gy)
  })
  singles.forEach((c, k) => {
    const gx = singles.length === 1 ? 0.5 : 0.12 + (k / (singles.length - 1)) * 0.76
    centerX.set(c, GRAPH_W * gx)
    centerY.set(c, GRAPH_H * 0.86)
  })

  // 初始位置：多成员簇绕岛心一圈，孤岛就落在自己的岛心。
  const xs = new Array(n).fill(0)
  const ys = new Array(n).fill(0)
  const memberIndex = new Map<number, number>()
  for (let i = 0; i < n; i++) {
    const c = clusterOf[i]
    const idx = memberIndex.get(c) || 0
    memberIndex.set(c, idx + 1)
    const cx = centerX.get(c) || GRAPH_W / 2
    const cy = centerY.get(c) || GRAPH_H / 2
    const members = clusterOf.filter((x) => x === c).length
    if (members > 1) {
      const ang = (idx / members) * Math.PI * 2 - Math.PI / 2
      const ring = 56 + members * 8
      xs[i] = cx + ring * Math.cos(ang)
      ys[i] = cy + ring * Math.sin(ang) * 0.8
    } else {
      xs[i] = cx
      ys[i] = cy
    }
  }

  // 轻力导向收尾：簇内向岛心聚拢 + 彼此不重叠，红线轻轻拉住，孤岛不被拖走。
  for (let iter = 0; iter < 240; iter++) {
    const fx = new Array(n).fill(0)
    const fy = new Array(n).fill(0)
    for (let i = 0; i < n; i++) {
      const c = clusterOf[i]
      const cx = centerX.get(c) || GRAPH_W / 2
      const cy = centerY.get(c) || GRAPH_H / 2
      fx[i] += (cx - xs[i]) * 0.03
      fy[i] += (cy - ys[i]) * 0.03
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
        const sameCluster = clusterOf[i] === clusterOf[j]
        const push = Math.min(sameCluster ? 18 : 30, (sameCluster ? 9000 : 26000) / d2)
        fx[i] += (dx / d) * push
        fy[i] += (dy / d) * push
        fx[j] -= (dx / d) * push
        fy[j] -= (dy / d) * push
      }
    }
    for (const [a, b] of links) {
      const dx = xs[b] - xs[a]
      const dy = ys[b] - ys[a]
      const d = Math.sqrt(dx * dx + dy * dy) || 1
      const rest = rs[a] + rs[b] + 66
      const pull = (d - rest) * 0.02
      fx[a] += (dx / d) * pull
      fy[a] += (dy / d) * pull
      fx[b] -= (dx / d) * pull
      fy[b] -= (dy / d) * pull
    }
    for (let i = 0; i < n; i++) {
      xs[i] += Math.max(-12, Math.min(12, fx[i]))
      ys[i] += Math.max(-12, Math.min(12, fy[i]))
      xs[i] = Math.max(88, Math.min(GRAPH_W - 88, xs[i]))
      ys[i] = Math.max(60, Math.min(GRAPH_H - 60, ys[i]))
    }
  }

  const nodes: GraphNode[] = active.map((entity, i) => ({
    entity,
    x: xs[i],
    y: ys[i],
    size: sizes[i],
    warm: warmTier(entity),
  }))
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
  // Ghost satellites: unanchored names that share a mem note with an anchor,
  // parked quietly next to it. No co-occurrence, no ghost — chips below
  // remain their home.
  const ghosts: GhostNode[] = []
  const linkByName = new Map(candidateLinks.value.map((link) => [link.name, link]))
  for (const candidate of candidates.value) {
    if (ghosts.length >= 8) break
    const link = linkByName.get(candidate.name)
    if (!link) continue
    const anchor = nodeById[link.entity_id]
    if (!anchor) continue
    const ang = ((-90 + ghosts.length * 137.5) * Math.PI) / 180
    const dist = 96
    ghosts.push({
      candidate,
      x: Math.max(56, Math.min(GRAPH_W - 56, anchor.x + dist * Math.cos(ang))),
      y: Math.max(40, Math.min(GRAPH_H - 48, anchor.y + dist * Math.sin(ang))),
      anchor,
    })
  }
  return { nodes, edges, ghosts }
})

// ---------- recall (shown the way Shenyu receives it; gateway accounting stays hidden) ----------

onMounted(async () => {
  await Promise.all([loadGraph(), loadAnchorEntities(), loadCandidates()])
})

function splitAliases(value: string): string[] {
  return [...new Set(value.split(/[,，、\n]+/).map((item) => item.trim()).filter(Boolean))]
}

function typeLabel(type: string): string {
  return ({ person: '人物', place: '地点', object: '物件', topic: '主题' } as Record<string, string>)[type] || type
}

function sourceDate(item: MemoryGraphRecallPreviewItem): string {
  return (item.event_date || '').replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}

function timeAgo(at?: string): string {
  if (!at) return ''
  const time = new Date(at).getTime()
  if (!time) return ''
  const days = Math.floor((Date.now() - time) / 86400000)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 30) return `${days} 天前`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months} 个月前`
  return `${Math.floor(months / 12)} 年前`
}

function selectEntity(entity: MemoryEntity) {
  selectedId.value = entity.id
  editName.value = entity.canonical_name
  editDescription.value = entity.description || ''
  aliasDraft.value = ''
  relationTarget.value = ''
  relationType.value = ''
  relationEvidence.value = ''
  void loadSelectedMentions(entity.id)
}

// Reading overlay: picking a name off the net lifts its papers up front.
// 点一个词 = 把它的原件阅读卡抬到前面（不再拽去想起页；
// 想去木板「想起」，用详情里的「让沈予想起 →」）。
function openAnchor(entity: MemoryEntity) {
  ghostCard.value = null
  selectEntity(entity)
  overlayOpen.value = true
}

function closeOverlay() {
  overlayOpen.value = false
  if (ghostCard.value) closeGhost()
}

const anchorPapers = computed<OverlayPaper[]>(() =>
  selectedMentions.value.map((mention) => ({
    key: `${mention.source_table} ${mention.source_id}`,
    sourceType: mention.source_type,
    sourceTable: mention.source_table,
    sourceId: mention.source_id,
    title: mention.title || '',
    dateLabel: shortDate(mention.event_date),
    content: mention.content || mention.excerpt || '',
    complete: mention.content_complete !== false,
    badge: mention.origin === 'manual' ? '你钉的' : '',
  })),
)

const ghostPapers = computed<OverlayPaper[]>(() => [
  ...ghostMentions.value.map((note) => ({
    key: `mem ${note.id}`,
    sourceType: 'mem_note',
    title: note.mem_type || 'Mem',
    dateLabel: shortDate(note.event_date),
    content: note.content,
    complete: true,
    badge: note.kind || '',
  })),
  ...ghostTextHits.value.map((hit) => ({
    key: `${hit.source_table} ${hit.source_id}`,
    sourceType: hit.source_type,
    title: hit.title || '',
    dateLabel: shortDate(hit.event_date),
    content: hit.content || hit.excerpt || '',
    complete: hit.content_complete !== false,
    badge: '',
  })),
])

const overlayAnchor = computed(() => (overlayOpen.value && !ghostCard.value ? selected.value : null))
const overlayGhost = computed(() => (overlayOpen.value ? ghostCard.value : null))
const overlayPapers = computed(() => (ghostCard.value ? ghostPapers.value : anchorPapers.value))
const overlayLoading = computed(() => (ghostCard.value ? ghostLoading.value : mentionsLoading.value))

async function onOverlayEntityMutated() {
  await Promise.all([loadGraph(), loadAnchorEntities()])
}

async function loadSelectedMentions(entityId: string) {
  mentionsLoading.value = true
  try {
    const items = await fetchMemoryEntityMentions(entityId)
    if (selectedId.value === entityId) selectedMentions.value = items
  } catch {
    if (selectedId.value === entityId) selectedMentions.value = []
  } finally {
    if (selectedId.value === entityId) mentionsLoading.value = false
  }
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
    recentActivity.value = result.recent || []
    if (!keepSelection || !entities.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = ''
      selectedMentions.value = []
      manageOpen.value = false
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
    const result = await fetchMemoryGraphNameCandidates(20)
    candidates.value = result.candidates
    candidateLinks.value = result.links
  } catch {
    candidates.value = []
    candidateLinks.value = []
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

async function openGhost(candidate: MemoryGraphNameCandidate) {
  selectedId.value = ''
  selectedMentions.value = []
  manageOpen.value = false
  overlayOpen.value = true
  ghostCard.value = candidate
  ghostMentions.value = []
  ghostTextHits.value = []
  ghostLoading.value = true
  try {
    const result = await fetchMemoryCandidateMentions(candidate.name)
    ghostMentions.value = result.items
    ghostTextHits.value = result.textHits
  } catch {
    ghostMentions.value = []
    ghostTextHits.value = []
  } finally {
    ghostLoading.value = false
  }
}

function closeGhost() {
  overlayOpen.value = false
  ghostCard.value = null
  ghostMentions.value = []
  ghostTextHits.value = []
}

async function pinGhostNow() {
  const candidate = ghostCard.value
  if (!candidate || saving.value) return
  saving.value = true
  try {
    const entity = await createMemoryEntity({
      entity_type: candidate.kind,
      canonical_name: candidate.name,
      description: '',
      aliases: [],
    })
    await Promise.all([loadGraph(false), loadAnchorEntities(), loadCandidates()])
    closeGhost()
    const created = entities.value.find((item) => item.id === entity.id)
    if (created) selectEntity(created)
    message.success('锚点已钉住；点「扫描历史关联」把旧原件连上来')
  } catch {
    message.error('建立锚点失败')
  } finally {
    saving.value = false
  }
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
      recallTokens.value = []
      recallError.value = result.error || '这次没有读到 recall 结果'
      return
    }
    recallItems.value = result.items || []
    recallTokens.value = result.tokens || []
    recallRunId.value += 1
  } catch {
    recallItems.value = []
    recallTokens.value = []
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

function otherEntity(relation: MemoryEntityRelation): MemoryEntity | undefined {
  const otherId = relation.source_entity_id === selectedId.value
    ? relation.target_entity_id
    : relation.source_entity_id
  return entityById.value[otherId]
}

// ---------- evidence rendering ----------
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, (ch) => '\\' + ch)
}

const highlightTokens = computed(() => {
  const tokens = recallTokens.value.filter(Boolean)
  const text = recallQuery.value.trim()
  const all = text ? [text, ...tokens] : [...tokens]
  return [...new Set(all)].sort((a, b) => b.length - a.length).slice(0, 12)
})

function highlightSegments(item: MemoryGraphRecallPreviewItem): { text: string; hit: boolean }[] {
  const content = item.content || ''
  const tokens = highlightTokens.value
  if (!content || !tokens.length) return [{ text: content, hit: false }]
  const re = new RegExp(`(${tokens.map(escapeRegExp).join('|')})`, 'gi')
  const segments: { text: string; hit: boolean }[] = []
  let last = 0
  for (const match of content.matchAll(re)) {
    const index = match.index ?? 0
    if (index > last) segments.push({ text: content.slice(last, index), hit: false })
    segments.push({ text: match[0], hit: true })
    last = index + match[0].length
  }
  if (last < content.length) segments.push({ text: content.slice(last), hit: false })
  return segments
}

function shortDate(value?: string): string {
  return (value || '').slice(0, 10)
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
        <p class="drawer-note">收起来的锚点住在这里——不删，只是不挂在网上了，随时可以放回。</p>
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
          <svg :viewBox="`0 0 ${GRAPH_W} ${GRAPH_H}`" role="img" aria-label="记忆网络">
            <g v-for="edge in graphLayout.edges" :key="edge.relation.id">
              <path class="thread" :class="{ dashed: edge.dashed }" :d="edge.d" />
              <text class="thread-label" :x="edge.lx" :y="edge.ly">{{ edge.relation.relation_type }}</text>
            </g>
            <g
              v-for="node in graphLayout.nodes"
              :key="node.entity.id"
              class="anchor"
              :class="[{ selected: node.entity.id === selectedId }, node.warm]"
              role="button"
              tabindex="0"
              :aria-label="`锚点：${node.entity.canonical_name}`"
              @click="openAnchor(node.entity)"
              @keydown.enter.prevent="openAnchor(node.entity)"
              @keydown.space.prevent="openAnchor(node.entity)"
            >
              <circle class="type-dot" :cx="node.x" :cy="node.y - node.size - 13" r="3.2" :style="{ fill: TYPE_COLOR[node.entity.entity_type] }" />
              <text class="anchor-name" :x="node.x" :y="node.y" :style="{ fontSize: `${node.size}px` }">{{ node.entity.canonical_name }}</text>
              <text class="anchor-sub" :x="node.x" :y="node.y + 19">{{ typeLabel(node.entity.entity_type) }} · 提及 {{ node.entity.mention_count }}</text>
            </g>
            <g
              v-for="ghost in graphLayout.ghosts"
              :key="ghost.candidate.name"
              class="ghost"
              role="button"
              tabindex="0"
              :aria-label="`还没钉的名字：${ghost.candidate.name}，点一下看原文`"
              @click="openGhost(ghost.candidate)"
              @keydown.enter.prevent="openGhost(ghost.candidate)"
            >
              <path class="ghost-tie" :d="`M ${ghost.anchor.x} ${ghost.anchor.y} L ${ghost.x.toFixed(1)} ${ghost.y.toFixed(1)}`" />
              <text class="ghost-name" :x="ghost.x" :y="ghost.y">{{ ghost.candidate.name }}</text>
              <text class="ghost-sub" :x="ghost.x" :y="ghost.y + 14">未钉 · 提过 {{ ghost.candidate.count }}</text>
            </g>
            <text v-if="!graphLayout.nodes.length" class="canvas-empty" :x="GRAPH_W / 2" :y="GRAPH_H / 2">还没有锚点，先钉一个名字</text>
          </svg>
          <div class="legend">
            <span v-for="option in entityTypeOptions" :key="option.value" class="legend-item">
              <span class="legend-dot" :style="{ background: TYPE_COLOR[option.value] }"></span>{{ option.label }}
            </span>
            <span class="legend-item"><span class="legend-line"></span>红线</span>
            <span class="legend-item"><span class="legend-line dashed"></span>候选</span>
            <span class="legend-item legend-note">名字变暖 = 最近被提起 · 虚线小字 = 还没钉，点一下钉住</span>
          </div>
        </div>
      </NSpin>

      <div v-if="recentActivity.length" class="recent-band">
        <h4>最近落进网里 <small>按事情发生的日子算</small></h4>
        <ul>
          <li v-for="(item, index) in recentActivity" :key="index">
            <span class="recent-mark" :class="item.kind"></span>
            <span class="recent-text">
              <template v-if="item.kind === 'mention'">「{{ item.entity_name }}」在{{ sourceLabel(item.source_type || '') }}里被提起</template>
              <template v-else>{{ item.source_name }} <i>—{{ item.relation_type }}→</i> {{ item.target_name }}</template>
            </span>
            <time>{{ timeAgo(item.at) }}</time>
          </li>
        </ul>
      </div>

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

        <button class="manage-toggle" @click="manageOpen = !manageOpen">
          {{ manageOpen ? '收起管理 ▾' : '管理 ▸' }}
        </button>
        <div v-show="manageOpen" class="manage-zone">
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
      </div>
    </section>

    <AnchorOriginalsOverlay
      :open="overlayOpen"
      :anchor="overlayAnchor"
      :ghost="overlayGhost"
      :papers="overlayPapers"
      :loading="overlayLoading"
      :anchor-options="recallAnchorOptions"
      @close="closeOverlay"
      @pin="pinGhostNow"
      @entity-mutated="onOverlayEntityMutated"
    />

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

      <RecallBoard
        :query="recallQuery.trim()"
        :items="recallItems"
        :loading="recalling"
        :error="recallError"
        :has-run="recallHasRun"
        :manage-anchor-name="recallMatchedAnchor?.canonical_name || ''"
        :highlight="highlightSegments"
        :source-date="sourceDate"
        :anchor-options="recallAnchorOptions"
        :run-id="recallRunId"
        @manage="openAnchorManage"
        @saved="onOverlayEntityMutated"
      />
    </section>
  </div>
</template>

<style scoped>
.graph-page {
  /* 桥接全局设计 token（token 在 :root 全局可用，这里不再自带 fallback 色） */
  --mg-paper: var(--sy-paper);
  --mg-panel: var(--sy-panel);
  --mg-ink: var(--sy-ink);
  --mg-ink-2: var(--sy-ink-2);
  --mg-ink-3: var(--sy-mute);
  --mg-hairline: var(--sy-hair-2);
  --mg-accent: var(--sy-accent);
  --mg-accent-ink: var(--sy-accent-d);
  --mg-gilt: var(--sy-gilt);
  --mg-gilt-d: var(--sy-gilt-d);
  --mg-hair-gilt: var(--sy-hair-gilt);
  --mg-accent-soft: var(--sy-rose-soft);
  --mg-resident: var(--sy-resident);
  --mg-resident-d: var(--sy-resident-d);
  --mg-serif: var(--sy-serif);
  width: min(1180px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 20px 0 48px;
  color: var(--mg-ink);
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.page-head h2 {
  font-family: var(--mg-serif);
  font-size: 30px;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.page-head > div > span {
  color: var(--mg-ink-3);
  font-size: 12px;
  letter-spacing: 0.06em;
}

.tab-rail {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--mg-hairline);
  border-radius: 999px;
  background: var(--mg-paper);
}

.tab-rail button {
  border: 0;
  border-radius: 999px;
  background: none;
  color: var(--mg-ink-3);
  font-size: 13px;
  padding: 6px 18px;
  cursor: pointer;
  transition: color 0.2s, background 0.2s;
}

.tab-rail button[aria-selected='true'] {
  background: var(--mg-panel);
  color: var(--mg-ink);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(60, 50, 43, 0.1);
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
  margin: 18px 0 12px;
}

.drawer {
  margin: 0 0 12px;
  padding: 12px 18px;
  border: 1px solid var(--mg-hairline);
  border-radius: 14px;
  background: var(--mg-panel);
  max-height: 220px;
  overflow: auto;
}

.drawer-note {
  margin: 0 0 8px;
  font-size: 12px;
  font-style: italic;
  color: var(--mg-ink-3);
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
  border: 1px solid var(--mg-hair-gilt);
  border-radius: 18px;
  background:
    radial-gradient(ellipse at 30% 18%, rgba(255, 252, 246, 0.5), transparent 55%),
    var(--mg-paper);
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
  align-items: center;
  gap: 4px 18px;
  padding: 12px 16px 14px;
  border-top: 1px dashed var(--mg-hairline);
  font-size: 12px;
  color: var(--mg-ink-2);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.legend-line {
  width: 18px;
  border-top: 1.5px solid var(--mg-accent);
  opacity: 0.6;
}

.legend-line.dashed {
  border-top-style: dashed;
}

.legend-note {
  margin-left: auto;
  color: var(--mg-ink-3);
  font-style: italic;
}

.thread {
  fill: none;
  stroke: var(--mg-gilt);
  stroke-width: 1.1;
  opacity: 0.5;
}

.thread.dashed {
  stroke-dasharray: 4 4;
  opacity: 0.32;
}

.thread-label {
  font-family: var(--mg-serif);
  font-size: 11.5px;
  font-style: italic;
  fill: var(--mg-ink-2);
  text-anchor: middle;
  paint-order: stroke;
  stroke: var(--mg-paper);
  stroke-width: 4px;
  stroke-linejoin: round;
}

.anchor {
  cursor: pointer;
}

.anchor:focus {
  outline: none;
}

.type-dot {
  opacity: 0.9;
}

.anchor.fresh .type-dot {
  stroke: var(--mg-resident);
  stroke-width: 1.5;
  stroke-opacity: 0.35;
}

.anchor-name {
  font-family: var(--mg-serif);
  font-weight: 600;
  fill: var(--mg-ink);
  text-anchor: middle;
  dominant-baseline: middle;
  paint-order: stroke;
  stroke: var(--mg-paper);
  stroke-width: 3px;
  stroke-linejoin: round;
  transition: fill 0.3s;
}

.anchor-sub {
  font-size: 11px;
  fill: var(--mg-ink-3);
  text-anchor: middle;
  font-variant-numeric: tabular-nums;
}

/* 名字变松绿 = 最近被沈予提起（fresh ≤ 2 天，warm ≤ 7 天） */
.anchor.warm .anchor-name {
  fill: var(--mg-resident);
  fill-opacity: 0.78;
}

.anchor.fresh .anchor-name {
  fill: var(--mg-resident);
}

.anchor:hover .anchor-name,
.anchor:focus-visible .anchor-name {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.anchor.selected .anchor-name {
  fill: var(--mg-accent-ink);
  text-decoration: underline;
  text-underline-offset: 4px;
}

.canvas-empty {
  fill: var(--mg-ink-3);
  font-family: var(--mg-serif);
  font-style: italic;
  font-size: 15px;
  text-anchor: middle;
}

.recent-band {
  margin-top: 14px;
  padding: 14px 20px 10px;
  border: 1px solid var(--mg-hairline);
  border-radius: 14px;
  background: var(--mg-panel);
}

.recent-band h4 {
  font-family: var(--mg-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--mg-ink-2);
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}

.recent-band h4 small {
  font-size: 11.5px;
  font-weight: 400;
  font-style: italic;
  color: var(--mg-ink-3);
  letter-spacing: 0.02em;
}

.recent-band ul {
  list-style: none;
  display: grid;
  gap: 2px;
}

.recent-band li {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 3px 0;
  font-size: 13px;
}

.recent-mark {
  flex: none;
  width: 14px;
  text-align: center;
}

.recent-mark.mention::before {
  content: '○';
  color: var(--mg-ink-3);
  font-size: 10px;
}

.recent-mark.relation::before {
  content: '—';
  color: var(--mg-accent);
}

.recent-text {
  color: var(--mg-ink);
}

.recent-text i {
  color: var(--mg-accent);
  font-style: normal;
  padding: 0 2px;
}

.recent-band time {
  margin-left: auto;
  color: var(--mg-ink-3);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.create-band {
  display: grid;
  grid-template-columns: 110px minmax(140px, 1fr) minmax(200px, 1.4fr) auto;
  gap: 8px;
  margin: 16px 0 0;
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
  border-color: var(--mg-accent);
  color: var(--mg-accent);
}

.candidate-chip small {
  color: var(--mg-ink-3);
}

.detail {
  margin-top: 18px;
  padding: 22px 24px;
  border: 1px solid var(--mg-hairline);
  border-radius: 18px;
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
  font-family: var(--mg-serif);
  font-size: 26px;
  font-weight: 600;
}

.type-chip {
  color: #fff;
  font-size: 11px;
  border-radius: 999px;
  padding: 2px 10px;
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
  grid-template-columns: minmax(140px, 240px) 1fr auto;
  gap: 8px;
  margin-top: 12px;
}

.detail-block {
  margin-top: 16px;
  border-top: 1px solid var(--mg-hairline);
  padding-top: 14px;
}

.detail-block h4 {
  font-family: var(--mg-serif);
  font-size: 16px;
  font-weight: 600;
  color: var(--mg-ink-2);
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}

.manage-toggle {
  margin-top: 16px;
  border: 0;
  background: none;
  color: var(--mg-ink-3);
  font-size: 12.5px;
  cursor: pointer;
  padding: 4px 0;
  letter-spacing: 0.05em;
}

.manage-toggle:hover {
  color: var(--mg-accent);
}

.manage-zone {
  margin-top: 4px;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.tag-action {
  border: 0;
  background: none;
  color: var(--mg-ink-3);
  cursor: pointer;
  font-size: 11px;
  margin-left: 4px;
  padding: 0 2px;
}

.tag-action:hover {
  color: var(--mg-accent);
}

.tag-action.confirm {
  color: var(--mg-accent-ink);
}

.inline-add {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}

.inline-add :deep(.n-input) {
  width: 140px;
}

.relation-list {
  display: grid;
  gap: 8px;
  margin-bottom: 10px;
}

.relation-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--mg-hairline);
  border-radius: 12px;
  background: var(--mg-paper);
}

.relation-row > div:first-child {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.relation-row b {
  color: var(--mg-accent-ink);
  font-family: var(--mg-serif);
  font-size: 15px;
}

.relation-row small {
  color: var(--mg-ink-3);
}

.relation-actions {
  display: flex;
  gap: 6px;
  flex: none;
}

.relation-form {
  display: grid;
  grid-template-columns: minmax(160px, 1.2fr) minmax(120px, 0.8fr) minmax(160px, 1fr) auto;
  gap: 8px;
}

/* ---------- 想起的一瞬间 ---------- */
.recall-bar {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  margin: 18px 0 14px;
}

.ghost {
  cursor: pointer;
}

.ghost:focus {
  outline: none;
}

.ghost-tie {
  fill: none;
  stroke: var(--mg-ink-3);
  stroke-width: 1;
  stroke-dasharray: 2 4;
  opacity: 0.55;
}

.ghost-name {
  font-family: var(--mg-serif);
  font-style: italic;
  font-size: 12.5px;
  fill: var(--mg-ink-3);
  text-anchor: middle;
  dominant-baseline: middle;
  paint-order: stroke;
  stroke: var(--mg-paper);
  stroke-width: 3px;
  stroke-linejoin: round;
  transition: fill 0.2s;
}

.ghost:hover .ghost-name,
.ghost:focus-visible .ghost-name {
  fill: var(--mg-accent);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.ghost-sub {
  font-size: 9.5px;
  fill: var(--mg-ink-3);
  text-anchor: middle;
  opacity: 0.8;
}

@media (max-width: 720px) {
  .toolbar {
    grid-template-columns: 96px 1fr auto;
  }

  .toolbar > :first-child {
    grid-column: 1 / -1;
  }

  .create-band {
    grid-template-columns: 96px 1fr;
  }

  .create-band > :nth-child(3) {
    grid-column: 1 / -1;
  }

  .create-band > :last-child {
    grid-column: 1 / -1;
  }

  .canvas-card {
    overflow-x: auto;
    overflow-y: hidden;
  }

  .canvas-card svg {
    min-width: 620px;
  }

  .relation-form {
    grid-template-columns: 1fr;
  }

  .edit-row {
    grid-template-columns: 1fr;
  }

  .page-head h2 {
    font-size: 26px;
  }
}
</style>
