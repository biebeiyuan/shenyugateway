// Production worker source is executed, not a reimplementation of its policy.
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { afterEach, describe, expect, it, vi } from 'vitest'
function harness() {
  const listeners: Record<string, (event: any) => void> = {}
  const values = new Map<string, Map<string, Response>>()
  const origin = 'https://example.test'
  const key = (request: any) => typeof request === 'string' ? new URL(request, origin).href : request.url
  const fetcher = vi.fn(async (request: any) => key(request).endsWith('build-info.json')
    ? Response.json({ buildId: 'build-test' }) : new Response(`network ${key(request)}`))
  const caches = {
    keys: async () => [...values.keys()],
    delete: vi.fn(async (name: string) => values.delete(name)),
    open: async (name: string) => {
      if (!values.has(name)) values.set(name, new Map())
      const cache = values.get(name)!
      return { match: async (request: any) => cache.get(key(request))?.clone(),
        put: async (request: any, value: Response) => { cache.set(key(request), value.clone()) },
        addAll: async (requests: string[]) => {
          for (const request of requests) {
            const response = await fetcher(request)
            if (!response.ok) throw new Error('precache failed')
            cache.set(key(request), response)
          }
        } }
    },
    match: async (request: any) => {
      for (const cache of values.values()) if (cache.has(key(request))) return cache.get(key(request))!.clone()
    },
  }
  const clients = { claim: vi.fn(), matchAll: vi.fn(async () => [{ url: origin + '/chat/' }]) }
  const skipWaiting = vi.fn()
  const source = readFileSync('public/sw.js', 'utf8')
    .replace('const BUILD_ID = null', 'const BUILD_ID = "build-test"')
    .replace('const PRECACHE_FILES = []', 'const PRECACHE_FILES = ["/chat/", "/chat/assets/main.js"]')
  runInNewContext(source, { self: { location: new URL(origin + '/chat/sw.js'), addEventListener: (name: string, callback: any) => { listeners[name] = callback }, skipWaiting, clients },
    caches, fetch: fetcher, URL, Request, Response, AbortController, setTimeout, clearTimeout })
  async function lifecycle(name: string) { const tasks: Promise<unknown>[] = []; listeners[name]({ waitUntil: (p: Promise<unknown>) => tasks.push(p) }); await Promise.all(tasks) }
  async function request(path: string) {
    let response: Promise<Response> | undefined
    listeners.fetch({ request: new Request(origin + path), respondWith: (value: Promise<Response>) => { response = value }, waitUntil: () => {} })
    return response
  }
  return { caches, values, fetcher, clients, skipWaiting, lifecycle, request, listeners }
}
afterEach(() => vi.useRealTimers())

describe('non-disruptive app shell updates', () => {
  it('installs a complete version without taking over or reloading existing pages', async () => {
    const h = harness(); await h.lifecycle('install')
    expect(h.skipWaiting).not.toHaveBeenCalled()
    const entries = [...h.values.values()]
    expect(entries.some(cache => cache.has('https://example.test/chat/') && cache.has('https://example.test/chat/assets/main.js'))).toBe(true)
    await h.lifecycle('activate')
    expect(h.clients.claim).not.toHaveBeenCalled()
  })
  it('keeps old assets while an existing page is still using them', async () => {
    const h = harness()
    await (await h.caches.open('shenyu-pwa-shell-old')).put('/chat/assets/old.js', new Response('old bundle'))
    await h.lifecycle('activate')
    expect(h.values.has('shenyu-pwa-shell-old')).toBe(true)
  })
  it('uses the paired cached entry for offline deep-link navigation', async () => {
    const h = harness(); await h.lifecycle('install')
    h.fetcher.mockRejectedValue(new TypeError('offline'))
    const response = await h.request('/chat/?session_tag=A')
    expect(await response?.text()).toContain('network https://example.test/chat/')
  })
  it('falls back to the paired entry for an HTTP error rather than replacing it', async () => {
    const h = harness(); await h.lifecycle('install')
    h.fetcher.mockResolvedValue(new Response('bad gateway', { status: 502 }))
    expect(await (await h.request('/chat/'))?.text()).toContain('network https://example.test/chat/')
  })
  it('falls back without waiting indefinitely for a silent connection', async () => {
    vi.useFakeTimers()
    const h = harness(); await h.lifecycle('install')
    h.fetcher.mockImplementation(() => new Promise(() => {}))
    const response = h.request('/chat/')
    await vi.advanceTimersByTimeAsync(2000)
    expect(await (await response)?.text()).toContain('network https://example.test/chat/')
  })
  it('never serves cached build proof or chat APIs', async () => {
    const h = harness(); await h.lifecycle('install')
    h.fetcher.mockRejectedValue(new TypeError('offline'))
    await expect(h.request('/chat/build-info.json')).rejects.toThrow('offline')
    expect(await h.request('/api/gateway/sessions')).toBeUndefined()
  })
  it('rejects an incomplete candidate without deleting the old shell', async () => {
    const h = harness()
    await (await h.caches.open('shenyu-pwa-shell-old')).put('/chat/', new Response('old page'))
    h.fetcher.mockImplementation(async (request: any) => String(request?.url || request).includes('main.js')
      ? new Response('missing', { status: 404 }) : Response.json({ buildId: 'build-test' }))
    await expect(h.lifecycle('install')).rejects.toThrow()
    expect(h.values.has('shenyu-pwa-shell-old')).toBe(true)
    expect([...h.values.keys()].filter(name => name !== 'shenyu-pwa-shell-old')).toHaveLength(0)
  })
})

it('reports its own paired build over a read-only message port, without activation side effects', () => {
  const h = harness()
  const port = { postMessage: vi.fn() }
  expect(h.listeners.message).toBeTypeOf('function')
  h.listeners.message({ data: { type: 'SHENYU_PWA_BUILD_INFO' }, ports: [port] })
  expect(port.postMessage).toHaveBeenCalledWith({ type: 'SHENYU_PWA_BUILD_INFO', schema: 1, buildId: 'build-test' })
  h.listeners.message({ data: { type: 'SKIP_WAITING' }, ports: [port] })
  expect(port.postMessage).toHaveBeenCalledTimes(1)
  expect(h.skipWaiting).not.toHaveBeenCalled()
  expect(h.clients.claim).not.toHaveBeenCalled()
})
