<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  ArrowLeftRight,
  Check,
  ChevronLeft,
  Clock3,
  ChevronDown,
  ChevronRight,
  CircleStop,
  Clipboard,
  ExternalLink,
  ImagePlus,
  Menu,
  MessageCirclePlus,
  Pencil,
  Plus,
  RotateCcw,
  Send,
  SlidersHorizontal,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from 'lucide-vue-next'
import { CHATNEST_STATUS_SPRITES } from './chatnestSprite'
import ChatNestSprite from './ChatNestSprite.vue'
import { renderMarkdown } from './markdown'
import { toolState, toolWarmCopy, type ToolEvent } from './toolLanguage'
import type {
  Attachment,
  GatewaySession,
  ModelOption,
  ProcessGroup,
  ProcessSheet,
  Role,
  ThinkingSegment,
  UiMessage,
  UpstreamPreset,
  WorkspaceId,
} from './types'
import { createId } from './utils'
import {
  deleteSession,
  fetchModels,
  fetchRuntimeConfig,
  fetchSessionDetail,
  fetchSessions,
  postChatCompletion,
  postChatStream,
  postUpstreamConfig,
  renameSession,
  wireMessages,
  type RequestContext,
} from './api/client'
import { readUpstreamPresets } from './api/presets'
import {
  initBatteryWatch,
  initWeatherWatch,
  splitStatusSuffix,
  stampStatusSuffix,
  stripStatusSuffix,
} from './meta/statusSuffix'
import {
  coldStartHistoryRows,
  dedupeUiMessagesForRecovery,
  hasExactDuplicateRows,
  sessionHistoryRows,
  sessionMessageContent,
  sessionTagFromLocation,
} from './session/history'
import {
  FALLBACK_SESSION_MESSAGE_LIMIT,
  STORAGE_SESSION,
  loadStoredMessages,
  persistStoredMessages,
} from './session/persistence'
import { hydrateToolEvents } from './session/toolHydration'
import {
  applyVariant,
  canSwitchMessageVariant,
  emptyVariant,
  ensureVariants,
  selectedVariantIndex,
  syncCurrentVariant,
  variantCount,
} from './session/variants'
import { parseSseFrame, pumpSseStream, toolEventKey } from './stream/sse'
import { applyChatCompletion } from './stream/completion'
import {
  assistantParts,
  formatToolInput,
  formatToolOutput,
  groupHasThinking,
  processGroups,
  processSummary,
  processTimeline,
  thinkingPreview,
  toolLabel,
  toolResultPreview,
  traceRows,
} from './stream/timeline'

type SpriteMode = keyof typeof CHATNEST_STATUS_SPRITES

const STORAGE_TOKEN = 'shenyu_pwa_gateway_token'
const STORAGE_GATEWAY = 'shenyu_pwa_gateway_url'
const STORAGE_MODEL = 'shenyu_pwa_model'
const STORAGE_EFFORT = 'shenyu_pwa_effort'
const STORAGE_EXTENDED = 'shenyu_pwa_extended'
const STORAGE_PRESET = 'shenyu_pwa_preset'
const STORAGE_STREAM = 'shenyu_pwa_stream'

const requestedSessionTag = sessionTagFromLocation()
const storedSessionTag = localStorage.getItem(STORAGE_SESSION) || ''

const messages = ref<UiMessage[]>(loadStoredMessages())
const draft = ref('')
const pendingAttachments = ref<Attachment[]>([])
const models = ref<ModelOption[]>([])
const recentSessions = ref<GatewaySession[]>([])
const selectedModel = ref(localStorage.getItem(STORAGE_MODEL) || 'default')
const effort = ref(localStorage.getItem(STORAGE_EFFORT) || 'medium')
const extendedThinking = ref(localStorage.getItem(STORAGE_EXTENDED) !== 'false')
const selectedPresetName = ref(localStorage.getItem(STORAGE_PRESET) || '')
const streamResponses = ref(localStorage.getItem(STORAGE_STREAM) !== 'false')
const authToken = ref(localStorage.getItem(STORAGE_TOKEN) || localStorage.getItem('shenyu_token') || '')
const gatewayUrl = ref(localStorage.getItem(STORAGE_GATEWAY) || '')
const maxClientMessages = ref<number | null>(null)
const sessionTag = ref(requestedSessionTag || storedSessionTag || createId('pwa'))
const activeWorkspace = ref<WorkspaceId>('chats')
const menuOpen = ref(false)
const settingsOpen = ref(false)
const handoffOpen = ref(false)
const handoffLoading = ref(false)
const modelOpen = ref(false)
const modelSheetPage = ref<'main' | 'effort' | 'more' | 'preset'>('main')
const processSheet = ref<ProcessSheet | null>(null)
const editId = ref<string | null>(null)
const busy = ref(false)
const status = ref('')
const errorNotice = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const fileRef = ref<HTMLInputElement | null>(null)
const streamRef = ref<HTMLElement | null>(null)
const presets = ref<UpstreamPreset[]>([])
const switchingPreset = ref('')
const runtimeUpstream = ref({ url: '', protocol: '', extraBody: '' })
const brandMarkUrl = `${import.meta.env.BASE_URL}brand-mark.svg`
const brandWordmarkUrl = `${import.meta.env.BASE_URL}brand-wordmark.svg`
let activeController: AbortController | null = null
let activeAssistantId: string | null = null

const currentModel = computed(() => models.value.find((model) => model.id === selectedModel.value))
const currentModelLabel = computed(() => modelLabel(currentModel.value))
const hasContent = computed(() => Boolean(draft.value.trim()) || pendingAttachments.value.length > 0)
const isEmpty = computed(() => messages.value.length === 0)
const primaryModels = computed(() => models.value.filter((model) => model.primary !== false))
const secondaryModels = computed(() => models.value.filter((model) => model.primary === false))
const currentPreset = computed(() => {
  const stored = presets.value.find((preset) => preset.name === selectedPresetName.value)
  if (stored && (!runtimeUpstream.value.url || stored.url === runtimeUpstream.value.url)) return stored
  return presets.value.find((preset) => preset.url === runtimeUpstream.value.url && preset.protocol === runtimeUpstream.value.protocol)
})
const effectiveEffort = computed(() => extendedThinking.value ? 'max' : effort.value)
const handoffSessions = computed(() => recentSessions.value.filter((session) => {
  const messageCount = Number(session.user_message_count || session.message_count || 0)
  return messageCount > 0
}))
const processSheetMessage = computed(() => {
  const messageId = processSheet.value?.messageId
  return messageId ? messages.value.find((message) => message.id === messageId) : undefined
})
const processSheetEvent = computed(() => {
  const current = processSheet.value
  const message = processSheetMessage.value
  if (!current || current.view !== 'tool' || !message || !current.toolKey) return undefined
  return traceRows(message).find((event) => toolEventKey(event) === current.toolKey)
})
const processSheetGroup = computed(() => {
  const message = processSheetMessage.value
  const offset = processSheet.value?.textOffset
  if (!message || offset === undefined) return undefined
  return processGroups(message).find((group) => group.textOffset === offset)
})
const processSheetThinking = computed(() => {
  const current = processSheet.value
  const group = processSheetGroup.value
  if (!current || current.view !== 'thinking' || !group) return undefined
  return group.thinking.find((item) => item.id === current.thinkingKey)
})
const processSheetTitle = computed(() => {
  if (processSheet.value?.view === 'thinking') return '思考片段'
  if (processSheet.value?.view === 'tool') return toolWarmCopy(processSheetEvent.value || { phase: '', tool_call_id: '', name: '' })
  return '沈予刚才做了什么'
})

