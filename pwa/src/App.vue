<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
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
import { toolName, toolState, toolWarmCopy, type ToolEvent } from './toolLanguage'

type Role = 'user' | 'assistant'

type Attachment = {
  id: string
  name: string
  mime: string
  dataUrl: string
}

type UiMessage = {
  id: string
  role: Role
  content: string
  attachments: Attachment[]
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  streaming?: boolean
  error?: string
  expanded?: boolean
  variants?: MessageVariant[]
  selectedVariantIndex?: number
}

type MessageVariant = {
  content: string
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  error?: string
}

type ThinkingSegment = {
  id: string
  content: string
  textOffset: number
  streamOrder: number
}

type ProcessGroup = {
  textOffset: number
  thinking: ThinkingSegment[]
  tools: ToolEvent[]
}

type ProcessTimelineItem =
  | { kind: 'thinking'; key: string; thinking: ThinkingSegment; streamOrder: number }
  | { kind: 'tool'; key: string; tool: ToolEvent; streamOrder: number }

type AssistantPart =
  | { kind: 'content'; key: string; content: string }
  | { kind: 'process'; key: string; group: ProcessGroup }

type ModelOption = {
  id: string
  object?: string
  owned_by?: string
  label?: string
  desc?: string
  thinking?: string
  primary?: boolean
}

type GatewaySession = {
  session_tag: string
  client_name?: string
  last_active_at?: string
  latest_user_text?: string
  message_count?: number
  user_message_count?: number
}

type WorkspaceId = 'chats' | 'projects' | 'artifacts' | 'memory' | 'diary'

type UpstreamPreset = {
  name: string
  url: string
  key: string
  protocol: string
  proto?: string
  extra_body?: string
  passthrough_headers?: string[]
}

type ProcessSheet = {
  messageId: string
  view: 'summary' | 'thinking' | 'tool'
  textOffset?: number
  thinkingKey?: string
  toolKey?: string
}

type SpriteMode = keyof typeof CHATNEST_STATUS_SPRITES

const STORAGE_MESSAGES = 'shenyu_pwa_messages'
const STORAGE_SESSION = 'shenyu_pwa_session'
const STORAGE_TOKEN = 'shenyu_pwa_gateway_token'
const STORAGE_GATEWAY = 'shenyu_pwa_gateway_url'
const STORAGE_MODEL = 'shenyu_pwa_model'
const STORAGE_EFFORT = 'shenyu_pwa_effort'
const STORAGE_EXTENDED = 'shenyu_pwa_extended'
const STORAGE_PRESET = 'shenyu_pwa_preset'
const PRESETS_KEY = 'shenyu_upstream_presets'
const FALLBACK_SESSION_MESSAGE_LIMIT = 75

function sessionTagFromLocation(): string {
  try {
    const params = new URLSearchParams(window.location.search)
    return (params.get('session_tag') || params.get('session') || params.get('thread') || '').trim()
  } catch {
    return ''
  }
}

const requestedSessionTag = sessionTagFromLocation()
const storedSessionTag = localStorage.getItem(STORAGE_SESSION) || ''

const messages = ref<UiMessage[]>(loadMessages())
const draft = ref('')
const pendingAttachments = ref<Attachment[]>([])
const models = ref<ModelOption[]>([])
const recentSessions = ref<GatewaySession[]>([])
const selectedModel = ref(localStorage.getItem(STORAGE_MODEL) || 'default')
const effort = ref(localStorage.getItem(STORAGE_EFFORT) || 'medium')
const extendedThinking = ref(localStorage.getItem(STORAGE_EXTENDED) !== 'false')
const selectedPresetName = ref(localStorage.getItem(STORAGE_PRESET) || '')
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

function createId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function cloneVariant(variant: Partial<MessageVariant>): MessageVariant {
  return {
    content: String(variant.content || ''),
    thinking: String(variant.thinking || ''),
    thinkingSegments: Array.isArray(variant.thinkingSegments)
      ? variant.thinkingSegments.map((item) => ({
          id: String(item?.id || createId('thinking')),
          content: String(item?.content || ''),
          textOffset: Number(item?.textOffset || 0),
          streamOrder: Number(item?.streamOrder || 0),
        }))
      : [],
    events: Array.isArray(variant.events) ? variant.events.map((item) => ({ ...item })) : [],
    error: variant.error ? String(variant.error) : undefined,
  }
}

