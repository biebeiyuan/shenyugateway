// Filled by the production build after index.html and hashed assets exist.
const BUILD_ID = null
const PRECACHE_FILES = []
const PREFIX = 'shenyu-pwa-shell-'
const CACHE = `${PREFIX}${BUILD_ID}`
const ENTRY = '/chat/'

async function deployedBuild() {
  const response = await fetch(new Request(new URL('/chat/build-info.json', self.location.origin), { cache: 'no-store' }))
  if (!response.ok) throw new Error('build proof unavailable')
  return (await response.json()).buildId
}

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    if (!BUILD_ID || !PRECACHE_FILES.length) throw new Error('unbuilt service worker')
    try {
      if (await deployedBuild() !== BUILD_ID) throw new Error('deployment changed before precache')
      const cache = await caches.open(CACHE)
      await cache.addAll(PRECACHE_FILES.map(path => new Request(new URL(path, self.location.origin), { cache: 'reload' })))
      if (await deployedBuild() !== BUILD_ID) throw new Error('deployment changed during precache')
    } catch (error) {
      await caches.delete(CACHE)
      throw error
    }
    // Do not skipWaiting: an active conversation must keep its current worker.
  })())
})

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    // An uncontrolled page may still reference the previous build. Leave its
    // resources alone; cleanup is safe after all chat pages have closed.
    const pages = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    if (pages.some(page => new URL(page.url).pathname.startsWith('/chat/'))) return
    const keys = await caches.keys()
    await Promise.all(keys.filter(key => key.startsWith(PREFIX) && key !== CACHE).map(key => caches.delete(key)))
    // Do not clients.claim: no controllerchange-triggered interruption.
  })())
})

async function navigate(request) {
  const cache = await caches.open(CACHE)
  const cached = await cache.match(ENTRY)
  const controller = new AbortController()
  let timer
  const fresh = fetch(new Request(request, { cache: 'no-store', signal: controller.signal }))
    .then(response => response.ok || !cached ? response : cached)
    .catch(error => { if (cached) return cached; throw error })
  if (!cached) return fresh
  try {
    return await Promise.race([fresh, new Promise(resolve => {
      timer = setTimeout(() => { controller.abort(); resolve(cached) }, 1200)
    })])
  } finally {
    clearTimeout(timer)
  }
  // Never replace the paired cached index with HTML from a different build.
}

self.addEventListener('fetch', event => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== self.location.origin) return
  if (url.pathname.includes('/v1/') || url.pathname.includes('/api/') || !url.pathname.startsWith('/chat/')) return
  if (url.pathname === '/chat/build-info.json') {
    event.respondWith(fetch(new Request(request, { cache: 'no-store' })))
    return
  }
  if (request.mode === 'navigate' || url.pathname === ENTRY) {
    event.respondWith(navigate(request))
    return
  }
  event.respondWith((async () => {
    const own = await caches.open(CACHE)
    return await own.match(request) || await caches.match(request) || fetch(request)
  })())
})
