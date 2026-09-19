import 'fake-indexeddb/auto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick, type App as VueApp } from 'vue'
import App from '../src/App.vue'
import { TranscriptStore, transcriptKey } from '../src/session/transcriptStore'
import { closePhotoStore } from '../src/session/photoStore'
import type { UiMessage } from '../src/types'
vi.mock('../src/meta/statusSuffix', async importOriginal => ({
  ...await importOriginal<object>(), initWeatherWatch: () => {}, initBatteryWatch: () => {},
}))
vi.mock('../src/ChatNestSprite.vue', () => ({ default: { template: '<span />' } }))
const apps: VueApp[] = []
function row(role: 'user' | 'assistant', id: string, content = id): UiMessage {
  return { id, role, content, echo: '', echoSegments: [], thinking: '', thinkingSegments: [], attachments: [], events: [],
    archiveEvent: { id, event_at: '2026-09-19T01:00:00Z' }, ...(role === 'assistant' ? { replyVersionId: id } : {}) }
}
function detail(tag: string) {
  return { context_snapshots: [{ messages: [row('user', `u-${tag}`), row('assistant', `r-${tag}`)].map(m => ({
    role: m.role, content: m.content, archive_event: m.archiveEvent,
  })) }], recent_messages: [] }
}
function setupFetch(details: (tag: string) => Promise<unknown> = async tag => detail(tag)) {
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    if (url.pathname.endsWith('/reply-recovery')) return Response.json({ replies: [] })
    if (url.pathname === '/api/gateway/sessions') return Response.json({ sessions: [{ session_tag: 'A' }, { session_tag: 'B' }] })
    if (url.pathname.startsWith('/api/gateway/sessions/')) return Response.json(await details(decodeURIComponent(url.pathname.split('/')[4])))
    if (url.pathname.endsWith('/album/resolve')) return Response.json({ media: {}, photos: {} })
    if (url.pathname === '/api/config') return Response.json({ max_client_messages: 75 })
    if (url.pathname === '/v1/models') return Response.json({ data: [] })
    throw new Error(`Unexpected request ${options?.method || 'GET'} ${url.pathname}`)
  }))
}
function mount() {
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp(App); apps.push(app)
  const vm = app.mount(host) as any
  return { host, state: vm.$.setupState as any }
}
async function flush() { await nextTick(); await new Promise(resolve => setTimeout(resolve, 40)); await nextTick() }

beforeEach(async () => {
  localStorage.clear(); sessionStorage.clear(); window.history.replaceState(null, '', '/chat/')
  await closePhotoStore()
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.deleteDatabase('shenyu-pwa-transcripts-v1')
    request.onsuccess = () => resolve(); request.onerror = () => reject(request.error)
  })
  setupFetch()
})
afterEach(async () => {
  apps.splice(0).forEach(app => app.unmount()); await flush()
  document.body.innerHTML = ''; vi.unstubAllGlobals(); vi.restoreAllMocks()
})

describe('real PWA retention wiring', () => {
  it('keeps rich process state through actual A to B to A and a new page mount', async () => {
    const a = [row('user', 'u-A'), row('assistant', 'r-A')]
    a[1].thinking = 'remember this local thought'
    a[1].events = [{ phase: 'tool_end', name: 'shenyu_recall', tool_call_id: 'call-A', output: 'saved result', ok: true }]
    localStorage.setItem('shenyu_pwa_session', 'A')
    localStorage.setItem('shenyu_pwa_messages', JSON.stringify(a))
    const { state } = mount(); await flush()
    await state.openSession({ session_tag: 'B' }); await flush()
    await state.openSession({ session_tag: 'A' }); await flush()
    expect(state.messages[1].thinking).toBe('remember this local thought')
    expect(state.messages[1].events[0]?.output).toBe('saved result')
    state.draft = 'a draft still being written'
    await state.persistMessages()
    apps.splice(0).forEach(app => app.unmount()); await flush()
    const restarted = mount(); await flush()
    expect(restarted.state.draft).toBe('a draft still being written')
    expect(restarted.state.messages[1].events[0]?.output).toBe('saved result')
  })

  it('does not wait for configuration network requests to restore local draft and messages', async () => {
    const store = new TranscriptStore()
    await store.save(transcriptKey('', 'A'), { messages: [row('user','u-A')], draft: 'offline draft', pendingAttachments: [], editId: null, viewport: { atBottom: true } }, 0)
    store.close()
    localStorage.setItem('shenyu_pwa_session', 'A')
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const { state, host } = mount(); await flush()
    expect(state.draft).toBe('offline draft')
    expect(host.textContent).toContain('u-A')
    expect(state.storageReady).toBe(true)
  })

  it('ignores a stale A response after B has become the selected conversation', async () => {
    let resolveA!: (value: unknown) => void
    setupFetch(tag => tag === 'A' ? new Promise(resolve => { resolveA = resolve }) : Promise.resolve(detail(tag)))
    const { state } = mount(); await flush()
    const pendingA = state.openSession({ session_tag: 'A' }); await flush()
    await state.openSession({ session_tag: 'B' }); await flush()
    resolveA(detail('A')); await pendingA; await flush()
    expect(state.sessionTag).toBe('B')
    expect(state.messages.at(-1).content).toBe('r-B')
  })
})