function snapshotMessage(message: UiMessage): MessageVariant {
  return cloneVariant(message)
}

function selectedVariantIndex(message: UiMessage): number {
  const count = message.variants?.length || 1
  return Math.max(0, Math.min(Number(message.selectedVariantIndex || 0), count - 1))
}

function variantCount(message: UiMessage): number {
  return message.variants?.length || 1
}

function syncCurrentVariant(message: UiMessage) {
  if (message.role !== 'assistant' || !message.variants?.length) return
  const index = selectedVariantIndex(message)
  message.selectedVariantIndex = index
  message.variants[index] = snapshotMessage(message)
}

function applyVariant(message: UiMessage, variant: MessageVariant, index: number) {
  message.selectedVariantIndex = index
  message.content = variant.content
  message.thinking = variant.thinking
  message.thinkingSegments = variant.thinkingSegments.map((item) => ({ ...item }))
  message.events = variant.events.map((item) => ({ ...item }))
  message.error = variant.error
}

function emptyVariant(): MessageVariant {
  return { content: '', thinking: '', thinkingSegments: [], events: [] }
}

function ensureVariants(message: UiMessage): MessageVariant[] {
  if (!message.variants?.length) {
    message.variants = [snapshotMessage(message)]
    message.selectedVariantIndex = 0
  } else {
    message.selectedVariantIndex = selectedVariantIndex(message)
    syncCurrentVariant(message)
  }
  return message.variants
}

function hasExactDuplicateRows(rows: Record<string, unknown>[]): boolean {
  const seen = new Set<string>()
  for (const row of rows) {
    if (row.role !== 'user' && row.role !== 'assistant') continue
    const key = `${String(row.role)}\u0000${sessionMessageContent(row.content)}`
    if (seen.has(key)) return true
    seen.add(key)
  }
  return false
}

