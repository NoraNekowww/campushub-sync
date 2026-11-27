/* CampusHub Sync service worker.
 *
 * Strategy
 *   • app shell / hashed assets → cache-first (they are immutable per build)
 *   • wallpapers (same-origin & cross-origin Unsplash/CDN) → persistent cache-first
 *     across SW versions (`campushub-wallpapers-v1`), ensuring instant 0ms background paint
 *   • navigation              → network-first, fall back to the cached shell
 *   • api/events|status|config (GET) → network-first with a stale fallback so the
 *     agenda still renders offline; everything else under the API is passthrough.
 *
 * Every path is derived from the registration scope, so one bundle works both
 * at `/` (local, Docker) and at `/schedule/` (nzlab.online).
 */
const VERSION = 'campushub-v104'
const SHELL_CACHE = `${VERSION}-shell`
const DATA_CACHE = `${VERSION}-data`
const WALLPAPER_CACHE = 'campushub-wallpapers-v1'

const BASE = new URL(self.registration.scope).pathname // '/', '/schedule/'
const SHELL = [
  BASE,
  `${BASE}index.html`,
  `${BASE}favicon.ico`,
  `${BASE}widget.html`,
  `${BASE}manifest.webmanifest`,
  `${BASE}widgets/today-template.json`,
  `${BASE}icons/icon-192.png`,
  `${BASE}wallpapers/default-light.jpg`,
  `${BASE}wallpapers/default-dark.jpg`,
]
const API_PREFIX = `${BASE}api/`
const CACHEABLE_API = ['events', 'status', 'config', 'widgets']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys()
      await Promise.all(
        keys
          .filter((k) => !k.startsWith(VERSION) && k !== WALLPAPER_CACHE)
          .map((k) => caches.delete(k)),
      )
      await self.clients.claim()
    })(),
  )
})

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName)
  try {
    const response = await fetch(request)
    if (response && response.ok) cache.put(request, response.clone())
    return response
  } catch (error) {
    const cached = await cache.match(request)
    if (cached) return cached
    throw error
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName)
  const cached = await cache.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response && (response.ok || response.type === 'opaque')) {
    cache.put(request, response.clone())
  }
  return response
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)

  // Cross-origin wallpaper image requests: persist in long-lived WALLPAPER_CACHE
  if (url.origin !== self.location.origin) {
    if (request.destination === 'image' || url.hostname.includes('unsplash.com')) {
      event.respondWith(cacheFirst(request, WALLPAPER_CACHE))
    }
    return
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          return await fetch(request)
        } catch (error) {
          const cache = await caches.open(SHELL_CACHE)
          return (
            (await cache.match(`${BASE}index.html`)) ||
            (await cache.match(BASE)) ||
            Response.error()
          )
        }
      })(),
    )
    return
  }

  if (url.pathname.startsWith(`${BASE}wallpapers/`)) {
    event.respondWith(cacheFirst(request, WALLPAPER_CACHE))
    return
  }

  if (url.pathname.startsWith(API_PREFIX)) {
    const rest = url.pathname.slice(API_PREFIX.length)
    if (CACHEABLE_API.some((endpoint) => rest.startsWith(endpoint))) {
      event.respondWith(networkFirst(request, DATA_CACHE))
    }
    return
  }

  event.respondWith(
    cacheFirst(request, SHELL_CACHE).catch(async () => (await caches.match(`${BASE}index.html`)) || Response.error()),
  )
})

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting()
  // Signing out must not leave another account's timeline in the cache.
  if (event.data === 'clear-data-cache') event.waitUntil(caches.delete(DATA_CACHE))
})

/* ------------------------------------------------------------------ PWA Widgets */

async function updatePwaWidget(widget) {
  if (!widget) return
  try {
    const resp = await fetch(`${API_PREFIX}widgets/today`)
    if (!resp.ok) return
    const data = await resp.json()
    const templateResp = await fetch(`${BASE}widgets/today-template.json`)
    if (!templateResp.ok) return
    const template = await templateResp.text()

    if (self.widgets && self.widgets.updateByTag) {
      await self.widgets.updateByTag('today-agenda', {
        template,
        data: JSON.stringify(data),
      })
    }
  } catch (e) {
    // 离线时不打断
  }
}

self.addEventListener('widgetinstall', (event) => {
  event.waitUntil(updatePwaWidget(event.widget))
})

self.addEventListener('widgetresume', (event) => {
  event.waitUntil(updatePwaWidget(event.widget))
})

self.addEventListener('widgetclick', (event) => {
  event.waitUntil(
    (async () => {
      const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      if (allClients.length > 0) {
        allClients[0].focus()
      } else {
        await self.clients.openWindow(BASE)
      }
    })(),
  )
})