it('commits the outgoing turn and reply identity before starting the network request', async () => {
  const { state } = mount(); await flush()
  const normalFetch = globalThis.fetch
  let committed = false
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      const body = JSON.parse(String(options?.body))
      const store = new TranscriptStore()
      const record = await store.load(transcriptKey('', state.sessionTag))
      store.close()
      expect(record?.state.messages.at(-1)?.replyVersionId).toBe(body.metadata.reply_version_id)
      expect(record?.state.messages.at(-1)?.truncated).toBeUndefined()
      expect(record?.state.messages.at(-2)?.content).toContain('save before send')
      committed = true
      return new Response('data: {"choices":[{"delta":{"content":"received"}}]}\n\ndata: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
    }
    return normalFetch(input, options)
  }))
  state.draft = 'save before send'
  await state.submit(); await flush()
  expect(committed).toBe(true)
  expect(state.messages.at(-1).content).toBe('received')
})

it('does not relabel the legacy single slot after changing gateways and restarting', async () => {
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([row('user', 'private-to-origin')]))
  const { state } = mount(); await flush()
  state.settingsGateway = 'https://second.example'
  await state.saveSettings(); await flush()
  expect(state.messages).toHaveLength(0)
  state.draft = 'second gateway draft'
  await state.persistMessages()
  apps.splice(0).forEach(app => app.unmount()); await flush()
  const restarted = mount(); await flush()
  expect(restarted.state.draft).toBe('second gateway draft')
  expect(restarted.state.messages).toHaveLength(0)
})

it('does not send when the initial durable checkpoint fails', async () => {
  const { state } = mount(); await flush()
  vi.spyOn(TranscriptStore.prototype, 'saveTail').mockRejectedValue(new DOMException('full', 'QuotaExceededError'))
  state.draft = 'must stay on device if checkpoint failed'
  await state.submit(); await flush()
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/v1/chat/completions'))).toBe(false)
  expect(state.errorNotice).toContain('本机未能保存这次发送')
  expect(state.messages[0].content).toContain('must stay on device')
})


it('does not place an active conversation in an empty hidden list', async () => {
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([row('user', 'u-A')]))
  const { state, host } = mount(); await flush()
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ sessions: [] })))
  state.showHiddenSessions = true; await flush()
  await state.loadSessions(); await flush()
  expect(host.querySelectorAll('.session-item')).toHaveLength(0)
  expect(host.querySelector('.sidebar-empty')?.textContent).toContain('还没有已收起的对话')
})

it('can recover a conflict through the visible action without first saving the stale page', async () => {
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([row('assistant', 'r-A')]))
  const { state, host } = mount(); await flush()
  const store = new TranscriptStore()
  try {
    const key = transcriptKey('', 'A')
    const latest = (await store.load(key))!
    await store.save(key, { ...latest.state, draft: 'draft from another page' }, latest.revision)
    state.draft = 'my uncommitted draft'
    expect(await state.persistMessages()).toBe(false)
    expect(await state.openSession({ session_tag: 'B' })).toBe(false)
    const button = host.querySelector<HTMLButtonElement>('[data-testid="recover-local-record"]')
    expect(button).not.toBeNull()
    button!.click(); await flush(); await flush()
    expect(state.storageConflict).toBe(false)
    expect(state.draft).toBe('draft from another page')
    state.openSettings(); await flush()
    expect(host.textContent).toContain('保留副本')
    const copies = await store.listRecoveryCopies(key)
    const local = copies.find(copy => copy.kind === 'local')!
    expect(await state.restoreLocalDraft(local.id)).toBe(true)
    expect(state.draft).toBe('my uncommitted draft')
    expect(await state.openSession({ session_tag: 'B' })).toBe(true)
    expect(state.sessionTag).toBe('B')
  } finally { store.close() }
})

it('shows page build and offline-worker status as separate evidence in Settings', async () => {
  const { state, host } = mount(); await flush()
  state.openSettings(); await flush()
  expect(host.querySelector('[data-testid="offline-update-status"]')).not.toBeNull()
  expect(host.querySelector('.build-proof')?.textContent).toContain('本页代码')
  expect(host.querySelector('.build-proof')?.textContent).toContain('当前离线版本')
})


