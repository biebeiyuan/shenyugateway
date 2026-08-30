<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  ArrowLeftRight,
  Check,
  Clock3,
  ChevronDown,
  ChevronRight,
  CircleStop,
  Clipboard,
  DoorOpen,
  ExternalLink,
  ImagePlus,
  Menu,
  MessageCirclePlus,
  Pencil,
  Plus,
  RotateCcw,
  ScrollText,
  Send,
  SlidersHorizontal,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from 'lucide-vue-next'
import ChatMessageRow from './components/ChatMessageRow.vue'
import PhotoViewer from './components/PhotoViewer.vue'
import { activePwaBuildInfo, samePwaBuild, type PwaBuildInfo } from './buildInfo'
import { toolState, toolWarmCopy, type ToolEvent } from './toolLanguage'
import type {
  Attachment,
  EchoSegment,
  GatewaySession,
  ProcessGroup,
  ProcessSheet,
  Role,
  ThinkingSegment,
  UiMessage,
  UpstreamPreset,
} from './types'
import { createId } from './utils'
import {
  deleteSession,
  fetchDeployedPwaBuildInfo,
  fetchSessionDetail,
  fetchSessions,
  postChatCompletion,
  postChatStream,
  renameSession,
  wireMessages,
  type RequestContext,
} from './api/client'
import { useUpstream } from './api/useUpstream'
import { useComposer } from './session/useComposer'
import {
  CLAUDE_CODE_USER_AGENT,
  claudeCodeMetadata,
  claudeCodeSessionIdFromHeaders,
  readClaudeCodeSessionId,
  upstreamHeadersPayload,
} from './api/upstreamHeaders'
import {
  initBatteryWatch,
  initWeatherWatch,
  stampStatusSuffix,
  stripStatusSuffix,
} from './meta/statusSuffix'
import { buildRoomEntry, isRoomEntry, roomEntryTime } from './meta/roomEntry'
import {
  coldStartHistoryRows,
  dedupeUiMessagesForRecovery,
  hasExactDuplicateRows,
  sessionHistoryRows,
  sessionMessageContent,
  sessionMessageParts,
  sessionTagFromLocation,
} from './session/history'
import {
  FALLBACK_SESSION_MESSAGE_LIMIT,
  STORAGE_SESSION,
  loadStoredMessages,
  persistStoredMessages,
} from './session/persistence'
import { getPhotos, photoDataUrl, prunePhotos, putPhoto } from './session/photoStore'
import { hydrateToolEvents } from './session/toolHydration'
import { applyReconciledTail, tailNeedsReconcile } from './session/reconcile'
import {
  applyVariant,
  emptyVariant,
  ensureVariants,
  selectedVariantIndex,
  syncCurrentVariant,
  variantCount,
} from './session/variants'
import { parseSseFrame, pumpSseStream, toolEventKey } from './stream/sse'
import { applyChatCompletion } from './stream/completion'
import {
  formatToolInput,
  formatToolOutput,
  processGroups,
  processTimeline,
  thinkingPreview,
  toolLabel,
  toolResultPreview,
  traceRows,
} from './stream/timeline'

const STORAGE_TOKEN = 'shenyu_pwa_gateway_token'
const STORAGE_GATEWAY = 'shenyu_pwa_gateway_url'

// 一条消息最多几张图。本机总量另有上限（photoStore 的最近 30 张）。
const MESSAGE_IMAGE_LIMIT = 9

const requestedSessionTag = sessionTagFromLocation()
const storedSessionTag = localStorage.getItem(STORAGE_SESSION) || ''

