import type { MessageVariant, UiMessage } from '../types'
import { createId } from '../utils'

export function cloneVariant(variant: Partial<MessageVariant>): MessageVariant {
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
  message.selectedVariantIndex = index
  message.content = variant.content
  message.thinking = variant.thinking
  message.thinkingSegments = variant.thinkingSegments.map((item) => ({ ...item }))
  message.events = variant.events.map((item) => ({ ...item }))
  message.error = variant.error
}

export function emptyVariant(): MessageVariant {
  return { content: '', thinking: '', thinkingSegments: [], events: [] }
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