it('only removes a selected recovery copy after explicit confirmation and leaves the main record intact', async () => {
  localStorage.setItem('shenyu_pwa_session', 'A')
  const { state, host } = mount(); await flush()
  const store = new TranscriptStore()
  try {
    const key = transcriptKey('', 'A')
    const active = (await store.load(key))!
    const copy = await store.saveRecoveryCopy(key, { ...active.state, draft: 'only in this copy' })
    state.openSettings(); await flush()
    const select = Array.from(host.querySelectorAll<HTMLButtonElement>('.recovery-copy-row button'))[0]
    select.click(); await flush()
    const remove = () => host.querySelector<HTMLButtonElement>('[data-testid="remove-recovery-copy"]')
    expect(remove()).not.toBeNull()
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    remove()!.click(); await flush()
    expect(await store.loadRecoveryCopy(key, copy.id)).not.toBeNull()
    confirm.mockReturnValue(true)
    const before = await store.load(key)
    remove()!.click(); await flush()
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('无法恢复'))
    expect(await store.loadRecoveryCopy(key, copy.id)).toBeNull()
    expect(await store.load(key)).toEqual(before)
    expect(host.textContent).toContain('当前对话没有恢复副本')
  } finally { store.close() }
})


it('sends the full pre-target history while keeping the full local transcript', async () => {
  const history: UiMessage[] = []
  for (let turn = 0; turn < 6; turn++) {
    history.push(row('user', `u${turn}`, `question-${turn}`))
    history.push(row('assistant', `a${turn}`, `answer-${turn}`))
  }
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify(history))
  const { state } = mount(); await flush()
  state.maxClientMessages = 5

  const normalFetch = globalThis.fetch
  let sent: Record<string, unknown> | undefined
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      sent = JSON.parse(String(options?.body))
      return new Response('data: {"choices":[{"delta":{"content":"new-roll"}}]}\n\ndata: [DONE]\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return normalFetch(input, options)
  }))

  await state.retryMessage(11); await flush()
  const outbound = sent?.messages as Array<{role: string; content: string}>
  expect(outbound).toHaveLength(11)
  expect(outbound[0]).toMatchObject({ role: 'user', content: 'question-0' })
  expect(outbound.at(-1)).toMatchObject({ role: 'user', content: 'question-5' })
  expect(state.messages).toHaveLength(12)
  const store = new TranscriptStore()
  try {
    const saved = await store.load(transcriptKey('', 'A'))
    expect(saved?.state.messages).toHaveLength(12)
  } finally { store.close() }
})

it.each([167, 169, 199, 201])('sends %i pre-target messages without a client-side sliding window', async outboundCount => {
  const history: UiMessage[] = []
  for (let index = 0; index <= outboundCount; index++) {
    const role = index % 2 === 0 ? 'user' : 'assistant'
    history.push(row(role, `${role}-${index}`, `message-${index}`))
  }
  expect(history.at(-1)?.role).toBe('assistant')
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify(history))
  const { state } = mount(); await flush()
  state.maxClientMessages = 5
  const normalFetch = globalThis.fetch
  let sent: Record<string, unknown> | undefined
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      sent = JSON.parse(String(options?.body))
      return new Response('data: {"choices":[{"delta":{"content":"boundary ok"}}]}\n\ndata: [DONE]\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return normalFetch(input, options)
  }))

  await state.retryMessage(history.length - 1); await flush()
  expect((sent?.messages as unknown[])).toHaveLength(outboundCount)
  expect((sent?.messages as any[])[0]).toMatchObject({ role: 'user', content: 'message-0' })
  expect(state.messages).toHaveLength(history.length)
})

it('records the 1000-message request cost without truncating local history or reviving old image bytes', async () => {
  const history: UiMessage[] = []
  for (let index = 0; index < 1000; index++) {
    const role = index % 2 === 0 ? 'user' : 'assistant'
    history.push(row(role, `${role}-large-${index}`, `synthetic-${index}-${'x'.repeat(64)}`))
  }
  history[0].attachments = [{
    id: 'expired-image', name: 'expired.jpg', mime: 'image/jpeg', fingerprint: 'c'.repeat(64),
  }]
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify(history))
  const { state } = mount(); await flush()
  for (let i = 0; i < 200 && (!state.storageReady || state.messages.length !== 1000); i++) {
    await new Promise(resolve => setTimeout(resolve, 5)); await nextTick()
  }
  expect(state.storageReady).toBe(true)
  expect(state.messages).toHaveLength(1000)
  state.maxClientMessages = 5
  const normalFetch = globalThis.fetch
  let bodyText = ''
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      bodyText = String(options?.body)
      return new Response('data: {"choices":[{"delta":{"content":"large ok"}}]}\n\ndata: [DONE]\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return normalFetch(input, options)
  }))

  await state.retryMessage(999); await flush()
  const parsed = JSON.parse(bodyText)
  const started = performance.now()
  const reserialized = JSON.stringify(parsed)
  const serializeMs = performance.now() - started
  console.info(`PWA_WINDOW_METRIC messages=${parsed.messages.length} bytes=${new TextEncoder().encode(bodyText).byteLength} reserialize_ms=${serializeMs.toFixed(3)}`)
  expect(parsed.messages).toHaveLength(999)
  expect(bodyText).not.toContain('data:image')
  expect(bodyText).toContain('expired_image')
  expect(reserialized.length).toBe(bodyText.length)
  expect(Number.isFinite(serializeMs)).toBe(true)
  expect(state.messages).toHaveLength(1000)
})

