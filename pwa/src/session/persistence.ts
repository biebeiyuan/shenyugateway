import { storedAttachments } from './media'
import type { ToolEvent } from '../toolLanguage'
import { clampErrorText } from '../api/errors'
import type { ArchiveEvent, Attachment, EchoSegment, MessageVariant, ResponseMeta, Role, ThinkingSegment, UiMessage } from '../types'
import { createId } from '../utils'
import { readArchiveEvent } from './history'
import { applyVariant, cloneVariant, selectedVariantIndex, syncCurrentVariant } from './variants'

export const STORAGE_MESSAGES = 'shenyu_pwa_messages'
export const STORAGE_SESSION = 'shenyu_pwa_session'
export const FALLBACK_SESSION_MESSAGE_LIMIT = 75

function cloneStoredEvents(value: unknown): ToolEvent[] {
  return Array.isArray(value)
    ? value
        .filter((item): item is ToolEvent => Boolean(item && typeof item === 'object'))
        .map((item) => ({ ...item }))
    : []
}

function cloneStoredThinkingSegments(value: unknown): ThinkingSegment[] {
  return Array.isArray(value)
    ? value
        .filter((item): item is Partial<ThinkingSegment> => Boolean(item && typeof item === 'object'))
        .map((item) => ({
          id: String(item.id || createId('thinking')),
          content: String(item.content || ''),
          textOffset: Number(item.textOffset || 0),
          streamOrder: Number(item.streamOrder || 0),
        }))
    : []
}

// 附件只落元数据，绝不落 dataUrl：base64 图片进 localStorage 就是当初
// 「附件干脆不存」的原因（一张约 560KB，5MB 配额装九张）。字节在 IndexedDB。
function cloneStoredAttachments(value: unknown): Attachment[] {
  return storedAttachments(value)
}

function cloneStoredEchoSegments(value: unknown): EchoSegment[] {
  return Array.isArray(value)
    ? value
        .filter((item): item is Partial<EchoSegment> => Boolean(item && typeof item === 'object'))
        .map((item) => ({
          id: String(item.id || createId('echo')),
          content: String(item.content || ''),
          textOffset: Number(item.textOffset || 0),
          streamOrder: Number(item.streamOrder || 0),
        }))
    : []
}

function cloneStoredResponseMeta(value: unknown): ResponseMeta | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const raw = value as Record<string, unknown>
  return {
    context_rounds: Number.isFinite(Number(raw.context_rounds)) ? Number(raw.context_rounds) : undefined,
    context_trim_in_rounds: raw.context_trim_in_rounds === null
      ? null
      : Number.isFinite(Number(raw.context_trim_in_rounds)) ? Number(raw.context_trim_in_rounds) : undefined,
    cache_read_percent: raw.cache_read_percent === null
      ? null
      : Number.isFinite(Number(raw.cache_read_percent)) ? Number(raw.cache_read_percent) : undefined,
    cache_read_input_tokens: Number.isFinite(Number(raw.cache_read_input_tokens)) ? Number(raw.cache_read_input_tokens) : undefined,
    cache_total_input_tokens: Number.isFinite(Number(raw.cache_total_input_tokens)) ? Number(raw.cache_total_input_tokens) : undefined,
    tool_rounds: Number.isFinite(Number(raw.tool_rounds)) ? Number(raw.tool_rounds) : undefined,
    first_tool_round_cache_hit: raw.first_tool_round_cache_hit === true,
    heartbeat_captured: raw.heartbeat_captured === true,
  }
}

export function loadStoredMessages(): UiMessage[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_MESSAGES) || '[]')
    if (!Array.isArray(raw)) return []
    return raw.filter((item) => item && (item.role === 'user' || item.role === 'assistant'))
      .map((item) => {
        const storedSegments = cloneStoredThinkingSegments(item.thinkingSegments)
        const storedEchoSegments = cloneStoredEchoSegments(item.echoSegments)
        const message: UiMessage = {
          id: String(item.id || createId('message')),
          role: item.role as Role,
          content: String(item.content || ''),
          echo: String(item.echo || ''),
          echoSegments: storedEchoSegments.length
            ? storedEchoSegments
            : item.echo
              ? [{ id: createId('echo'), content: String(item.echo), textOffset: 0, streamOrder: 0 }]
              : [],
          // 附件元数据（id / 指纹 / 名字）一直落盘，图片字节在 IndexedDB。
          // dataUrl 留空，由 App 启动时按 id 回填本机还留着的那些——这就是
          // 「本机最近 30 张」的实现方式：元数据一直在，图会过期。
          attachments: cloneStoredAttachments(item.attachments),
          thinking: String(item.thinking || ''),
          thinkingSegments: storedSegments.length
            ? storedSegments
            : item.thinking
              ? [{ id: createId('thinking'), content: String(item.thinking), textOffset: 0, streamOrder: 0 }]
              : [],
          events: cloneStoredEvents(item.events),
          streaming: false,
          // 读回也截断：早于错误护栏落盘的那条整页 HTML 还躺在 localStorage 里，
          // 每次重开都会重新顶飞界面。截在读回这一步，旧记录自己就好了。
          error: item.error ? clampErrorText(String(item.error)) : undefined,
          truncated: item.truncated === true ? true : undefined,
          responseMeta: cloneStoredResponseMeta(item.responseMeta),
          archiveEvent: readArchiveEvent(item.archiveEvent),
          archiveReplay: item.archiveReplay === true || undefined,
          replyVersionId: item.replyVersionId ? String(item.replyVersionId) : undefined,
        }
        if (message.role === 'assistant' && Array.isArray(item.variants) && item.variants.length) {
          const variants = item.variants.map((variant: Partial<MessageVariant>) => cloneVariant(variant))
          message.variants = variants
          const storedIndex = Number(item.selectedVariantIndex)
          message.selectedVariantIndex = selectedVariantIndex({
            ...message,
            variants,
            selectedVariantIndex: Number.isFinite(storedIndex) ? storedIndex : 0,
          })
          const selected = variants[message.selectedVariantIndex]
          applyVariant(message, selected, message.selectedVariantIndex)
          if (selected.truncated === undefined && item.truncated === true) message.truncated = true
        }
        return message
      })
  } catch {
    return []
  }
}

