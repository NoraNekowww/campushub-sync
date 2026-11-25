/**
 * Persistent local wallpaper cache:
 * 1. Bundled local default wallpapers (`/wallpapers/default-light.jpg`, `/wallpapers/default-dark.jpg`)
 *    guarantee 0ms rendering even on first cold boot or offline launch.
 * 2. Synchronous `localStorage` DataURL snapshot guarantees 0ms frame-1 rendering for ANY
 *    previously selected remote wallpaper without waiting for network or async IndexedDB/Cache API.
 * 3. `CacheStorage` (`campushub-wallpapers-v1`, preserved across SW version bumps) stores full-resolution
 *    image blobs so full-HD textures are served locally without re-downloading.
 */

export const WALLPAPER_CACHE_NAME = 'campushub-wallpapers-v1'
const SNAP_LIGHT_KEY = 'campushub.bg_snap_light.v1'
const SNAP_DARK_KEY = 'campushub.bg_snap_dark.v1'

export const DEFAULT_REMOTE_LIGHT =
  'https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?auto=format&fit=crop&w=1920&q=85'
export const DEFAULT_REMOTE_DARK =
  'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1920&q=85'

function basePrefix() {
  const b = (typeof import.meta !== 'undefined' && import.meta.env?.BASE_URL) || '/'
  return b.endsWith('/') ? b : `${b}/`
}

export function getBundledDefaultUrl(isDark = false) {
  return `${basePrefix()}wallpapers/${isDark ? 'default-dark.jpg' : 'default-light.jpg'}`
}

const memoryBlobUrls = new Map()

function readSnap(isDark) {
  try {
    if (typeof localStorage === 'undefined') return null
    const raw = localStorage.getItem(isDark ? SNAP_DARK_KEY : SNAP_LIGHT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed.sourceUrl === 'string' && typeof parsed.dataUrl === 'string') {
      return parsed
    }
  } catch {}
  return null
}

function writeSnap(isDark, sourceUrl, dataUrl) {
  if (!sourceUrl || !dataUrl) return
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(
      isDark ? SNAP_DARK_KEY : SNAP_LIGHT_KEY,
      JSON.stringify({ sourceUrl, dataUrl, ts: Date.now() }),
    )
  } catch {
    // Quota exceeded: evict older opposite-slot snap only if needed, otherwise rely on CacheStorage
  }
}

export function clearWallpaperSnapshots() {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(SNAP_LIGHT_KEY)
      localStorage.removeItem(SNAP_DARK_KEY)
    }
  } catch {}
}

/**
 * Synchronously return an immediately renderable URL for the target wallpaper:
 * - In-memory Blob URL (if already hydrated this session)
 * - `data:` / `blob:` / same-origin bundled asset URL
 * - Synchronous `localStorage` compressed snapshot matching `targetUrl`
 * - Bundled local default wallpaper when `targetUrl` is the default wallpaper
 * - Finally `targetUrl` itself while background caching runs
 */
export function getInstantWallpaperSrc(targetUrl, isDark = false) {
  if (!targetUrl) return ''
  if (targetUrl.startsWith('data:') || targetUrl.startsWith('blob:')) return targetUrl
  if (memoryBlobUrls.has(targetUrl)) return memoryBlobUrls.get(targetUrl)

  const snap = readSnap(isDark)
  if (snap && snap.sourceUrl === targetUrl && snap.dataUrl) {
    return snap.dataUrl
  }

  if (!isDark && targetUrl === DEFAULT_REMOTE_LIGHT) {
    return getBundledDefaultUrl(false)
  }
  if (isDark && targetUrl === DEFAULT_REMOTE_DARK) {
    return getBundledDefaultUrl(true)
  }

  return targetUrl
}

async function blobToSnapshotDataUrl(blob) {
  if (typeof document === 'undefined' || typeof Image === 'undefined') return ''
  return new Promise((resolve) => {
    const tempUrl = URL.createObjectURL(blob)
    const img = new Image()
    img.onload = () => {
      try {
        const maxSide = 1280
        let w = img.naturalWidth || img.width || 1280
        let h = img.naturalHeight || img.height || 720
        if (w > maxSide || h > maxSide) {
          if (w >= h) {
            h = Math.max(1, Math.round((h * maxSide) / w))
            w = maxSide
          } else {
            w = Math.max(1, Math.round((w * maxSide) / h))
            h = maxSide
          }
        }
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0, w, h)
        const dataUrl = canvas.toDataURL('image/jpeg', 0.78)
        resolve(dataUrl)
      } catch {
        resolve('')
      } finally {
        URL.revokeObjectURL(tempUrl)
      }
    }
    img.onerror = () => {
      URL.revokeObjectURL(tempUrl)
      resolve('')
    }
    img.src = tempUrl
  })
}

async function fetchAndCacheSingle(url, isDark) {
  if (!url || url.startsWith('data:') || url.startsWith('blob:')) return url
  // Default bundled URLs are already local static assets precached by SW & APK assets
  if (url.includes('/wallpapers/default-')) return url

  if (memoryBlobUrls.has(url)) {
    const existingSnap = readSnap(isDark)
    if (existingSnap?.sourceUrl === url) return memoryBlobUrls.get(url)
  }

  let response = null
  let cache = null
  try {
    if (typeof caches !== 'undefined') {
      cache = await caches.open(WALLPAPER_CACHE_NAME)
      response = await cache.match(url)
    }
  } catch {}

  if (!response) {
    try {
      const fetched = await fetch(url, { mode: 'cors', credentials: 'omit' })
      if (fetched && fetched.ok) {
        if (cache) {
          try {
            await cache.put(url, fetched.clone())
          } catch {}
        }
        response = fetched
      }
    } catch {
      return null
    }
  }

  if (!response) return null

  try {
    const blob = await response.blob()
    if (!blob || !blob.size) return null

    const snap = readSnap(isDark)
    if (!snap || snap.sourceUrl !== url) {
      const dataUrl = await blobToSnapshotDataUrl(blob)
      if (dataUrl) writeSnap(isDark, url, dataUrl)
    }

    if (!memoryBlobUrls.has(url)) {
      const objUrl = URL.createObjectURL(blob)
      memoryBlobUrls.set(url, objUrl)
    }
    return memoryBlobUrls.get(url)
  } catch {
    return null
  }
}

/**
 * Ensure both light and dark wallpapers are cached locally in CacheStorage + localStorage snapshot.
 * Calls `onResolved()` whenever a cached blob/snapshot becomes ready so reactive UI can update.
 */
export async function ensureWallpapersCached({ lightUrl, darkUrl, isDark = false } = {}, onResolved = null) {
  if (typeof window === 'undefined') return
  const primaryUrl = isDark ? darkUrl : lightUrl
  const secondaryUrl = isDark ? lightUrl : darkUrl

  if (primaryUrl) {
    const resolvedPrimary = await fetchAndCacheSingle(primaryUrl, isDark)
    if (resolvedPrimary && typeof onResolved === 'function') onResolved()
  }
  if (secondaryUrl && secondaryUrl !== primaryUrl) {
    const resolvedSecondary = await fetchAndCacheSingle(secondaryUrl, !isDark)
    if (resolvedSecondary && typeof onResolved === 'function') onResolved()
  }
}