it('releases the clean DONE UI before the final local tail save resolves', async () => {
  const { state } = mount(); await flush()
  let releaseFinal!: (revision: number) => void
  vi.spyOn(TranscriptStore.prototype, 'saveTail')
    .mockResolvedValueOnce(1)
    .mockImplementationOnce(() => new Promise(resolve => { releaseFinal = resolve }))
  const normalFetch = globalThis.fetch
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      return new Response('data: {"choices":[{"delta":{"content":"done"}}]}\n\ndata: [DONE]\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return normalFetch(input, options)
  }))

  state.draft = 'do not let disk block DONE'
  const sending = state.submit()
  for (let i = 0; i < 40 && !releaseFinal; i++) {
    await new Promise(resolve => setTimeout(resolve, 5)); await nextTick()
  }
  expect(releaseFinal).toBeTypeOf('function')
  const contentBeforeRelease = state.messages.at(-1)?.content
  const busyBeforeRelease = state.busy
  const blockedBeforeRelease = state.controlsBlocked
  releaseFinal(2)
  await sending; await flush()

  expect(contentBeforeRelease).toBe('done')
  expect(busyBeforeRelease).toBe(false)
  expect(blockedBeforeRelease).toBe(false)
  expect(state.messages.at(-1)?.truncated).toBeUndefined()
})

it('cancels a pending pre-send checkpoint without a late POST', async () => {
  const { state } = mount(); await flush()
  let releaseCheckpoint!: (revision: number) => void
  vi.spyOn(TranscriptStore.prototype, 'saveTail').mockImplementation(() => new Promise(resolve => { releaseCheckpoint = resolve }))
  const normalFetch = globalThis.fetch
  const chatCalls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    if (url.pathname === '/v1/chat/completions') {
      chatCalls.push(url.pathname)
      if (options?.signal?.aborted) throw new DOMException('cancelled', 'AbortError')
      return new Response('data: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
    }
    return normalFetch(input, options)
  }))

  state.draft = 'cancel before the request exists'
  let settled = false
  const sending = state.submit().finally(() => { settled = true })
  for (let i = 0; i < 40 && !releaseCheckpoint; i++) await new Promise(resolve => setTimeout(resolve, 5))
  expect(releaseCheckpoint).toBeTypeOf('function')
  state.cancelGeneration()
  await new Promise(resolve => setTimeout(resolve, 20)); await nextTick()
  const busyBeforeRelease = state.busy
  const settledBeforeRelease = settled
  releaseCheckpoint(1)
  await sending; await flush()

  expect(busyBeforeRelease).toBe(false)
  expect(settledBeforeRelease).toBe(true)
  expect(chatCalls).toHaveLength(0)
})

it('shows streaming state immediately while the lightweight pre-send checkpoint is still pending', async () => {
  const { state } = mount(); await flush()
  let release!: (revision: number) => void
  vi.spyOn(TranscriptStore.prototype, 'saveTail').mockImplementation(() => new Promise(resolve => { release = resolve }))
  const normalFetch = globalThis.fetch
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      return new Response('data: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
    }
    return normalFetch(input, options)
  }))
  state.draft = 'show activity immediately'
  const sending = state.submit()
  await nextTick()
  expect(state.messages.at(-1)?.streaming).toBe(true)
  for (let i = 0; i < 20 && !release; i++) await new Promise(resolve => setTimeout(resolve, 5))
  expect(release).toBeTypeOf('function')
  release(1)
  await sending
})

it('does not invent background recovery when a reroll fetch fails before a stream is accepted', async () => {
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([
    row('user', 'u1', 'question'),
    row('assistant', 'a1', 'old answer'),
  ]))
  const { state } = mount(); await flush()
  const normalFetch = globalThis.fetch
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    calls.push(url.pathname)
    if (url.pathname === '/v1/chat/completions') throw new TypeError('Failed to fetch')
    return normalFetch(input, options)
  }))

  await state.retryMessage(1); await flush(); await new Promise(resolve => setTimeout(resolve, 60))
  expect(calls.filter(path => path.endsWith('/reply-recovery'))).toHaveLength(0)
  expect(state.errorNotice).toContain('Failed to fetch')
  expect(state.messages[1].content).toBe('old answer')
  expect(state.messages[1].truncated).toBeUndefined()
})