const workspaceContent: Record<WorkspaceId, { eyebrow: string; title: string; description: string; action: string; detail: string }> = {
  chats: {
    eyebrow: 'Chats',
    title: '',
    description: '',
    action: '',
    detail: '',
  },
  projects: {
    eyebrow: 'Projects',
    title: 'Keep your work together.',
    description: 'Projects give a conversation a home, with shared instructions and reference material close at hand.',
    action: 'Create a project',
    detail: 'Project storage is ready for the next gateway-backed workspace layer.',
  },
  artifacts: {
    eyebrow: 'Artifacts',
    title: 'A place for things you make.',
    description: 'Documents, code, and other working pieces will live here when the artifact store is connected.',
    action: 'Browse artifacts',
    detail: 'No artifacts are connected to this gateway yet.',
  },
  memory: {
    eyebrow: 'Memory',
    title: 'The things worth carrying forward.',
    description: 'Review the memories this space keeps available to Claude, without interrupting the conversation.',
    action: 'Open memory',
    detail: 'Memory is currently managed by the gateway tools in chat.',
  },
  diary: {
    eyebrow: 'Diary',
    title: 'A quieter place to look back.',
    description: 'A private timeline for notes, reflections, and the small details that should not disappear between chats.',
    action: 'Open diary',
    detail: 'Diary entries will appear here when its dedicated store is enabled.',
  },
}

const effortOptions = [
  { id: 'low', label: 'Low', note: 'Quick replies to simple questions' },
  { id: 'medium', label: 'Medium', note: 'Balanced for everyday work' },
  { id: 'high', label: 'High', note: 'Complex, detailed work' },
  { id: 'max', label: 'Max', note: 'The hardest problems. Takes longest.' },
]

const quickPrompts = [
  '帮我理一理今天最重要的三件事',
  '翻翻最近的便签，看看有没有值得继续的念头',
  '把这段文字改得更自然一点',
]

function modelLabel(model?: ModelOption): string {
  if (!model) return selectedModel.value === 'default' ? 'Sonnet 4.6' : selectedModel.value
  if (model.label) return model.label
  const id = model.id || selectedModel.value
  if (id === 'default') return 'Sonnet 4.6'
  const family = /sonnet/i.test(id) ? 'Sonnet' : /opus/i.test(id) ? 'Opus' : /haiku/i.test(id) ? 'Haiku' : ''
  if (family) {
    const match = id.match(new RegExp(`${family}[-_ ]?(\\d+(?:[-_]\\d+)?)`, 'i'))
    const version = match?.[1]?.replace(/[-_]/g, '.')
    return version ? `${family} ${version}` : family
  }
  if (/gpt[-_]?4o/i.test(id)) return 'GPT-4o'
  if (/gpt[-_]?4/i.test(id)) return 'GPT-4'
  if (/gemini/i.test(id)) return 'Gemini'
  return id.replace(/[-_]+/g, ' ')
}

function modelDescription(model?: ModelOption): string {
  if (model?.desc) return model.desc
  if (model?.id === 'default' || selectedModel.value === 'default') return 'Fast and capable'
  if (model?.owned_by === 'shenyu' || model?.owned_by === 'shenyu-alias') return 'Gateway alias'
  return currentPreset.value ? `${currentPreset.value.name} model` : 'Default gateway model'
}

function modelUpstreamId(model?: ModelOption): string {
  return model?.id || selectedModel.value
}

function persistMessages() {
  persistStoredMessages(messages.value, sessionMessageLimit())
}

function clientContext(): RequestContext {
  return { gatewayUrl: gatewayUrl.value, authToken: authToken.value, sessionTag: sessionTag.value }
}

function loadPresets() {
  presets.value = readUpstreamPresets()
}

async function loadRuntimeUpstream() {
  try {
    const payload = await fetchRuntimeConfig(clientContext())
    const configuredMessageLimit = Number(payload.max_client_messages)
    maxClientMessages.value = Number.isFinite(configuredMessageLimit) && configuredMessageLimit > 0
      ? Math.floor(configuredMessageLimit)
      : null
    runtimeUpstream.value = {
      url: String(payload.upstream_url || ''),
      protocol: String(payload.upstream_protocol || 'auto'),
      extraBody: JSON.stringify(payload.upstream_extra_body || {}),
    }
    const matching = presets.value.find((preset) => preset.url === runtimeUpstream.value.url && preset.protocol === runtimeUpstream.value.protocol)
    if (matching) {
      selectedPresetName.value = matching.name
      localStorage.setItem(STORAGE_PRESET, matching.name)
    }
  } catch {
    // The preset selector remains usable even when config read access is protected.
  }
}

function sessionMessageLimit(): number {
  return maxClientMessages.value || FALLBACK_SESSION_MESSAGE_LIMIT
}

async function loadModels() {
  try {
    const payload = await fetchModels(clientContext())
    models.value = Array.isArray(payload.data)
      ? payload.data.filter((model: unknown): model is ModelOption => Boolean(model && typeof model === 'object' && (model as ModelOption).id))
      : []
    if (models.value.length && !models.value.some((model) => model.id === selectedModel.value)) {
      selectedModel.value = models.value[0].id
    }
  } catch {
    models.value = [{ id: selectedModel.value || 'default', owned_by: 'shenyu', label: selectedModel.value === 'default' ? 'Sonnet 4.6' : undefined }]
  }
}

async function loadSessions() {
  try {
    const payload = await fetchSessions(clientContext(), 24)
    recentSessions.value = Array.isArray(payload.sessions) ? payload.sessions : []
  } catch {
    recentSessions.value = []
  }
}

function sessionTitle(session: GatewaySession): string {
  return session.display_name?.trim() || session.latest_user_text?.trim() || session.session_tag || '未命名对话'
}

function sessionMeta(session: GatewaySession): string {
  const count = Number(session.user_message_count || session.message_count || 0)
  return count ? `${count} 轮` : '还没有消息'
}

// ---- 最近对话的长按操作（改名/删除） ----------------------------------------
// 长按（或桌面右键）弹出操作单；滑动列表时移动超过阈值就取消判定。

const sessionActionTarget = ref<GatewaySession | null>(null)
// 错误必须显示在操作单里：底下的 errorNotice 会被侧栏和面板盖住，等于没提示。
const sessionActionError = ref('')
watch(sessionActionTarget, () => { sessionActionError.value = '' })
let sessionPressTimer: number | null = null
let sessionPressMoved = false
let sessionLongPressFired = false
let sessionPressStartX = 0
let sessionPressStartY = 0

function sessionPressStart(session: GatewaySession, event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  sessionPressCancel()
  sessionLongPressFired = false
  sessionPressMoved = false
  sessionPressStartX = event.clientX
  sessionPressStartY = event.clientY
  sessionPressTimer = window.setTimeout(() => {
    sessionLongPressFired = true
    sessionActionTarget.value = session
  }, 550)
}

function sessionPressMove(event: PointerEvent) {
  if (sessionPressTimer === null) return
  if (Math.abs(event.clientX - sessionPressStartX) > 10 || Math.abs(event.clientY - sessionPressStartY) > 10) {
    sessionPressMoved = true
    sessionPressCancel()
  }
}

function sessionPressCancel() {
  if (sessionPressTimer !== null) {
    window.clearTimeout(sessionPressTimer)
    sessionPressTimer = null
  }
}

function sessionItemClick(session: GatewaySession) {
  sessionPressCancel()
  if (sessionLongPressFired || sessionPressMoved) {
    sessionLongPressFired = false
    sessionPressMoved = false
    return
  }
  void openSession(session)
}

function openSessionActions(session: GatewaySession) {
  sessionActionTarget.value = session
}

