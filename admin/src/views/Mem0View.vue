<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NCheckbox,
  NCollapse,
  NCollapseItem,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import type {
  GatewayConfig,
  LegacyAtomicMemoryItem,
  MemNoteItem,
  MemNotePatch,
  MemNoteStatus,
  MemNoteType,
  MemoryKind,
} from '@/api/config'
import {
  bulkUpdateMemNotes,
  deleteMemNote,
  fetchLegacyAtomicMemories,
  fetchMem0Config,
  fetchMemNotes,
  saveMem0Config,
  updateMemNote,
} from '@/api/mem0'
import {
  createMemoryEntity,
  fetchMemoryGraph,
  fetchSourceEntityMentions,
  replaceSourceEntities,
  type MemoryEntity,
  type MemoryEntityType,
  type SourceEntityMention,
} from '@/api/memoryGraph'

const message = useMessage()

/* ─── options ─── */
const memTypeOptions: Array<{ label: string; value: MemNoteType | '' }> = [
  { label: '全部分类', value: '' },
  { label: '她为我做的事', value: '她为我做的事' },
  { label: '我为她做的事', value: '我为她做的事' },
  { label: '关于她的事实', value: '关于她的事实' },
  { label: '关于我的事', value: '关于我的事' },
  { label: '心里那一档', value: '心里那一档' },
  { label: '承诺', value: '承诺' },
]

const memoryKindOptions: Array<{ label: string; value: MemoryKind | '' }> = [
  { label: '全部种类', value: '' },
  { label: '事件', value: 'event' },
  { label: '关于 ta', value: 'person_fact' },
  { label: '社交', value: 'social' },
  { label: '旅行', value: 'trip' },
  { label: '物品', value: 'object' },
  { label: '偏好', value: 'preference' },
  { label: '日常', value: 'routine' },
  { label: '承诺', value: 'promise' },
  { label: '我们的梗', value: 'running_joke' },
  { label: '话题线', value: 'thread' },
]

type MemViewStatus = 'eligible' | 'stored' | 'all'

const statusTabs: Array<{ label: string; value: MemViewStatus }> = [
  { label: '可自动想起', value: 'eligible' },
  { label: '已收起', value: 'stored' },
  { label: '全部', value: 'all' },
]

/* ─── config state ─── */
const MEM_TUNING_DEFAULTS: Partial<GatewayConfig> = {
  inject_mem_notes: true,
  enable_gateway_tools: true,
  enable_mem0_management_tools: true,
  mem_note_limit: 3,
  mem_note_min_score: 0.45,
  mem_note_context_keyword_min_score: 0.25,
  mem_note_semantic_min_score: 0.4,
  mem_note_semantic_min_vector_score: 0.5,
  mem_note_anchored_semantic_min_score: 0.3,
  mem_note_anchored_semantic_min_vector_score: 0.42,
  mem_note_dedupe_turns: 6,
  mem_note_soft_cooldown_hours: 12,
  mem_note_default_cooldown_hours: 12,
}

const config = ref<Partial<GatewayConfig>>({
  inject_mem_notes: true,
  enable_gateway_tools: true,
  enable_mem0_management_tools: true,
})
const savingConfig = ref(false)

/* ─── notes state ─── */
const notes = ref<MemNoteItem[]>([])
const totalCount = ref(0)
const loadingNotes = ref(false)
const savingNoteId = ref('')
const deletingNoteId = ref('')
const bulkSaving = ref(false)
const selectedNoteIds = ref<string[]>([])

const noteStatus = ref<MemViewStatus>('eligible')
const noteType = ref<MemNoteType | ''>('')
const noteMemoryKind = ref<MemoryKind | ''>('')
const noteSessionTag = ref('')
const noteQuery = ref('')

/* ─── drafts ─── */
const keywordDrafts = ref<Record<string, string>>({})
const entityDrafts = ref<Record<string, string>>({})
const peopleDrafts = ref<Record<string, string>>({})
const placesDrafts = ref<Record<string, string>>({})
const objectsDrafts = ref<Record<string, string>>({})
const keywordsDrafts = ref<Record<string, string>>({})
const sceneDrafts = ref<Record<string, string>>({})
const triggerScenariosDrafts = ref<Record<string, string>>({})
const constraintsDrafts = ref<Record<string, string>>({})
const openQuestionsDrafts = ref<Record<string, string>>({})

/* ─── drawer ─── */
const drawerVisible = ref(false)
const activeNote = ref<MemNoteItem | null>(null)
const graphEntities = ref<MemoryEntity[]>([])
const graphAvailable = ref(false)
const manualAnchorIds = ref<string[]>([])
const automaticAnchors = ref<SourceEntityMention[]>([])
const loadingAnchors = ref(false)
const creatingAnchor = ref(false)
const newAnchorType = ref<MemoryEntityType>('person')
const newAnchorName = ref('')
const newAnchorAliases = ref('')

/* ─── legacy ─── */
const legacyItems = ref<LegacyAtomicMemoryItem[]>([])
const loadingLegacy = ref(false)
const legacyQuery = ref('')
const legacySessionTag = ref('')
const legacyLimit = ref(30)

/* ─── computed ─── */
const visibleNotes = computed(() => notes.value.filter((item) => {
  if (noteStatus.value === 'eligible') return isAutoSurfaceEligible(item)
  if (noteStatus.value === 'stored') return !isAutoSurfaceEligible(item)
  return true
}))
const eligibleCount = computed(() => notes.value.filter(isAutoSurfaceEligible).length)
const storedCount = computed(() => notes.value.length - eligibleCount.value)
const selectedNotes = computed(() => notes.value.filter((item) => selectedNoteIds.value.includes(item.id)))
const selectedActivationMissing = computed(() => {
  const missing = selectedNotes.value.map((item) => restoreMissing(item)).filter(Boolean)
  return missing[0] || ''
})
const drawerWidth = computed(() => (typeof window === 'undefined' ? 720 : Math.min(720, window.innerWidth)))
const graphAnchorOptions = computed(() => graphEntities.value.map((entity) => ({
  label: `${entity.canonical_name} · ${entityTypeLabel(entity.entity_type)}`,
  value: entity.id,
})))
const graphEntityTypeOptions: Array<{ label: string; value: MemoryEntityType }> = [
  { label: '人物', value: 'person' },
  { label: '地点', value: 'place' },
  { label: '物件', value: 'object' },
  { label: '主题', value: 'topic' },
]

/* ─── lifecycle ─── */
onMounted(async () => {
  await Promise.all([loadConfig(), loadNotes(), loadGraphAnchors()])
})

async function loadGraphAnchors() {
  try {
    const result = await fetchMemoryGraph()
    graphAvailable.value = result.available
    graphEntities.value = result.entities || []
  } catch {
    graphAvailable.value = false
    graphEntities.value = []
  }
}

