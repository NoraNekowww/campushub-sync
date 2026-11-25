import { dayKey, toDate } from './datetime.js'

/** Pure-JS synchronous SHA-256 hex (matches Python hashlib.sha256(...).hexdigest()). */
const K256 = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

export function sha256Hex(text) {
  const bytes = new TextEncoder().encode(String(text))
  const bitLenHi = Math.floor((bytes.length * 8) / 0x100000000)
  const bitLenLo = (bytes.length * 8) >>> 0
  const paddedLen = (((bytes.length + 9 + 63) >> 6) << 6)
  const buf = new Uint8Array(paddedLen)
  buf.set(bytes)
  buf[bytes.length] = 0x80
  const dv = new DataView(buf.buffer)
  dv.setUint32(paddedLen - 8, bitLenHi, false)
  dv.setUint32(paddedLen - 4, bitLenLo, false)

  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19
  const w = new Uint32Array(64)

  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(offset + i * 4, false)
    for (let i = 16; i < 64; i++) {
      const x = w[i - 15]
      const s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3)
      const y = w[i - 2]
      const s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7
    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7))
      const ch = (e & f) ^ (~e & g)
      const t1 = (h + S1 + ch + K256[i] + w[i]) >>> 0
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10))
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + maj) >>> 0
      h = g; g = f; f = e; e = (d + t1) >>> 0
      d = c; c = b; b = a; a = (t1 + t2) >>> 0
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((v) => v.toString(16).padStart(8, '0'))
    .join('')
}

/** Deterministic 32-char event ID identical to backend `make_event_id(Source.custom, sourceId)`. */
export function makeCustomEventId(sourceId) {
  return sha256Hex(`custom:${sourceId}`).slice(0, 32)
}

/** Generate a globally unique `source_id` for a locally created custom event. */
export function generateClientSourceId(suffix = '') {
  const rand = `${Math.random().toString(36).slice(2, 10)}${Math.random().toString(36).slice(2, 6)}`
  return suffix ? `custom-${Date.now()}-${rand}-${suffix}` : `custom-${Date.now()}-${rand}`
}

/** Parse ISO string or epoch ms into finite epoch milliseconds (0 if invalid). */
export function parseTimestampMs(raw) {
  if (!raw) return 0
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : 0
  const parsed = toDate(raw)
  if (parsed) return parsed.getTime()
  const ms = new Date(raw).getTime()
  return Number.isFinite(ms) ? ms : 0
}

/** Return an event's latest modification timestamp in epoch ms (Last-Write-Wins). */
export function parseEventModifiedMs(event) {
  if (!event) return 0
  const clientMs = parseTimestampMs(event.client_updated_at)
  const updatedMs = parseTimestampMs(event.updated_at)
  if (clientMs || updatedMs) return Math.max(clientMs, updatedMs)
  return parseTimestampMs(event.created_at)
}

/**
 * Compute a strictly monotonic ISO timestamp for a local mutation:
 * always >= (Date.now() + clockOffsetMs) AND >= (existingEvent's modifiedMs + 1ms),
 * eliminating resurrected status or reverted edits caused by client/server clock skew.
 */
let lastIssuedMs = 0
export function computeNextMutationIso(existingEvent = null, clockOffsetMs = 0) {
  const alignedNow = Date.now() + (Number.isFinite(clockOffsetMs) ? clockOffsetMs : 0)
  const prevMs = existingEvent ? parseEventModifiedMs(existingEvent) : 0
  const nextMs = Math.max(alignedNow, prevMs + 1, lastIssuedMs + 1)
  lastIssuedMs = nextMs
  return new Date(nextMs).toISOString()
}

/**
 * Align and merge a server event with the local copy using Last-Write-Wins (LWW).
 * Protects pending local mutations (edits, status toggles, deletions) from being
 * overwritten by stale cloud snapshots while applying newer remote changes cleanly.
 */