async function renameSessionAction(session: GatewaySession) {
  const name = window.prompt('给这条对话起个名字（留空恢复默认标题）', session.display_name?.trim() || '')
  if (name === null) return
  const trimmed = name.trim()
  if (trimmed.length > 60) {
    sessionActionError.value = '名字太长了，60 个字以内。'
    return
  }
  try {
    await renameSession(clientContext(), session.session_tag, trimmed)
    session.display_name = trimmed || null
    sessionActionTarget.value = null
    status.value = trimmed ? `已改名：${trimmed}` : '已恢复默认标题'
    await loadSessions()
  } catch (error) {
    sessionActionError.value = error instanceof Error ? error.message : '改名没有成功。'
  }
}

async function deleteSessionAction(session: GatewaySession) {
  if (session.session_tag === sessionTag.value) return
  const label = sessionTitle(session)
  if (!window.confirm(`删除「${label}」？\n只清掉网关里这条对话的快照和心跳，Supabase 档案（我们说过的话）不受影响。`)) return
  try {
    await deleteSession(clientContext(), session.session_tag)
    recentSessions.value = recentSessions.value.filter((item) => item.session_tag !== session.session_tag)
    sessionActionTarget.value = null
    status.value = `已删除 ${label}`
  } catch (error) {
    sessionActionError.value = error instanceof Error ? error.message : '删除没有成功。'
  }
}

async function openSession(session: GatewaySession): Promise<boolean> {
  if (busy.value || !session.session_tag) return false
  try {
    const payload = await fetchSessionDetail(clientContext(), session.session_tag, sessionMessageLimit())
    const rows = sessionHistoryRows(payload)
    messages.value = rows
      .filter((row: Record<string, unknown>) => row.role === 'user' || row.role === 'assistant')
      .map((row: Record<string, unknown>) => ({
        id: String(row.id || createId('message')),
        role: row.role as Role,
        content: sessionMessageContent(row.content),
        attachments: [],
        thinking: '',
        thinkingSegments: [],
        events: [],
        streaming: false,
      }))
    // 快照只带正文；用 recent_messages 里的 tool 原始行补回工具事件，
    // 随后的 persistMessages 会把补好的 events 一起落盘。
    hydrateToolEvents(messages.value, payload.recent_messages)
    sessionTag.value = session.session_tag
    localStorage.setItem(STORAGE_SESSION, sessionTag.value)
    persistMessages()
    menuOpen.value = false
    errorNotice.value = ''
    await nextTick()
    scrollToBottom()
    return true
  } catch {
    errorNotice.value = '这页对话暂时拿不到，当前页面还在。'
    return false
  }
}

async function recoverSessionFromColdStart(session: GatewaySession = { session_tag: sessionTag.value }): Promise<boolean> {
  if (busy.value || !session.session_tag) return false
  if (!window.confirm('将保留当前 PWA 新消息，只移除完全相同的重复历史，并让下一次请求使用干净冷启动源。继续吗？')) return false
  try {
    const payload = await fetchSessionDetail(clientContext(), session.session_tag, sessionMessageLimit())
    const cleanRows = coldStartHistoryRows(payload, session.session_tag)
    if (!cleanRows.length || hasExactDuplicateRows(cleanRows)) throw new Error('没有找到干净的冷启动源')
    if (messages.value.length) messages.value = dedupeUiMessagesForRecovery(messages.value)
    else {
      messages.value = cleanRows.map((row) => ({
        id: createId('message'),
        role: row.role as Role,
        content: sessionMessageContent(row.content),
        attachments: [],
        thinking: '',
        thinkingSegments: [],
        events: [],
        streaming: false,
      }))
      hydrateToolEvents(messages.value, payload.recent_messages)
    }
    sessionTag.value = session.session_tag
    localStorage.setItem(STORAGE_SESSION, sessionTag.value)
    persistMessages()
    handoffOpen.value = false
    errorNotice.value = ''
    status.value = `已清理重复历史，保留 PWA 新消息；下一次请求将使用干净基线 ${session.session_tag}`
    await nextTick()
    scrollToBottom()
    return true
  } catch (error) {
    errorNotice.value = error instanceof Error ? error.message : '干净恢复失败。'
    return false
  }
}

async function adoptInitialSession() {
  if (!requestedSessionTag) return
  const matching = recentSessions.value.find((session) => session.session_tag === requestedSessionTag)
  const opened = await openSession(matching || { session_tag: requestedSessionTag })
  if (!opened) {
    localStorage.setItem(STORAGE_SESSION, requestedSessionTag)
  }
  status.value = opened ? `已接上线程 ${requestedSessionTag}` : `将继续使用线程 ${requestedSessionTag}`
}

async function openHandoffSheet() {
  menuOpen.value = false
  handoffOpen.value = true
  handoffLoading.value = true
  await loadSessions()
  handoffLoading.value = false
}

async function selectHandoffSession(session: GatewaySession) {
  const opened = await openSession(session)
  if (!opened) return
  handoffOpen.value = false
  status.value = `已接上线程 ${session.session_tag}`
}

async function copyCurrentSessionTag() {
  await copyText(sessionTag.value)
}

function selectModel(id: string) {
  selectedModel.value = id
  localStorage.setItem(STORAGE_MODEL, id)
  modelOpen.value = false
}

async function selectPreset(preset: UpstreamPreset) {
  if (switchingPreset.value) return
  let extraBody: Record<string, unknown> = {}
  if (preset.extra_body?.trim()) {
    try {
      const parsed = JSON.parse(preset.extra_body)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('extra body must be an object')
      extraBody = parsed as Record<string, unknown>
    } catch {
      errorNotice.value = `预设 ${preset.name} 的 extra body 不是有效 JSON。`
      return
    }
  }
  const body: Record<string, unknown> = {
    upstream_url: preset.url,
    upstream_protocol: preset.protocol || 'auto',
    upstream_extra_body: extraBody,
    upstream_passthrough_headers: [...(preset.passthrough_headers || [])],
  }
  if (preset.key) body.upstream_api_key = preset.key
  switchingPreset.value = preset.name
  errorNotice.value = ''
  try {
    await postUpstreamConfig(clientContext(), body)
    runtimeUpstream.value = { url: preset.url, protocol: preset.protocol || 'auto', extraBody: JSON.stringify(extraBody) }
    selectedPresetName.value = preset.name
    localStorage.setItem(STORAGE_PRESET, preset.name)
    models.value = []
    await loadModels()
    modelOpen.value = false
    modelSheetPage.value = 'main'
    status.value = `已切换到 ${preset.name}`
    window.setTimeout(() => { if (!busy.value) status.value = '' }, 1800)
  } catch (error) {
    errorNotice.value = error instanceof Error ? `预设切换失败：${error.message}` : '预设切换失败。'
  } finally {
    switchingPreset.value = ''
  }
}

function selectEffort(id: string) {
  effort.value = id
  localStorage.setItem(STORAGE_EFFORT, id)
}

function toggleExtended() {
  extendedThinking.value = !extendedThinking.value
  localStorage.setItem(STORAGE_EXTENDED, String(extendedThinking.value))
}

function toggleStreamResponses() {
  streamResponses.value = !streamResponses.value
  localStorage.setItem(STORAGE_STREAM, String(streamResponses.value))
}

function openModelSheet(page: 'main' | 'effort' | 'more' | 'preset' = 'main') {
  loadPresets()
  modelSheetPage.value = page
  modelOpen.value = true
}

function closeModelSheet() {
  modelOpen.value = false
  modelSheetPage.value = 'main'
}

function modelSheetTitle(): string {
  if (modelSheetPage.value === 'effort') return 'Effort'
  if (modelSheetPage.value === 'more') return 'More models'
  if (modelSheetPage.value === 'preset') return 'Preset'
  return 'Select model'
}