type StoredRow = {
  archiveReplay?: boolean
  archiveEvent?: ArchiveEvent
  id: string
  role: Role
  content: string
  echo: string
  echoSegments: EchoSegment[]
  // 只有元数据，没有 dataUrl。
  attachments: Attachment[]
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  error?: string
  truncated?: boolean
  variants?: MessageVariant[]
  selectedVariantIndex?: number
  responseMeta?: ResponseMeta
  replyVersionId?: string
}

// 落盘是「从 UiMessage 重建一行」，所以任何本版本不认识的字段都会在重建时消失。
// 装成 PWA 时这不是理论问题：Service Worker 先用缓存里的旧包把界面画出来，旧包
// 落一次盘就把新包写的字段抹掉了，等新包刷新上来已经晚了。2026-08-30 圆圆手机上
// 的图就是这样丢的（旧包连 attachments 都不写）。
//
// 所以按 id 保留上一次落盘里的未知字段。这不是通用的「向前兼容」承诺——只是让
// 一个旧包最多做到「不更新」，而不是「擦掉」。
const KNOWN_ROW_KEYS = new Set([
  'id', 'role', 'content', 'echo', 'echoSegments', 'attachments', 'thinking',
  'thinkingSegments', 'events', 'error', 'truncated', 'variants',
  'selectedVariantIndex', 'responseMeta', 'replyVersionId', 'archiveEvent', 'archiveReplay',
])

function unknownFieldsById(): Map<string, Record<string, unknown>> {
  const carried = new Map<string, Record<string, unknown>>()
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_MESSAGES) || '[]')
    if (!Array.isArray(raw)) return carried
    for (const row of raw) {
      if (!row || typeof row !== 'object' || !row.id) continue
      const extras: Record<string, unknown> = {}
      for (const [key, value] of Object.entries(row)) {
        if (!KNOWN_ROW_KEYS.has(key)) extras[key] = value
      }
      if (Object.keys(extras).length) carried.set(String(row.id), extras)
    }
  } catch {
    // 读不出来就当没有可保留的字段。
  }
  return carried
}

export function persistStoredMessages(messages: UiMessage[], sessionMessageLimit: number) {
  messages.forEach(syncCurrentVariant)
  const carried = unknownFieldsById()
  const safe: StoredRow[] = messages.map((message) => ({
    ...carried.get(message.id),
    id: message.id,
    role: message.role,
    content: message.content,
    echo: message.echo || '',
    echoSegments: message.echoSegments || [],
    // dataUrl 刻意剥掉：base64 图片进 localStorage 正是当初「附件干脆不存」的
    // 原因。字节在 IndexedDB，这里只留够回填和过期上传用的元数据。
    attachments: storedAttachments(message.attachments),
    thinking: message.thinking,
    thinkingSegments: message.thinkingSegments,
    events: message.events,
    error: message.error ? clampErrorText(message.error) : undefined,
    // streaming 态只在流式中途落盘（节流/pagehide）时出现；正常收尾会先清掉
    // streaming 再落盘。它留在存储里就意味着进程死在了流中间——按截断标记，
    // 重启后 reconcile 会去服务器找回全文。
    truncated: message.truncated || message.streaming || undefined,
    variants: message.variants?.map(cloneVariant),
    selectedVariantIndex: message.selectedVariantIndex,
    responseMeta: message.responseMeta,
    replyVersionId: message.replyVersionId,
    archiveEvent: readArchiveEvent(message.archiveEvent),
    archiveReplay: message.archiveReplay === true || undefined,
  }))
  // Keep a little more than the gateway high-water window so a resident PWA
  // can stop relying on a temporary cold-start handoff.
  const storageLimit = Math.max(240, sessionMessageLimit + 72)
  const windowRows = safe.slice(-storageLimit)
  // A failed full write leaves the previous committed record untouched.
  // Rich process history is not disposable data: never trim outputs or erase events.
  try {
    localStorage.setItem(STORAGE_MESSAGES, JSON.stringify(windowRows))
    return true
  } catch {
    // The caller receives an explicit unsuccessful save, not a thinner success.
  }
  console.warn('persistStoredMessages: 本机保存失败，上一份记录已保留')
  return false
}