async function loadNoteAnchors(noteId: string) {
  manualAnchorIds.value = []
  automaticAnchors.value = []
  if (!graphAvailable.value) return
  loadingAnchors.value = true
  try {
    const mentions = await fetchSourceEntityMentions('shenyu_mem_notes', noteId)
    manualAnchorIds.value = mentions
      .filter((mention) => mention.origin === 'manual')
      .map((mention) => mention.entity_id)
    automaticAnchors.value = mentions.filter((mention) => mention.origin !== 'manual')
  } catch {
    message.error('读取关联锚点失败')
  } finally {
    loadingAnchors.value = false
  }
}

async function createAnchorForActiveNote() {
  if (!activeNote.value || !newAnchorName.value.trim() || creatingAnchor.value) return
  creatingAnchor.value = true
  try {
    const entity = await createMemoryEntity({
      entity_type: newAnchorType.value,
      canonical_name: newAnchorName.value.trim(),
      aliases: splitAnchorAliases(newAnchorAliases.value),
    })
    newAnchorName.value = ''
    newAnchorAliases.value = ''
    await loadGraphAnchors()
    manualAnchorIds.value = [...new Set([...manualAnchorIds.value, entity.id])]
    message.success('锚点已建立并选中')
  } catch {
    message.error('建立锚点失败')
  } finally {
    creatingAnchor.value = false
  }
}

/* ─── config methods ─── */
async function loadConfig() {
  try {
    config.value = await fetchMem0Config()
  } catch {
    message.error('加载设置失败')
  }
}

async function saveSettings() {
  savingConfig.value = true
  try {
    const result = await saveMem0Config({
      inject_mem_notes: config.value.inject_mem_notes,
      enable_gateway_tools: config.value.enable_gateway_tools,
      enable_mem0_management_tools: config.value.enable_mem0_management_tools,
      mem_note_limit: config.value.mem_note_limit,
      mem_note_min_score: config.value.mem_note_min_score,
      mem_note_context_keyword_min_score: config.value.mem_note_context_keyword_min_score,
      mem_note_semantic_min_score: config.value.mem_note_semantic_min_score,
      mem_note_semantic_min_vector_score: config.value.mem_note_semantic_min_vector_score,
      mem_note_anchored_semantic_min_score: config.value.mem_note_anchored_semantic_min_score,
      mem_note_anchored_semantic_min_vector_score: config.value.mem_note_anchored_semantic_min_vector_score,
      mem_note_dedupe_turns: config.value.mem_note_dedupe_turns,
      mem_note_soft_cooldown_hours: config.value.mem_note_soft_cooldown_hours,
      mem_note_default_cooldown_hours: config.value.mem_note_default_cooldown_hours,
    })
    config.value = { ...config.value, ...result.config }
    message.success('设置已保存 ✓')
  } catch {
    message.error('保存失败')
  } finally {
    savingConfig.value = false
  }
}

function resetMemTuningDefaults() {
  config.value = { ...config.value, ...MEM_TUNING_DEFAULTS }
  message.info('已恢复默认，记得点保存')
}

function setMemToolsOnly() {
  config.value.inject_mem_notes = false
  config.value.enable_gateway_tools = true
  config.value.enable_mem0_management_tools = true
  message.info('已切到只保留工具，记得点保存')
}

function setMemAllOn() {
  config.value.inject_mem_notes = true
  config.value.enable_gateway_tools = true
  config.value.enable_mem0_management_tools = true
  message.info('已全部开启，记得点保存')
}

/* ─── notes methods ─── */
async function loadNotes() {
  loadingNotes.value = true
  try {
    const result = await fetchMemNotes({
      status: 'all',
      all_rows: true,
      session_tag: noteSessionTag.value.trim() || undefined,
      q: noteQuery.value.trim() || undefined,
      mem_type: noteType.value || undefined,
      memory_kind: noteMemoryKind.value || undefined,
    })
    notes.value = result.items || []
    totalCount.value = result.count ?? notes.value.length
    rebuildDrafts()
    const visibleIds = new Set(notes.value.map((item) => item.id))
    selectedNoteIds.value = selectedNoteIds.value.filter((id) => visibleIds.has(id))
  } catch {
    notes.value = []
    totalCount.value = 0
    message.error('加载便签失败')
  } finally {
    loadingNotes.value = false
  }
}

function rebuildDrafts() {
  keywordDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.trigger_keywords || []).join('，')]))
  entityDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.entities || []).join('，')]))
  peopleDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.people || []).join('，')]))
  placesDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.places || []).join('，')]))
  objectsDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.objects || []).join('，')]))
  keywordsDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.keywords || []).join('，')]))
  sceneDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.scene_tags || []).join('，')]))
  triggerScenariosDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.trigger_scenarios || []).join('，')]))
  constraintsDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.constraints || []).join('，')]))
  openQuestionsDrafts.value = Object.fromEntries(notes.value.map((n) => [n.id, (n.open_questions || []).join('，')]))
}

function splitKeywords(value: string): string[] {
  return value.split(/[,，、\s]+/).map((s) => s.trim()).filter(Boolean)
}

function splitAnchorAliases(value: string): string[] {
  return [...new Set(value.split(/[,，、\n]+/).map((item) => item.trim()).filter(Boolean))]
}

/* ─── card helpers ─── */
function typeColor(item: MemNoteItem): string {
  if (!isAutoSurfaceEligible(item)) return '#f7f7f4'
  return '#fffefb'
}

function typeBorder(item: MemNoteItem): string {
  const t = item.mem_type || ''
  if (t === '她为我做的事') return '#c9b7dc'
  if (t === '我为她做的事') return '#a9c7d1'
  if (t === '关于她的事实') return '#ddb8b2'
  if (t === '关于我的事') return '#aec9b5'
  if (t === '心里那一档') return '#d8c18c'
  if (t === '承诺') return '#d6a8ba'
  return 'var(--sy-hair-2)'
}

function isRecent(item: MemNoteItem): boolean {
  if (!item.created_at) return false
  const created = new Date(item.created_at).getTime()
  const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000
  return created > oneDayAgo
}

function cardPreview(item: MemNoteItem): string {
  const text = item.content || item.summary || ''
  return text.length > 60 ? text.slice(0, 60) + '…' : text
}

function isAutoSurfaceEligible(item: MemNoteItem): boolean {
  if (typeof item.auto_surface_eligible === 'boolean') return item.auto_surface_eligible
  return item.status === 'active' && !(item.memory_kind === 'promise' && item.resolved)
}

function isShenyuWritten(item: MemNoteItem): boolean {
  if (typeof item.written_by_shenyu === 'boolean') return item.written_by_shenyu
  return (item.source_model || '').startsWith('tool:shenyu_write_mem_note')
}

