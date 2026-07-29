const CACHE = 'shenyu-pwa-shell-v3'

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith('shenyu-pwa-shell-') && key !== CACHE).map((key) => caches.delete(key)),
    )).then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.pathname.includes('/v1/') || url.pathname.includes('/api/')) return
  if (!url.pathname.startsWith('/chat/')) return

  const isNavigation = request.mode === 'navigate' || url.pathname === '/chat/'
  if (isNavigation) {
    // Do not let an HTTP-cached index keep pointing at an old hashed bundle.
    const freshRequest = new Request(request, { cache: 'no-store' })
    event.respondWith(
      fetch(freshRequest).then((response) => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(CACHE).then((cache) => cache.put(request, copy))
        }
        return response
      }).catch(() => caches.match(request)),
    )
    return
  }

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone()
        caches.open(CACHE).then((cache) => cache.put(request, copy))
      }
      return response
    })),
  )
})
