import 'fake-indexeddb/auto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useTranscript } from '../src/session/useTranscript'
import { TranscriptStore, transcriptKey, type TranscriptState } from '../src/session/transcriptStore'
import type { RequestContext } from '../src/api/client'
import type { UiMessage } from '../src/types'

function message(id = 'reply', content = 'same answer'): UiMessage {
  return { id, role: 'assistant', content, echo: '', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [], streaming: false,
    replyVersionId: id, archiveEvent: { id, event_at: '2026-09-19T01:00:00Z' } }
}
const state = (draft: string): TranscriptState => ({ messages: [message()], draft, pendingAttachments: [], editId: null, viewport: { atBottom: true } })
const handles: ReturnType<typeof useTranscript>[] = []
const stores: TranscriptStore[] = []
const context: RequestContext = { gatewayUrl: '', sessionTag: 'A', authToken: '' }
const key = () => transcriptKey('', 'A')
function page() {
  const deps = { context: () => context, messages: ref<UiMessage[]>([]), draft: ref(''), pendingAttachments: ref([]), editId: ref<string | null>(null), stream: ref<HTMLElement | null>(null) }
  const handle = useTranscript(deps); handles.push(handle)
  return { handle, deps }
}
async function conflict() {
  const { handle, deps } = page()
  const other = new TranscriptStore(); stores.push(other)
  await other.save(key(), state('initial'), 0)
  const first = await handle.load(context)
  await handle.apply(first!.state); handle.ready.value = true
  await other.save(key(), state('other page draft'), 1)
  other.close()
  deps.draft.value = 'this page draft'
  deps.messages.value[0].thinking = 'thought received only here'
  deps.messages.value[0].thinkingSegments = [{ id: 'thought-1', content: 'thought received only here', textOffset: 0, streamOrder: 0 }]
  deps.messages.value[0].events = [{ phase: 'tool_end', tool_call_id: 'call', name: 'shenyu_recall', ok: false, output: 'real result' }]
  expect(await handle.save()).toBe(false)
  return { handle, deps }
}
beforeEach(async () => {
  context.sessionTag = 'A'; context.gatewayUrl = ''
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.deleteDatabase('shenyu-pwa-transcripts-v1')
    request.onsuccess = () => resolve(); request.onerror = () => reject(request.error)
  })
})
afterEach(async () => {
  for (const handle of handles.splice(0)) { handle.ready.value = false; handle.dispose() }
  stores.splice(0).forEach(store => store.close())
  await new Promise(resolve => setTimeout(resolve, 10))
  vi.restoreAllMocks()
})

