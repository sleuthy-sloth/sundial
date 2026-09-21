/* sundial service worker: an offline shell, and the landing place for a
   notification. The API is deliberately never cached — a stale plan is worse
   than no plan.

   CACHE names the offline shell's own storage. The server sends `no-cache` for the shell
   and the worker and a year of `immutable` for the hashed assets, so a new build arrives
   on its own and nothing here has to be bumped by hand after a deploy. Change this name
   only if the caching in THIS file changes. */

const CACHE = 'sundial-shell-2'
const SHELL = ['/', '/manifest.webmanifest']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return // always live

  // Navigations: network first, so a deploy lands instead of being shadowed.
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/')))
    return
  }

  // Everything else is content-hashed by the build: cache first.
  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request).then((res) => {
          if (res.ok) {
            const copy = res.clone()
            caches.open(CACHE).then((cache) => cache.put(request, copy))
          }
          return res
        }),
    ),
  )
})

// A notification arrives here once the sending side exists (see the plan, phase 7).
self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { body: event.data?.text?.() ?? '' }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || 'sundial', {
      body: payload.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      tag: payload.tag || 'sundial',
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    self.clients.matchAll({ type: 'window' }).then((list) => {
      if (list.length) return list[0].focus()
      return self.clients.openWindow('/')
    }),
  )
})