function statusDot(item: MemNoteItem): string {
  return isAutoSurfaceEligible(item) ? '可自动想起' : '已收起'
}

function eligibilityText(item: MemNoteItem): string {
  if (isAutoSurfaceEligible(item)) return '聊到相关内容时，这条便签有资格参与召回；不代表每一轮都会浮现。'
  if (item.auto_surface_reason === 'resolved_promise') return '这条承诺已标记兑现，不会再自动浮现。'
  if (item.auto_surface_reason === 'missing_trigger') return '缺少分类或触发条件，暂时不能参与自动召回。'
  return '这条便签已收起，不会参与自动召回；需要时可以再放回来。'
}

function kindLabel(kind?: string | null): string {
  if (!kind) return ''
  const map: Record<string, string> = {
    event: '事件',
    person_fact: '关于 ta',
    social: '社交',
    trip: '旅行',
    object: '物品',
    preference: '偏好',
    routine: '日常',
    promise: '承诺',
    running_joke: '我们的梗',
    thread: '话题线',
  }
  return map[kind] || kind
}

function entityTypeLabel(kind: string): string {
  return ({ person: '人物', place: '地点', object: '物件', topic: '主题' } as Record<string, string>)[kind] || kind
}

/* ─── drawer ─── */
async function openNote(item: MemNoteItem) {
  activeNote.value = item
  newAnchorType.value = 'person'
  newAnchorName.value = ''
  newAnchorAliases.value = ''
  drawerVisible.value = true
  await loadNoteAnchors(item.id)
}

function closeDrawer() {
  drawerVisible.value = false
  activeNote.value = null
  newAnchorName.value = ''
  newAnchorAliases.value = ''
}

/* ─── note CRUD ─── */
function suggestionKeywordsText(item: MemNoteItem): string {
  return (item.suggested_trigger_keywords || []).join('，')
}

function applySuggestion(item: MemNoteItem) {
  if (!item.mem_type && item.suggested_mem_type) item.mem_type = item.suggested_mem_type
  if (!(item.trigger_text || '').trim() && item.suggested_trigger_text) item.trigger_text = item.suggested_trigger_text
  if (!splitKeywords(keywordDrafts.value[item.id] || '').length && item.suggested_trigger_keywords?.length) {
    keywordDrafts.value[item.id] = suggestionKeywordsText(item)
  }
}

function applySuggestionsToSelection() {
  const target = selectedNotes.value.length ? selectedNotes.value : notes.value
  target.forEach(applySuggestion)
  message.success('已套用建议')
}

function notePatch(item: MemNoteItem, status?: MemNoteStatus): MemNotePatch {
  const patch: MemNotePatch = {
    content: item.content,
    mem_type: item.mem_type || null,
    trigger_text: item.trigger_text || '',
    trigger_keywords: splitKeywords(keywordDrafts.value[item.id] || ''),
    entities: splitKeywords(entityDrafts.value[item.id] || ''),
    status: status || item.status,
    cooldown_hours: item.cooldown_hours,
    review_note: item.review_note || '',
    summary: item.summary || null,
    memory_kind: item.memory_kind || null,
    people: splitKeywords(peopleDrafts.value[item.id] || ''),
    places: splitKeywords(placesDrafts.value[item.id] || ''),
    objects: splitKeywords(objectsDrafts.value[item.id] || ''),
    keywords: splitKeywords(keywordsDrafts.value[item.id] || ''),
    event_time: item.event_time || null,
    importance: item.importance ?? null,
    remind_on: (item.remind_on || '').trim() || null,
  }
  if (item.memory_kind === 'promise') {
    patch.promise_text = item.promise_text || null
    patch.trigger_scenarios = splitKeywords(triggerScenariosDrafts.value[item.id] || '')
    patch.due_hint = item.due_hint || null
    patch.resolved = item.resolved ?? false
    patch.next_action = item.next_action || null
    patch.privacy_level = item.privacy_level || null
  }
  if (item.memory_kind === 'running_joke') {
    patch.joke_text = item.joke_text || null
    patch.scene_tags = splitKeywords(sceneDrafts.value[item.id] || '')
  }
  if (item.memory_kind === 'routine') {
    patch.routine_domain = item.routine_domain || null
    patch.pattern = item.pattern || null
    patch.phase = item.phase || null
    patch.constraints = splitKeywords(constraintsDrafts.value[item.id] || '')
  }
  if (item.memory_kind === 'thread') {
    patch.topic = item.topic || null
    patch.last_position = item.last_position || null
    patch.open_questions = splitKeywords(openQuestionsDrafts.value[item.id] || '')
    patch.next_prompt = item.next_prompt || null
    patch.thread_resolved = item.thread_resolved ?? false
  }
  return patch
}

function activationMissing(item: MemNoteItem): string {
  const hasType = Boolean(item.mem_type)
  const hasTrigger = Boolean((item.trigger_text || '').trim())
    || splitKeywords(keywordDrafts.value[item.id] || '').length > 0
    || splitKeywords(entityDrafts.value[item.id] || '').length > 0
    || splitKeywords(peopleDrafts.value[item.id] || '').length > 0
    || splitKeywords(placesDrafts.value[item.id] || '').length > 0
    || splitKeywords(objectsDrafts.value[item.id] || '').length > 0
    || splitKeywords(keywordsDrafts.value[item.id] || '').length > 0
    || splitKeywords(sceneDrafts.value[item.id] || '').length > 0
    || splitKeywords(triggerScenariosDrafts.value[item.id] || '').length > 0
    // 一个日子本身就是锚点：到了那天它自己会挂上来，不需要关键词。
    || Boolean((item.remind_on || '').trim())
  if (!hasType && !hasTrigger) return '需要补充「分类」和「什么时候想起来」才能放回来'
  if (!hasType) return '需要补充「分类」才能放回来'
  if (!hasTrigger) return '需要补充「什么时候想起来」才能放回来'
  return ''
}

function restoreMissing(item: MemNoteItem): string {
  if (item.memory_kind === 'promise' && item.resolved) return '承诺已标记兑现；取消「已兑现」后才能放回来'
  return activationMissing(item)
}

function canActivate(item: MemNoteItem): boolean {
  return !restoreMissing(item)
}

async function saveNote(item: MemNoteItem, status?: MemNoteStatus) {
  if (savingNoteId.value) return
  const missing = status === 'active'
    ? restoreMissing(item)
    : item.status === 'active'
      ? activationMissing(item)
      : ''
  if (missing) {
    message.warning(missing)
    return
  }
  savingNoteId.value = item.id
  try {
    await updateMemNote(item.id, notePatch(item, status))
    if (graphAvailable.value) {
      await replaceSourceEntities({
        source_table: 'shenyu_mem_notes',
        source_type: 'mem_note',
        source_id: item.id,
        entity_ids: manualAnchorIds.value,
        evidence: 'Mem 管理页手动确认',
      })
      await loadNoteAnchors(item.id)
    }
    message.success('已保存 ✓')
    await loadNotes()
  } catch {
    message.error('保存失败')
  } finally {
    savingNoteId.value = ''
  }
}

