import { describe, expect, it } from 'vitest'
import { mergeSessionHistory } from '../src/session/restore'
import type { UiMessage } from '../src/types'
const at = '2026-09-19T01:00:00Z'
function message(role: 'user' | 'assistant', id: string, content = id): UiMessage {
  return { id, role, content, echo: '', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [],
    archiveEvent: { id, event_at: at }, ...(role === 'assistant' ? { replyVersionId: id } : {}) }
}
function payload(messages: UiMessage[], recent: unknown[] = []) {
  return { context_snapshots: [{ messages: messages.map(m => ({ role: m.role, content: m.content, archive_event: m.archiveEvent })) }], recent_messages: recent }
}
describe('non-destructive session opening', () => {
  it('does not replace a rich selected variant with a thin snapshot', () => {
    const user = message('user', 'u'), reply = message('assistant', 'r')
    reply.thinking = 'received thinking'
    reply.thinkingSegments = [{ id: 't', content: reply.thinking, textOffset: 0, streamOrder: 1 }]
    reply.events = [{ phase: 'tool_end', tool_call_id: 'c', name: 'shenyu_recall', ok: true, text_offset: 1, stream_order: 2 }]
    reply.responseMeta = { context_rounds: 3 }
    reply.variants = [{ ...reply }]
    const restored = mergeSessionHistory([user, reply], payload([user, reply]))
    expect(restored[1].thinking).toBe('received thinking')
    expect(restored[1].events).toEqual(reply.events)
    expect(restored[1].variants?.[0].events).toEqual(reply.events)
    expect(restored[1].responseMeta?.context_rounds).toBe(3)
  })
  it('keeps local history outside the shorter server window', () => {
    const history = [message('user', 'u0'), message('assistant', 'r0'), message('user', 'u1'), message('assistant', 'r1')]
    expect(mergeSessionHistory(history, payload(history.slice(2))).map(m => m.id)).toEqual(history.map(m => m.id))
  })
  it('does not erase a draft reply when the server window is empty or older', () => {
    const history = [message('user', 'u'), message('assistant', 'r', 'half')]
    history[1].truncated = true
    expect(mergeSessionHistory(history, {})).toEqual(history)
    expect(mergeSessionHistory(history, payload([message('user', 'old')]))).toEqual(history)
  })
  it('appends only a provably continuous server suffix', () => {
    const history = [message('user', 'u0'), message('assistant', 'r0')]
    const added = [message('user', 'u1'), message('assistant', 'r1')]
    expect(mergeSessionHistory(history, payload([...history, ...added])).map(m => m.archiveEvent?.id)).toEqual(['u0','r0','u1','r1'])
  })
  it('never merges equal text across different identified replies', () => {
    const local = message('assistant', 'local', '好了')
    local.thinking = 'only local'
    const result = mergeSessionHistory([local], payload([message('assistant', 'other', '好了')]))
    expect(result).toHaveLength(1)
    expect(result[0].archiveEvent?.id).toBe('local')
    expect(result[0].thinking).toBe('only local')
  })
  it('does not use a same-id server prefix to shorten the local reply', () => {
    const local = message('assistant', 'r', '完整的回复')
    expect(mergeSessionHistory([local], payload([message('assistant', 'r', '完整')]))[0].content).toBe('完整的回复')
  })
})