function dedupeUiMessagesForRecovery(source: UiMessage[]): UiMessage[] {
  const seen = new Set<string>()
  return source.filter((message) => {
    const key = `${message.role}\u0000${message.content}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

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

function loadMessages(): UiMessage[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_MESSAGES) || '[]')
    if (!Array.isArray(raw)) return []
    return raw.filter((item) => item && (item.role === 'user' || item.role === 'assistant'))
      .map((item) => {
        const message: UiMessage = {
          id: String(item.id || createId('message')),
          role: item.role as Role,
          content: String(item.content || ''),
          attachments: [],
          thinking: String(item.thinking || ''),
          thinkingSegments: item.thinking
            ? [{ id: createId('thinking'), content: String(item.thinking), textOffset: 0, streamOrder: 0 }]
            : [],
          events: [],
          streaming: false,
          error: item.error ? String(item.error) : undefined,
        }
        if (message.role === 'assistant' && Array.isArray(item.variants) && item.variants.length) {
          const variants = item.variants.map((variant: Partial<MessageVariant>) => cloneVariant(variant))
          message.variants = variants
          message.selectedVariantIndex = selectedVariantIndex({ ...message, variants })
          applyVariant(message, variants[message.selectedVariantIndex], message.selectedVariantIndex)
        }
        return message
      })
  } catch {
    return []
  }
}

function persistMessages() {
  messages.value.forEach(syncCurrentVariant)
  const safe = messages.value.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    thinking: message.thinking,
    error: message.error,
    variants: message.variants,
    selectedVariantIndex: message.selectedVariantIndex,
  }))
  localStorage.setItem(STORAGE_MESSAGES, JSON.stringify(safe.slice(-120)))
}

function apiUrl(path: string): string {
  const base = gatewayUrl.value.trim().replace(/\/$/, '')
  return `${base}${path}`
}

function requestHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Shenyu-Client': 'shenyu-pwa',
    'X-Shenyu-Tool-Events': 'true',
    'X-Shenyu-Tool-Details': 'true',
    'X-Shenyu-Session-Tag': sessionTag.value,
  }
  if (authToken.value.trim()) headers.Authorization = `Bearer ${authToken.value.trim()}`
  return headers
}

function loadPresets() {
  try {
    const raw = JSON.parse(localStorage.getItem(PRESETS_KEY) || '{}')
    presets.value = Object.entries(raw).map(([name, value]) => {
      const preset = value as Partial<UpstreamPreset>
      return {
        name,
        url: preset.url || '',
        key: preset.key || '',
        protocol: preset.protocol || preset.proto || 'auto',
        extra_body: preset.extra_body || '',
        passthrough_headers: preset.passthrough_headers || [],
      }
    })
  } catch {
    presets.value = []
  }
}

async function loadRuntimeUpstream() {
  try {
    const response = await fetch(apiUrl('/api/config'), { headers: requestHeaders() })
    if (!response.ok) throw new Error('config unavailable')
    const payload = await response.json()
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
    const response = await fetch(apiUrl('/v1/models'), { headers: requestHeaders() })
    if (!response.ok) throw new Error('模型列表暂时拿不到')
    const payload = await response.json()
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
    const response = await fetch(apiUrl('/api/gateway/sessions?limit=24'), { headers: requestHeaders() })
    if (!response.ok) throw new Error('session list unavailable')
    const payload = await response.json()
    recentSessions.value = Array.isArray(payload.sessions) ? payload.sessions : []
  } catch {
    recentSessions.value = []
  }
}

function sessionTitle(session: GatewaySession): string {
  return session.latest_user_text?.trim() || session.session_tag || '未命名对话'
}

function sessionMeta(session: GatewaySession): string {
  const count = Number(session.user_message_count || session.message_count || 0)
  return count ? `${count} 轮` : '还没有消息'
}

function sessionHistoryRows(payload: Record<string, unknown>): Record<string, unknown>[] {
  // Context snapshots are the trimmed client transcript. `recent_messages` is
  // an inspection stream and is only a compatibility fallback for old data.
  const snapshotCollections = [payload.context_snapshots, payload.request_context_snapshots]
  for (const candidate of snapshotCollections) {
    if (!Array.isArray(candidate)) continue
    const latest = candidate[0]
    if (!latest || typeof latest !== 'object') continue
    const rows = (latest as Record<string, unknown>).messages
    if (!Array.isArray(rows)) continue
    return rows.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
  }
  const fallback = payload.recent_messages
  return Array.isArray(fallback)
    ? fallback.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
    : []
}

function coldStartHistoryRows(payload: Record<string, unknown>, targetTag: string): Record<string, unknown>[] {
  const snapshots = payload.cold_start_snapshots
  if (!Array.isArray(snapshots)) return []
  const latest = snapshots.find((item) => item && typeof item === 'object' && (item as Record<string, unknown>).active !== false) as Record<string, unknown> | undefined
  const sources = latest?.sources
  if (!Array.isArray(sources)) return []
  const source = sources.find((item) => {
    if (!item || typeof item !== 'object') return false
    const row = item as Record<string, unknown>
    return !targetTag || String(row.session_tag || '') === targetTag
  }) || sources[0]
  if (!source || typeof source !== 'object') return []
  const rows = (source as Record<string, unknown>).messages
  if (!Array.isArray(rows)) return []
  return rows
    .filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
    .filter((row) => row.role === 'user' || row.role === 'assistant')
}

function sessionMessageContent(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map((block) => {
      if (typeof block === 'string') return block
      if (!block || typeof block !== 'object') return ''
      const item = block as Record<string, unknown>
      return item.type === 'text' ? String(item.text || '') : ''
    }).join('')
  }
  return value == null ? '' : String(value)
}

async function openSession(session: GatewaySession): Promise<boolean> {
  if (busy.value || !session.session_tag) return false
  try {
    const response = await fetch(apiUrl(`/api/gateway/sessions/${encodeURIComponent(session.session_tag)}?messages_limit=${sessionMessageLimit()}`), {
      headers: requestHeaders(),
    })
    if (!response.ok) throw new Error('session unavailable')
    const payload = await response.json() as Record<string, unknown>
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
    const response = await fetch(apiUrl(`/api/gateway/sessions/${encodeURIComponent(session.session_tag)}?messages_limit=${sessionMessageLimit()}`), {
      headers: requestHeaders(),
    })
    if (!response.ok) throw new Error('session unavailable')
    const payload = await response.json() as Record<string, unknown>
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
    const response = await fetch(apiUrl('/api/config'), {
      method: 'POST',
      headers: requestHeaders(),
      body: JSON.stringify(body),
    })
    if (!response.ok) throw new Error((await response.text()) || `网关返回 ${response.status}`)
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
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`
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

function wireContent(message: UiMessage): string | Array<Record<string, unknown>> {
  if (!message.attachments.length) return message.content
  const blocks: Array<Record<string, unknown>> = []
  if (message.content.trim()) blocks.push({ type: 'text', text: message.content })
  for (const attachment of message.attachments) {
    blocks.push({ type: 'image_url', image_url: { url: attachment.dataUrl } })
  }
  return blocks
}

function wireMessages(source: UiMessage[]) {
  return source.map((message) => ({
    role: message.role,
    content: wireContent(message),
  }))
}

function textLength(value: string): number {
  return Array.from(value).length
}

function textSlice(value: string, start: number, end?: number): string {
  return Array.from(value).slice(start, end).join('')
}

function nextProcessOrder(message: UiMessage): number {
  const thoughtOrder = message.thinkingSegments.reduce((max, item) => Math.max(max, item.streamOrder), -1)
  const toolOrder = message.events.reduce((max, item) => Math.max(max, item.stream_order || -1), -1)
  return Math.max(thoughtOrder, toolOrder) + 1
}

function appendToolEvent(message: UiMessage, event: ToolEvent) {
  const key = `${event.phase}:${event.tool_call_id || event.name}`
  const existingIndex = message.events.findIndex((item) => `${item.phase}:${item.tool_call_id || item.name}` === key)
  const existing = existingIndex >= 0 ? message.events[existingIndex] : undefined
  const relatedStart = message.events.find((item) => item.phase === 'tool_start' && toolEventKey(item) === toolEventKey(event))
  const stored = {
    ...event,
    text_offset: existing?.text_offset ?? relatedStart?.text_offset ?? textLength(message.content),
    stream_order: existing?.stream_order ?? relatedStart?.stream_order ?? nextProcessOrder(message),
  }
  if (existingIndex >= 0) message.events.splice(existingIndex, 1, stored)
  else message.events.push(stored)
}

function appendThinking(message: UiMessage, delta: string) {
  if (!delta) return
  message.thinking += delta
  const textOffset = textLength(message.content)
  const last = message.thinkingSegments[message.thinkingSegments.length - 1]
  if (last && last.textOffset === textOffset) {
    last.content += delta
    return
  }
  message.thinkingSegments.push({
    id: createId('thinking'),
    content: delta,
    textOffset,
    streamOrder: nextProcessOrder(message),
  })
}

function toolLabel(event: ToolEvent): string {
  return toolName(event).replace(/[_-]+/g, ' ')
}

function toolResultPreview(event: ToolEvent): string {
  if (event.phase === 'tool_start' || event.ok === undefined) return '正在执行…'
  const output = String(event.output || '').replace(/\s+/g, ' ').trim()
  if (output) return output.length > 72 ? `${output.slice(0, 72)}…` : output
  return event.ok === false ? '执行失败' : '执行成功'
}

function parseSseFrame(frame: string, assistant: UiMessage) {
  let eventName = ''
  const dataLines: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  const data = dataLines.join('\n')
  if (!data) return false
  if (data === '[DONE]') return true
  try {
    const payload = JSON.parse(data)
    if (eventName === 'shenyu_tool' || payload.type === 'shenyu.tool_event') {
      const event = payload.event as ToolEvent
      if (event) appendToolEvent(assistant, event)
      return false
    }
    if (payload.error) throw new Error(String(payload.error.message || payload.error))
    const delta = payload.choices?.[0]?.delta || {}
    if (typeof delta.content === 'string') assistant.content += delta.content
    if (typeof delta.reasoning_content === 'string') appendThinking(assistant, delta.reasoning_content)
    if (typeof delta.reasoning === 'string') appendThinking(assistant, delta.reasoning)
    const message = payload.choices?.[0]?.message
    if (message && typeof message.content === 'string') assistant.content += message.content
  } catch (error) {
    if (error instanceof Error && error.message) throw error
  }
  return false
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
    const response = await fetch(apiUrl('/v1/chat/completions'), {
      method: 'POST',
      headers: requestHeaders(),
      body: JSON.stringify({
        model: selectedModel.value,
        messages: wireMessages(source.filter((message) => message.id !== assistant.id)),
        stream: true,
        reasoning_effort: effectiveEffort.value,
      }),
      signal: activeController.signal,
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || `网关返回 ${response.status}`)
    }
    if (!response.body) throw new Error('没有收到流式回应')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let done = false
    while (!done) {
      const chunk = await reader.read()
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const frame of frames) {
        if (parseSseFrame(frame, assistant)) done = true
      }
      if (chunk.done) {
        if (buffer.trim()) parseSseFrame(buffer, assistant)
        done = true
      }
      scrollToBottom()
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
  const text = draft.value.trim()
  if (editId.value) {
    const index = messages.value.findIndex((message) => message.id === editId.value)
    if (index >= 0 && messages.value[index].role === 'user') {
      messages.value[index].content = text
      messages.value[index].attachments = [...pendingAttachments.value]
      messages.value = messages.value.slice(0, index + 1)
      draft.value = ''
      pendingAttachments.value = []
      editId.value = null
      resizeInput()
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
  resizeInput()
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
  draft.value = message.content
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
  resizeInput()
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

function canSwitchMessageVariant(message: UiMessage, direction: -1 | 1): boolean {
  const count = variantCount(message)
  const current = selectedVariantIndex(message)
  return count > 1 && current + direction >= 0 && current + direction < count
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

function traceRows(message: UiMessage): ToolEvent[] {
  const rows: ToolEvent[] = []
  const byId = new Map<string, ToolEvent>()
  for (const event of message.events) {
    if (event.phase === 'tool_start') {
      const row = { ...event }
      rows.push(row)
      byId.set(event.tool_call_id || event.name, row)
    } else if (event.phase === 'tool_end') {
      const row = byId.get(event.tool_call_id || event.name)
      if (row) Object.assign(row, event)
      else rows.push({ ...event })
    }
  }
  return rows
}

function toolEventKey(event: ToolEvent): string {
  return event.tool_call_id || `${event.name}:${event.round || 0}`
}

function processGroups(message: UiMessage): ProcessGroup[] {
  const groups = new Map<number, ProcessGroup>()
  const ensure = (textOffset: number) => {
    const normalized = Math.max(0, Math.min(textLength(message.content), textOffset))
    const existing = groups.get(normalized)
    if (existing) return existing
    const created: ProcessGroup = { textOffset: normalized, thinking: [], tools: [] }
    groups.set(normalized, created)
    return created
  }

  const thinking = message.thinkingSegments.length
    ? message.thinkingSegments
    : message.thinking
      ? [{ id: `${message.id}-thinking`, content: message.thinking, textOffset: 0, streamOrder: 0 }]
      : []
  for (const item of thinking) ensure(item.textOffset).thinking.push(item)
  for (const event of traceRows(message)) ensure(event.text_offset || 0).tools.push(event)

  return [...groups.values()]
    .sort((left, right) => left.textOffset - right.textOffset)
    .map((group) => ({
      ...group,
      thinking: [...group.thinking].sort((left, right) => left.streamOrder - right.streamOrder),
      tools: [...group.tools].sort((left, right) => (left.stream_order || 0) - (right.stream_order || 0)),
    }))
}

function assistantParts(message: UiMessage): AssistantPart[] {
  const parts: AssistantPart[] = []
  let cursor = 0
  for (const group of processGroups(message)) {
    if (group.textOffset > cursor) {
      parts.push({ kind: 'content', key: `content-${cursor}`, content: textSlice(message.content, cursor, group.textOffset) })
    }
    parts.push({ kind: 'process', key: `process-${group.textOffset}`, group })
    cursor = group.textOffset
  }
  if (cursor < textLength(message.content) || !parts.length) {
    parts.push({ kind: 'content', key: `content-${cursor}`, content: textSlice(message.content, cursor) })
  }
  return parts
}

function processSummary(group: ProcessGroup): string {
  const active = group.tools.find((event) => event.phase === 'tool_start' || event.ok === undefined)
  if (active) return `正在${toolWarmCopy(active)} · ${toolLabel(active)}…`
  const thought = group.thinking[group.thinking.length - 1]
  if (thought) return thinkingPreview(thought.content) || '想了一会儿'
  const tool = group.tools[group.tools.length - 1]
  return tool ? `${toolWarmCopy(tool)} · ${toolLabel(tool)}` : '想了一会儿'
}

function groupHasThinking(group: ProcessGroup): boolean {
  return group.thinking.length > 0
}

function processTimeline(group?: ProcessGroup): ProcessTimelineItem[] {
  if (!group) return []
  return [
    ...group.thinking.map((thinking) => ({
      kind: 'thinking' as const,
      key: `thinking-${thinking.id}`,
      thinking,
      streamOrder: thinking.streamOrder,
    })),
    ...group.tools.map((tool) => ({
      kind: 'tool' as const,
      key: `tool-${toolEventKey(tool)}`,
      tool,
      streamOrder: tool.stream_order || 0,
    })),
  ].sort((left, right) => left.streamOrder - right.streamOrder)
}

function thinkingPreview(thinking: string): string {
  const compact = thinking.replace(/\s+/g, ' ').trim()
  const first = compact.match(/^[^。！？.!?]+[。！？.!?]?/)?.[0] || compact
  return first.length > 30 ? `${first.slice(0, 30)}…` : first
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

function statusSpriteMode(message: UiMessage): SpriteMode {
  const hasActiveTool = traceRows(message).some((event) => event.phase === 'tool_start' || event.ok === undefined)
  if (hasActiveTool) return 'shimmer'
  if (message.thinking && !message.content) return 'thinking'
  if (message.content) return 'writing'
  return 'entrance'
}

function formatToolInput(event?: ToolEvent): string {
  if (!event || event.input === undefined) return '（这条旧的工具记录没有保留参数）'
  if (typeof event.input === 'string') {
    try {
      return JSON.stringify(JSON.parse(event.input), null, 2)
    } catch {
      return event.input
    }
  }
  try {
    return JSON.stringify(event.input, null, 2)
  } catch {
    return String(event.input)
  }
}

function formatToolOutput(event?: ToolEvent): string {
  if (!event) return '（找不到这一步工具记录）'
  if (event.phase === 'tool_start' || event.ok === undefined) return '正在执行…'
  if (event.output !== undefined) return event.output || '（工具没有返回正文）'
  return '（这条旧的工具记录没有保留结果）'
}

function runQuickPrompt(prompt: string) {
  draft.value = prompt
  nextTick(() => {
    resizeInput()
    submit()
  })
}

onMounted(async () => {
  localStorage.setItem(STORAGE_SESSION, sessionTag.value)
  loadPresets()
  await loadRuntimeUpstream()
  await loadModels()
  await loadSessions()
  await adoptInitialSession()
  nextTick(() => inputRef.value?.focus())
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
          @click="openSession(session)"
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
              {{ message.content || '（一张图片）' }}
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
          <textarea
            ref="inputRef"
            :value="draft"
            rows="1"
            placeholder="Message Claude..."
            @input="updateDraft"
            @keydown="onComposerKeydown"
          />
          <div class="composer-tools">
            <button class="composer-icon" aria-label="添加图片" title="添加图片" @click="fileRef?.click()"><ImagePlus :size="19" /></button>
            <input ref="fileRef" class="visually-hidden" type="file" accept="image/*" multiple @change="chooseImages" />
            <button v-if="busy" class="send-button stop" aria-label="停止生成" title="停止生成" @click="cancelGeneration"><CircleStop :size="19" /></button>
            <button v-else class="send-button" :class="{ ready: hasContent }" :disabled="!hasContent" aria-label="发送" title="发送" @click="submit"><Send :size="18" /></button>
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