describe('explicit lossless conflict recovery', () => {
  it('resumes writes after the other writer closed, retaining both original drafts and process records', async () => {
    const { handle, deps } = await conflict()
    expect(await handle.recoverConflict()).toBe(true)
    expect(handle.error.value).toBe('')
    expect(deps.draft.value).toBe('other page draft')
    expect(deps.messages.value[0].thinking).toBe('thought received only here')
    expect(deps.messages.value[0].events[0].output).toBe('real result')
    const copies = await handle.store.listRecoveryCopies(key())
    expect(copies).toHaveLength(2)
    const originals = await Promise.all(copies.map(copy => handle.store.loadRecoveryCopy(key(), copy.id)))
    expect(originals.map(copy => copy?.state.draft).sort()).toEqual(['other page draft', 'this page draft'])
    deps.draft.value = 'can save again'
    expect(await handle.save()).toBe(true)
    expect((await handle.store.load(key()))?.state.draft).toBe('can save again')
  })

  it('does not replace live content or unlock when the safety copy fails to commit', async () => {
    const { handle, deps } = await conflict()
    const before = JSON.stringify(deps.messages.value)
    const spy = vi.spyOn(handle.store, 'saveRecoveryCopy').mockRejectedValue(new DOMException('full', 'QuotaExceededError'))
    expect(await handle.recoverConflict()).toBe(false)
    expect(deps.draft.value).toBe('this page draft')
    expect(JSON.stringify(deps.messages.value)).toBe(before)
    expect((await handle.store.load(key()))?.state.draft).toBe('other page draft')
    expect(await handle.save()).toBe(false)
    spy.mockRestore()
    expect(await handle.recoverConflict()).toBe(true)
  })

  it('retains the local snapshot even when the latest transcript cannot be read', async () => {
    const { handle, deps } = await conflict()
    vi.spyOn(handle.store, 'load').mockRejectedValue(new Error('corrupt record'))
    expect(await handle.recoverConflict()).toBe(false)
    expect(deps.draft.value).toBe('this page draft')
    expect(await handle.store.listRecoveryCopies(key())).toHaveLength(1)
    expect(await handle.save()).toBe(false)
  })

  it('never adopts a new revision merely because load was called without applying or protecting live state', async () => {
    const { handle, deps } = await conflict()
    await handle.load(context)
    expect(await handle.save()).toBe(false)
    expect(deps.draft.value).toBe('this page draft')
    expect((await handle.store.load(key()))?.state.draft).toBe('other page draft')
  })

  it('invalidates pre-resync queued snapshots so they cannot later overwrite the recovered state', async () => {
    const { handle, deps } = await conflict()
    const queued = [handle.save(), handle.save()]
    expect(await handle.recoverConflict()).toBe(true)
    expect(await Promise.all(queued)).toEqual([false, false])
    expect((await handle.store.load(key()))?.state.draft).toBe('other page draft')
    deps.draft.value = 'after resync'
    expect(await handle.save()).toBe(true)
  })

  it('fails closed on a second writer race during resync, with originals still accessible', async () => {
    const { handle, deps } = await conflict()
    const original = handle.store.save.bind(handle.store)
    vi.spyOn(handle.store, 'save').mockImplementationOnce(async (scope, next, revision) => {
      const other = new TranscriptStore(); stores.push(other)
      await other.save(scope, state('newest concurrent draft'), revision)
      return original(scope, next, revision)
    })
    expect(await handle.recoverConflict()).toBe(false)
    expect(deps.draft.value).toBe('this page draft')
    expect((await handle.store.load(key()))?.state.draft).toBe('newest concurrent draft')
    expect(await handle.store.listRecoveryCopies(key())).toHaveLength(2)
    expect(await handle.save()).toBe(false)
  })

  it('does not apply a recovered A state to another active context', async () => {
    const { handle, deps } = await conflict()
    const original = handle.store.saveRecoveryCopy.bind(handle.store)
    vi.spyOn(handle.store, 'saveRecoveryCopy').mockImplementationOnce(async (...args) => {
      const copy = await original(...args)
      context.sessionTag = 'B'
      return copy
    })
    expect(await handle.recoverConflict()).toBe(false)
    expect(deps.draft.value).toBe('this page draft')
    expect(await handle.store.load(transcriptKey('', 'B'))).toBeNull()
  })

  it('offers scoped, immutable copies after a new instance opens and backs up the input before draft retrieval', async () => {
    const { handle, deps } = await conflict()
    expect(await handle.recoverConflict()).toBe(true)
    const reopened = new TranscriptStore(); stores.push(reopened)
    const copies = await reopened.listRecoveryCopies(key())
    const local = copies.find(copy => copy.kind === 'local')!
    expect(await reopened.loadRecoveryCopy(transcriptKey('', 'B'), local.id)).toBeNull()
    deps.draft.value = 'another unsaved draft'
    expect(await handle.restoreRecoveryDraft(local.id)).toBe(true)
    expect(deps.draft.value).toBe('this page draft')
    expect(deps.editId.value).toBeNull()
    const retained = await reopened.listRecoveryCopies(key())
    const priorDraft = retained.find(copy => copy.kind === 'before-draft')!
    expect((await reopened.loadRecoveryCopy(key(), priorDraft.id))?.state.draft).toBe('another unsaved draft')
    expect((await reopened.loadRecoveryCopy(key(), local.id))?.state.draft).toBe('this page draft')
  })
})

