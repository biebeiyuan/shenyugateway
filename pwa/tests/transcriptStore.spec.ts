import 'fake-indexeddb/auto'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TranscriptStore, transcriptKey, StorageConflictError } from '../src/session/transcriptStore'
import type { UiMessage } from '../src/types'

const opened: TranscriptStore[] = []
function store(name = `retention-test-${Math.random()}`) {
  const value = new TranscriptStore(name)
  opened.push(value)
  return value
}
function row(id: string, content = id): UiMessage {
  return { id, role: 'assistant', content, echo: 'echo', echoSegments: [{ id: 'e', content: 'echo', textOffset: 2, streamOrder: 3 }],
    attachments: [], thinking: 'local thought', thinkingSegments: [{ id: 't', content: 'local thought', textOffset: 1, streamOrder: 1 }],
    events: [{ phase: 'tool_end', name: 'shenyu_recall', tool_call_id: `call-${id}`, text_offset: 2, stream_order: 2, output: 'result', ok: true }],
    replyVersionId: id, archiveEvent: { id, event_at: '2026-09-19T01:00:00Z' } }
}
function state(messages: UiMessage[], draft = '') {
  return { messages, draft, pendingAttachments: [], editId: null, viewport: { atBottom: true } }
}
afterEach(() => { opened.splice(0).forEach(db => db.close()); vi.restoreAllMocks() })

describe('durable per-session transcript', () => {
  it('normalizes a gateway without mixing gateways or sessions', () => {
    expect(transcriptKey('', 'A', 'https://example.test/chat/')).toBe(transcriptKey('https://example.test/', 'A'))
    expect(transcriptKey('https://one.test', 'A')).not.toBe(transcriptKey('https://two.test', 'A'))
    expect(transcriptKey('https://one.test', 'A')).not.toBe(transcriptKey('https://one.test', 'B'))
  })

  it('preserves rich messages and drafts through A to B to A and a new store instance', async () => {
    const name = `switch-${Math.random()}`
    const db = store(name)
    const a = state([row('reply-a')], 'unfinished draft')
    a.messages[0].variants = [{ ...row('older-a'), content: 'older answer', events: [] }, { ...row('reply-a') }]
    a.messages[0].selectedVariantIndex = 1
    await db.save('A', a, 0)
    await db.save('B', state([row('reply-b')]), 0)
    db.close()
    const reopened = store(name)
    const read = await reopened.load('A')
    expect(read?.state.draft).toBe('unfinished draft')
    expect(read?.state.messages[0].events[0].output).toBe('result')
    expect(read?.state.messages[0].thinking).toBe('local thought')
    expect(read?.state.messages[0].variants).toHaveLength(2)
    expect((await reopened.load('B'))?.state.messages[0].content).toBe('reply-b')
  })

  it('does not discard older messages at the old 240-row display window', async () => {
    const db = store()
    await db.save('A', state(Array.from({ length: 310 }, (_, n) => row(`reply-${n}`))), 0)
    const read = await db.load('A')
    expect(read?.state.messages).toHaveLength(310)
    expect(read?.state.messages[0].id).toBe('reply-0')
  })

  it('rejects stale writers atomically instead of overwriting a newer transcript', async () => {
    const name = `tabs-${Math.random()}`
    const first = store(name), second = store(name)
    await first.save('A', state([row('r', 'original')]), 0)
    const stale = await second.load('A')
    await first.save('A', state([row('r', 'complete')]), 1)
    await expect(second.save('A', state([row('r', 'stale')]), stale!.revision)).rejects.toBeInstanceOf(StorageConflictError)
    expect((await first.load('A'))?.state.messages[0].content).toBe('complete')
  })

  it('keeps the previous transaction on failure and does not drop events', async () => {
    const db = store()
    await db.save('A', state([row('r')]), 0)
    vi.spyOn(IDBObjectStore.prototype, 'put').mockImplementation(() => { throw new DOMException('full', 'QuotaExceededError') })
    await expect(db.save('A', state([row('r', 'newer')]), 1)).rejects.toThrow()
    vi.restoreAllMocks()
    const read = await db.load('A')
    expect(read?.revision).toBe(1)
    expect(read?.state.messages[0].events[0].output).toBe('result')
  })

  it('never serializes image bytes, but preserves unknown metadata', async () => {
    const db = store()
    const message = row('r')
    message.attachments = [{ id: 'image', name: 'x', mime: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,Yg==', displayUrl: 'blob:temporary', fingerprint: 'f'.repeat(64) }]
    ;(message as unknown as Record<string, unknown>).futureField = { value: 4 }
    await db.save('A', state([message]), 0)
    const read = await db.load('A')
    expect(read?.state.messages[0].attachments[0].dataUrl).toBeUndefined()
    expect(JSON.stringify(read)).not.toContain('blob:temporary')
    expect((read?.state.messages[0] as unknown as Record<string, unknown>).futureField).toEqual({ value: 4 })
  })

  it('retains superseded branch records without re-inserting them into the selected branch', async () => {
    const db = store()
    await db.save('A', state([row('old'), row('tail')]), 0)
    await db.save('A', state([row('edited')]), 1)
    expect((await db.load('A'))?.state.messages.map(m => m.id)).toEqual(['edited'])
    expect((await db.readRetainedMessages('A')).map(m => m.id).sort()).toEqual(['edited', 'old', 'tail'])
  })

  it('imports a legacy snapshot only once and retains its exact backup', async () => {
    const db = store()
    const raw = JSON.stringify([row('legacy')])
    await db.migrateLegacy('A', raw)
    await db.save('A', state([row('modern')]), 1)
    await db.migrateLegacy('A', JSON.stringify([row('old-tab')]))
    expect((await db.load('A'))?.state.messages[0].id).toBe('modern')
    expect(await db.legacyBackup('A')).toBe(raw)
  })
})

it('pins the single legacy source to its original gateway/session across later switches', async () => {
  const db = store()
  const raw = JSON.stringify([row('legacy-a')])
  await db.migrateLegacySource('gateway-a:A', raw)
  await db.migrateLegacySource('gateway-b:B', raw)
  expect((await db.load('gateway-a:A'))?.state.messages[0].id).toBe('legacy-a')
  expect(await db.load('gateway-b:B')).toBeNull()
})

it('records an empty legacy slot without creating an empty conversation or importing later stale writes', async () => {
  const db = store()
  await db.migrateLegacySource('initial', '[]')
  expect(await db.load('initial')).toBeNull()
  await db.migrateLegacySource('another-gateway', JSON.stringify([row('stale-later')]))
  expect(await db.load('another-gateway')).toBeNull()
})