const messages = ref<UiMessage[]>(loadStoredMessages())
const draft = ref('')
const pendingAttachments = ref<Attachment[]>([])
// 看图器：点开的是哪条消息的第几张。null = 关着。
const photoViewer = ref<{ messageId: string; position: number } | null>(null)
// 首屏只画最后这么多条，其余在下一帧补上。240 条全画要 235ms（实测），而屏幕上
// 一次只看得到三五条——先把你要看的那几条摆对位置，比一次画完更快到位。
const FIRST_PAINT_MESSAGES = 20
// null = 全部渲染。启动时先设成 FIRST_PAINT_MESSAGES，补齐后置回 null。
const renderTail = ref<number | null>(FIRST_PAINT_MESSAGES)
const recentSessions = ref<GatewaySession[]>([])
const authToken = ref(localStorage.getItem(STORAGE_TOKEN) || localStorage.getItem('shenyu_token') || '')
const gatewayUrl = ref(localStorage.getItem(STORAGE_GATEWAY) || '')
const sessionTag = ref(requestedSessionTag || storedSessionTag || createId('pwa'))
const menuOpen = ref(false)
const settingsOpen = ref(false)
const deployedPwaBuildInfo = ref<PwaBuildInfo | null>(null)
const pwaBuildCheck = ref<'idle' | 'checking' | 'current' | 'outdated' | 'unavailable'>('idle')
const handoffOpen = ref(false)
const handoffLoading = ref(false)
const modelOpen = ref(false)
const composerMenuOpen = ref(false)
const modelSheetPage = ref<'main' | 'effort' | 'more' | 'preset' | 'headers'>('main')
const processSheet = ref<ProcessSheet | null>(null)
const editId = ref<string | null>(null)
const busy = ref(false)
const status = ref('')
const errorNotice = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const fileRef = ref<HTMLInputElement | null>(null)
const composerMenuRef = ref<HTMLElement | null>(null)
const streamRef = ref<HTMLElement | null>(null)
// 上游配置（模型 / effort / 预设 / 请求头）整块在 api/useUpstream.ts。
// 它只通过 status / errorNotice / busy 与聊天说话，所以那三个注入进去。
const {
  models, presets, selectedModel, effort, extendedThinking, selectedPresetName,
  streamResponses, switchingPreset, runtimeUpstream, upstreamHeaders, maxClientMessages,
  currentModel, currentPreset, primaryModels, secondaryModels, effectiveEffort,
  customHeaderSummary, hasActiveUpstreamHeaders, claudeCodeHeaderSelected,
  modelLabel, modelDescription, modelUpstreamId,
  loadPresets, loadRuntimeUpstream, loadModels,
  selectModel: applyModel, selectPreset: applyPreset, selectEffort: applyEffort,
  toggleExtended, toggleStreamResponses,
  clearUpstreamHeaders, selectClaudeCodeHeaders, refreshClaudeCodeHeaders,
  addUpstreamHeader, removeUpstreamHeader,
} = useUpstream({ clientContext: () => clientContext(), status, errorNotice, busy })

// 输入框与滚动手感在 session/useComposer.ts（软键盘抬升、自动增高、滚到底）。
const {
  scrollToBottom, jumpToBottom, atBottom, resizeInput, resetInputSize, updateDraft, clearKeyboardTimers,
  keepComposerVisible, scheduleComposerVisible, handleComposerBlur, onComposerKeydown,
} = useComposer({ draft, inputRef, streamRef, onSubmit: () => submit() })

const currentModelLabel = computed(() => modelLabel(currentModel.value))

// 选模型/预设/effort 会关掉弹层——那是界面编排，留在主壳。
function selectModel(id: string) {
  applyModel(id)
  modelOpen.value = false
}

async function selectPreset(preset: UpstreamPreset) {
  const switched = await applyPreset(preset)
  if (switched) {
    modelOpen.value = false
    modelSheetPage.value = 'main'
  }
}

function selectEffort(id: string) {
  applyEffort(id)
  modelOpen.value = false
}

const brandMarkUrl = `${import.meta.env.BASE_URL}brand-mark.svg`
const brandWordmarkUrl = `${import.meta.env.BASE_URL}brand-wordmark.svg`
let activeController: AbortController | null = null
let activeAssistantId: string | null = null

const hasContent = computed(() => Boolean(draft.value.trim()) || pendingAttachments.value.length > 0)
const isEmpty = computed(() => !messages.value.some((message) => !isRoomEntry(message.content)))
// 首屏窗口。index 必须是在完整 messages 里的下标——重试/编辑/变体都按它定位，
// 用窗口内的相对下标会错位。
const visibleMessages = computed(() => {
  const tail = renderTail.value
  if (tail === null || messages.value.length <= tail) {
    return messages.value.map((message, index) => ({ message, index }))
  }
  const start = messages.value.length - tail
  return messages.value.slice(start).map((message, offset) => ({ message, index: start + offset }))
})
const pwaBuildStatus = computed(() => {
  if (pwaBuildCheck.value === 'checking') return '正在核验线上版本'
  if (pwaBuildCheck.value === 'current') return '当前页面就是线上版本'
  if (pwaBuildCheck.value === 'outdated') return '线上已更新，请重新打开页面'
  if (pwaBuildCheck.value === 'unavailable') return '暂时无法核验线上版本'
  return '尚未核验线上版本'
})
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
const processSheetEcho = computed(() => {
  const current = processSheet.value
  const group = processSheetGroup.value
  if (!current || current.view !== 'echo' || !group) return undefined
  return group.echo.find((item) => item.id === current.echoKey)
})
const processSheetTitle = computed(() => {
  if (processSheet.value?.view === 'echo') return '回响'
  if (processSheet.value?.view === 'thinking') return 'Thought process'
  if (processSheet.value?.view === 'tool') return toolWarmCopy(processSheetEvent.value || { phase: '', tool_call_id: '', name: '' })
  return '沈予刚才做了什么'
})