it('invalidates an old interrupted receipt before a new reroll and restores the rich old version losslessly', async () => {
  const old = row('assistant', 'old-reply', 'old answer')
  old.echo = 'old echo'
  old.echoSegments = [{ id: 'echo-old', content: 'old echo', textOffset: 0, streamOrder: 0 }]
  old.thinking = 'old thinking'
  old.thinkingSegments = [{ id: 'think-old', content: 'old thinking', textOffset: 0, streamOrder: 1 }]
  old.events = [
    { phase: 'tool_start', tool_call_id: 'old-call', name: 'shenyu_recall', input: '{"q":"kept"}' },
    { phase: 'tool_end', tool_call_id: 'old-call', name: 'shenyu_recall', ok: true, output: 'full old tool result' },
  ]
  old.attachments = [{ id: 'old-photo', name: 'kept.jpg', mime: 'image/jpeg', fingerprint: 'a'.repeat(64), photoId: 'phot_kept' }]
  old.truncated = true
  old.variants = [
    {
      content: 'older answer', echo: '', echoSegments: [], thinking: '', thinkingSegments: [], events: [],
      attachments: [], replyVersionId: 'older-reply', archiveEvent: { id: 'older-reply', event_at: '2026-09-19T00:30:00Z' },
    },
    {
      content: old.content, echo: old.echo, echoSegments: old.echoSegments, thinking: old.thinking,
      thinkingSegments: old.thinkingSegments, events: old.events, attachments: old.attachments,
      replyVersionId: old.replyVersionId, archiveEvent: old.archiveEvent, truncated: true,
    },
  ]
  old.selectedVariantIndex = 1
  const history = [row('user', 'u1', 'question'), old]
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify(history))
  localStorage.setItem(`shenyu_pwa_inflight:${transcriptKey('', 'A')}`, JSON.stringify({ replyVersionId: 'old-reply' }))
  const { state } = mount(); await flush()
  const before = JSON.parse(JSON.stringify(state.messages[1]))
  const normalFetch = globalThis.fetch
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    calls.push(url.pathname)
    if (url.pathname === '/v1/chat/completions') throw new TypeError('Failed to fetch')
    return normalFetch(input, options)
  }))

  await state.retryMessage(1); await flush(); await new Promise(resolve => setTimeout(resolve, 60))
  expect(state.busy).toBe(false)
  expect(state.controlsBlocked).toBe(false)
  expect(state.messages[1].content).toBe(before.content)
  expect(state.messages[1].echo).toBe(before.echo)
  expect(state.messages[1].thinking).toBe(before.thinking)
  expect(state.messages[1].events).toEqual(before.events)
  expect(state.messages[1].attachments).toEqual(before.attachments)
  expect(state.messages[1].selectedVariantIndex).toBe(1)
  expect(state.messages[1].variants).toEqual(before.variants)
  expect(calls.filter(path => path.endsWith('/reply-recovery'))).toHaveLength(0)
  expect(localStorage.getItem(`shenyu_pwa_inflight:${transcriptKey('', 'A')}`)).toBeNull()
})

it('does not treat an explicit upstream stream failure as a recoverable background disconnect', async () => {
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([
    row('user', 'u1', 'question'),
    row('assistant', 'a1', 'old answer'),
  ]))
  const { state } = mount(); await flush()
  const normalFetch = globalThis.fetch
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    calls.push(url.pathname)
    if (url.pathname === '/v1/chat/completions') {
      return new Response(
        'event: shenyu_error\n'
        + 'data: {"error":{"message":"peer closed connection without sending complete message body (incomplete chunked read)","type":"upstream_stream_error","recoverable":false}}\n\n'
        + 'data: [DONE]\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      )
    }
    return normalFetch(input, options)
  }))

  await state.retryMessage(1); await flush(); await new Promise(resolve => setTimeout(resolve, 60))
  expect(calls.filter(path => path.endsWith('/reply-recovery'))).toHaveLength(0)
  expect(state.messages[1].content).toBe('old answer')
  expect(state.messages[1].truncated).toBeUndefined()
  expect(state.errorNotice).toContain('peer closed connection')
})

it('does not call reply recovery on a healthy reopen without an inflight receipt', async () => {
  const history = [row('user', 'u1', 'question'), row('assistant', 'r1', 'complete answer')]
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify(history))
  const normalFetch = globalThis.fetch
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    calls.push(url.pathname)
    return normalFetch(input, options)
  }))

  mount(); await flush(); await new Promise(resolve => setTimeout(resolve, 60))
  expect(calls.some(path => path.startsWith('/api/gateway/sessions/A'))).toBe(true)
  expect(calls.filter(path => path.endsWith('/reply-recovery'))).toHaveLength(0)
})

it('does not recover a stale truncated marker without the exact inflight receipt', async () => {
  const partial = row('assistant', 'r1', 'old partial')
  partial.truncated = true
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([row('user', 'u1', 'question'), partial]))
  const normalFetch = globalThis.fetch
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    calls.push(url.pathname)
    return normalFetch(input, options)
  }))

  const { state } = mount(); await flush(); await new Promise(resolve => setTimeout(resolve, 60))
  expect(state.messages.at(-1)?.content).toBe('old partial')
  expect(state.messages.at(-1)?.truncated).toBe(true)
  expect(calls.filter(path => path.endsWith('/reply-recovery'))).toHaveLength(0)
})

