import { describe, expect, it } from 'vitest'
import { applyReconciledTail, applyReplyRecovery } from '../src/session/reconcile'
import { wireMessages } from '../src/api/client'
import { applyVariant, snapshotMessage } from '../src/session/variants'
import type { UiMessage } from '../src/types'

const stamp = '2026-09-19T01:00:00Z'
const event = (id: string) => ({ id, event_at: stamp })
function row(role: 'user' | 'assistant', content: string, extra: Partial<UiMessage> = {}): UiMessage {
  return { id: role, role, content, echo: '', echoSegments: [], attachments: [], thinking: '',
    thinkingSegments: [], events: [], ...extra }
}
const detail = (id: string | undefined, archiveId = id) => ({ recent_messages: [
  { role: 'user', content: '同一个问题' },
  { role: 'assistant', source_id: id, content: '你好，这是一版完整回复。',
    archive_event: archiveId ? event(archiveId) : undefined },
] })

// Removing the exact-version guard must make these fail even for empty/common-prefix tails.
describe('fallback recovery keeps version and archive identity together', () => {
  it.each(['', '你好'])('does not fill a new roll with an old reply: local %j', content => {
    const messages = [row('user', '同一个问题'), row('assistant', content,
      { replyVersionId: 'v2', archiveEvent: event('v2'), truncated: true, error: '断线' })]
    expect(applyReconciledTail(messages, detail('v1'))).toBe(false)
    expect(messages[1].content).toBe(content)
    expect(messages[1].archiveEvent).toEqual(event('v2'))
    expect(wireMessages(messages)[1]).toHaveProperty('archive_pending', true)
  })
  it('does not fall back to an unversioned legacy row when waiting for a known version', () => {
    const messages = [row('user', '同一个问题'), row('assistant', '', { replyVersionId: 'v2', truncated: true })]
    expect(applyReconciledTail(messages, detail(undefined))).toBe(false)
    expect(messages[1].truncated).toBe(true)
  })
  it('treats an archive event as known identity even without a display version id', () => {
    const messages = [row('user', '同一个问题'), row('assistant', '', { archiveEvent: event('v2'), truncated: true })]
    expect(applyReconciledTail(messages, detail('v1'))).toBe(false)
    expect(applyReconciledTail(messages, detail('v2'))).toBe(true)
    expect(messages[1].archiveEvent).toEqual(event('v2'))
  })
  it('recovers the exact version, preserving its original clock and clearing pending', () => {
    const messages = [row('user', '同一个问题'), row('assistant', '你好',
      { replyVersionId: 'v2', archiveEvent: event('v2'), truncated: true })]
    expect(applyReconciledTail(messages, detail('v2'))).toBe(true)
    expect(messages[1].content).toBe('你好，这是一版完整回复。')
    expect(messages[1].archiveEvent).toEqual(event('v2'))
    expect(wireMessages(messages)[1]).not.toHaveProperty('archive_pending')
  })
  it('rejects conflicting archive and reply ids, even if content covers the local prefix', () => {
    const messages = [row('user', '同一个问题'), row('assistant', '',
      { replyVersionId: 'v2', archiveEvent: event('v2'), truncated: true })]
    expect(applyReconciledTail(messages, detail('v2', 'v1'))).toBe(false)
    expect(messages[1].content).toBe('')
  })
  it('preserves content-anchored compatibility for genuinely unversioned history', () => {
    const messages = [row('user', '同一个问题'), row('assistant', '你好', { truncated: true })]
    expect(applyReconciledTail(messages, detail(undefined))).toBe(true)
    expect(messages[1].content).toBe('你好，这是一版完整回复。')
  })
})

describe('primary recovery obeys the same archive identity boundary', () => {
  const payload = (id: string, archiveId = id) => ({ replies: [
    { reply_version_id: id, archive_event: event(archiveId), content: '你好，这是一版完整回复。' },
  ] })
  it('does not adopt the latest unrelated version when the archive id is known', () => {
    const messages = [row('user', '同一个问题'), row('assistant', '', { archiveEvent: event('v2'), truncated: true })]
    expect(applyReplyRecovery(messages, payload('v1'))).toBe(false)
    expect(messages[1].content).toBe('')
    expect(messages[1].truncated).toBe(true)
  })
  it('rejects an envelope from another version on an otherwise matching reply', () => {
    const messages = [row('user', '同一个问题'), row('assistant', '',
      { replyVersionId: 'v2', archiveEvent: event('v2'), truncated: true })]
    expect(applyReplyRecovery(messages, payload('v2', 'v1'))).toBe(false)
    expect(messages[1].content).toBe('')
    expect(messages[1].truncated).toBe(true)
  })
})


it('keeps completion and identity on the saved variant even when recovered text is unchanged', () => {
  const target = row('assistant', '完整原文', { replyVersionId: 'v2', truncated: true, error: '断线' })
  target.variants = [snapshotMessage(target)]
  const messages = [row('user', '同一个问题'), target]
  expect(applyReplyRecovery(messages, { replies: [
    { reply_version_id: 'v2', archive_event: event('v2'), content: '完整原文' },
  ] })).toBe(true)
  applyVariant(target, target.variants[0], 0)
  expect(target.archiveEvent).toEqual(event('v2'))
  expect(wireMessages(messages)[1]).not.toHaveProperty('archive_pending')
})