// 侧栏里除 Chats 之外的入口，都指向同源控制台的对应页面。刻意不在 PWA 里重做
// 那些界面：控制台已经有它们，而且共用登录 cookie，点开就是。
// 名称与控制台首页的卡片一致（星星 / 日志 / 房间 / 配置），避免同一个东西两个叫法。
const consoleLinks = [
  { label: '星星', path: '/stars', icon: Sparkles },
  { label: '房间', path: '/room', icon: DoorOpen },
  { label: '日志', path: '/logs', icon: ScrollText },
  { label: '配置', path: '/config', icon: Settings2 },
]

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




function persistMessages() {
  persistStoredMessages(messages.value, sessionMessageLimit())
}

// 流式中途每 ~3 秒落盘一次：进程在后台被杀时半截回复不丢（pagehide 再兜底）。
const STREAM_PERSIST_INTERVAL_MS = 3_000
let lastStreamPersistAt = 0

function onStreamChunkEnd() {
  scrollToBottom()
  const now = Date.now()
  if (now - lastStreamPersistAt >= STREAM_PERSIST_INTERVAL_MS) {
    lastStreamPersistAt = now
    persistMessages()
  }
}

function clientContext(): RequestContext {
  return { gatewayUrl: gatewayUrl.value, authToken: authToken.value, sessionTag: sessionTag.value }
}



function sessionMessageLimit(): number {
  return maxClientMessages.value || FALLBACK_SESSION_MESSAGE_LIMIT
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
    invalidateReconcile()
    messages.value = rows
      .filter((row: Record<string, unknown>) => row.role === 'user' || row.role === 'assistant')
      .map((row: Record<string, unknown>) => {
        const parts = sessionMessageParts(row.content)
        return {
          id: String(row.id || createId('message')),
          role: row.role as Role,
          content: parts.content,
          echo: row.role === 'assistant' ? parts.echo : '',
          echoSegments: row.role === 'assistant' && parts.echo
            ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }]
            : [],
          attachments: [],
          thinking: '',
          thinkingSegments: [],
          events: [],
          streaming: false,
        }
      })
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
    invalidateReconcile()
    if (messages.value.length) messages.value = dedupeUiMessagesForRecovery(messages.value)
    else {
      messages.value = cleanRows.map((row) => {
        const parts = sessionMessageParts(row.content)
        return {
          id: createId('message'),
          role: row.role as Role,
          content: parts.content,
          echo: row.role === 'assistant' ? parts.echo : '',
          echoSegments: row.role === 'assistant' && parts.echo
            ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }]
            : [],
          attachments: [],
          thinking: '',
          thinkingSegments: [],
          events: [],
          streaming: false,
        }
      })
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

// ---- 尾部对账：后台断流/进程被杀后，从服务器找回 drain 落库的完整回复 ------
// 触发点：流结束没等到 [DONE]、看门狗/网络错误、回前台、冷启动恢复本地消息。
// 服务端 drain 可能还没跑完，锚不上就按退避重试；切会话/新会话使旧的重试链作废。

const RECONCILE_RETRY_DELAYS_MS = [5_000, 15_000, 30_000]
const RECONCILE_STATUS = '正在找回后台期间的回复…'
let reconcileGeneration = 0
let reconcileTimer: number | null = null

function invalidateReconcile() {
  reconcileGeneration++
  if (reconcileTimer !== null) {
    window.clearTimeout(reconcileTimer)
    reconcileTimer = null
  }
}