function openWorkspace(id: WorkspaceId) {
  activeWorkspace.value = id
  menuOpen.value = false
  if (id === 'chats') nextTick(() => inputRef.value?.focus())
}

function workspaceAction(id: WorkspaceId) {
  if (id === 'chats') return
  errorNotice.value = `${workspaceContent[id].detail}`
}

function saveSettings() {
  localStorage.setItem(STORAGE_TOKEN, authToken.value.trim())
  localStorage.setItem(STORAGE_GATEWAY, gatewayUrl.value.trim())
  settingsOpen.value = false
  loadModels()
  loadPresets()
  loadRuntimeUpstream()
}

function newChat() {
  if (busy.value) cancelGeneration()
  messages.value = []
  pendingAttachments.value = []
  editId.value = null
  sessionTag.value = createId('pwa')
  localStorage.setItem(STORAGE_SESSION, sessionTag.value)
  persistMessages()
  loadSessions()
  menuOpen.value = false
  nextTick(() => inputRef.value?.focus())
}

function openConsole() {
  const base = gatewayUrl.value.trim().replace(/\/$/, '')
  window.open(base ? `${base}/admin/` : '/admin/', '_blank', 'noopener,noreferrer')
}

function scrollToBottom() {
  nextTick(() => {
    if (streamRef.value) streamRef.value.scrollTop = streamRef.value.scrollHeight
  })
}

function updateDraft(event: Event) {
  draft.value = (event.target as HTMLTextAreaElement).value
  resizeInput()
}

function resizeInput() {
  const input = inputRef.value
  if (!input) return
  input.style.height = 'auto'
  input.style.height = `${Math.min(input.scrollHeight, 144)}px`
  input.scrollTop = input.scrollHeight
}

function resetInputSize() {
  nextTick(() => {
    const input = inputRef.value
    if (!input) return
    input.style.height = 'auto'
    input.scrollTop = 0
  })
}

let keyboardTimers: number[] = []

function clearKeyboardTimers() {
  keyboardTimers.forEach((timer) => window.clearTimeout(timer))
  keyboardTimers = []
}

function keyboardViewportBottom(): number {
  const viewport = window.visualViewport
  return viewport ? viewport.offsetTop + viewport.height : window.innerHeight
}

function keepComposerVisible() {
  const input = inputRef.value
  const stream = streamRef.value
  const wrap = input?.closest<HTMLElement>('.composer-wrap')
  if (!input || !stream || !wrap) return
  if (document.activeElement !== input) {
    wrap.style.transform = ''
    stream.style.paddingBottom = ''
    return
  }
  wrap.style.transform = ''
  const lift = Math.max(0, Math.ceil(wrap.getBoundingClientRect().bottom - keyboardViewportBottom() + 8))
  wrap.style.transform = lift ? `translateY(${-lift}px)` : ''
  stream.style.paddingBottom = lift ? `calc(var(--space-6) + ${lift}px)` : ''
  scrollToBottom()
}

function scheduleComposerVisible() {
  clearKeyboardTimers()
  for (const delay of [0, 80, 180, 320, 520, 800]) {
    keyboardTimers.push(window.setTimeout(keepComposerVisible, delay))
  }
  window.requestAnimationFrame(keepComposerVisible)
}

function handleComposerBlur() {
  clearKeyboardTimers()
  keyboardTimers.push(window.setTimeout(keepComposerVisible, 80))
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

async function resizeImage(file: File): Promise<Attachment> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error || new Error('图片读取失败'))
    reader.readAsDataURL(file)
  })

  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new Error('图片解码失败'))
      element.src = dataUrl
    })
    const maxSide = 1600
    const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    canvas.getContext('2d')?.drawImage(image, 0, 0, canvas.width, canvas.height)
    const compressed = canvas.toDataURL('image/jpeg', 0.82)
    return { id: createId('image'), name: file.name, mime: 'image/jpeg', dataUrl: compressed }
  } catch {
    return { id: createId('image'), name: file.name, mime: file.type || 'image/*', dataUrl }
  }
}

async function chooseImages(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  for (const file of files.slice(0, 4 - pendingAttachments.value.length)) {
    if (!file.type.startsWith('image/')) {
      errorNotice.value = `${file.name} 不是图片，第一版先只收图片。`
      continue
    }
    if (file.size > 12 * 1024 * 1024) {
      errorNotice.value = `${file.name} 太大了，先压到 12MB 以内吧。`
      continue
    }
    pendingAttachments.value.push(await resizeImage(file))
  }
}

function removeAttachment(id: string) {
  pendingAttachments.value = pendingAttachments.value.filter((item) => item.id !== id)
}

async function sendConversation(source: UiMessage[], target?: UiMessage) {
  let assistant: UiMessage
  let previousVariantIndex: number | null = null
  let generatedVariantIndex: number | null = null
  if (target) {
    const variants = ensureVariants(target)
    previousVariantIndex = selectedVariantIndex(target)
    variants.push(emptyVariant())
    generatedVariantIndex = variants.length - 1
    applyVariant(target, variants[generatedVariantIndex], generatedVariantIndex)
    target.error = undefined
    target.streaming = true
    assistant = target
  } else {
    const assistantDraft: UiMessage = {
      id: createId('assistant'),
      role: 'assistant',
      content: '',
      attachments: [],
      thinking: '',
      thinkingSegments: [],
      events: [],
      streaming: true,
    }
    messages.value.push(assistantDraft)
    // Read the object back through Vue's proxy. Mutating the detached draft would
    // leave the template unaware until another top-level ref changes.
    assistant = messages.value[messages.value.length - 1]
  }
  activeAssistantId = assistant.id
  activeController = new AbortController()
  busy.value = true
  status.value = '沈予正在看着这边…'
  errorNotice.value = ''
  scrollToBottom()

  try {
    const useStreaming = streamResponses.value
    const body = {
      model: selectedModel.value,
      messages: wireMessages(source.filter((message) => message.id !== assistant.id)),
      stream: useStreaming,
      reasoning_effort: effectiveEffort.value,
    }
    if (useStreaming) {
      const stream = await postChatStream(clientContext(), body, activeController.signal)
      await pumpSseStream(stream, (frame) => parseSseFrame(frame, assistant), scrollToBottom)
    } else {
      const completion = await postChatCompletion(clientContext(), body, activeController.signal)
      applyChatCompletion(completion, assistant)
    }
    assistant.streaming = false
    if (!assistant.content && !assistant.thinking && !assistant.events.length) assistant.content = '这次没有收到可显示的回应。'
    syncCurrentVariant(assistant)
  } catch (error) {
    assistant.streaming = false
    if (target && generatedVariantIndex !== null && previousVariantIndex !== null) {
      const variants = target.variants || []
      variants.splice(generatedVariantIndex, 1)
      const restoredIndex = Math.max(0, Math.min(previousVariantIndex, variants.length - 1))
      if (variants[restoredIndex]) applyVariant(target, variants[restoredIndex], restoredIndex)
      target.streaming = false
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        errorNotice.value = error instanceof Error ? error.message : '请求没有完成'
      }
    } else if (error instanceof DOMException && error.name === 'AbortError') {
      assistant.content = assistant.content || '这次先停在这里。'
    } else {
      assistant.error = error instanceof Error ? error.message : '请求没有完成'
      errorNotice.value = assistant.error
    }
  } finally {
    busy.value = false
    activeController = null
    activeAssistantId = null
    status.value = ''
    persistMessages()
    loadSessions()
    scrollToBottom()
  }
}