async function removeNote(item: MemNoteItem) {
  if (deletingNoteId.value) return
  deletingNoteId.value = item.id
  try {
    await deleteMemNote(item.id)
    message.success('便签已删除')
    closeDrawer()
    await loadNotes()
  } catch {
    message.error('删除失败')
  } finally {
    deletingNoteId.value = ''
  }
}

async function saveSelectedNotes(status?: MemNoteStatus) {
  if (bulkSaving.value || !selectedNotes.value.length) return
  const missing = status === 'active' ? selectedActivationMissing.value : ''
  if (missing) {
    message.warning(missing)
    return
  }
  bulkSaving.value = true
  try {
    const result = await bulkUpdateMemNotes({
      updates: selectedNotes.value.map((item) => ({
        id: item.id,
        patch: notePatch(item, status),
      })),
    })
    if (!result.ok && result.max_count) {
      message.error(`一次最多处理 ${result.max_count} 条`)
      return
    }
    if (result.failed_count) {
      message.warning(`保存了 ${result.updated_count} 条，${result.failed_count} 条失败`)
    } else {
      const label = status === 'active' ? '已放回来' : status === 'archived' ? '已收起来' : '已保存'
      message.success(`${label} ${result.updated_count} 条 ✓`)
    }
    await loadNotes()
  } catch {
    message.error('批量操作失败')
  } finally {
    bulkSaving.value = false
  }
}

async function activateSelectedWithSuggestions() {
  if (bulkSaving.value || !selectedNotes.value.length) return
  bulkSaving.value = true
  try {
    const result = await bulkUpdateMemNotes({
      ids: selectedNoteIds.value,
      patch: { status: 'active' },
      use_suggestions: true,
    })
    if (!result.ok && result.max_count) {
      message.error(`一次最多处理 ${result.max_count} 条`)
      return
    }
    if (result.failed_count) {
      message.warning(`放回了 ${result.updated_count} 条，${result.failed_count} 条失败`)
    } else {
      message.success(`已整理并放回来 ${result.updated_count} 条 ✓`)
    }
    await loadNotes()
  } catch {
    message.error('整理并放回来失败')
  } finally {
    bulkSaving.value = false
  }
}

function toggleSelected(id: string, checked: boolean) {
  if (checked) {
    if (!selectedNoteIds.value.includes(id)) selectedNoteIds.value = [...selectedNoteIds.value, id]
  } else {
    selectedNoteIds.value = selectedNoteIds.value.filter((x) => x !== id)
  }
}

function selectVisibleNotes() {
  selectedNoteIds.value = visibleNotes.value.map((item) => item.id)
}

function clearSelectedNotes() {
  selectedNoteIds.value = []
}

/* ─── legacy ─── */
async function loadLegacy() {
  loadingLegacy.value = true
  try {
    const result = await fetchLegacyAtomicMemories({
      limit: Math.max(1, Math.min(100, Number(legacyLimit.value || 30))),
      session_tag: legacySessionTag.value.trim() || undefined,
      q: legacyQuery.value.trim() || undefined,
    })
    legacyItems.value = result.items || []
  } catch {
    legacyItems.value = []
    message.error('读取旧表失败')
  } finally {
    loadingLegacy.value = false
  }
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}

// 挂过一次就打这个戳，便签本身不动。改了提醒日期，戳会由网关清掉。
function reminderStamp(item: MemNoteItem) {
  return item.reminded_at ? formatTime(item.reminded_at) : ''
}
</script>

