import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

  it('restores roll variants and lands on the previously selected roll', () => {
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
    expect(restored.selectedVariantIndex).toBe(1)
    expect(restored.content).toBe('current')
  })

  it('clamps a corrupted stored index and defaults legacy rows to the first roll', () => {
    localStorage.setItem(STORAGE_MESSAGES, JSON.stringify([
      {
        id: 'a1', role: 'assistant', content: 'x',
        variants: [{ content: 'v0' }, { content: 'v1' }],
        selectedVariantIndex: 9,
      },
      {
        id: 'a2', role: 'assistant', content: 'y',
        variants: [{ content: 'w0' }, { content: 'w1' }],
      },
    ]))
    const [clamped, legacy] = loadStoredMessages()
    expect(clamped.selectedVariantIndex).toBe(1)
    expect(clamped.content).toBe('v1')
    expect(legacy.selectedVariantIndex).toBe(0)
    expect(legacy.content).toBe('w0')
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

describe('tool event persistence', () => {
  it('round-trips events and thinking segments with their offsets', () => {
    const message = uiMessage('assistant', 'answer', {
      thinking: 'deep',
      thinkingSegments: [{ id: 't1', content: 'deep', textOffset: 4, streamOrder: 2 }],
      events: [
        { phase: 'tool_start', tool_call_id: 'c1', name: 'shenyu_recall', input: { query: 'x' }, text_offset: 3, stream_order: 0 },
        { phase: 'tool_end', tool_call_id: 'c1', name: 'shenyu_recall', ok: true, output: 'found it', text_offset: 3, stream_order: 1 },
      ],
    })
    persistStoredMessages([message], FALLBACK_SESSION_MESSAGE_LIMIT)
    const [restored] = loadStoredMessages()
    expect(restored.events).toHaveLength(2)
    expect(restored.events[0].input).toEqual({ query: 'x' })
    expect(restored.events[1].output).toBe('found it')
    expect(restored.events[1].ok).toBe(true)
    expect(restored.thinkingSegments).toEqual([{ id: 't1', content: 'deep', textOffset: 4, streamOrder: 2 }])
  })

  it('keeps legacy rows without events readable', () => {
    localStorage.setItem(STORAGE_MESSAGES, JSON.stringify([{ id: 'a1', role: 'assistant', content: 'old', thinking: 'why' }]))
    const [restored] = loadStoredMessages()
    expect(restored.events).toEqual([])
    expect(restored.thinkingSegments).toHaveLength(1)
    expect(restored.thinkingSegments[0].content).toBe('why')
  })
})

describe('quota degradation', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  // happy-dom's localStorage does not dispatch through Storage.prototype, so the
  // quota is simulated with a stubbed global storage instead of a method spy.
  function withQuotaLimit(maxLength: number): () => number {
    const store = new Map<string, string>()
    let rejected = 0
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
      setItem: (key: string, value: string) => {
        if (value.length > maxLength) {
          rejected++
          throw new DOMException('quota', 'QuotaExceededError')
        }
        store.set(key, value)
      },
      removeItem: (key: string) => { store.delete(key) },
      clear: () => { store.clear() },
    })
    return () => rejected
  }

  it('truncates long event outputs when the first write overflows', () => {
    const rejectedCount = withQuotaLimit(30000)
    const message = uiMessage('assistant', 'a', {
      events: [
        { phase: 'tool_start', tool_call_id: 'c1', name: 'shenyu_recall', input: {} },
        { phase: 'tool_end', tool_call_id: 'c1', name: 'shenyu_recall', ok: true, output: 'x'.repeat(60000) },
      ],
    })
    expect(() => persistStoredMessages([message], FALLBACK_SESSION_MESSAGE_LIMIT)).not.toThrow()
    expect(rejectedCount()).toBe(1)
    const [restored] = loadStoredMessages()
    expect(restored.events).toHaveLength(2)
    expect(restored.events[1].output).toHaveLength(2000)
  })

  it('drops events entirely when truncation still overflows', () => {
    const rejectedCount = withQuotaLimit(300)
    const message = uiMessage('assistant', 'kept content', {
      events: [
        { phase: 'tool_start', tool_call_id: 'c1', name: 'shenyu_recall', input: {} },
        { phase: 'tool_end', tool_call_id: 'c1', name: 'shenyu_recall', ok: true, output: 'x'.repeat(60000) },
      ],
    })
    expect(() => persistStoredMessages([message], FALLBACK_SESSION_MESSAGE_LIMIT)).not.toThrow()
    expect(rejectedCount()).toBe(2)
    const [restored] = loadStoredMessages()
    expect(restored.content).toBe('kept content')
    expect(restored.events).toEqual([])
  })

  it('gives up quietly when storage keeps overflowing', () => {
    withQuotaLimit(0)
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(() => persistStoredMessages([uiMessage('user', 'hello')], FALLBACK_SESSION_MESSAGE_LIMIT)).not.toThrow()
    expect(warn).toHaveBeenCalledOnce()
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