async function submit() {
  if (busy.value || !hasContent.value) return
  // 尾部状态后缀：先剥旧再追新，编辑重发换新不叠加（跨端契约第1条）。
  const text = stampStatusSuffix(draft.value.trim())
  if (editId.value) {
    const index = messages.value.findIndex((message) => message.id === editId.value)
    if (index >= 0 && messages.value[index].role === 'user') {
      messages.value[index].content = text
      messages.value[index].attachments = [...pendingAttachments.value]
      messages.value = messages.value.slice(0, index + 1)
      draft.value = ''
      pendingAttachments.value = []
      editId.value = null
      resetInputSize()
      await sendConversation(messages.value)
    }
    return
  }

  const user: UiMessage = {
    id: createId('user'),
    role: 'user',
    content: text,
    attachments: [...pendingAttachments.value],
    thinking: '',
    thinkingSegments: [],
    events: [],
  }
  messages.value.push(user)
  draft.value = ''
  pendingAttachments.value = []
  resetInputSize()
  await sendConversation(messages.value)
}

function cancelGeneration() {
  activeController?.abort()
  if (activeAssistantId) {
    const assistant = messages.value.find((message) => message.id === activeAssistantId)
    if (assistant) assistant.streaming = false
  }
}

function beginEdit(message: UiMessage) {
  if (message.role !== 'user' || busy.value) return
  editId.value = message.id
  draft.value = stripStatusSuffix(message.content)
  pendingAttachments.value = [...message.attachments]
  nextTick(() => {
    resizeInput()
    inputRef.value?.focus()
  })
}

function cancelEdit() {
  editId.value = null
  draft.value = ''
  pendingAttachments.value = []
  resetInputSize()
}

async function retryMessage(index: number) {
  if (busy.value) return
  const assistant = messages.value[index]
  if (!assistant || assistant.role !== 'assistant') return
  syncCurrentVariant(assistant)
  messages.value = messages.value.slice(0, index + 1)
  await sendConversation(messages.value.slice(0, index), assistant)
}

function switchMessageVariant(index: number, direction: -1 | 1) {
  if (busy.value) return
  const message = messages.value[index]
  if (!message || message.role !== 'assistant' || variantCount(message) < 2) return
  syncCurrentVariant(message)
  const count = message.variants?.length || 0
  const current = selectedVariantIndex(message)
  const next = current + direction
  if (next < 0 || next >= count) return
  const variant = message.variants?.[next]
  if (!variant) return
  applyVariant(message, variant, next)
  persistMessages()
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    status.value = '已经放进剪贴板了'
    window.setTimeout(() => { if (!busy.value) status.value = '' }, 1500)
  } catch {
    errorNotice.value = '剪贴板没有打开，长按文字也可以复制。'
  }
}

function openProcessSheet(message: UiMessage, group: ProcessGroup) {
  processSheet.value = { messageId: message.id, view: 'summary', textOffset: group.textOffset }
}

function closeProcessSheet() {
  processSheet.value = null
}

function showThinkingDetail(thinking: ThinkingSegment) {
  if (!processSheet.value) return
  processSheet.value = { ...processSheet.value, view: 'thinking', thinkingKey: thinking.id }
}

function showToolDetail(event: ToolEvent) {
  if (!processSheet.value) return
  processSheet.value = { ...processSheet.value, view: 'tool', toolKey: toolEventKey(event) }
}

function backToProcessSummary() {
  if (!processSheet.value) return
  processSheet.value = { ...processSheet.value, view: 'summary', thinkingKey: undefined, toolKey: undefined }
}

// 渲染层切分：气泡里正文与尾部状态后缀分开、后缀淡化展示（数据本身不变）。
function userBubbleBody(message: UiMessage): string {
  return splitStatusSuffix(message.content).body
}

function userBubbleSuffix(message: UiMessage): string {
  // 展示层去掉机器锚点【】，消息数据本身保持跨端契约不变。
  return splitStatusSuffix(message.content).suffix.replace(/^【|】$/gu, '')
}

function statusSpriteMode(message: UiMessage): SpriteMode {
  const hasActiveTool = traceRows(message).some((event) => event.phase === 'tool_start' || event.ok === undefined)
  if (hasActiveTool) return 'shimmer'
  if (message.thinking && !message.content) return 'thinking'
  if (message.content) return 'writing'
  return 'entrance'
}

function runQuickPrompt(prompt: string) {
  draft.value = prompt
  nextTick(() => {
    resizeInput()
    submit()
  })
}

onMounted(async () => {
  window.visualViewport?.addEventListener('resize', scheduleComposerVisible)
  window.visualViewport?.addEventListener('scroll', scheduleComposerVisible)
  localStorage.setItem(STORAGE_SESSION, sessionTag.value)
  initBatteryWatch()
  initWeatherWatch(clientContext)
  loadPresets()
  await loadRuntimeUpstream()
  await loadModels()
  await loadSessions()
  await adoptInitialSession()
  nextTick(() => inputRef.value?.focus())
})

onUnmounted(() => {
  clearKeyboardTimers()
  window.visualViewport?.removeEventListener('resize', scheduleComposerVisible)
  window.visualViewport?.removeEventListener('scroll', scheduleComposerVisible)
})
</script>