<template>
  <div class="memo-page" data-testid="page-mem">
    <!-- ─── header ─── -->
    <div class="memo-header">
      <div>
        <h1 class="memo-title">便签</h1>
        <p class="memo-subtitle">这里显示全部便签；“可自动想起”只是参与召回的资格，不代表这一轮一定浮现。</p>
      </div>
      <div class="memo-header-mark">
        {{ totalCount }}
      </div>
    </div>

    <!-- ─── status tabs + count ─── -->
    <div class="memo-tabs">
      <button
        v-for="tab in statusTabs"
        :key="tab.value"
        class="tab-btn"
        :class="{ active: noteStatus === tab.value }"
        @click="noteStatus = tab.value"
      >
        {{ tab.label }}
      </button>
      <span class="memo-count">可自动想起 {{ eligibleCount }} · 已收起 {{ storedCount }} · 全部 {{ totalCount }}</span>
    </div>

    <!-- ─── filters ─── -->
    <div class="memo-filters">
      <NSelect v-model:value="noteType" :options="memTypeOptions" placeholder="分类" style="width:150px" size="small" @update:value="loadNotes" />
      <NSelect v-model:value="noteMemoryKind" :options="memoryKindOptions" placeholder="种类" style="width:130px" size="small" @update:value="loadNotes" />
      <input data-testid="mem-search" v-model="noteQuery" class="filter-input" placeholder="搜索内容…" @keyup.enter="loadNotes()">
      <NButton size="small" :loading="loadingNotes" @click="loadNotes">刷新</NButton>
      <template v-if="selectedNoteIds.length">
        <span class="sel-badge">已选 {{ selectedNoteIds.length }}</span>
        <NButton size="tiny" @click="clearSelectedNotes">取消选择</NButton>
        <NButton size="tiny" @click="applySuggestionsToSelection">套用建议</NButton>
        <NButton size="tiny" :loading="bulkSaving" @click="saveSelectedNotes()">批量保存</NButton>
        <NButton size="tiny" type="primary" :loading="bulkSaving" :disabled="Boolean(selectedActivationMissing)" @click="saveSelectedNotes('active')">批量放回来</NButton>
        <NButton size="tiny" :loading="bulkSaving" @click="saveSelectedNotes('archived')">批量收起来</NButton>
        <NPopconfirm positive-text="确认" negative-text="取消" @positive-click="activateSelectedWithSuggestions">
          <template #trigger>
            <NButton size="tiny" :loading="bulkSaving" :disabled="!selectedNoteIds.length">整理并放回来</NButton>
          </template>
          会用系统建议补齐缺失的分类和触发条件，然后把所选便签放回自动召回池。
        </NPopconfirm>
      </template>
    </div>

    <!-- ─── card grid ─── -->
    <div v-if="!visibleNotes.length && !loadingNotes" class="memo-empty">
      <div class="empty-note">
        <span>暂时没有便签</span>
        <small>换个状态或关键词再看一次。</small>
      </div>
    </div>
    <div v-else class="memo-grid">
      <div
        v-for="item in visibleNotes"
        :key="item.id"
        class="memo-card"
        :class="{ 'is-recent': isRecent(item) }"
        :style="{ background: typeColor(item), borderColor: typeBorder(item) }"
        @click="openNote(item)"
      >
        <div class="card-top">
          <NCheckbox
            :checked="selectedNoteIds.includes(item.id)"
            @update:checked="(c) => toggleSelected(item.id, c)"
            @click.stop
          />
          <span class="card-status" :class="isAutoSurfaceEligible(item) ? 'st-active' : 'st-stored'">{{ statusDot(item) }}</span>
          <span v-if="isShenyuWritten(item)" class="card-author">沈予写的</span>
          <span v-if="item.memory_kind" class="card-kind">{{ kindLabel(item.memory_kind) }}</span>
        </div>
        <div class="card-body">{{ cardPreview(item) }}</div>
        <div class="card-foot">
          <span class="card-type">{{ item.mem_type || '未分类' }}</span>
          <span v-if="item.trigger_count" class="card-count">×{{ item.trigger_count }}</span>
        </div>
      </div>
    </div>

    <!-- ─── bulk tools for select-all ─── -->
    <div v-if="visibleNotes.length" class="memo-bulk-bar">
      <NButton size="tiny" quaternary @click="selectVisibleNotes">全选当前列表</NButton>
    </div>

    <!-- ─── drawer for editing ─── -->
    <NDrawer v-model:show="drawerVisible" :width="drawerWidth" placement="right" @after-leave="activeNote = null">
      <NDrawerContent v-if="activeNote" closable>
        <template #header>
          <div class="drawer-title">
            <span>便签详情</span>
            <small>{{ activeNote.mem_type || '未分类' }} · {{ statusDot(activeNote) }}<template v-if="isShenyuWritten(activeNote)"> · 沈予写的</template></small>
          </div>
        </template>
        <div class="drawer-form">
          <NForm label-placement="top">
            <NFormItem label="内容">
              <NInput v-model:value="activeNote.content" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" placeholder="这张便签写了什么…" />
            </NFormItem>
            <NFormItem label="一句话摘要">
              <NInput v-model:value="activeNote.summary" placeholder="可选，简短概括" />
            </NFormItem>

            <div class="drawer-row">
              <NFormItem label="分类">
                <NSelect v-model:value="activeNote.mem_type" :options="memTypeOptions.slice(1)" clearable placeholder="选一个…" />
              </NFormItem>
              <NFormItem label="种类">
                <NSelect v-model:value="activeNote.memory_kind" :options="memoryKindOptions.slice(1)" clearable placeholder="可选" />
              </NFormItem>
            </div>

            <div class="eligibility-box" :class="{ eligible: isAutoSurfaceEligible(activeNote) }">
              <b>{{ statusDot(activeNote) }}</b>
              <span>{{ eligibilityText(activeNote) }}</span>
            </div>

            <div v-if="graphAvailable" class="anchor-box">
              <NFormItem label="关联锚点">
                <NSelect
                  v-model:value="manualAnchorIds"
                  multiple
                  filterable
                  clearable
                  :loading="loadingAnchors"
                  :options="graphAnchorOptions"
                  placeholder="选择已确认的人、地方、物件或主题"
                />
              </NFormItem>
              <NFormItem label="新建锚点">
                <div class="new-anchor-inline">
                  <NSelect v-model:value="newAnchorType" :options="graphEntityTypeOptions" aria-label="新建锚点类型" />
                  <NInput v-model:value="newAnchorName" placeholder="名称" @keyup.enter="createAnchorForActiveNote" />
                  <NInput v-model:value="newAnchorAliases" placeholder="别名，逗号分开" @keyup.enter="createAnchorForActiveNote" />
                  <NButton :loading="creatingAnchor" :disabled="!newAnchorName.trim()" @click="createAnchorForActiveNote">新建并选中</NButton>
                </div>
              </NFormItem>
              <div v-if="automaticAnchors.length" class="automatic-anchors">
                <span>精确别名自动连上</span>
                <NTag v-for="mention in automaticAnchors" :key="mention.id" size="small" :bordered="false">
                  {{ mention.entity?.canonical_name || mention.matched_alias }}
                </NTag>
              </div>
            </div>

            <!-- suggestion banner -->
            <div v-if="activeNote.suggested_mem_type && activeNote.suggested_mem_type !== activeNote.mem_type" class="suggestion-banner">
              <span>系统建议分为「{{ activeNote.suggested_mem_type }}」</span>
              <span v-if="activeNote.suggestion_reason" class="sug-reason">── {{ activeNote.suggestion_reason }}</span>
              <NButton size="tiny" type="primary" ghost @click="applySuggestion(activeNote!)">采用建议</NButton>
            </div>

            <NFormItem label="什么时候想起来（触发文本）">
              <NInput v-model:value="activeNote.trigger_text" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="描述在什么场景下这条便签应该被想起来" />
            </NFormItem>

            <div class="drawer-row two">
              <NFormItem label="触发词">
                <NInput v-model:value="keywordDrafts[activeNote.id]" placeholder="逗号分开" />
              </NFormItem>
              <NFormItem label="精确匹配（人名/地名/物名）">
                <NInput v-model:value="entityDrafts[activeNote.id]" placeholder="逗号分开" />
              </NFormItem>
            </div>
            <div class="drawer-row two">
              <NFormItem label="涉及的人">
                <NInput v-model:value="peopleDrafts[activeNote.id]" placeholder="逗号分开" />
              </NFormItem>
              <NFormItem label="涉及的地方">
                <NInput v-model:value="placesDrafts[activeNote.id]" placeholder="逗号分开" />
              </NFormItem>
            </div>
            <div class="drawer-row two">
              <NFormItem label="涉及的物品">
                <NInput v-model:value="objectsDrafts[activeNote.id]" placeholder="逗号分开" />
              </NFormItem>
              <NFormItem label="关键词">
                <NInput v-model:value="keywordsDrafts[activeNote.id]" placeholder="逗号分开" />
              </NFormItem>
            </div>

            <div class="drawer-row">
              <NFormItem label="冷却时间（小时）">
                <NInputNumber v-model:value="activeNote.cooldown_hours" :min="0" :max="8760" style="width:100%" />
              </NFormItem>
              <NFormItem label="重要度（0-5）">
                <NInputNumber v-model:value="activeNote.importance" :min="0" :max="5" style="width:100%" />
              </NFormItem>
              <NFormItem label="时间">
                <NInput v-model:value="activeNote.event_time" placeholder="2026-06-15" />
              </NFormItem>
            </div>

            <div class="drawer-row two">
              <NFormItem label="提醒日期">
                <NInput v-model:value="activeNote.remind_on" placeholder="2026-09-01（到那天自己挂上动态岛一次）" />
              </NFormItem>
              <NFormItem label="已提醒">
                <NInput :value="reminderStamp(activeNote)" readonly placeholder="还没挂过" />
              </NFormItem>
            </div>

            <!-- promise -->
            <template v-if="activeNote.memory_kind === 'promise'">
              <div class="kind-section">承诺相关</div>
              <NFormItem label="承诺内容">
                <NInput v-model:value="activeNote.promise_text" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" />
              </NFormItem>
              <div class="drawer-row two">
                <NFormItem label="下一步">
                  <NInput v-model:value="activeNote.next_action" />
                </NFormItem>
                <NFormItem label="截止提示">
                  <NInput v-model:value="activeNote.due_hint" placeholder="下周三之前" />
                </NFormItem>
              </div>
              <div class="drawer-row two">
                <NFormItem label="触发场景">
                  <NInput v-model:value="triggerScenariosDrafts[activeNote.id]" placeholder="逗号分开" />
                </NFormItem>
                <NFormItem label="已兑现">
                  <NSwitch :value="activeNote.resolved ?? false" @update:value="v => activeNote!.resolved = v" />
                </NFormItem>
              </div>
            </template>

            <!-- running_joke -->
            <template v-if="activeNote.memory_kind === 'running_joke'">
              <div class="kind-section">我们的梗</div>
              <NFormItem label="梗的内容">
                <NInput v-model:value="activeNote.joke_text" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" />
              </NFormItem>
              <NFormItem label="适用场景">
                <NInput v-model:value="sceneDrafts[activeNote.id]" placeholder="逗号分开" />
              </NFormItem>
            </template>

            <!-- routine -->
            <template v-if="activeNote.memory_kind === 'routine'">
              <div class="kind-section">日常习惯</div>
              <div class="drawer-row two">
                <NFormItem label="领域">
                  <NInput v-model:value="activeNote.routine_domain" placeholder="睡眠、饮食、运动…" />
                </NFormItem>
                <NFormItem label="规律">
                  <NInput v-model:value="activeNote.pattern" />
                </NFormItem>
              </div>
              <div class="drawer-row two">
                <NFormItem label="阶段">
                  <NInput v-model:value="activeNote.phase" />
                </NFormItem>
                <NFormItem label="限制条件">
                  <NInput v-model:value="constraintsDrafts[activeNote.id]" placeholder="逗号分开" />
                </NFormItem>
              </div>
            </template>

            <!-- thread -->
            <template v-if="activeNote.memory_kind === 'thread'">
              <div class="kind-section">话题线</div>
              <div class="drawer-row two">
                <NFormItem label="话题">
                  <NInput v-model:value="activeNote.topic" />
                </NFormItem>
                <NFormItem label="上次说到">
                  <NInput v-model:value="activeNote.last_position" />
                </NFormItem>
              </div>
              <div class="drawer-row two">
                <NFormItem label="未解决的问题">
                  <NInput v-model:value="openQuestionsDrafts[activeNote.id]" placeholder="逗号分开" />
                </NFormItem>
                <NFormItem label="下次可以聊">
                  <NInput v-model:value="activeNote.next_prompt" />
                </NFormItem>
              </div>
              <NFormItem label="已结束">
                <NSwitch :value="activeNote.thread_resolved ?? false" @update:value="v => activeNote!.thread_resolved = v" />
              </NFormItem>
            </template>

            <NFormItem label="整理备注（只有你能看到）">
              <NInput v-model:value="activeNote.review_note" placeholder="给自己的笔记" />
            </NFormItem>
          </NForm>

          <!-- source excerpt -->
          <div v-if="activeNote.source_excerpt" class="source-box">
            <b>来源</b><br>{{ activeNote.source_excerpt }}
          </div>

          <!-- meta info -->
          <div class="drawer-meta">
            <span>浮现过 {{ activeNote.trigger_count || 0 }} 次</span>
            <span v-if="activeNote.last_triggered_at">· 上次 {{ formatTime(activeNote.last_triggered_at) }}</span>
            <span v-if="activeNote.created_at">· 创建于 {{ formatTime(activeNote.created_at) }}</span>
          </div>

          <!-- activation hint -->
          <div v-if="restoreMissing(activeNote)" class="activation-hint">
            {{ restoreMissing(activeNote) }}
          </div>
        </div>

        <template #footer>
          <div class="drawer-actions">
            <NButton type="primary" :loading="savingNoteId === activeNote.id" @click="saveNote(activeNote!)">保存</NButton>
            <NButton v-if="!isAutoSurfaceEligible(activeNote)" :disabled="!canActivate(activeNote)" @click="saveNote(activeNote!, 'active')">放回来</NButton>
            <NButton v-else @click="saveNote(activeNote!, 'archived')">收起来</NButton>
            <NPopconfirm positive-text="确认删除" negative-text="取消" @positive-click="removeNote(activeNote!)">
              <template #trigger>
                <NButton type="error" ghost :loading="deletingNoteId === activeNote.id">删除</NButton>
              </template>
              删掉这条便签？
            </NPopconfirm>
          </div>
        </template>
      </NDrawerContent>
    </NDrawer>

    <!-- ─── collapsible settings ─── -->
    <NCollapse class="bottom-sections" :default-expanded-names="[]">
      <NCollapseItem title="记忆设置" name="settings">
        <NForm label-placement="top">
          <!-- 第一组：核心开关 -->
          <div class="settings-group">
            <div class="settings-group-title">核心开关</div>
            <div class="settings-group-desc">日常可能会调的，开和关就好</div>
            <div class="cfg-row">
              <NFormItem label="便签参与对话">
                <NSwitch v-model:value="config.inject_mem_notes" />
                <span class="cfg-hint">开了之后，相关便签才有机会参加自动召回</span>
              </NFormItem>
              <NFormItem label="网关工具">
                <NSwitch v-model:value="config.enable_gateway_tools" />
                <span class="cfg-hint">他能不能主动使用工具</span>
              </NFormItem>
              <NFormItem label="便签管理工具">
                <NSwitch v-model:value="config.enable_mem0_management_tools" />
                <span class="cfg-hint">他能不能自己新建、修改便签</span>
              </NFormItem>
            </div>
          </div>

          <!-- 第二组：回忆行为 -->
          <div class="settings-group">
            <div class="settings-group-title">回忆行为</div>
            <div class="settings-group-desc">控制便签怎么被想起来，调好一次就不用动了</div>
            <div class="cfg-row">
              <NFormItem label="每次最多回忆几条">
                <NInputNumber v-model:value="config.mem_note_limit" :min="1" :max="5" style="width:100%" />
                <span class="cfg-hint">推荐 3，太多会分散注意力</span>
              </NFormItem>
              <NFormItem label="相同便签间隔几轮再出现">
                <NInputNumber v-model:value="config.mem_note_dedupe_turns" :min="0" :max="50" style="width:100%" />
                <span class="cfg-hint">避免同一条反复出现，推荐 6</span>
              </NFormItem>
            </div>
            <div class="cfg-row">
              <NFormItem label="自动回忆冷却（小时）">
                <NInputNumber v-model:value="config.mem_note_soft_cooldown_hours" :min="0" :max="168" style="width:100%" />
                <span class="cfg-hint">刚想起来的便签多久后才能再自动出现</span>
              </NFormItem>
              <NFormItem label="新便签默认冷却（小时）">
                <NInputNumber v-model:value="config.mem_note_default_cooldown_hours" :min="0" :max="168" style="width:100%" />
                <span class="cfg-hint">如果便签自己没设冷却时间，就用这个</span>
              </NFormItem>
            </div>
          </div>

          <!-- 第三组：匹配精度 -->
          <div class="settings-group">
            <div class="settings-group-title">匹配精度</div>
            <div class="settings-group-desc">控制「多像才算匹配上了」，一般不用动</div>
            <div class="cfg-row">
              <NFormItem label="关键词搜索灵敏度">
                <NInputNumber v-model:value="config.mem_note_min_score" :min="0" :max="1" :step="0.01" style="width:100%" />
                <span class="cfg-hint">越低越容易匹配上，推荐 0.45</span>
              </NFormItem>
              <NFormItem label="自动回忆灵敏度">
                <NInputNumber v-model:value="config.mem_note_context_keyword_min_score" :min="0.05" :max="0.9" :step="0.01" style="width:100%" />
                <span class="cfg-hint">聊天时自动联想的门槛，推荐 0.25</span>
              </NFormItem>
            </div>
            <div class="cfg-row">
              <NFormItem label="语义匹配阈值">
                <NInputNumber v-model:value="config.mem_note_semantic_min_score" :min="0" :max="1" :step="0.01" style="width:100%" />
              </NFormItem>
              <NFormItem label="向量匹配阈值">
                <NInputNumber v-model:value="config.mem_note_semantic_min_vector_score" :min="0" :max="1" :step="0.01" style="width:100%" />
              </NFormItem>
            </div>
            <div class="cfg-row">
              <NFormItem label="锚定语义阈值">
                <NInputNumber v-model:value="config.mem_note_anchored_semantic_min_score" :min="0" :max="1" :step="0.01" style="width:100%" />
              </NFormItem>
              <NFormItem label="锚定向量阈值">
                <NInputNumber v-model:value="config.mem_note_anchored_semantic_min_vector_score" :min="0" :max="1" :step="0.01" style="width:100%" />
              </NFormItem>
            </div>
          </div>

          <NSpace>
            <NButton type="primary" :loading="savingConfig" @click="saveSettings">保存设置</NButton>
            <NButton :disabled="savingConfig" @click="setMemToolsOnly">静音模式</NButton>
            <NButton :disabled="savingConfig" @click="setMemAllOn">全部开启</NButton>
            <NPopconfirm positive-text="恢复" negative-text="取消" @positive-click="resetMemTuningDefaults">
              <template #trigger>
                <NButton :disabled="savingConfig">恢复默认</NButton>
              </template>
              恢复默认值后需要点保存才会生效
            </NPopconfirm>
          </NSpace>
        </NForm>
      </NCollapseItem>

      <NCollapseItem title="旧版便签（只读）" name="legacy">
        <div class="legacy-toolbar">
          <input v-model="legacyQuery" class="filter-input" placeholder="搜索旧表">
          <input v-model="legacySessionTag" class="filter-input short" placeholder="session">
          <input v-model="legacyLimit" class="filter-input tiny" type="number" min="1" max="100">
          <NButton size="small" :loading="loadingLegacy" @click="loadLegacy">读取</NButton>
        </div>
        <div v-if="!legacyItems.length" class="memo-empty">点击「读取」加载旧版便签</div>
        <div v-for="item in legacyItems" :key="item.id" class="legacy-card">
          <div class="legacy-meta">
            <NTag size="small">{{ item.status }}</NTag>
            <NTag size="small">{{ item.subject || item.owner || '-' }}</NTag>
            <NTag size="small">{{ item.memory_type }}</NTag>
          </div>
          <div class="legacy-body">{{ item.content_surface || item.quote || item.source_excerpt || '-' }}</div>
        </div>
      </NCollapseItem>
    </NCollapse>
  </div>
