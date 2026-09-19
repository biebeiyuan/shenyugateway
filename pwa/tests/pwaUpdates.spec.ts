import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { usePwaUpdates, probeWorkerBuild } from '../src/usePwaUpdates'
import type { PwaBuildInfo } from '../src/buildInfo'

class Port {
  peer?: Port
  onmessage: ((event: { data: unknown }) => void) | null = null
  close() { this.onmessage = null }
  postMessage(data: unknown) { queueMicrotask(() => this.peer?.onmessage?.({ data })) }
}
class Channel {
  port1 = new Port(); port2 = new Port()
  constructor() { this.port1.peer = this.port2; this.port2.peer = this.port1 }
}
class Worker extends EventTarget {
  state = 'activated'
  constructor(public build: string | null) { super() }
  postMessage = vi.fn((data: any, ports: Port[]) => {
    if (this.build) ports[0].postMessage({ type: data.type, schema: 1, buildId: this.build })
  })
}
class Registration extends EventTarget {
  active: Worker | null = new Worker('old')
  waiting: Worker | null = null
  installing: Worker | null = null
  update = vi.fn(async () => {})
}
function harness(pageId = 'new') {
  vi.stubGlobal('MessageChannel', Channel)
  const registration = new Registration()
  const container = Object.assign(new EventTarget(), { controller: registration.active,
    getRegistration: vi.fn(async () => registration), ready: Promise.resolve(registration) })
  const deployed = ref<PwaBuildInfo | null>({ schema: 1, buildId: 'new', revision: 'new', builtAt: 'today' })
  const observer = usePwaUpdates(deployed, pageId, container as unknown as ServiceWorkerContainer)
  return { registration, container, observer }
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('separate page and offline worker evidence', () => {
  it('does not label an online new page as an updated offline shell while its controller is old', async () => {
    const { observer } = harness('new')
    await observer.refresh()
    expect(observer.evidence.value.controllerBuildId).toBe('old')
    expect(observer.status.value).toContain('离线页面仍是旧版')
    observer.stop()
  })
  it('shows a waiting candidate and never asks it to skipWaiting or reload', async () => {
    const { observer, registration } = harness()
    registration.waiting = new Worker('new'); registration.waiting.state = 'installed'
    await observer.refresh()
    expect(observer.evidence.value.waitingBuildId).toBe('new')
    expect(observer.status.value).toContain('已准备')
    expect(observer.status.value).toContain('关闭')
    expect(registration.waiting.postMessage.mock.calls.every(([data]) => data.type === 'SHENYU_PWA_BUILD_INFO')).toBe(true)
    observer.stop()
  })
  it('shows download progress separately from a ready offline build', async () => {
    const { observer, registration } = harness()
    registration.installing = new Worker('new'); registration.installing.state = 'installing'
    await observer.refresh()
    expect(observer.status.value).toContain('正在下载')
    observer.stop()
  })
  it('labels old nonresponding workers unknown rather than claiming they are current', async () => {
    vi.useFakeTimers(); vi.stubGlobal('MessageChannel', Channel)
    const promise = probeWorkerBuild(new Worker(null) as unknown as ServiceWorker)
    await vi.advanceTimersByTimeAsync(1500)
    expect(await promise).toBeNull()
  })
  it('does not let a delayed inspection overwrite the newer controller evidence', async () => {
    vi.useFakeTimers()
    const { observer, container, registration } = harness()
    container.controller = registration.active = new Worker(null)
    const old = observer.refresh()
    await vi.advanceTimersByTimeAsync(0)
    container.controller = registration.active = new Worker('new')
    await observer.refresh()
    await vi.advanceTimersByTimeAsync(1500); await old
    expect(observer.evidence.value.controllerBuildId).toBe('new')
    observer.stop()
  })
  it('reports failed update checks without discarding existing offline evidence', async () => {
    const { observer, registration } = harness()
    await observer.refresh()
    registration.update.mockRejectedValue(new TypeError('offline'))
    await observer.checkForUpdate()
    expect(observer.checkError.value).toBeTruthy()
    expect(observer.evidence.value.controllerBuildId).toBe('old')
    observer.stop()
  })
})

it('removes lifecycle listeners and ignores delayed evidence after disposal', async () => {
  vi.useFakeTimers()
  const { observer, container, registration } = harness()
  container.controller = registration.active = new Worker(null)
  observer.start()
  await vi.advanceTimersByTimeAsync(0)
  observer.stop()
  const calls = container.getRegistration.mock.calls.length
  registration.dispatchEvent(new Event('updatefound'))
  container.dispatchEvent(new Event('controllerchange'))
  await vi.advanceTimersByTimeAsync(1500)
  expect(container.getRegistration).toHaveBeenCalledTimes(calls)
  expect(observer.evidence.value.controllerBuildId).toBeNull()
})
