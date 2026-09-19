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

it('rolls back the manifest if a later message write fails after the result was staged', async () => {
  const db = store()
  await db.save('A', state([row('r', 'original')], 'original draft'), 0)
  const before = await db.load('A')
  const original = IDBObjectStore.prototype.put
  vi.spyOn(IDBObjectStore.prototype, 'put').mockImplementation(function (this: IDBObjectStore, ...args) {
    if (this.name === 'messages') throw new DOMException('late message failure', 'QuotaExceededError')
    return original.apply(this, args)
  })
  await expect(db.save('A', state([row('r', 'changed')], 'changed draft'), 1)).rejects.toThrow('late message failure')
  expect(await db.load('A')).toEqual(before)
})


describe('bounded recovery copies, never automatic transcript eviction', () => {
  it('reuses an identical same-kind checkpoint even if only the viewport changed', async () => {
    const db = store()
    const original = await db.saveRecoveryCopy('A', state([row('r')], 'kept'), 'local')
    const again = await db.saveRecoveryCopy('A', { ...state([row('r')], 'kept'), viewport: { atBottom: false } }, 'local')
    expect(again.id).toBe(original.id)
    expect(await db.listRecoveryCopies('A')).toHaveLength(1)
  })

  it('caps additional copies at 20 without evicting originals or blocking ordinary saves', async () => {
    const db = store()
    await db.save('A', state([row('r')], 'active'), 0)
    for (let n = 0; n < 20; n++) await db.saveRecoveryCopy('A', state([row('r')], `copy-${n}`))
    const before = await db.listRecoveryCopies('A')
    await expect(db.saveRecoveryCopy('A', state([row('r')], 'overflow'))).rejects.toThrow(/副本.*上限/)
    expect(await db.listRecoveryCopies('A')).toEqual(before)
    await expect(db.save('A', state([row('r')], 'ordinary save still works'), 1)).resolves.toBe(2)
    await expect(db.saveRecoveryCopy('B', state([row('b')], 'separate scope'))).resolves.toBeTruthy()
  })

  it('also bounds recovery bytes and never alters an existing main transcript', async () => {
    const db = store()
    await db.save('A', state([row('r')], 'active'), 0)
    const before = await db.load('A')
    await expect(db.saveRecoveryCopy('A', state([row('large', 'x'.repeat(32 * 1024 * 1024))]))).rejects.toThrow(/副本.*上限/)
    expect(await db.listRecoveryCopies('A')).toHaveLength(0)
    expect(await db.load('A')).toEqual(before)
  })

  it('scoped removal frees a copy slot, leaving other copies, main rows, list cache and legacy bytes alone', async () => {
    const db = store()
    await db.migrateLegacy('A', JSON.stringify([row('legacy')]))
    const main = await db.load('A'), legacy = await db.legacyBackup('A')
    await db.saveList('A', { sessions: [{ session_tag: 'A' }] })
    const first = await db.saveRecoveryCopy('A', state([row('r')], 'first'))
    const second = await db.saveRecoveryCopy('A', state([row('r')], 'second'))
    await expect(db.removeRecoveryCopy('B', first.id)).resolves.toBe(false)
    await expect(db.removeRecoveryCopy('A', first.id)).resolves.toBe(true)
    expect(await db.loadRecoveryCopy('A', first.id)).toBeNull()
    expect((await db.loadRecoveryCopy('A', second.id))?.state.draft).toBe('second')
    expect(await db.load('A')).toEqual(main)
    expect(await db.legacyBackup('A')).toBe(legacy)
    expect(await db.loadList('A')).toEqual({ sessions: [{ session_tag: 'A' }] })
  })
})


it('serializes concurrent copy admissions so two tabs cannot exceed the cap', async () => {
  const name = `copy-race-${Math.random()}`
  const one = store(name), two = store(name)
  for (let n = 0; n < 19; n++) await one.saveRecoveryCopy('A', state([row('r')], `copy-${n}`))
  const results = await Promise.allSettled([
    one.saveRecoveryCopy('A', state([row('r')], 'first tab')),
    two.saveRecoveryCopy('A', state([row('r')], 'second tab')),
  ])
  expect(results.filter(result => result.status === 'fulfilled')).toHaveLength(1)
  const copies = await one.listRecoveryCopies('A')
  expect(copies).toHaveLength(20)
  await one.removeRecoveryCopy('A', copies[0].id)
  await expect(two.saveRecoveryCopy('A', state([row('r')], 'after explicit cleanup'))).resolves.toBeTruthy()
})

it('does not drop a copy or the active record when confirmed deletion fails', async () => {
  const db = store()
  await db.save('A', state([row('r')], 'active'), 0)
  const main = await db.load('A')
  const copy = await db.saveRecoveryCopy('A', state([row('r')], 'only in copy'))
  vi.spyOn(IDBObjectStore.prototype, 'delete').mockImplementation(() => { throw new Error('write unavailable') })
  await expect(db.removeRecoveryCopy('A', copy.id)).rejects.toThrow('write unavailable')
  expect((await db.loadRecoveryCopy('A', copy.id))?.state.draft).toBe('only in copy')
  expect(await db.load('A')).toEqual(main)
})