export function mergeServerEventWithLocal(
  serverItem,
  localItem,
  { hasPendingSync = false, completedOverride = null, deletedAtMs = 0 } = {},
) {
  const serverTs = parseTimestampMs(
    serverItem?.updated_at || serverItem?.client_updated_at || serverItem?.created_at,
  )
  const overrideTs = parseTimestampMs(completedOverride?.timestamp)
  const overrideStatus = completedOverride?.status || null
  const delTs = parseTimestampMs(deletedAtMs)

  // Local tombstone newer than server version -> stays hidden/deleted
  if (delTs > 0 && (hasPendingSync || delTs > serverTs)) {
    return {
      ...(localItem || serverItem),
      hidden: true,
      updated_at: new Date(delTs).toISOString(),
      client_updated_at: new Date(delTs).toISOString(),
    }
  }

  if (localItem) {
    const localTs = parseEventModifiedMs(localItem)
    const shouldKeepLocal = hasPendingSync || localTs > serverTs
    if (shouldKeepLocal) {
      if (overrideStatus && overrideTs >= localTs) {
        return {
          ...localItem,
          status: overrideStatus,
          completed_at:
            overrideStatus === 'completed'
              ? localItem.completed_at || new Date(overrideTs).toISOString()
              : null,
          updated_at: new Date(overrideTs).toISOString(),
          client_updated_at: new Date(overrideTs).toISOString(),
        }
      }
      return localItem
    }
  }

  const alignedBase = {
    ...serverItem,
    client_updated_at: serverItem?.updated_at || serverItem?.client_updated_at || null,
  }

  if (overrideStatus && !alignedBase.hidden && (hasPendingSync || overrideTs > serverTs)) {
    const winnerMs = Math.max(serverTs, overrideTs)
    const winnerIso = winnerMs > 0 ? new Date(winnerMs).toISOString() : serverItem?.updated_at
    return {
      ...alignedBase,
      status: overrideStatus,
      completed_at: overrideStatus === 'completed' ? serverItem?.completed_at || winnerIso : null,
      updated_at: winnerIso,
      client_updated_at: winnerIso,
    }
  }

  return alignedBase
}

/**
 * Reconcile a newly created server event against a local item that may have
 * been toggled or edited while `create` was in flight.
 */
export function mergeSyncedCreateResult(
  serverItem,
  localBefore,
  { createClientUpdatedAt = null, completedOverride = null } = {},
) {
  const alignedServerTs = serverItem?.updated_at || createClientUpdatedAt || null
  if (!localBefore) {
    return { ...serverItem, client_updated_at: alignedServerTs }
  }

  const createTs = parseTimestampMs(createClientUpdatedAt || localBefore.created_at)
  const localTs = parseEventModifiedMs(localBefore)
  const overrideStatus = completedOverride?.status || null
  const overrideTs = parseTimestampMs(completedOverride?.timestamp)

  if (localTs > createTs || overrideStatus) {
    const nextStatus = overrideStatus || localBefore.status || serverItem.status
    const winnerMs = Math.max(localTs, overrideTs, createTs)
    return {
      ...serverItem,
      title: localBefore.title ?? serverItem.title,
      description: localBefore.description ?? serverItem.description,
      location: localBefore.location ?? serverItem.location,
      start_time: localBefore.start_time ?? serverItem.start_time,
      end_time: localBefore.end_time !== undefined ? localBefore.end_time : serverItem.end_time,
      is_deadline: localBefore.is_deadline ?? serverItem.is_deadline,
      is_undated: localBefore.is_undated ?? serverItem.is_undated,
      priority: localBefore.priority ?? serverItem.priority,
      hidden: Boolean(localBefore.hidden),
      status: nextStatus,
      completed_at:
        nextStatus === 'completed'
          ? localBefore.completed_at || new Date(winnerMs).toISOString()
          : null,
      updated_at: localBefore.updated_at || serverItem.updated_at,
      client_updated_at: localBefore.client_updated_at || new Date(winnerMs).toISOString(),
    }
  }

  return {
    ...serverItem,
    client_updated_at: alignedServerTs,
  }
}

/** Return true if a queued patch response is still the latest state for `localCurrent`. */
export function shouldApplySyncedPatchResult(localCurrent, patchClientUpdatedAt) {
  if (!localCurrent) return false
  if (!patchClientUpdatedAt) return true
  const patchTs = parseTimestampMs(patchClientUpdatedAt)
  const localTs = parseEventModifiedMs(localCurrent)
  return localTs <= patchTs
}