</template>

<style scoped>
.memo-page {
  margin: 0 auto;
  max-width: 1180px;
  min-height: calc(100vh - 58px);
  padding: 28px 18px 64px;
  color: #272522;
  background: #f7f6f2;
  box-shadow: 0 0 0 100vmax #f7f6f2;
  clip-path: inset(0 -100vmax -80px);
}

.memo-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--sy-hair-2);
}

.memo-title {
  font-size: 28px;
  font-weight: 650;
  line-height: 1.15;
  color: #25221e;
  margin: 0;
}

.memo-subtitle {
  margin: 8px 0 0;
  color: #827a70;
  font-size: 13px;
  line-height: 1.6;
}

.memo-header-mark {
  min-width: 52px;
  height: 52px;
  border: 1px solid #ded5c7;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #71685d;
  background: var(--sy-paper, #fff);
  font-size: 15px;
  font-weight: 600;
}

.memo-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.tab-btn {
  min-height: 32px;
  padding: 5px 13px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: #696158;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
}

.tab-btn:hover {
  background: #ece9e1;
}

.tab-btn.active {
  background: #2d2b28;
  border-color: #2d2b28;
  color: var(--sy-paper, #fff);
}

.memo-count {
  margin-left: auto;
  font-size: 12px;
  color: #9c958c;
}

.memo-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding: 10px;
  border: 1px solid var(--sy-hair-2);
  border-radius: 8px;
  background: var(--sy-paper, #fff);
}

.filter-input {
  height: 32px;
  padding: 5px 11px;
  border: 1px solid #ded8cf;
  border-radius: 6px;
  font-size: 13px;
  color: #38332d;
  background: var(--sy-paper, #fff);
  min-width: 140px;
  outline: none;
}

.filter-input:focus {
  border-color: #9b8f7e;
  box-shadow: 0 0 0 2px rgba(155, 143, 126, 0.12);
}

.filter-input.short { min-width: 100px; }
.filter-input.tiny { min-width: 60px; width: 70px; }

.sel-badge {
  padding: 3px 8px;
  border-radius: 999px;
  background: #ece9e1;
  color: #5d554b;
  font-size: 12px;
}

.memo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}

.memo-card {
  position: relative;
  padding: 14px 14px 12px;
  border: 1px solid var(--sy-hair-2);
  border-left-width: 3px;
  border-radius: 7px;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.18s, border-color 0.18s;
  min-height: 128px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 2px rgba(42, 36, 28, 0.05);
}

.memo-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(55, 46, 35, 0.1);
}

.memo-card.is-recent {
  box-shadow: 0 0 0 2px rgba(214, 193, 140, 0.18), 0 1px 2px rgba(42, 36, 28, 0.06);
}

.memo-card::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: 7px;
  background: linear-gradient(180deg, rgba(255,255,255,0.56), rgba(255,255,255,0));
}