it('does not recover an explicit upstream failure just because a tool_start was rendered', async () => {
  const { state } = mount(); await flush()
  const normalFetch = globalThis.fetch
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    calls.push(url.pathname)
    if (url.pathname === '/v1/chat/completions') {
      return new Response(
        'event: shenyu_tool\n'
        + 'data: {"event":{"phase":"tool_start","tool_call_id":"t1","name":"shenyu_recall"}}\n\n'
        + 'event: shenyu_error\n'
        + 'data: {"error":{"message":"upstream closed","type":"upstream_stream_error","recoverable":false}}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      )
    }
    return normalFetch(input, options)
  }))

  state.draft = 'tool then explicit failure'
  await state.submit(); await flush(); await new Promise(resolve => setTimeout(resolve, 60))
  expect(state.messages.at(-1)?.events.some((event: any) => event.phase === 'tool_start')).toBe(true)
  expect(state.messages.at(-1)?.truncated).toBeUndefined()
  expect(state.busy).toBe(false)
  expect(calls.filter(path => path.endsWith('/reply-recovery'))).toHaveLength(0)
})

it('keeps a healthy stream healthy when inflight receipt storage throws', async () => {
  const { state } = mount(); await flush()
  const originalSetItem = window.localStorage.setItem.bind(window.localStorage)
  const receiptWrite = vi.spyOn(window.localStorage, 'setItem').mockImplementation((key: string, value: string) => {
    if (String(key).startsWith('shenyu_pwa_inflight:')) throw new DOMException('receipt quota', 'QuotaExceededError')
    return originalSetItem(key, value)
  })
  const normalFetch = globalThis.fetch
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      return new Response('data: {"choices":[{"delta":{"content":"healthy despite receipt failure"}}]}\n\ndata: [DONE]\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return normalFetch(input, options)
  }))

  try {
    state.draft = 'receipt storage is not the network'
    await state.submit(); await flush()
    expect(state.messages.at(-1)?.content).toBe('healthy despite receipt failure')
    expect(state.messages.at(-1)?.truncated).toBeUndefined()
    expect(state.messages.at(-1)?.error).toBeUndefined()
    expect(state.receiptStorageError).toContain('恢复凭据')
  } finally {
    receiptWrite.mockRestore()
  }
})

it('persists an older photo reference that resolves while a new reply is streaming', async () => {
  const oldUser = row('user', 'u-old', 'old question')
  const oldReply = row('assistant', 'r-old', 'old answer')
  oldReply.attachments = [{ id: 'shared-photo', name: 'shared.jpg', mime: 'image/jpeg', fingerprint: 'b'.repeat(64) }]
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([oldUser, oldReply]))

  const normalFetch = globalThis.fetch
  let releaseAlbum!: () => void
  let closeStream!: () => void
  const encoder = new TextEncoder()
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    if (url.pathname.endsWith('/album/resolve')) {
      await new Promise<void>(resolve => { releaseAlbum = resolve })
      return Response.json({
        media: {
          'assistant:r-old': [{
            id: 'shared-photo', name: 'shared.jpg', mime: 'image/jpeg', fingerprint: 'b'.repeat(64),
            photo_id: 'phot_late_reference', title: 'kept', content: 'late stable reference',
          }],
        },
        photos: {},
      })
    }
    if (url.pathname === '/v1/chat/completions') {
      return new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"streaming"}}]}\n\n'))
          closeStream = () => {
            controller.enqueue(encoder.encode('data: [DONE]\n\n'))
            controller.close()
          }
        },
      }), { headers: { 'Content-Type': 'text/event-stream' } })
    }
    return normalFetch(input, options)
  }))

  const { state } = mount()
  for (let i = 0; i < 40 && !releaseAlbum; i++) await new Promise(resolve => setTimeout(resolve, 5))
  expect(releaseAlbum).toBeTypeOf('function')
  state.draft = 'new question while old photo resolves'
  const sending = state.submit()
  for (let i = 0; i < 40 && state.messages.at(-1)?.content !== 'streaming'; i++) {
    await new Promise(resolve => setTimeout(resolve, 5)); await nextTick()
  }
  expect(state.busy).toBe(true)

  releaseAlbum()
  for (let i = 0; i < 40 && state.messages[1]?.attachments[0]?.photoId !== 'phot_late_reference'; i++) {
    await new Promise(resolve => setTimeout(resolve, 5)); await nextTick()
  }
  expect(state.messages[1].attachments[0].photoId).toBe('phot_late_reference')
  expect(state.busy).toBe(true)

  closeStream()
  await sending; await flush()
  let persistedPhotoId: string | undefined
  for (let i = 0; i < 40 && persistedPhotoId !== 'phot_late_reference'; i++) {
    const store = new TranscriptStore()
    try {
      const saved = await store.load(transcriptKey('', 'A'))
      persistedPhotoId = saved?.state.messages[1]?.attachments[0]?.photoId
    } finally { store.close() }
    if (persistedPhotoId !== 'phot_late_reference') await new Promise(resolve => setTimeout(resolve, 5))
  }
  expect(persistedPhotoId).toBe('phot_late_reference')
})

