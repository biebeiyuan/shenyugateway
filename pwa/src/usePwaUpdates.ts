import { computed, ref, type Ref } from 'vue'
import type { PwaBuildInfo } from './buildInfo'

const BUILD_QUERY = 'SHENYU_PWA_BUILD_INFO'
type Evidence = {
  supported: boolean; registered: boolean; installing: boolean; waiting: boolean; controlled: boolean
  controllerBuildId: string | null; activeBuildId: string | null; waitingBuildId: string | null
}

// Old installed workers do not implement this message. Silence is "unknown",
// never evidence that the page's build is also its offline build.
export function probeWorkerBuild(worker: ServiceWorker | null): Promise<string | null> {
  if (!worker || typeof MessageChannel === 'undefined') return Promise.resolve(null)
  return new Promise(resolve => {
    const channel = new MessageChannel()
    let settled = false
    const finish = (build: string | null) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      channel.port1.close(); channel.port2.close()
      resolve(build)
    }
    const timer = setTimeout(() => finish(null), 1000)
    channel.port1.onmessage = ({ data }) => {
      if (data?.type === BUILD_QUERY && data.schema === 1 && typeof data.buildId === 'string' && data.buildId.trim()) finish(data.buildId)
    }
    channel.port1.onmessageerror = () => finish(null)
    try { worker.postMessage({ type: BUILD_QUERY }, [channel.port2]) } catch { finish(null) }
  })
}

// Read-only observer. No skipWaiting, claim, reload or cache mutation.
export function usePwaUpdates(deployed: Ref<PwaBuildInfo | null>, pageBuildId: string,
  container: ServiceWorkerContainer | undefined = navigator.serviceWorker) {
  const evidence = ref<Evidence>({ supported: Boolean(container), registered: false,
    installing: false, waiting: false, controlled: false, controllerBuildId: null, activeBuildId: null, waitingBuildId: null })
  const checkError = ref('')
  let stopped = false, generation = 0, started = false
  let registration: ServiceWorkerRegistration | undefined
  const cleanup: (() => void)[] = []
  const status = computed(() => {
    const value = evidence.value
    if (!value.supported) return '此浏览器不支持离线页面。聊天记录仍由本机存储保存。'
    if (value.installing) return '正在下载离线页面；当前聊天不会刷新。'
    if (value.waiting) return '新版离线页面已准备，等待旧聊天页面关闭后切换。切后台不一定等于关闭。'
    if (!value.registered) return '离线页面尚未准备好。'
    const offline = value.controlled ? value.controllerBuildId : value.activeBuildId
    if (!offline) return '当前离线版本暂时无法核验，旧版可能不支持版本查询。'
    if (deployed.value && offline !== deployed.value.buildId) return '离线页面仍是旧版；在线打开新版不代表离线更新已经完成。'
    if (deployed.value && pageBuildId !== deployed.value.buildId) return '发现新版，本页保持原样；先保存内容，再关闭旧聊天页面后重开。'
    return value.controlled ? '本页使用的离线页面已准备。' : '离线页面已准备，本页尚未由它管理。'
  })

  function unbind() { cleanup.splice(0).forEach(fn => fn()) }
  function bind(value: ServiceWorkerRegistration) {
    unbind()
    const changed = () => { void refresh() }
    value.addEventListener('updatefound', changed)
    cleanup.push(() => value.removeEventListener('updatefound', changed))
    for (const worker of [value.installing, value.waiting, value.active]) {
      if (!worker) continue
      worker.addEventListener('statechange', changed)
      cleanup.push(() => worker.removeEventListener('statechange', changed))
    }
  }

  async function refresh() {
    if (!container || stopped) return
    const token = ++generation
    try {
      const value = await container.getRegistration(new URL('/chat/', window.location.href).href)
      if (stopped || token !== generation) return
      registration = value
      if (!value) { unbind(); evidence.value = { ...evidence.value, registered: false }; return }
      bind(value)
      const controller = container.controller, active = value.active, waiting = value.waiting
      evidence.value = { ...evidence.value, registered: true, installing: Boolean(value.installing), waiting: Boolean(waiting) }
      const [controllerBuildId, activeBuildId, waitingBuildId] = await Promise.all([
        probeWorkerBuild(controller), active === controller ? Promise.resolve(null) : probeWorkerBuild(active), probeWorkerBuild(waiting),
      ])
      if (stopped || token !== generation) return
      evidence.value = { supported: true, registered: true, installing: Boolean(value.installing), waiting: Boolean(value.waiting),
        controlled: Boolean(controller), controllerBuildId, activeBuildId: active === controller ? controllerBuildId : activeBuildId, waitingBuildId }
    } catch {
      if (!stopped && token === generation) checkError.value = '暂时无法读取离线版本；没有删除缓存或记录。'
    }
  }

  async function checkForUpdate() {
    await refresh()
    if (stopped || !registration) return
    checkError.value = ''
    try { await registration.update() }
    catch { if (!stopped) checkError.value = '暂时无法检查离线更新；已有离线页面和聊天记录未删除。' }
    if (!stopped) await refresh()
  }
  const controllerChanged = () => { void refresh() }
  function start() {
    if (!container || started || stopped) return
    started = true
    container.addEventListener('controllerchange', controllerChanged)
    void refresh()
    void container.ready.then(() => { if (!stopped) void refresh() }).catch(() => undefined)
  }
  function stop() {
    stopped = true; ++generation; unbind()
    container?.removeEventListener('controllerchange', controllerChanged)
  }
  return { evidence, status, checkError, refresh, checkForUpdate, start, stop }
}