/**
 * Reconcile local event store with incoming server items strictly by `id` and
 * Last-Write-Wins modification timestamp (`updated_at` / `client_updated_at`).
 * Returns `{ activeEvents, nextDeletedMap }`.
 */
export function reconcileEventCollections({
  localEvents = [],
  serverItems = [],
  pendingIds = new Set(),
  completedOverrides = {},
  deletedMap = {},
  windowStartKey = '',
  windowEndKey = '',
  queriedUndated = false,
  serverWindowComplete = false,
} = {}) {
  const nextDeletedMap = { ...deletedMap }

  // 1. Collapse local list by canonical id (highest modified timestamp wins)
  const localById = new Map()
  for (const item of Array.isArray(localEvents) ? localEvents : []) {
    if (!item || !item.id) continue
    const prev = localById.get(item.id)
    if (!prev || parseEventModifiedMs(item) >= parseEventModifiedMs(prev)) {
      localById.set(item.id, item)
    }
  }

  // 2. Collapse server list by canonical id (highest updated_at wins)
  const serverById = new Map()
  for (const item of Array.isArray(serverItems) ? serverItems : []) {
    if (!item || !item.id) continue
    const prev = serverById.get(item.id)
    if (!prev || parseEventModifiedMs(item) >= parseEventModifiedMs(prev)) {
      serverById.set(item.id, item)
    }
  }

  const mergedById = new Map()

  // 3. Reconcile every server record against local state
  for (const [id, sItem] of serverById.entries()) {
    const lItem = localById.get(id) || null
    const merged = mergeServerEventWithLocal(sItem, lItem, {
      hasPendingSync: pendingIds.has(id),
      completedOverride: completedOverrides[id] || null,
      deletedAtMs: nextDeletedMap[id] || 0,
    })
    if (merged.hidden) {
      nextDeletedMap[id] = Math.max(nextDeletedMap[id] || 0, parseEventModifiedMs(merged) || Date.now())
      continue
    }
    if (nextDeletedMap[id] && parseEventModifiedMs(merged) > nextDeletedMap[id]) {
      delete nextDeletedMap[id]
    }
    mergedById.set(id, merged)
  }

  // 4. Handle local-only records not present in this server response
  const nowMs = Date.now()
  for (const [id, lItem] of localById.entries()) {
    if (serverById.has(id)) continue
    const lModMs = parseEventModifiedMs(lItem)
    const delMs = parseTimestampMs(nextDeletedMap[id])
    if (lItem.hidden || (delMs > 0 && delMs >= lModMs && !pendingIds.has(id))) {
      continue
    }

    const isTemp = String(id).startsWith('local_')
    const isPending = pendingIds.has(id) || isTemp
    if (!isPending && serverWindowComplete) {
      // Recently created within 15s grace window stays protected
      if (nowMs - lModMs > 15000) {
        if (lItem.is_undated && queriedUndated) {
          continue
        }
        if (!lItem.is_undated && windowStartKey && windowEndKey) {
          const k = dayKey(lItem.start_time)
          if (k && k >= windowStartKey && k <= windowEndKey) {
            // Un-overridden TJU classes or hard-deleted items inside full-fetched window are pruned
            if (lItem.source === 'tju_schedule' && !lItem.local_override) {
              continue
            }
          }
        }
      }
    }

    const override = completedOverrides[id]
    if (override?.status && parseTimestampMs(override.timestamp) >= lModMs) {
      const ovIso = new Date(parseTimestampMs(override.timestamp)).toISOString()
      mergedById.set(id, {
        ...lItem,
        status: override.status,
        completed_at: override.status === 'completed' ? lItem.completed_at || ovIso : null,
        updated_at: ovIso,
        client_updated_at: ovIso,
      })
    } else {
      mergedById.set(id, lItem)
    }
  }

  return {
    activeEvents: [...mergedById.values()],
    nextDeletedMap,
  }
}