it('bounds empty reply recovery retries without locking the UI or resending the model request', async () => {
  vi.useFakeTimers()
  try {
    const partial = row('assistant', 'reply-retry', 'kept partial')
    partial.truncated = true
    localStorage.setItem('shenyu_pwa_session', 'A')
    localStorage.setItem('shenyu_pwa_messages', JSON.stringify([row('user', 'u-retry', 'question'), partial]))
    localStorage.setItem(`shenyu_pwa_inflight:${transcriptKey('', 'A')}`, JSON.stringify({ replyVersionId: 'reply-retry' }))
    const normalFetch = globalThis.fetch
    const recoveryCalls: string[] = []
    const modelCalls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
      const url = new URL(String(input), window.location.href)
      if (url.pathname.endsWith('/reply-recovery')) {
        recoveryCalls.push(url.pathname)
        return Response.json({ replies: [] })
      }
      if (url.pathname === '/v1/chat/completions') {
        modelCalls.push(url.pathname)
        throw new Error('model must not be resent')
      }
      return normalFetch(input, options)
    }))

    const { state } = mount()
    await nextTick(); await vi.advanceTimersByTimeAsync(100)
    expect(recoveryCalls).toHaveLength(1)
    expect(state.busy).toBe(false)
    expect(state.controlsBlocked).toBe(false)
    expect(state.messages.at(-1)?.content).toBe('kept partial')

    await vi.advanceTimersByTimeAsync(5_000)
    expect(recoveryCalls).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(15_000)
    expect(recoveryCalls).toHaveLength(3)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(recoveryCalls).toHaveLength(4)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(recoveryCalls).toHaveLength(4)
    expect(modelCalls).toHaveLength(0)
    expect(state.busy).toBe(false)
    expect(state.controlsBlocked).toBe(false)
    expect(state.messages.at(-1)?.content).toBe('kept partial')
  } finally {
    vi.useRealTimers()
  }
})

it('ignores a late recovery after the user switches to an older variant', async () => {
  const partial = row('assistant', 'reply-current', 'partial current')
  partial.truncated = true
  partial.variants = [
    {
      content: 'older complete', echo: '', echoSegments: [], thinking: 'older thinking',
      thinkingSegments: [], events: [], attachments: [], replyVersionId: 'reply-old',
      archiveEvent: { id: 'reply-old', event_at: '2026-09-19T00:30:00Z' },
    },
    {
      content: 'partial current', echo: '', echoSegments: [], thinking: '',
      thinkingSegments: [], events: [], attachments: [], replyVersionId: 'reply-current',
      archiveEvent: partial.archiveEvent, truncated: true,
    },
  ]
  partial.selectedVariantIndex = 1
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem('shenyu_pwa_messages', JSON.stringify([row('user', 'u-late', 'same question'), partial]))
  localStorage.setItem(`shenyu_pwa_inflight:${transcriptKey('', 'A')}`, JSON.stringify({ replyVersionId: 'reply-current' }))
  const normalFetch = globalThis.fetch
  let releaseRecovery!: () => void
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    if (url.pathname.endsWith('/reply-recovery')) {
      await new Promise<void>(resolve => { releaseRecovery = resolve })
      return Response.json({ user_content: 'same question', replies: [
        { reply_version_id: 'reply-current', content: 'completed current after delay' },
      ] })
    }
    return normalFetch(input, options)
  }))

  const { state } = mount()
  for (let i = 0; i < 40 && !releaseRecovery; i++) await new Promise(resolve => setTimeout(resolve, 5))
  expect(releaseRecovery).toBeTypeOf('function')
  state.switchMessageVariant(1, -1); await nextTick()
  expect(state.messages[1].content).toBe('older complete')
  expect(state.messages[1].selectedVariantIndex).toBe(0)
  releaseRecovery()
  await flush(); await flush()
  expect(state.messages[1].content).toBe('older complete')
  expect(state.messages[1].thinking).toBe('older thinking')
  expect(state.messages[1].selectedVariantIndex).toBe(0)
  expect(state.messages[1].variants?.[1].content).toBe('partial current')
})