async function reconcileTailFromServer(attempt = 0) {
  invalidateReconcile()
  const generation = reconcileGeneration
  if (busy.value || !tailNeedsReconcile(messages.value)) return
  status.value = RECONCILE_STATUS
  try {
    const payload = await fetchSessionDetail(clientContext(), sessionTag.value, sessionMessageLimit())
    if (generation !== reconcileGeneration || busy.value) return
    if (applyReconciledTail(messages.value, payload)) {
      persistMessages()
      errorNotice.value = ''
      status.value = '已找回后台期间的回复'
      await nextTick()
      scrollToBottom()
      return
    }
  } catch {
    // 网络可能还没恢复，与"drain 未完成"一样按退避重试。
  }
  if (generation !== reconcileGeneration) return
  if (attempt < RECONCILE_RETRY_DELAYS_MS.length) {
    reconcileTimer = window.setTimeout(() => {
      reconcileTimer = null
      void reconcileTailFromServer(attempt + 1)
    }, RECONCILE_RETRY_DELAYS_MS[attempt])
    return
  }
  if (status.value === RECONCILE_STATUS) status.value = ''
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











function openModelSheet(page: 'main' | 'effort' | 'more' | 'preset' | 'headers' = 'main') {
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
  if (modelSheetPage.value === 'headers') return '上游请求头'
  return 'Select model'
}


function saveSettings() {
  localStorage.setItem(STORAGE_TOKEN, authToken.value.trim())
  localStorage.setItem(STORAGE_GATEWAY, gatewayUrl.value.trim())
  settingsOpen.value = false
  loadModels()
  loadPresets()
  loadRuntimeUpstream()
}

function openSettings() {
  settingsOpen.value = true
  void checkPwaBuildInfo()
}

async function checkPwaBuildInfo() {
  pwaBuildCheck.value = 'checking'
  try {
    const deployed = await fetchDeployedPwaBuildInfo(clientContext())
    deployedPwaBuildInfo.value = deployed
    pwaBuildCheck.value = samePwaBuild(activePwaBuildInfo, deployed) ? 'current' : 'outdated'
  } catch {
    deployedPwaBuildInfo.value = null
    pwaBuildCheck.value = 'unavailable'
  }
}

function newChat() {
  if (busy.value) cancelGeneration()
  invalidateReconcile()
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

// 控制台在同源的 /admin/ 下，共用登录 cookie，所以直接开新标签就行——不需要在
// PWA 里再实现一遍那些页面。path 例如 '/stars'、'/room'。
function openConsole(path = '') {
  const base = gatewayUrl.value.trim().replace(/\/$/, '')
  const suffix = path ? `#${path}` : ''
  window.open(`${base}/admin/${suffix}` || `/admin/${suffix}`, '_blank', 'noopener,noreferrer')
}












function dataUrlToBlob(dataUrl: string, mime: string): Blob {
  const payload = dataUrl.slice(dataUrl.indexOf(',') + 1)
  const binary = atob(payload)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index)
  return new Blob([bytes], { type: mime })
}

// 存进 IndexedDB 并算好指纹。落盘失败不该挡住发送——图还在这次会话的内存里，
// 只是刷新后本机不再有它（届时按过期处理，送指纹）。
async function keepPhotoLocally(attachment: Attachment): Promise<Attachment> {
  if (!attachment.dataUrl) return attachment
  try {
    const meta = await putPhoto(attachment.id, dataUrlToBlob(attachment.dataUrl, attachment.mime), attachment.mime)
    void prunePhotos().then((removed) => {
      if (removed.length) forgetExpiredPhotos(removed)
    })
    return { ...attachment, fingerprint: meta.fingerprint }
  } catch {
    return attachment
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

// 本机淘汰掉的图：清掉 dataUrl，气泡改说「图过期了」。指纹留着——过期后正是靠它
// 让网关认出这张图，从而把占位换成沈予存相册时写的那句话（第三批）。
function forgetExpiredPhotos(removedIds: string[]) {
  if (!removedIds.length) return
  const gone = new Set(removedIds)
  for (const message of messages.value) {
    for (const attachment of message.attachments) {
      if (gone.has(attachment.id) && attachment.dataUrl) attachment.dataUrl = undefined
    }
  }
}

// 启动时把本机还留着的图接回气泡。元数据一直在 localStorage，字节按 30 张淘汰，
// 所以「有 attachment 没有 dataUrl」就是「这张图在本机过期了」。
async function restoreLocalPhotos() {
  const wanted = messages.value.flatMap((message) =>
    message.attachments.filter((attachment) => !attachment.dataUrl).map((attachment) => attachment.id))
  if (!wanted.length) return
  try {
    const found = await getPhotos(wanted)
    if (!found.size) return
    for (const message of messages.value) {
      for (const attachment of message.attachments) {
        const stored = found.get(attachment.id)
        // 必须是 data URL 而不是 createObjectURL 的 blob: 地址——后者只在本进程
        // 有效，写进 dataUrl 就会当真图上传，上游取不到（线上 500）。
        if (stored) attachment.dataUrl = photoDataUrl(stored)
      }
    }
  } catch {
    // 本机图取不回来就按过期显示，不影响对话本身。
  }
}

// 回填只在 onMounted 跑一次是不够的：装成 PWA 时 Service Worker 接管会强制刷新
// 页面（main.ts），刷新打断那一次就没有第二次机会，气泡会一直停在「图过期了」。
// 回前台和切会话后各补一次——它本身按 id 幂等，重复跑没有代价。
// 看图器只收还有字节的图：本机已淘汰的那些没有可看的内容。
const viewerPhotos = computed(() => {
  const target = messages.value.find((message) => message.id === photoViewer.value?.messageId)
  return (target?.attachments || []).filter((attachment) => attachment.dataUrl)
})

function openPhotoViewer(message: UiMessage, position: number) {
  const usable = message.attachments.filter((attachment) => attachment.dataUrl)
  // position 是在全部附件里的下标；换算成「可看的那些」里的下标。
  const clicked = message.attachments[position]
  const index = Math.max(0, usable.findIndex((attachment) => attachment.id === clicked?.id))
  if (!usable.length) return
  photoViewer.value = { messageId: message.id, position: index }
}

function scheduleLocalPhotoRestore() {
  void restoreLocalPhotos()
}

async function chooseImages(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  // 一条消息最多 9 张：4 张的堆太薄，看不出是一叠（照片堆那批要用）。
  for (const file of files.slice(0, MESSAGE_IMAGE_LIMIT - pendingAttachments.value.length)) {
    if (!file.type.startsWith('image/')) {
      errorNotice.value = `${file.name} 不是图片，第一版先只收图片。`
      continue
    }
    if (file.size > 12 * 1024 * 1024) {
      errorNotice.value = `${file.name} 太大了，先压到 12MB 以内吧。`
      continue
    }
    pendingAttachments.value.push(await keepPhotoLocally(await resizeImage(file)))
  }
}

function removeAttachment(id: string) {
  pendingAttachments.value = pendingAttachments.value.filter((item) => item.id !== id)
}

function openImagePicker() {
  composerMenuOpen.value = false
  fileRef.value?.click()
}

async function enterRoom() {
  if (busy.value || editId.value) return
  composerMenuOpen.value = false
  const user: UiMessage = {
    id: createId('room-entry'),
    role: 'user',
    content: buildRoomEntry(),
    echo: '',
    echoSegments: [],
    attachments: [],
    thinking: '',
    thinkingSegments: [],
    events: [],
  }
  messages.value.push(user)
  await sendConversation(messages.value)
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
      echo: '',
      echoSegments: [],
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
    const body: Record<string, unknown> = {
      model: selectedModel.value,
      messages: wireMessages(source.filter((message) => message.id !== assistant.id)),
      stream: useStreaming,
      reasoning_effort: effectiveEffort.value,
    }
    const requestHeaders = upstreamHeadersPayload(upstreamHeaders.value)
    if (Object.keys(requestHeaders).length) body.upstream_headers = requestHeaders
    if (claudeCodeHeaderSelected.value) {
      const claudeCodeSessionId = claudeCodeSessionIdFromHeaders(upstreamHeaders.value)
      if (claudeCodeSessionId) body.metadata = claudeCodeMetadata(claudeCodeSessionId)
    }
    if (useStreaming) {
      const stream = await postChatStream(clientContext(), body, activeController.signal)
      // 3 分钟看门狗：Doze/NAT 让 socket 静默死亡时解锁 UI，交给 reconcile 找回。
      const { sawDone } = await pumpSseStream(stream, (frame) => parseSseFrame(frame, assistant), onStreamChunkEnd, 180_000)
      if (!sawDone) {
        assistant.truncated = true
        errorNotice.value = '回复可能被截断，正在尝试找回…'
      }
    } else {
      const completion = await postChatCompletion(clientContext(), body, activeController.signal)
      applyChatCompletion(completion, assistant)
    }
    assistant.streaming = false
    if (!assistant.content && !assistant.echo && !assistant.thinking && !assistant.events.length) {
      assistant.content = '这次没有收到可显示的回应。'
    }
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
    // 静默截断（!sawDone）或看门狗/网络错误后，去服务器找回 drain 落库的全文。
    // 用户主动停止不带 error/truncated，这里自然是无操作。
    if (tailNeedsReconcile(messages.value)) void reconcileTailFromServer()
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
    echo: '',
    echoSegments: [],
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

function showEchoDetail(echo: EchoSegment) {
  if (!processSheet.value) return
  processSheet.value = { ...processSheet.value, view: 'echo', echoKey: echo.id }
}

function showToolDetail(event: ToolEvent) {
  if (!processSheet.value) return
  processSheet.value = { ...processSheet.value, view: 'tool', toolKey: toolEventKey(event) }
}

function backToProcessSummary() {
  if (!processSheet.value) return
  processSheet.value = { ...processSheet.value, view: 'summary', echoKey: undefined, thinkingKey: undefined, toolKey: undefined }
}

function roomReplyLabel(index: number): string {
  const previous = messages.value[index - 1]
  if (!previous || previous.role !== 'user') return ''
  const time = roomEntryTime(previous.content)
  return time ? `${time} · 房间` : ''
}

function assistantMetaLabel(index: number, message: UiMessage): string {
  const parts: string[] = []
  const room = roomReplyLabel(index)
  if (room) parts.push(room)
  const meta = message.responseMeta
  if (!meta) return parts.join(' · ')

  if (typeof meta.context_rounds === 'number') {
    const trim = typeof meta.context_trim_in_rounds === 'number' && meta.context_trim_in_rounds > 0
      ? `（${meta.context_trim_in_rounds}）`
      : ''
    parts.push(`${meta.context_rounds}轮${trim}`)
  }
  if (typeof meta.cache_read_percent === 'number') {
    const percent = Number.isInteger(meta.cache_read_percent) ? meta.cache_read_percent : meta.cache_read_percent.toFixed(1)
    const firstRoundHit = meta.tool_rounds && meta.tool_rounds > 0 && meta.first_tool_round_cache_hit ? '√' : ''
    parts.push(`${percent}%${firstRoundHit}`)
  }
  if (meta.heartbeat_captured) parts.push('❤')
  return parts.join(' · ')
}

function closeComposerMenuFromOutside(event: PointerEvent) {
  const target = event.target
  if (target instanceof Node && !composerMenuRef.value?.contains(target)) {
    composerMenuOpen.value = false
  }
}

function runQuickPrompt(prompt: string) {
  draft.value = prompt
  nextTick(() => {
    resizeInput()
    submit()
  })
}

// 切后台瞬间同步落盘（localStorage 是同步 API，来得及写完）；回前台时找回
// 后台断掉的回复，并顺手核验线上版本（≥5 分钟一次；busy 时跳过——main.ts 的
// controllerchange reload 会杀掉活动流）。
const BUILD_CHECK_INTERVAL_MS = 5 * 60_000
let lastBuildCheckAt = 0

function handleVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    persistMessages()
    return
  }
  // 回前台补一次回填：SW 接管的强制刷新可能打断了 onMounted 那一次。
  scheduleLocalPhotoRestore()
  if (busy.value) return
  if (tailNeedsReconcile(messages.value)) void reconcileTailFromServer()
  const now = Date.now()
  if (now - lastBuildCheckAt >= BUILD_CHECK_INTERVAL_MS) {
    lastBuildCheckAt = now
    void checkPwaBuildInfo()
  }
}

function handlePageHide() {
  persistMessages()
}

onMounted(async () => {
  document.addEventListener('pointerdown', closeComposerMenuFromOutside)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('pagehide', handlePageHide)
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
  // 首屏定位：瞬时跳到底，不走动画。重开 App 期待的是「回到上次看的地方」，
  // 而不是看它从顶部滑下来——那条滑动本身就是圆圆看到的「顶上有进度条」。
  // 在这之前不能依赖 focus 的副作用来滚动：那条链路（focus → 视口变化 →
  // keepComposerVisible → scrollToBottom）时机随设备和键盘设置变化。
  await nextTick()
  jumpToBottom()
  // 首屏那 20 条已经在正确位置了，下一帧再把更早的补进 DOM。
  requestAnimationFrame(() => {
    // 先取样再补齐：更早的消息插在**上方**，DOM 变高之后 scrollTop 不动就意味着
    // 距底距离变大，那时再问 atBottom() 永远是 false。
    const wasAtBottom = atBottom()
    renderTail.value = null
    if (wasAtBottom) nextTick(jumpToBottom)
  })
  // 把本机还留着的图接回气泡；淘汰掉的保持「过期」样子。
  scheduleLocalPhotoRestore()
  // 本地恢复的消息可能停在半截（流式中途进程被杀）：去服务器找回全文。
  if (tailNeedsReconcile(messages.value)) void reconcileTailFromServer()
  nextTick(() => inputRef.value?.focus())
})

onUnmounted(() => {
  activeController?.abort()
  invalidateReconcile()
  clearKeyboardTimers()
  document.removeEventListener('pointerdown', closeComposerMenuFromOutside)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('pagehide', handlePageHide)
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
        <button class="sidebar-nav-item active" type="button" @click="menuOpen = false">
          <svg class="sidebar-nav-icon" viewBox="0 0 256 256" aria-hidden="true"><path d="M232.07,186.76a80,80,0,0,0-62.5-114.17A80,80,0,1,0,23.93,138.76l-7.27,24.71a16,16,0,0,0,19.87,19.87l24.71-7.27a80.39,80.39,0,0,0,25.18,7.35,80,80,0,0,0,108.34,40.65l24.71,7.27a16,16,0,0,0,19.87-19.86ZM62,159.5a8.28,8.28,0,0,0-2.26.32L32,168l8.17-27.76a8,8,0,0,0-.63-6,64,64,0,1,1,26.26,26.26A8,8,0,0,0,62,159.5Zm153.79,28.73L224,216l-27.76-8.17a8,8,0,0,0-6,.63,64.05,64.05,0,0,1-85.87-24.88A79.93,79.93,0,0,0,174.7,89.71a64,64,0,0,1,41.75,92.48A8,8,0,0,0,215.82,188.23Z" /></svg>
          <span>Chats</span>
        </button>
        <button
          v-for="link in consoleLinks"
          :key="link.path"
          class="sidebar-nav-item sidebar-console-link"
          type="button"
          @click="openConsole(link.path)"
        >
          <component :is="link.icon" :size="21" />
          <span>{{ link.label }}</span>
          <ExternalLink class="sidebar-external-icon" :size="15" />
        </button>
        <button class="sidebar-nav-item" type="button" @click="openHandoffSheet">
          <ArrowLeftRight :size="21" />
          <span>接入线程</span>
        </button>
        <button class="sidebar-nav-item sidebar-console-link" type="button" @click="openConsole()">
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
      <button class="sidebar-link" @click="openSettings(); menuOpen = false">
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


      <section ref="streamRef" class="message-stream">
        <div v-if="isEmpty" class="welcome-panel">
          <img class="welcome-mark" :src="brandMarkUrl" alt="Claude" />
          <h1>What's on your mind?</h1>
        </div>

        <template v-for="{ message, index } in visibleMessages" :key="message.id">
          <ChatMessageRow
            v-if="!isRoomEntry(message.content)"
            :message="message"
            :meta-label="assistantMetaLabel(index, message)"
            @open-process="openProcessSheet(message, $event)"
            @copy="copyText"
            @retry="retryMessage(index)"
            @switch-variant="switchMessageVariant(index, $event)"
            @edit="beginEdit(message)"
            @open-photo="openPhotoViewer(message, $event)"
          />
        </template>
      </section>

      <div v-if="status || errorNotice" class="notice-line" :class="{ error: errorNotice }">
        <span>{{ errorNotice || status }}</span>
        <button v-if="errorNotice" aria-label="关闭提示" title="关闭提示" @click="errorNotice = ''"><X :size="15" /></button>
      </div>

      <footer class="composer-wrap">
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
              <div ref="composerMenuRef" class="composer-menu-wrap">
                <button
                  class="composer-icon composer-tool-trigger"
                  :class="{ open: composerMenuOpen }"
                  aria-label="添加"
                  title="添加"
                  aria-haspopup="menu"
                  :aria-expanded="composerMenuOpen"
                  @click="composerMenuOpen = !composerMenuOpen"
                >
                  <Plus :size="20" />
                </button>
                <div v-if="composerMenuOpen" class="composer-tool-menu" role="menu">
                  <button type="button" role="menuitem" @click="openImagePicker">
                    <ImagePlus :size="18" />
                    <span>图片</span>
                  </button>
                  <button type="button" role="menuitem" :disabled="busy || Boolean(editId)" @click="enterRoom">
                    <DoorOpen :size="18" />
                    <span>房间</span>
                  </button>
                </div>
              </div>
              <span class="composer-spacer" />
              <button v-if="busy" class="send-button stop" aria-label="停止生成" title="停止生成" @click="cancelGeneration"><CircleStop :size="19" /></button>
              <button v-else class="send-button" :class="{ ready: hasContent }" :disabled="!hasContent" aria-label="发送" title="发送" @click="submit"><Send :size="18" /></button>
            </div>
          </div>
        </div>
      </footer>
    </main>

    <PhotoViewer
      v-if="photoViewer && viewerPhotos.length"
      :urls="viewerPhotos.map((attachment) => attachment.dataUrl || '')"
      :index="photoViewer.position"
      @close="photoViewer = null"
      @change="(next) => { if (photoViewer) photoViewer.position = next }"
    />

    <div v-if="processSheetMessage" class="sheet-layer" @click.self="closeProcessSheet">
      <section class="bottom-sheet process-sheet" :class="{ 'echo-detail': processSheet?.view === 'echo' }">
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
              <button
                v-for="item in processTimeline(processSheetGroup)"
                :key="item.key"
                class="process-timeline-item"
                :class="{ echo: item.kind === 'echo' }"
                type="button"
                @click="item.kind === 'echo' ? showEchoDetail(item.echo) : item.kind === 'thinking' ? showThinkingDetail(item.thinking) : showToolDetail(item.tool)"
              >
                <span class="process-timeline-rail">
                  <span class="process-timeline-icon"><Clock3 v-if="item.kind === 'thinking'" :size="16" /><Sparkles v-else :size="15" /></span>
                  <span class="process-timeline-line" />
                </span>
                <span class="process-timeline-copy">
                  <strong>{{ item.kind === 'echo' ? '回响' : item.kind === 'thinking' ? 'Thought process' : toolLabel(item.tool) }}</strong>
                  <small>{{ item.kind === 'echo' ? thinkingPreview(item.echo.content) || '留下了一点回响' : item.kind === 'thinking' ? thinkingPreview(item.thinking.content) || '正在整理想法…' : `${toolState(item.tool)} · ${toolResultPreview(item.tool)}` }}</small>
                </span>
                <ChevronRight :size="17" />
              </button>
            </div>
          </template>

          <template v-else-if="processSheet?.view === 'echo'">
            <pre class="process-text echo-text">{{ processSheetEcho?.content }}</pre>
            <div class="process-text-actions">
              <button title="复制" aria-label="复制" @click="copyText(processSheetEcho?.content || '')"><Clipboard :size="15" /></button>
            </div>
          </template>

          <template v-else-if="processSheet?.view === 'thinking'">
            <pre class="process-text">{{ processSheetThinking?.content }}</pre>
            <div class="process-text-actions">
              <button title="复制" aria-label="复制" @click="copyText(processSheetThinking?.content || '')"><Clipboard :size="15" /></button>
            </div>
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
              <button class="model-group-item" @click="openModelSheet('headers')">
                <span class="model-info">
                  <span class="model-name">请求头</span>
                  <span class="model-desc">{{ customHeaderSummary }}</span>
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
              <button class="workspace-action" type="button" @click="openConsole()"><ExternalLink :size="16" /> <span>Open Console</span></button>
            </div>
            <p class="effort-note">Presets use the same Console storage and update the fixed default gateway upstream.</p>
          </template>

          <template v-else-if="modelSheetPage === 'headers'">
            <div class="model-group">
              <button class="model-group-item" :class="{ selected: !hasActiveUpstreamHeaders }" @click="clearUpstreamHeaders">
                <span class="model-info">
                  <span class="model-name">不附加</span>
                  <span class="model-desc">默认网关请求</span>
                </span>
                <Check v-if="!hasActiveUpstreamHeaders" class="model-check" :size="18" />
              </button>
              <button class="model-group-item" :class="{ selected: claudeCodeHeaderSelected }" @click="selectClaudeCodeHeaders">
                <span class="model-info">
                  <span class="model-name">Claude Code</span>
                  <span class="model-desc">{{ CLAUDE_CODE_USER_AGENT }} · 电脑请求</span>
                </span>
                <Check v-if="claudeCodeHeaderSelected" class="model-check" :size="18" />
              </button>
            </div>

            <div v-if="upstreamHeaders.length" class="request-header-list">
              <div v-for="entry in upstreamHeaders" :key="entry.id" class="request-header-row">
                <input v-model="entry.name" class="request-header-input request-header-name" maxlength="256" placeholder="Header" autocomplete="off" spellcheck="false" :aria-label="`请求头名称 ${entry.name || ''}`">
                <input v-model="entry.value" class="request-header-input" maxlength="2048" placeholder="Value" autocomplete="off" spellcheck="false" :aria-label="`请求头 ${entry.name || '未命名'} 的值`">
                <button class="request-header-delete" type="button" aria-label="删除请求头" title="删除请求头" @click="removeUpstreamHeader(entry.id)"><Trash2 :size="17" /></button>
              </div>
            </div>

            <button class="request-header-add" type="button" :disabled="upstreamHeaders.length >= 20" @click="addUpstreamHeader">
              <Plus :size="17" />
              <span>添加请求头</span>
            </button>
            <button v-if="claudeCodeHeaderSelected" class="request-header-refresh" type="button" @click="refreshClaudeCodeHeaders">
              <RotateCcw :size="16" />
              <span>刷新会话 UUID</span>
            </button>
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
        <div class="build-proof" :class="`build-proof-${pwaBuildCheck}`" aria-live="polite">
          <div><span>当前运行</span><code>{{ activePwaBuildInfo.buildId }}</code></div>
          <div><span>线上已部署</span><code>{{ deployedPwaBuildInfo?.buildId || pwaBuildStatus }}</code></div>
          <button class="icon-button build-proof-refresh" :disabled="pwaBuildCheck === 'checking'" aria-label="重新核验线上版本" title="重新核验线上版本" @click="checkPwaBuildInfo"><RotateCcw :size="16" /></button>
        </div>
        <div class="settings-actions"><button class="quiet-button" @click="newChat"><Trash2 :size="16" /> 清空当前对话</button><button class="primary-button" @click="saveSettings"><Check :size="16" /> 收好设置</button></div>
      </section>
    </div>
  </div>
</template>