.card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  margin-bottom: 10px;
  position: relative;
  z-index: 1;
}

.card-status {
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.45;
  color: #696158;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(116, 106, 92, 0.14);
}

.card-status.st-active {
  color: #39634c;
  background: #edf6ef;
}

.card-status.st-stored {
  color: #6f6860;
  background: #eeeeeb;
}

.card-status.st-captured {
  color: #775f25;
  background: #fff6dd;
}

.card-status.st-paused {
  color: #685b50;
  background: #f3eee7;
}

.card-status.st-archived {
  color: #7b7b77;
  background: #eeeeeb;
}

.card-kind {
  font-size: 11px;
  color: #837a70;
  background: rgba(255, 255, 255, 0.58);
  padding: 2px 7px;
  border-radius: 999px;
}

.card-author {
  font-size: 11px;
  color: #75536f;
  background: #f4eaf2;
  border: 1px solid rgba(117, 83, 111, 0.14);
  padding: 2px 7px;
  border-radius: 999px;
}

.eligibility-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 2px 0 14px;
  padding: 10px 12px;
  border: 1px solid var(--sy-hair-2);
  border-radius: 7px;
  color: #6f6860;
  background: #f4f2ed;
  font-size: 12px;
  line-height: 1.55;
}

.eligibility-box.eligible {
  color: #39634c;
  border-color: #cfe0d3;
  background: #edf6ef;
}

