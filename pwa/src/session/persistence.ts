import type { ToolEvent } from '../toolLanguage'
import type { MessageVariant, ResponseMeta, Role, ThinkingSegment, UiMessage } from '../types'
import { createId } from '../utils'
import { applyVariant, cloneVariant, selectedVariantIndex, syncCurrentVariant } from './variants'

export const STORAGE_MESSAGES = 'shenyu_pwa_messages'
export const STORAGE_SESSION = 'shenyu_pwa_session'
export const FALLBACK_SESSION_MESSAGE_LIMIT = 75

// 配额告急时先把工具输出截到这个长度再重试落盘。
const EVENT_OUTPUT_PERSIST_LIMIT = 2000

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
        const message: UiMessage = {
          id: String(item.id || createId('message')),
          role: item.role as Role,
          content: String(item.content || ''),
          attachments: [],
          thinking: String(item.thinking || ''),
          thinkingSegments: storedSegments.length
            ? storedSegments
            : item.thinking
              ? [{ id: createId('thinking'), content: String(item.thinking), textOffset: 0, streamOrder: 0 }]
              : [],
          events: cloneStoredEvents(item.events),
          streaming: false,
          error: item.error ? String(item.error) : undefined,
          responseMeta: cloneStoredResponseMeta(item.responseMeta),
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
          applyVariant(message, variants[message.selectedVariantIndex], message.selectedVariantIndex)
        }
        return message
      })
  } catch {
    return []
  }
}

type StoredRow = {
  id: string
  role: Role
  content: string
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  error?: string
  variants?: MessageVariant[]
  selectedVariantIndex?: number
  responseMeta?: ResponseMeta
}

function mapRowEvents(row: StoredRow, mapper: (events: ToolEvent[]) => ToolEvent[]): StoredRow {
  return {
    ...row,
    events: mapper(row.events),
    variants: row.variants?.map((variant) => ({ ...variant, events: mapper(variant.events || []) })),
  }
}

function truncateEventOutputs(events: ToolEvent[]): ToolEvent[] {
  return events.map((event) => (
    typeof event.output === 'string' && event.output.length > EVENT_OUTPUT_PERSIST_LIMIT
      ? { ...event, output: event.output.slice(0, EVENT_OUTPUT_PERSIST_LIMIT) }
      : event
  ))
}

export function persistStoredMessages(messages: UiMessage[], sessionMessageLimit: number) {
  messages.forEach(syncCurrentVariant)
  const safe: StoredRow[] = messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    thinking: message.thinking,
    thinkingSegments: message.thinkingSegments,
    events: message.events,
    error: message.error,
    variants: message.variants,
    selectedVariantIndex: message.selectedVariantIndex,
    responseMeta: message.responseMeta,
  }))
  // Keep a little more than the gateway high-water window so a resident PWA
  // can stop relying on a temporary cold-start handoff.
  const storageLimit = Math.max(240, sessionMessageLimit + 72)
  const windowRows = safe.slice(-storageLimit)
  // 落盘失败绝不打断 UI：配额爆时逐级降级——截短工具输出 → 丢弃工具事件 → 放弃。
  const attempts: Array<() => StoredRow[]> = [
    () => windowRows,
    () => windowRows.map((row) => mapRowEvents(row, truncateEventOutputs)),
    () => windowRows.map((row) => mapRowEvents(row, () => [])),
  ]
  for (const build of attempts) {
    try {
      localStorage.setItem(STORAGE_MESSAGES, JSON.stringify(build()))
      return
    } catch {
      // 换下一级瘦身方案重试。
    }
  }
  console.warn('persistStoredMessages: localStorage 配额不足，这一轮消息没有落盘')
}
