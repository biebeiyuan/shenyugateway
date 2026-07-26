import { beforeEach, describe, expect, it } from 'vitest'
import { FALLBACK_SESSION_MESSAGE_LIMIT, STORAGE_MESSAGES, loadStoredMessages, persistStoredMessages } from '../src/session/persistence'
import type { UiMessage } from '../src/types'

function uiMessage(role: 'user' | 'assistant', content: string, extra: Partial<UiMessage> = {}): UiMessage {
  return { id: `id-${content}`, role, content, attachments: [], thinking: '', thinkingSegments: [], events: [], ...extra }
}

beforeEach(() => {
  localStorage.clear()
})

describe('message persistence round-trip', () => {
  it('restores role, content, thinking and error', () => {
    persistStoredMessages([
      uiMessage('user', 'question'),
      uiMessage('assistant', 'answer', { thinking: 'why', error: 'boom' }),
    ], FALLBACK_SESSION_MESSAGE_LIMIT)
    const restored = loadStoredMessages()
    expect(restored).toHaveLength(2)
    expect(restored[1].thinking).toBe('why')
    expect(restored[1].error).toBe('boom')
    expect(restored[1].thinkingSegments).toHaveLength(1)
  })

  it('restores roll variants; the stored selected index is currently ignored', () => {
    // Known pre-existing quirk: persistStoredMessages saves selectedVariantIndex,
    // but loadStoredMessages never reads it back, so a reload always lands on the
    // first roll. If that gets fixed, update these last two expectations to 1 /
    // 'current'.
    const message = uiMessage('assistant', 'current', {
      variants: [
        { content: 'first roll', thinking: '', thinkingSegments: [], events: [] },
        { content: 'current', thinking: '', thinkingSegments: [], events: [] },
      ],
      selectedVariantIndex: 1,
    })
    persistStoredMessages([message], FALLBACK_SESSION_MESSAGE_LIMIT)
    const [restored] = loadStoredMessages()
    expect(restored.variants).toHaveLength(2)
    expect(restored.selectedVariantIndex).toBe(0)
    expect(restored.content).toBe('first roll')
  })

  it('syncs live edits into the selected variant before saving', () => {
    const message = uiMessage('assistant', 'edited live', {
      variants: [{ content: 'stale copy', thinking: '', thinkingSegments: [], events: [] }],
      selectedVariantIndex: 0,
    })
    persistStoredMessages([message], FALLBACK_SESSION_MESSAGE_LIMIT)
    const [restored] = loadStoredMessages()
    expect(restored.variants?.[0].content).toBe('edited live')
  })

  it('drops rows with unknown roles and survives corrupted storage', () => {
    localStorage.setItem(STORAGE_MESSAGES, JSON.stringify([{ role: 'system', content: 'x' }, { role: 'user', content: 'keep' }]))
    expect(loadStoredMessages().map((message) => message.content)).toEqual(['keep'])
    localStorage.setItem(STORAGE_MESSAGES, 'not json')
    expect(loadStoredMessages()).toEqual([])
  })
})

describe('storage window limit', () => {
  it('keeps a margin above the gateway window and trims the oldest rows', () => {
    const many = Array.from({ length: 400 }, (_, index) => uiMessage('user', `m${index}`))
    persistStoredMessages(many, FALLBACK_SESSION_MESSAGE_LIMIT)
    const restored = loadStoredMessages()
    expect(restored).toHaveLength(240)
    expect(restored[0].content).toBe('m160')
    expect(restored[restored.length - 1].content).toBe('m399')
  })

  it('scales the stored window with a larger gateway limit', () => {
    const many = Array.from({ length: 400 }, (_, index) => uiMessage('user', `m${index}`))
    persistStoredMessages(many, 300)
    expect(loadStoredMessages()).toHaveLength(372)
  })
})
