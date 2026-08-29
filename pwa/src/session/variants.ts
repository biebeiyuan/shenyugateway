import { clampErrorText } from '../api/errors'
import type { MessageVariant, UiMessage } from '../types'
import { createId } from '../utils'

export function cloneVariant(variant: Partial<MessageVariant>): MessageVariant {
  return {
    content: String(variant.content || ''),
    echo: String(variant.echo || ''),
    echoSegments: Array.isArray(variant.echoSegments)
      ? variant.echoSegments.map((item) => ({
          id: String(item?.id || createId('echo')),
          content: String(item?.content || ''),
          textOffset: Number(item?.textOffset || 0),
          streamOrder: Number(item?.streamOrder || 0),
        }))
      : [],
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
    // roll variant 也带 error，而它会原样落盘；这里是所有 variant 错误的唯一漏斗。
    error: variant.error ? clampErrorText(String(variant.error)) : undefined,
    responseMeta: variant.responseMeta && typeof variant.responseMeta === 'object'
      ? { ...variant.responseMeta }
      : undefined,
  }
}

export function snapshotMessage(message: UiMessage): MessageVariant {
  return cloneVariant(message)
}

export function selectedVariantIndex(message: UiMessage): number {
  const count = message.variants?.length || 1
  return Math.max(0, Math.min(Number(message.selectedVariantIndex || 0), count - 1))
}

export function variantCount(message: UiMessage): number {
  return message.variants?.length || 1
}

export function syncCurrentVariant(message: UiMessage) {
  if (message.role !== 'assistant' || !message.variants?.length) return
  const index = selectedVariantIndex(message)
  message.selectedVariantIndex = index
  message.variants[index] = snapshotMessage(message)
}

export function applyVariant(message: UiMessage, variant: MessageVariant, index: number) {
  const normalized = cloneVariant(variant)
  message.selectedVariantIndex = index
  message.content = normalized.content
  message.echo = normalized.echo
  message.echoSegments = normalized.echoSegments.map((item) => ({ ...item }))
  message.thinking = normalized.thinking
  message.thinkingSegments = normalized.thinkingSegments.map((item) => ({ ...item }))
  message.events = normalized.events.map((item) => ({ ...item }))
  message.error = normalized.error
  message.responseMeta = normalized.responseMeta ? { ...normalized.responseMeta } : undefined
}

export function emptyVariant(): MessageVariant {
  return { content: '', echo: '', echoSegments: [], thinking: '', thinkingSegments: [], events: [], responseMeta: undefined }
}

export function ensureVariants(message: UiMessage): MessageVariant[] {
  if (!message.variants?.length) {
    message.variants = [snapshotMessage(message)]
    message.selectedVariantIndex = 0
  } else {
    message.selectedVariantIndex = selectedVariantIndex(message)
    syncCurrentVariant(message)
  }
  return message.variants
}

export function canSwitchMessageVariant(message: UiMessage, direction: -1 | 1): boolean {
  const count = variantCount(message)
  const current = selectedVariantIndex(message)
  return count > 1 && current + direction >= 0 && current + direction < count
}