it('does not merge a different selected reply branch or overwrite either draft during resync', async () => {
  const { handle, deps } = await conflict()
  deps.messages.value.push(message('local-only-roll', 'different reply version'))
  const before = JSON.stringify(deps.messages.value)
  expect(await handle.recoverConflict()).toBe(true)
  expect(deps.messages.value.map(item => item.replyVersionId)).toEqual(['reply'])
  const copies = await handle.store.listRecoveryCopies(key())
  const copy = await handle.store.loadRecoveryCopy(key(), copies.find(item => item.kind === 'local')!.id)
  expect(JSON.stringify(copy!.state.messages)).toBe(before)
})

it('stops recovery rather than discarding edits made while the checkpoint was in flight', async () => {
  const { handle, deps } = await conflict()
  const original = handle.store.saveRecoveryCopy.bind(handle.store)
  vi.spyOn(handle.store, 'saveRecoveryCopy').mockImplementationOnce(async (...args) => {
    const copy = await original(...args)
    deps.draft.value = 'typed during checkpoint'
    return copy
  })
  expect(await handle.recoverConflict()).toBe(false)
  expect(deps.draft.value).toBe('typed during checkpoint')
  expect((await handle.store.load(key()))?.state.draft).toBe('other page draft')
})


it('scrolling during a recovery checkpoint is not an edit and keeps the latest reading position', async () => {
  const { handle, deps } = await conflict()
  const stream = document.createElement('div')
  Object.defineProperties(stream, { scrollHeight: { value: 1000 }, clientHeight: { value: 100 } })
  stream.scrollTop = 900
  deps.stream.value = stream
  const original = handle.store.saveRecoveryCopy.bind(handle.store)
  vi.spyOn(handle.store, 'saveRecoveryCopy').mockImplementationOnce(async (...args) => {
    const copy = await original(...args)
    stream.scrollTop = 0
    return copy
  })
  expect(await handle.recoverConflict()).toBe(true)
  expect(handle.conflicted.value).toBe(false)
  expect(stream.scrollTop).toBe(0)
  expect(await handle.save()).toBe(true)
})

it('a healthy page cannot enter the conflict path or become locked by a checkpoint failure', async () => {
  const { handle, deps } = page()
  handle.ready.value = true; deps.draft.value = 'healthy'
  expect(await handle.save()).toBe(true)
  const checkpoint = vi.spyOn(handle.store, 'saveRecoveryCopy').mockRejectedValue(new Error('full'))
  expect(await handle.recoverConflict()).toBe(false)
  expect(checkpoint).not.toHaveBeenCalled()
  expect(handle.conflicted.value).toBe(false)
  expect(await handle.save()).toBe(true)
})

it('explains why a retained draft cannot be retrieved before resynchronizing', async () => {
  const { handle, deps } = await conflict()
  handle.error.value = ''
  expect(await handle.restoreRecoveryDraft('some-copy')).toBe(false)
  expect(handle.error.value).toContain('先重新同步')
  expect(deps.draft.value).toBe('this page draft')
})

it('keeps a non-editing local draft when the saved composer has nothing to displace', async () => {
  const { handle, deps } = await conflict()
  const saved = (await handle.store.load(key()))!
  await handle.store.save(key(), { ...saved.state, draft: '' }, saved.revision)
  expect(await handle.recoverConflict()).toBe(true)
  expect(deps.draft.value).toBe('this page draft')
  expect((await handle.store.load(key()))?.state.draft).toBe('this page draft')
})

it('does not transplant an edit-mode draft into a different saved branch with an empty composer', async () => {
  const { handle, deps } = await conflict()
  deps.editId.value = 'a-prior-turn'
  const saved = (await handle.store.load(key()))!
  await handle.store.save(key(), { ...saved.state, draft: '' }, saved.revision)
  expect(await handle.recoverConflict()).toBe(true)
  expect(deps.draft.value).toBe('')
  const copies = await handle.store.listRecoveryCopies(key())
  expect(copies.some(copy => copy.draft === 'this page draft')).toBe(true)
})