.card-body {
  flex: 1;
  font-size: 14px;
  line-height: 1.65;
  color: #312d28;
  word-break: break-word;
  white-space: pre-wrap;
  position: relative;
  z-index: 1;
}

.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  font-size: 11px;
  color: #8c847a;
  position: relative;
  z-index: 1;
}

.card-type {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}

.card-count {
  color: #81715d;
  font-weight: 500;
}

.memo-bulk-bar {
  margin-top: 14px;
  text-align: center;
}

.memo-empty {
  padding: 44px 0 34px;
  display: flex;
  justify-content: center;
}

.empty-note {
  width: min(280px, 100%);
  min-height: 112px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 6px;
  text-align: center;
  color: #71695f;
  background: #fffefb;
  border: 1px solid var(--sy-hair-2);
  border-left: 3px solid #d8c18c;
  border-radius: 7px;
  box-shadow: 0 1px 2px rgba(42, 36, 28, 0.05);
}

.empty-note span {
  font-size: 14px;
  color: #38332d;
}

.empty-note small {
  font-size: 12px;
  color: #8c847a;
}

.drawer-title {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.drawer-title span {
  font-size: 18px;
  font-weight: 650;
  color: #26231f;
}

.drawer-title small {
  color: #8a8176;
  font-size: 12px;
  font-weight: 400;
}

.drawer-form {
  max-width: 660px;
  padding-bottom: 20px;
}

.anchor-box {
  padding: 12px;
  border: 1px solid #eadbd6;
  background: var(--sy-paper, #fff);
}

.new-anchor-inline {
  display: grid;
  grid-template-columns: 112px minmax(100px, 1fr) minmax(140px, 1.2fr) auto;
  gap: 8px;
  width: 100%;
}

.automatic-anchors {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  color: #927f7a;
  font-size: 12px;
}

.drawer-row {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, 1fr);
  margin-bottom: 2px;
}

.drawer-row.two {
  grid-template-columns: 1fr 1fr;
}

.suggestion-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 9px 12px;
  margin-bottom: 14px;
  background: #efede5;
  border: 1px solid #dcd6ca;
  border-radius: 7px;
  font-size: 12px;
  color: #574b3b;
}

.sug-reason {
  color: #897f73;
}

.kind-section {
  margin: 18px 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: #514a42;
  padding-bottom: 6px;
  border-bottom: 1px solid #ebe5dc;
}

.source-box {
  margin-top: 12px;
  padding: 12px;
  background: var(--sy-paper, #fff);
  border: 1px solid var(--sy-hair-2);
  border-radius: 7px;
  font-size: 12px;
  color: #70675c;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.drawer-meta {
  margin-top: 12px;
  font-size: 12px;
  color: #928a80;
}

.activation-hint {
  margin-top: 8px;
  padding: 7px 10px;
  background: #fff7ed;
  border: 1px solid #e9d0ad;
  border-radius: 6px;
  color: #8d4c25;
  font-size: 12px;
}

.drawer-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.bottom-sections {
  margin-top: 40px;
}

.settings-group {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--sy-paper, #fff);
  border: 1px solid var(--sy-hair-2);
  border-radius: 8px;
}

.settings-group-title {
  font-size: 14px;
  font-weight: 600;
  color: #332f2a;
  margin-bottom: 2px;
}

.settings-group-desc {
  font-size: 12px;
  color: #928a80;
  margin-bottom: 12px;
}

.cfg-hint {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #928a80;
  line-height: 1.4;
}

.cfg-row {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, 1fr);
  margin-bottom: 4px;
}

.legacy-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.legacy-card {
  padding: 10px;
  margin-top: 8px;
  border: 1px solid var(--sy-hair-2);
  border-radius: 6px;
  background: var(--sy-paper, #fff);
}

.legacy-meta {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}

.legacy-body {
  font-size: 13px;
  color: #4d463e;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 920px) {
  .memo-page {
    padding: 22px 14px 56px;
  }

  .memo-grid {
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  }

  .memo-count {
    width: 100%;
    margin-left: 0;
  }
}

@media (max-width: 768px) {
  .memo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .drawer-row,
  .drawer-row.two,
  .cfg-row,
  .settings-group .cfg-row,
  .new-anchor-inline {
    grid-template-columns: 1fr;
  }

  .memo-header {
    align-items: flex-start;
  }

  .memo-header-mark {
    min-width: 44px;
    height: 44px;
  }
}

@media (max-width: 480px) {
  .memo-header {
    flex-direction: row;
    align-items: flex-start;
    gap: 10px;
  }

  .memo-grid {
    grid-template-columns: 1fr;
  }

  .memo-filters {
    padding: 9px;
  }

  .filter-input {
    width: 100%;
  }

  .memo-title {
    font-size: 25px;
  }

  .memo-subtitle {
    font-size: 12px;
  }
}
</style>