<template>
  <div class="pwa-shell">
    <div v-if="menuOpen" class="drawer-scrim" @click="menuOpen = false" />

    <aside class="sidebar" :class="{ 'sidebar-open': menuOpen }">
      <div class="sidebar-head">
        <div class="brand-lockup">
          <img class="brand-mark" :src="brandMarkUrl" alt="" />
          <img class="brand-wordmark" :src="brandWordmarkUrl" alt="Claude" />
        </div>
        <button class="icon-button mobile-close" aria-label="关闭菜单" title="关闭菜单" @click="menuOpen = false">
          <X :size="18" />
        </button>
      </div>

      <nav class="sidebar-nav" aria-label="导航">
        <button class="sidebar-nav-item" :class="{ active: activeWorkspace === 'chats' }" type="button" @click="openWorkspace('chats')">
          <svg class="sidebar-nav-icon" viewBox="0 0 256 256" aria-hidden="true"><path d="M232.07,186.76a80,80,0,0,0-62.5-114.17A80,80,0,1,0,23.93,138.76l-7.27,24.71a16,16,0,0,0,19.87,19.87l24.71-7.27a80.39,80.39,0,0,0,25.18,7.35,80,80,0,0,0,108.34,40.65l24.71,7.27a16,16,0,0,0,19.87-19.86ZM62,159.5a8.28,8.28,0,0,0-2.26.32L32,168l8.17-27.76a8,8,0,0,0-.63-6,64,64,0,1,1,26.26,26.26A8,8,0,0,0,62,159.5Zm153.79,28.73L224,216l-27.76-8.17a8,8,0,0,0-6,.63,64.05,64.05,0,0,1-85.87-24.88A79.93,79.93,0,0,0,174.7,89.71a64,64,0,0,1,41.75,92.48A8,8,0,0,0,215.82,188.23Z" /></svg>
          <span>Chats</span>
        </button>
        <button class="sidebar-nav-item" :class="{ active: activeWorkspace === 'projects' }" type="button" @click="openWorkspace('projects')">
          <svg class="sidebar-nav-icon" viewBox="0 0 256 256" aria-hidden="true"><path d="M216,72H130.67L102.93,51.2a16.12,16.12,0,0,0-9.6-3.2H40A16,16,0,0,0,24,64V200a16,16,0,0,0,16,16H216.89A15.13,15.13,0,0,0,232,200.89V88A16,16,0,0,0,216,72Zm0,128H40V64H93.33L123.2,86.4A8,8,0,0,0,128,88h88Z" /></svg>
          <span>Projects</span>
        </button>
        <button class="sidebar-nav-item" :class="{ active: activeWorkspace === 'artifacts' }" type="button" @click="openWorkspace('artifacts')">
          <svg class="sidebar-nav-icon" viewBox="0 0 256 256" aria-hidden="true"><path d="M223.68,66.15,135.68,18h0a15.88,15.88,0,0,0-15.36,0l-88,48.17a16,16,0,0,0-8.32,14v95.64a16,16,0,0,0,8.32,14l88,48.17a15.88,15.88,0,0,0,15.36,0l88-48.17a16,16,0,0,0,8.32-14V80.18A16,16,0,0,0,223.68,66.15ZM128,32h0l80.34,44L128,120,47.66,76ZM40,90l80,43.78v85.79L40,175.82Zm96,129.57V133.82L216,90v85.78Z" /></svg>
          <span>Artifacts</span>
        </button>
        <button class="sidebar-nav-item" :class="{ active: activeWorkspace === 'memory' }" type="button" @click="openWorkspace('memory')">
          <svg class="sidebar-nav-icon" viewBox="0 0 256 256" aria-hidden="true"><path d="M184,32H72A16,16,0,0,0,56,48V224a8,8,0,0,0,12.24,6.78L128,193.43l59.77,37.35A8,8,0,0,0,200,224V48A16,16,0,0,0,184,32Zm0,177.57-51.77-32.35a8,8,0,0,0-8.48,0L72,209.57V48H184Z" /></svg>
          <span>Memory</span>
        </button>
        <button class="sidebar-nav-item" :class="{ active: activeWorkspace === 'diary' }" type="button" @click="openWorkspace('diary')">
          <svg class="sidebar-nav-icon" viewBox="0 0 256 256" aria-hidden="true"><path d="M200,32H168V24a8,8,0,0,0-16,0v8H104V24a8,8,0,0,0-16,0v8H56A16,16,0,0,0,40,48V208a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V48A16,16,0,0,0,200,32Zm0,176H56V48H88v8a8,8,0,0,0,16,0V48h48v8a8,8,0,0,0,16,0V48h32Z" /></svg>
          <span>Diary</span>
        </button>
        <button class="sidebar-nav-item" type="button" @click="openHandoffSheet">
          <ArrowLeftRight :size="21" />
          <span>接入线程</span>
        </button>
        <button class="sidebar-nav-item sidebar-console-link" type="button" @click="openConsole">
          <SlidersHorizontal :size="21" />
          <span>Console</span>
          <ExternalLink :size="14" class="sidebar-external-icon" />
        </button>
      </nav>

      <div class="sidebar-section-title">Recents</div>
      <div class="sidebar-empty" v-if="!recentSessions.length && isEmpty">
        还没有最近对话。
      </div>
      <div v-else class="session-list">
        <button
          v-for="session in recentSessions"
          :key="session.session_tag"
          class="session-item"
          :class="{ active: session.session_tag === sessionTag }"
          type="button"
          @click="sessionItemClick(session)"
          @pointerdown="sessionPressStart(session, $event)"
          @pointermove="sessionPressMove($event)"
          @pointerup="sessionPressCancel()"
          @pointercancel="sessionPressCancel()"
          @pointerleave="sessionPressCancel()"
          @contextmenu.prevent="openSessionActions(session)"
        >
          <span class="session-title">{{ sessionTitle(session) }}</span>
          <small>{{ sessionMeta(session) }}</small>
        </button>
        <button v-if="!recentSessions.length" class="session-item active" type="button" @click="menuOpen = false">
          <span class="session-title">当前对话</span>
          <small>{{ messages.filter((message) => message.role === 'user').length }} 轮</small>
        </button>
      </div>

      <div class="sidebar-spacer" />
      <button class="new-chat" @click="newChat">
        <MessageCirclePlus :size="18" />
        <span>New chat</span>
      </button>
      <button class="sidebar-link" @click="settingsOpen = true; menuOpen = false">
        <Settings2 :size="17" />
        <span>Settings</span>
      </button>
    </aside>

    <main class="chat-main">
      <header class="topbar">
        <button class="icon-button menu-button" aria-label="打开菜单" title="打开菜单" @click="menuOpen = true">
          <Menu :size="20" />
        </button>
        <button class="model-capsule" @click="openModelSheet()">
          <span class="model-capsule-main">
            <span class="model-capsule-text">{{ currentModelLabel }}</span>
            <ChevronDown :size="14" />
          </span>
          <span class="model-capsule-effort">{{ effortOptions.find((item) => item.id === effort)?.label }}</span>
        </button>
        <button class="icon-button" aria-label="新开一页" title="新开一页" @click="newChat">
          <Plus :size="20" />
        </button>
      </header>

      <section v-if="activeWorkspace !== 'chats'" class="workspace-view">
        <div class="workspace-hero">
          <span class="workspace-eyebrow">{{ workspaceContent[activeWorkspace].eyebrow }}</span>
          <h1>{{ workspaceContent[activeWorkspace].title }}</h1>
          <p>{{ workspaceContent[activeWorkspace].description }}</p>
        </div>
        <div class="workspace-empty">
          <div class="workspace-empty-mark"><img :src="brandMarkUrl" alt="" /></div>
          <h2>{{ workspaceContent[activeWorkspace].detail }}</h2>
          <p>This view is ready for the gateway-backed data when that workspace is enabled.</p>
          <button class="workspace-action" type="button" @click="workspaceAction(activeWorkspace)">
            <Plus :size="16" />
            <span>{{ workspaceContent[activeWorkspace].action }}</span>
          </button>
        </div>
      </section>

      <section v-else ref="streamRef" class="message-stream">
        <div v-if="isEmpty" class="welcome-panel">
          <img class="welcome-mark" :src="brandMarkUrl" alt="Claude" />
          <h1>What's on your mind?</h1>
        </div>

        <article v-for="(message, index) in messages" :key="message.id" class="message-row" :class="message.role">
          <div v-if="message.role === 'assistant'" class="assistant-avatar"><Sparkles :size="15" /></div>
          <div class="message-column">
            <div v-if="message.role === 'user' && message.attachments.length" class="message-images">
              <img v-for="attachment in message.attachments" :key="attachment.id" :src="attachment.dataUrl" :alt="attachment.name" />
            </div>
            <div v-if="message.role === 'user'" class="user-bubble">
              <template v-if="userBubbleBody(message)">{{ userBubbleBody(message) }}</template>
              <template v-else-if="!userBubbleSuffix(message)">{{ '（一张图片）' }}</template>
              <span v-if="userBubbleSuffix(message)" class="msg-suffix">{{ userBubbleSuffix(message) }}</span>
            </div>
            <div v-else class="assistant-body">
              <template v-for="part in assistantParts(message)" :key="part.key">
                <div v-if="part.kind === 'content' && part.content" class="markdown-content" v-html="renderMarkdown(part.content)" />
                <button v-else-if="part.kind === 'process'" class="process-strip" :class="{ thinking: groupHasThinking(part.group) }" type="button" @click="openProcessSheet(message, part.group)">
                  <span class="process-icon">
                    <Clock3 v-if="groupHasThinking(part.group)" :size="16" />
                    <Sparkles v-else :size="15" />
                  </span>
                  <span class="process-copy">{{ processSummary(part.group) }}</span>
                  <ChevronRight :size="16" />
                </button>
              </template>
              <ChatNestSprite v-if="message.streaming" :mode="statusSpriteMode(message)" />
              <div v-if="message.error" class="message-error">这次没有顺利接上：{{ message.error }}</div>
              <div v-if="!message.streaming && (message.content || message.error)" class="message-actions">
                <button title="复制" aria-label="复制" @click="copyText(message.content)"><Clipboard :size="15" /></button>
                <button title="重新生成" aria-label="重新生成" @click="retryMessage(index)"><RotateCcw :size="15" /></button>
                <span v-if="variantCount(message) > 1" class="variant-switcher">
                  <button title="上一版回答" aria-label="上一版回答" :disabled="!canSwitchMessageVariant(message, -1)" @click="switchMessageVariant(index, -1)"><ChevronLeft :size="15" /></button>
                  <span>{{ selectedVariantIndex(message) + 1 }} / {{ variantCount(message) }}</span>
                  <button title="下一版回答" aria-label="下一版回答" :disabled="!canSwitchMessageVariant(message, 1)" @click="switchMessageVariant(index, 1)"><ChevronRight :size="15" /></button>
                </span>
              </div>
            </div>
            <div v-if="message.role === 'user'" class="user-actions">
              <button title="编辑这条消息" aria-label="编辑这条消息" @click="beginEdit(message)"><Pencil :size="14" /></button>
              <button title="复制" aria-label="复制" @click="copyText(message.content)"><Clipboard :size="14" /></button>
            </div>
          </div>
        </article>
      </section>

      <div v-if="activeWorkspace === 'chats' && (status || errorNotice)" class="notice-line" :class="{ error: errorNotice }">
        <span>{{ errorNotice || status }}</span>
        <button v-if="errorNotice" aria-label="关闭提示" title="关闭提示" @click="errorNotice = ''"><X :size="15" /></button>
      </div>

      <footer v-if="activeWorkspace === 'chats'" class="composer-wrap">
        <div class="composer-box">
          <div v-if="editId" class="edit-banner">
            <Pencil :size="15" />
            <span>正在改写这条消息，送出后后面的回答会重新长出来。</span>
            <button aria-label="取消编辑" title="取消编辑" @click="cancelEdit"><X :size="15" /></button>
          </div>
          <div v-if="pendingAttachments.length" class="pending-attachments">
            <div v-for="attachment in pendingAttachments" :key="attachment.id" class="pending-image">
              <img :src="attachment.dataUrl" :alt="attachment.name" />
              <button aria-label="移除图片" title="移除图片" @click="removeAttachment(attachment.id)"><X :size="13" /></button>
            </div>
          </div>
          <div class="composer">
            <input ref="fileRef" class="visually-hidden" type="file" accept="image/*" multiple @change="chooseImages" />
            <div class="composer-input-row">
              <textarea
                ref="inputRef"
                class="composer-input"
                :value="draft"
                rows="1"
                placeholder="Reply to Claude..."
                enterkeyhint="send"
                @blur="handleComposerBlur"
                @focus="scheduleComposerVisible"
                @input="updateDraft"
                @keydown="onComposerKeydown"
              />
            </div>
            <div class="composer-actions">
              <button class="composer-icon" aria-label="添加图片" title="添加图片" @click="fileRef?.click()"><ImagePlus :size="19" /></button>
              <span class="composer-spacer" />
              <button v-if="busy" class="send-button stop" aria-label="停止生成" title="停止生成" @click="cancelGeneration"><CircleStop :size="19" /></button>
              <button v-else class="send-button" :class="{ ready: hasContent }" :disabled="!hasContent" aria-label="发送" title="发送" @click="submit"><Send :size="18" /></button>
            </div>
          </div>
        </div>
      </footer>
    </main>

    <div v-if="processSheetMessage" class="sheet-layer" @click.self="closeProcessSheet">
      <section class="bottom-sheet process-sheet">
        <div class="sheet-handle" />
        <header class="sheet-head">
          <button class="sheet-back" :aria-label="processSheet?.view === 'summary' ? '关闭' : '返回过程列表'" :title="processSheet?.view === 'summary' ? '关闭' : '返回过程列表'" @click="processSheet?.view === 'summary' ? closeProcessSheet() : backToProcessSummary()">
            <X v-if="processSheet?.view === 'summary'" :size="19" />
            <ArrowLeft v-else :size="20" />
          </button>
          <h2 class="sheet-title">{{ processSheetTitle }}</h2>
        </header>

        <div class="sheet-content process-sheet-content">
          <template v-if="processSheet?.view === 'summary'">
            <div class="process-timeline">
              <button v-for="item in processTimeline(processSheetGroup)" :key="item.key" class="process-timeline-item" type="button" @click="item.kind === 'thinking' ? showThinkingDetail(item.thinking) : showToolDetail(item.tool)">
                <span class="process-timeline-rail">
                  <span class="process-timeline-icon"><Clock3 v-if="item.kind === 'thinking'" :size="16" /><Sparkles v-else :size="15" /></span>
                  <span class="process-timeline-line" />
                </span>
                <span class="process-timeline-copy">
                  <strong>{{ item.kind === 'thinking' ? '思考片段' : toolLabel(item.tool) }}</strong>
                  <small>{{ item.kind === 'thinking' ? thinkingPreview(item.thinking.content) || '正在整理想法…' : `${toolState(item.tool)} · ${toolResultPreview(item.tool)}` }}</small>
                </span>
                <ChevronRight :size="17" />
              </button>
            </div>
          </template>

          <template v-else-if="processSheet?.view === 'thinking'">
            <pre class="process-text">{{ processSheetThinking?.content }}</pre>
          </template>

          <template v-else>
            <div class="process-code-section">
              <span class="process-code-label">调用参数</span>
              <pre class="process-code">{{ formatToolInput(processSheetEvent) }}</pre>
            </div>
            <div class="process-code-section">
              <span class="process-code-label">沈予看到的结果</span>
              <pre class="process-code">{{ formatToolOutput(processSheetEvent) }}</pre>
            </div>
          </template>
        </div>
      </section>
    </div>

    <div v-if="sessionActionTarget" class="sheet-layer" @click.self="sessionActionTarget = null">
      <section class="bottom-sheet session-action-sheet">
        <div class="sheet-handle" />
        <div class="sheet-heading">
          <div>
            <span class="sheet-eyebrow">最近对话</span>
            <h2>{{ sessionTitle(sessionActionTarget) }}</h2>
          </div>
          <button class="icon-button" aria-label="关闭" title="关闭" @click="sessionActionTarget = null"><X :size="18" /></button>
        </div>
        <p class="settings-note session-action-tag"><code>{{ sessionActionTarget.session_tag }}</code></p>
        <div class="session-action-list">
          <button class="quiet-button" @click="renameSessionAction(sessionActionTarget)">改名</button>
          <button
            class="quiet-button session-action-danger"
            :disabled="sessionActionTarget.session_tag === sessionTag"
            @click="deleteSessionAction(sessionActionTarget)"
          >删除</button>
        </div>
        <p v-if="sessionActionError" class="settings-note session-action-error">{{ sessionActionError }}</p>
        <p v-else-if="sessionActionTarget.session_tag === sessionTag" class="settings-note">正在聊的这条不能删，换到别的对话再回来删它。</p>
        <p v-else class="settings-note">删除只清网关里的快照和心跳，档案里我们说过的话都还在。</p>
      </section>
    </div>

    <div v-if="handoffOpen" class="sheet-layer" @click.self="handoffOpen = false">
      <section class="bottom-sheet settings-sheet">
        <div class="sheet-handle" />
        <div class="sheet-heading">
          <div><span class="sheet-eyebrow">跨客户端接力</span><h2>接入已有线程</h2></div>
          <button class="icon-button" aria-label="关闭" title="关闭" @click="handoffOpen = false"><X :size="18" /></button>
        </div>
        <p class="settings-note">选中要接入的已有线程后，PWA 会加载它的历史；切回其他客户端时请继续使用同一个线程标识。</p>
        <div class="handoff-current">
          <span>当前线程</span>
          <code>{{ sessionTag }}</code>
          <button class="icon-button" aria-label="复制当前线程标识" title="复制当前线程标识" @click="copyCurrentSessionTag"><Clipboard :size="16" /></button>
        </div>
        <button class="quiet-button recovery-button" :disabled="busy" @click="recoverSessionFromColdStart()">清理重复并保留 PWA 新消息</button>
        <div v-if="handoffLoading" class="preset-empty"><p>正在读取网关线程…</p></div>
        <div v-else-if="handoffSessions.length" class="session-list handoff-list">
          <button
            v-for="session in handoffSessions"
            :key="session.session_tag"
            class="session-item"
            :class="{ active: session.session_tag === sessionTag }"
            type="button"
            @click="selectHandoffSession(session)"
          >
            <span class="session-title">{{ sessionTitle(session) }}</span>
            <small>{{ session.session_tag }} · {{ sessionMeta(session) }}</small>
          </button>
        </div>
        <div v-else class="preset-empty"><p>网关里还没有可接入的其他客户端线程。</p></div>
        <div class="settings-actions"><button class="quiet-button" @click="handoffOpen = false">关闭</button></div>
      </section>
    </div>

    <div v-if="modelOpen" class="sheet-layer" @click.self="closeModelSheet">
      <section class="bottom-sheet model-sheet">
        <div class="sheet-handle" />
        <header class="sheet-head">
          <button class="sheet-back" aria-label="返回" title="返回" @click="modelSheetPage === 'main' ? closeModelSheet() : modelSheetPage = 'main'">
            <X v-if="modelSheetPage === 'main'" :size="19" />
            <ArrowLeft v-else :size="20" />
          </button>
          <h2 class="sheet-title">{{ modelSheetTitle() }}</h2>
        </header>

        <div class="sheet-content">
          <template v-if="modelSheetPage === 'main'">
            <div class="model-group">
              <button v-for="model in primaryModels" :key="model.id" class="model-group-item" :class="{ selected: model.id === selectedModel }" @click="selectModel(model.id)">
                <span class="model-info">
                  <span class="model-name">{{ modelLabel(model) }}</span>
                  <span class="model-desc">{{ modelDescription(model) }}</span>
                  <code v-if="model.id !== 'default'" class="model-upstream-id">上游：{{ modelUpstreamId(model) }}</code>
                </span>
                <Check v-if="model.id === selectedModel" class="model-check" :size="18" />
              </button>
            </div>
            <div v-if="currentModel" class="model-group">
              <button class="model-group-item" @click="openModelSheet('effort')">
                <span class="model-name">Effort</span>
                <span class="model-nav-right">{{ effortOptions.find((item) => item.id === effort)?.label }} <ChevronRight :size="18" /></span>
              </button>
            </div>
            <div class="model-group">
              <button class="model-group-item" @click="openModelSheet('preset')">
                <span class="model-info">
                  <span class="model-name">Preset</span>
                  <span class="model-desc">{{ currentPreset?.name || 'Default gateway configuration' }}</span>
                </span>
                <ChevronRight :size="18" class="model-nav-right" />
              </button>
            </div>
            <div class="model-group">
              <div class="extended-row">
                <span class="extended-info"><span class="extended-label">Stream</span><span class="extended-desc">{{ streamResponses ? '流式' : '非流式' }}</span></span>
                <button class="toggle" :class="{ on: streamResponses }" type="button" role="switch" :aria-checked="streamResponses" aria-label="切换流式回应" @click="toggleStreamResponses"><span /></button>
              </div>
            </div>
            <div v-if="secondaryModels.length" class="model-group">
              <button class="model-group-item" @click="openModelSheet('more')">
                <span class="model-name">More models</span>
                <span class="model-nav-right"><ChevronRight :size="18" /></span>
              </button>
            </div>
          </template>

          <template v-else-if="modelSheetPage === 'effort'">
            <div class="model-group">
              <button v-for="item in effortOptions" :key="item.id" class="model-group-item" :class="{ selected: item.id === effort }" @click="selectEffort(item.id)">
                <span class="model-info">
                  <span class="effort-option-name">{{ item.label }}<span v-if="item.id === 'medium'" class="effort-option-badge">Default</span></span>
                  <span class="effort-option-desc">{{ item.note }}</span>
                </span>
                <Check v-if="item.id === effort" class="model-check" :size="18" />
              </button>
            </div>
            <p class="effort-note">Higher effort means more thorough responses, but takes longer and uses your limits faster.</p>
            <div class="model-group">
              <div class="extended-row">
                <span class="extended-info"><span class="extended-label">Extended</span><span class="extended-desc">Always uses deep reasoning</span></span>
                <button class="toggle" :class="{ on: extendedThinking }" aria-label="切换 Extended" @click="toggleExtended"><span /></button>
              </div>
            </div>
          </template>

          <template v-else-if="modelSheetPage === 'preset'">
            <div v-if="presets.length" class="model-group">
              <button v-for="preset in presets" :key="preset.name" class="model-group-item" :class="{ selected: preset.name === selectedPresetName }" :disabled="!!switchingPreset" @click="selectPreset(preset)">
                <span class="model-info">
                  <span class="model-name">{{ preset.name }}</span>
                  <span class="model-desc">{{ preset.protocol || 'auto' }} · {{ preset.url || 'URL not set' }}</span>
                </span>
                <Check v-if="preset.name === selectedPresetName" class="model-check" :size="18" />
              </button>
            </div>
            <div v-else class="preset-empty">
              <p>No presets are saved in the Console yet.</p>
              <button class="workspace-action" type="button" @click="openConsole"><ExternalLink :size="16" /> <span>Open Console</span></button>
            </div>
            <p class="effort-note">Presets use the same Console storage and update the fixed default gateway upstream.</p>
          </template>

          <template v-else>
            <div class="model-group">
              <button v-for="model in secondaryModels" :key="model.id" class="model-group-item" :class="{ selected: model.id === selectedModel }" @click="selectModel(model.id)">
                <span class="model-info">
                  <span class="model-name">{{ modelLabel(model) }}</span>
                  <span class="model-desc">{{ modelDescription(model) }}</span>
                  <code v-if="model.id !== 'default'" class="model-upstream-id">上游：{{ modelUpstreamId(model) }}</code>
                </span>
                <Check v-if="model.id === selectedModel" class="model-check" :size="18" />
              </button>
            </div>
          </template>
        </div>
      </section>
    </div>

    <div v-if="settingsOpen" class="sheet-layer" @click.self="settingsOpen = false">
      <section class="bottom-sheet settings-sheet">
        <div class="sheet-handle" />
        <div class="sheet-heading"><div><span class="sheet-eyebrow">只保存在这台设备</span><h2>聊天设置</h2></div><button class="icon-button" aria-label="关闭" title="关闭" @click="settingsOpen = false"><X :size="18" /></button></div>
        <label class="field-label" for="gateway-url">网关地址</label>
        <input id="gateway-url" v-model="gatewayUrl" class="settings-input" placeholder="留空则使用当前站点" />
        <label class="field-label" for="gateway-token">网关密钥</label>
        <input id="gateway-token" v-model="authToken" class="settings-input" type="password" placeholder="只保存在本机 localStorage" />
        <p class="settings-note">图片会在发送前压缩，聊天端不会把图片放进 Service Worker 缓存。</p>
        <div class="settings-actions"><button class="quiet-button" @click="newChat"><Trash2 :size="16" /> 清空当前对话</button><button class="primary-button" @click="saveSettings"><Check :size="16" /> 收好设置</button></div>
      </section>
    </div>
  </div>
</template>
