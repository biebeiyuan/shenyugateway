import { afterEach, expect, it, vi } from 'vitest'
import { fetchReplyRecovery, fetchSessionDetail } from '../src/api/client'
const ctx = { gatewayUrl: '', sessionTag: 'A', authToken: '' }
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('bounds a stalled recovery read so the retry chain can continue', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })))
  const failed = expect(fetchReplyRecovery(ctx, 'exact-id')).rejects.toThrow()
  await vi.advanceTimersByTimeAsync(12000)
  await failed
})
it('cancels obsolete session detail work through the passed operation signal', async () => {
  vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })))
  const controller = new AbortController()
  const failed = expect(fetchSessionDetail(ctx, 'A', 75, controller.signal)).rejects.toThrow()
  controller.abort()
  await failed
})
