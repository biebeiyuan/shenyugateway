import type { MessageVariant, Role, UiMessage } from '../types'
import { createId } from '../utils'
import { applyVariant, cloneVariant, selectedVariantIndex, syncCurrentVariant } from './variants'

export const STORAGE_MESSAGES = 'shenyu_pwa_messages'
export const STORAGE_SESSION = 'shenyu_pwa_session'
export const FALLBACK_SESSION_MESSAGE_LIMIT = 75

export function loadStoredMessages(): UiMessage[] {
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

export function persistStoredMessages(messages: UiMessage[], sessionMessageLimit: number) {
  messages.forEach(syncCurrentVariant)
  const safe = messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    thinking: message.thinking,
    error: message.error,
    variants: message.variants,
    selectedVariantIndex: message.selectedVariantIndex,
  }))
  // Keep a little more than the gateway high-water window so a resident PWA
  // can stop relying on a temporary cold-start handoff.
  const storageLimit = Math.max(240, sessionMessageLimit + 72)
  localStorage.setItem(STORAGE_MESSAGES, JSON.stringify(safe.slice(-storageLimit)))
}
