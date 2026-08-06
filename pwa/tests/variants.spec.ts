import { describe, expect, it } from 'vitest'
import {
  applyVariant,
  canSwitchMessageVariant,
  cloneVariant,
  emptyVariant,
  ensureVariants,
  selectedVariantIndex,
  syncCurrentVariant,
  variantCount,
} from '../src/session/variants'
import type { UiMessage } from '../src/types'

function assistant(content: string): UiMessage {
  return { id: 'assistant-1', role: 'assistant', content, attachments: [], thinking: '', thinkingSegments: [], events: [] }
}

describe('cloneVariant', () => {
  it('fills defaults for missing fields', () => {
    expect(cloneVariant({})).toEqual({ content: '', thinking: '', thinkingSegments: [], events: [], error: undefined })
  })

  it('deep-copies segments and events', () => {
    const source = {
      content: 'text',
      thinking: 'thought',
      thinkingSegments: [{ id: 's1', content: 'seg', textOffset: 3, streamOrder: 1 }],
      events: [{ phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall' }],
    }
    const clone = cloneVariant(source)
    expect(clone.thinkingSegments).toEqual(source.thinkingSegments)
    expect(clone.thinkingSegments[0]).not.toBe(source.thinkingSegments[0])
    expect(clone.events[0]).not.toBe(source.events[0])
  })
})

describe('variant selection', () => {
  it('treats a message without variants as a single variant', () => {
    const message = assistant('only')
    expect(variantCount(message)).toBe(1)
    expect(selectedVariantIndex(message)).toBe(0)
  })

  it('clamps out-of-range selected indexes', () => {
    const message = assistant('current')
    message.variants = [emptyVariant(), emptyVariant()]
    message.selectedVariantIndex = 9
    expect(selectedVariantIndex(message)).toBe(1)
    message.selectedVariantIndex = -3
    expect(selectedVariantIndex(message)).toBe(0)
  })
})

describe('ensureVariants and syncCurrentVariant', () => {
  it('snapshots the live message as the first variant', () => {
    const message = assistant('first answer')
    const variants = ensureVariants(message)
    expect(variants).toHaveLength(1)
    expect(variants[0].content).toBe('first answer')
    expect(message.selectedVariantIndex).toBe(0)
  })

  it('writes live edits back into the selected variant', () => {
    const message = assistant('v1')
    ensureVariants(message)
    message.content = 'v1 updated'
    syncCurrentVariant(message)
    expect(message.variants?.[0].content).toBe('v1 updated')
  })

  it('does not touch user messages', () => {
    const message: UiMessage = { ...assistant('user text'), role: 'user' }
    message.variants = [emptyVariant()]
    message.content = 'changed'
    syncCurrentVariant(message)
    expect(message.variants[0].content).toBe('')
  })
})

describe('applyVariant and switching bounds', () => {
  it('replaces live fields with the chosen variant copy', () => {
    const message = assistant('old')
    const variant = {
      content: 'new',
      thinking: 'why',
      thinkingSegments: [{ id: 's', content: 'seg', textOffset: 0, streamOrder: 0 }],
      events: [],
      responseMeta: { context_rounds: 7, heartbeat_captured: true },
    }
    applyVariant(message, variant, 1)
    expect(message.content).toBe('new')
    expect(message.selectedVariantIndex).toBe(1)
    expect(message.thinkingSegments[0]).not.toBe(variant.thinkingSegments[0])
    expect(message.responseMeta).toEqual({ context_rounds: 7, heartbeat_captured: true })
  })

  it('allows switching only inside the variant list', () => {
    const message = assistant('roll')
    message.variants = [emptyVariant(), emptyVariant()]
    message.selectedVariantIndex = 0
    expect(canSwitchMessageVariant(message, 1)).toBe(true)
    expect(canSwitchMessageVariant(message, -1)).toBe(false)
    message.selectedVariantIndex = 1
    expect(canSwitchMessageVariant(message, 1)).toBe(false)
    expect(canSwitchMessageVariant(message, -1)).toBe(true)
    expect(canSwitchMessageVariant(assistant('single'), 1)).toBe(false)
  })
})
