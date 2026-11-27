/**
 * Dual-layer durable local persistence for CampusHub (Web localStorage + Android atomic file store).
 *
 * On Android WebView, `localStorage` commits asynchronously through Chromium's LevelDB write-ahead buffer
 * and can lag behind abrupt app kills right after creating an event. Mirroring every mutation to
 * `window.NativeAuthBridge.writeNativeStore(key, json)` (which writes atomically with `fsync`) and
 * reconciling both layers on cold boot ensures zero data loss.
 */

import { parseEventModifiedMs, parseTimestampMs } from './lww.js'

export function hasNativeStore() {
  return Boolean(
    typeof window !== 'undefined' &&
      window.NativeAuthBridge &&
      typeof window.NativeAuthBridge.readNativeStore === 'function' &&
      typeof window.NativeAuthBridge.writeNativeStore === 'function',
  )
}

function safeParseJson(raw, fallback = null) {
  if (!raw || typeof raw !== 'string') return fallback
  try {
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

export function readDualJson(nativeKey, lsKey, fallback = null) {
  let lsVal = null
  try {
    if (typeof localStorage !== 'undefined' && lsKey) {
      lsVal = safeParseJson(localStorage.getItem(lsKey), null)
    }
  } catch {}

  let nativeVal = null
  try {
    if (hasNativeStore() && nativeKey) {
      nativeVal = safeParseJson(window.NativeAuthBridge.readNativeStore(nativeKey), null)
    }
  } catch {}

  return { lsVal, nativeVal, value: lsVal ?? nativeVal ?? fallback }
}

export function writeDualJson(nativeKey, lsKey, obj) {
  let raw = ''
  try {
    raw = JSON.stringify(obj)
  } catch {
    return false
  }
  let ok = false
  try {
    if (typeof localStorage !== 'undefined' && lsKey) {
      localStorage.setItem(lsKey, raw)
      ok = true
    }
  } catch {}
  try {
    if (hasNativeStore() && nativeKey) {
      window.NativeAuthBridge.writeNativeStore(nativeKey, raw)
      ok = true
    }
  } catch {}
  return ok
}

export function removeDualKey(nativeKey, lsKey) {
  try {
    if (typeof localStorage !== 'undefined' && lsKey) {
      localStorage.removeItem(lsKey)
    }
  } catch {}
  try {
    if (hasNativeStore() && nativeKey && typeof window.NativeAuthBridge.removeNativeStore === 'function') {
      window.NativeAuthBridge.removeNativeStore(nativeKey)
    }
  } catch {}
}

export function clearNativeStoreAll() {
  try {
    if (hasNativeStore() && typeof window.NativeAuthBridge.clearNativeStore === 'function') {
      window.NativeAuthBridge.clearNativeStore()
    }
  } catch {}
}

/**
 * Reconcile events cache across Chromium localStorage and Android atomic native file store.
 * Keeps every unique ID at its latest LWW modification timestamp and heals whichever layer lagged.
 */
export function readEventsCacheDual(lsKey) {
  const { lsVal, nativeVal } = readDualJson('events_cache', lsKey, null)
  const lsItems = Array.isArray(lsVal?.items) ? lsVal.items : []
  const natItems = Array.isArray(nativeVal?.items) ? nativeVal.items : []

  if (!lsItems.length && !natItems.length) {
    return {
      items: [],
      total: 0,
      timestamp: Math.max(Number(lsVal?.timestamp) || 0, Number(nativeVal?.timestamp) || 0) || null,
    }
  }

  const byId = new Map()
  for (const item of [...natItems, ...lsItems]) {
    if (!item || !item.id || item.hidden) continue
    const prev = byId.get(item.id)
    if (!prev || parseEventModifiedMs(item) >= parseEventModifiedMs(prev)) {
      byId.set(item.id, item)
    }
  }
  const mergedItems = [...byId.values()]
  const timestamp = Math.max(Number(lsVal?.timestamp) || 0, Number(nativeVal?.timestamp) || 0) || Date.now()
  return {
    items: mergedItems,
    total: mergedItems.length,
    timestamp,
  }
}

/** Union offline sync queues across localStorage and Android native store by `_qid`. */
export function readSyncQueueDual(lsKey) {
  const { lsVal, nativeVal } = readDualJson('sync_queue', lsKey, null)
  const qA = Array.isArray(lsVal) ? lsVal : []
  const qB = Array.isArray(nativeVal) ? nativeVal : []
  if (!qA.length && !qB.length) return []

  const byQid = new Map()
  let fallbackIdx = 0
  for (const item of [...qB, ...qA]) {
    if (!item || typeof item !== 'object') continue
    const key = item._qid || `__idx_${fallbackIdx++}`
    if (!byQid.has(key)) byQid.set(key, item)
  }
  return [...byQid.values()].sort((a, b) => (Number(a.timestamp) || 0) - (Number(b.timestamp) || 0))
}

/** Merge deleted-id tombstone maps across localStorage and Android native store (max timestamp wins). */
export function readDeletedIdsDual(lsKey, maxAgeMs = 30 * 86400000) {
  const { lsVal, nativeVal } = readDualJson('deleted_ids', lsKey, null)
  const now = Date.now()
  const merged = {}
  for (const src of [nativeVal, lsVal]) {
    if (!src || typeof src !== 'object') continue
    for (const [id, ts] of Object.entries(src)) {
      const num = Number(ts) || 0
      if (num > 0 && now - num < maxAgeMs) {
        merged[id] = Math.max(merged[id] || 0, num)
      }
    }
  }
  return merged
}

/** Merge completed-status override maps across localStorage and Android native store (latest timestamp wins). */
export function readCompletedOverridesDual(lsKey, maxAgeMs = 7 * 86400000) {
  const { lsVal, nativeVal } = readDualJson('completed_overrides', lsKey, null)
  const now = Date.now()
  const merged = {}
  for (const src of [nativeVal, lsVal]) {
    if (!src || typeof src !== 'object') continue
    for (const [id, item] of Object.entries(src)) {
      if (!item || typeof item !== 'object' || !item.status) continue
      const ts = parseTimestampMs(item.timestamp)
      if (ts > 0 && now - ts < maxAgeMs) {
        if (!merged[id] || ts >= parseTimestampMs(merged[id].timestamp)) {
          merged[id] = item
        }
      }
    }
  }
  return merged
}

/** Union important/starred event IDs across localStorage and Android native store. */
export function readImportantIdsDual(lsKey) {
  const { lsVal, nativeVal } = readDualJson('important_ids', lsKey, [])
  const out = new Set()
  for (const src of [nativeVal, lsVal]) {
    if (!Array.isArray(src)) continue
    for (const id of src) {
      if (typeof id === 'string' && id) out.add(id)
    }
  }
  return [...out]
}
