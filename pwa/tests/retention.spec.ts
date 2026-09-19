import { afterEach, describe, expect, it, vi } from 'vitest'
import { hydrateToolEvents } from '../src/session/toolHydration'
import { applyReplyRecovery } from '../src/session/reconcile'
import { persistStoredMessages, STORAGE_MESSAGES } from '../src/session/persistence'
import type { UiMessage } from '../src/types'

const eventAt = '2026-09-19T01:00:00Z'
function message(role: 'user' | 'assistant', content: string, id: string): UiMessage {
  return { id, role, content, echo: '', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [],
    archiveEvent: { id, event_at: eventAt }, ...(role === 'assistant' ? { replyVersionId: id } : {}) }
}
function tool(id: string, reply: string) {
  return { id: `row-${id}`, role: 'tool', reply_version_id: reply, tool_call_id: id,
    tool_name: 'shenyu_recall', tool_args_json: '{"query":"test"}', content: '{"ok":true,"data":"found"}', tool_ok: true }
}
function recovery(content: string, rows: unknown[] = [tool('call-a', 'reply-a')]) {
  return { session_tag: 'test', user_content: 'question', replies: [{ reply_version_id: 'reply-a',
    archive_event: { id: 'reply-a', event_at: eventAt }, content, tool_rows: rows }] }
}

afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

describe('retention regressions', () => {
  it('matches a versioned reply after separating its echo from visible text', () => {
    const reply = message('assistant', '查到了', 'reply-a')
    const count = hydrateToolEvents([reply], [tool('call-a', 'reply-a'),
      { role: 'assistant', content: '[回响]记下了[/回响]查到了', source_id: 'reply-a' }])
    expect(count).toBe(1)
    expect(reply.events.some(e => e.phase === 'tool_end')).toBe(true)
  })

  it('never associates equal visible replies across different version identities', () => {
    const old = message('assistant', '好了', 'reply-old')
    const latest = message('assistant', '好了', 'reply-new')
    latest.events = [{ phase: 'tool_end', tool_call_id: 'new-call', name: 'shenyu_recall', ok: true }]
    hydrateToolEvents([old, latest], [tool('new-call', 'reply-new'),
      { role: 'assistant', source_id: 'reply-new', content: '好了' }])
    expect(old.events).toEqual([])
    expect(latest.events).toHaveLength(1)
  })

  it('supplements missing tools even when the visible reply did not change', () => {
    const messages = [message('user', 'question', 'user-a'), message('assistant', '查到了', 'reply-a')]
    applyReplyRecovery(messages, recovery('查到了'))
    expect(messages[1].events.find(e => e.phase === 'tool_end')?.tool_call_id).toBe('call-a')
    expect(messages[1].variants?.[0].events).toEqual(messages[1].events)
  })

  it('adds the missing terminal event while preserving the locally observed position', () => {
    const reply = message('assistant', '查到', 'reply-a')
    reply.truncated = true
    reply.events = [{ phase: 'tool_start', tool_call_id: 'call-a', name: 'shenyu_recall', text_offset: 2, stream_order: 4 }]
    const messages = [message('user', 'question', 'user-a'), reply]
    applyReplyRecovery(messages, recovery('查到了'))
    const end = reply.events.find(e => e.phase === 'tool_end' && e.tool_call_id === 'call-a')
    expect(end?.ok).toBe(true)
    expect(end?.text_offset).toBe(2)
    expect(reply.events.filter(e => e.phase === 'tool_start')).toHaveLength(1)
    expect(reply.truncated).not.toBe(true)
  })

  it('does not use an unrelated latest reply for an unanswered local user', () => {
    const messages = [message('user', 'another question', 'user-local')]
    expect(applyReplyRecovery(messages, recovery('unrelated reply'))).toBe(false)
    expect(messages).toHaveLength(1)
  })

  it('never silently replaces saved tools with empty events on quota failure', () => {
    const reply = message('assistant', '查到了', 'reply-a')
    reply.events = [{ phase: 'tool_end', tool_call_id: 'call-a', name: 'shenyu_recall', output: 'x'.repeat(4000), ok: true }]
    const previous = JSON.stringify([reply])
    localStorage.setItem(STORAGE_MESSAGES, previous)
    const actualSet = localStorage.setItem.bind(localStorage)
    vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      const rows = JSON.parse(value)
      if (key === STORAGE_MESSAGES && rows.some((row: UiMessage) => row.events?.length)) {
        throw new DOMException('full', 'QuotaExceededError')
      }
      actualSet(key, value)
    })
    persistStoredMessages([reply], 75)
    expect(localStorage.getItem(STORAGE_MESSAGES)).toBe(previous)
  })
})

it('requires a user anchor when neither side has a local reply identity', () => {
  const messages = [message('user', 'question', 'u'), { ...message('assistant', 'partial', 'r'), replyVersionId: undefined, archiveEvent: undefined }]
  expect(applyReplyRecovery(messages, { replies: [{ content: 'partial and complete' }] })).toBe(false)
  expect(messages[1].content).toBe('partial')
})