it('keeps a completed reply healthy when receipt removal fails, including on reopen', async () => {
  const { state } = mount(); await flush()
  const originalRemove = window.localStorage.removeItem.bind(window.localStorage)
  const removeReceipt = vi.spyOn(window.localStorage, 'removeItem').mockImplementation((key: string) => {
    if (String(key).startsWith('shenyu_pwa_inflight:')) throw new DOMException('receipt remove failed', 'QuotaExceededError')
    return originalRemove(key)
  })
  const normalFetch = globalThis.fetch
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(String(input), window.location.href)
    calls.push(url.pathname)
    if (url.pathname === '/v1/chat/completions') {
      return new Response('data: {"choices":[{"delta":{"content":"complete with stale receipt"}}]}\n\ndata: [DONE]\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return normalFetch(input, options)
  }))
  try {
    state.draft = 'finish despite remove failure'
    await state.submit(); await flush(); await flush()
    expect(state.messages.at(-1)?.content).toBe('complete with stale receipt')
    expect(state.messages.at(-1)?.truncated).toBeUndefined()
    expect(state.receiptStorageError).toContain('恢复凭据')
    const recoveryBeforeReopen = calls.filter(path => path.endsWith('/reply-recovery')).length

    apps.splice(0).forEach(app => app.unmount())
    await nextTick()
    const reopened = mount(); await flush(); await new Promise(resolve => setTimeout(resolve, 40))
    expect(reopened.state.messages.at(-1)?.content).toBe('complete with stale receipt')
    expect(reopened.state.messages.at(-1)?.truncated).toBeUndefined()
    expect(calls.filter(path => path.endsWith('/reply-recovery'))).toHaveLength(recoveryBeforeReopen)
  } finally {
    removeReceipt.mockRestore()
  }
})

it('keeps active text streaming free of full transcript checkpoints', async () => {
  const { state } = mount(); await flush()
  const save = vi.spyOn(TranscriptStore.prototype, 'save')
  const saveTail = vi.spyOn(TranscriptStore.prototype, 'saveTail')
  save.mockClear(); saveTail.mockClear()
  const normalFetch = globalThis.fetch
  let closeStream!: () => void
  const encoder = new TextEncoder()
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    if (String(input).includes('/v1/chat/completions')) {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"one"}}]}\n\n'))
          closeStream = () => {
            controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"two"}}]}\n\ndata: [DONE]\n\n'))
            controller.close()
          }
        },
      })
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
    return normalFetch(input, options)
  }))

  state.draft = 'stream without snapshot work'
  const sending = state.submit()
  for (let i = 0; i < 20 && state.messages.at(-1)?.content !== 'one'; i++) {
    await new Promise(resolve => setTimeout(resolve, 5)); await nextTick()
  }
  expect(state.messages.at(-1)?.content).toBe('one')
  expect(save).not.toHaveBeenCalled()
  const tailCallsDuringStream = saveTail.mock.calls.length

  closeStream()
  await sending; await flush()
  expect(state.messages.at(-1).content).toBe('onetwo')
  expect(state.messages.at(-1).truncated).toBeUndefined()
  expect(state.messages.at(-1).error).toBeUndefined()
  expect(save).not.toHaveBeenCalled()
  expect(saveTail.mock.calls.length).toBeGreaterThan(tailCallsDuringStream)
})

it('uses a lightweight inflight receipt to recover a stream after a process restart', async () => {
  const store = new TranscriptStore()
  const key = transcriptKey('', 'A')
  await store.save(key, {
    messages: [
      row('user', 'u1', 'question'),
      { ...row('assistant', 'reply-1', ''), replyVersionId: 'reply-1', archiveEvent: { id: 'reply-1', event_at: '2026-09-19T01:00:00Z' } },
    ],
    draft: '', pendingAttachments: [], editId: null, viewport: { atBottom: true },
  }, 0)
  store.close()
  localStorage.setItem('shenyu_pwa_session', 'A')
  localStorage.setItem(`shenyu_pwa_inflight:${key}`, JSON.stringify({ replyVersionId: 'reply-1' }))

  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = new URL(String(input), window.location.href)
    if (url.pathname.endsWith('/reply-recovery')) {
      return Response.json({
        user_content: 'question',
        replies: [{ reply_version_id: 'reply-1', content: 'recovered after restart' }],
      })
    }
    if (url.pathname.startsWith('/api/gateway/sessions/')) return Response.json({ context_snapshots: [], recent_messages: [] })
    if (url.pathname === '/api/gateway/sessions') return Response.json({ sessions: [] })
    if (url.pathname.endsWith('/album/resolve')) return Response.json({ media: {}, photos: {} })
    if (url.pathname === '/api/config') return Response.json({ max_client_messages: 75 })
    if (url.pathname === '/v1/models') return Response.json({ data: [] })
    throw new Error(`Unexpected request ${url.pathname}`)
  }))

  const { state } = mount(); await flush(); await new Promise(resolve => setTimeout(resolve, 80)); await nextTick()
  expect(state.messages.at(-1).content).toBe('recovered after restart')
  expect(state.messages.at(-1).truncated).toBeUndefined()
  expect(localStorage.getItem(`shenyu_pwa_inflight:${key}`)).toBeNull()
})
