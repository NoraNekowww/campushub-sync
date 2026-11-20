import { toDate } from './datetime.js'

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
 * Align and merge a server event with the local copy using Last-Write-Wins (LWW).
 * Protects pending local mutations (especially 可办事项 status toggles) from
 * being overwritten by stale cloud snapshots while allowing newer remote edits.
 */
export function mergeServerEventWithLocal(
  serverItem,
  localItem,
  { hasPendingSync = false, completedOverride = null } = {},
) {
  const serverTs = parseTimestampMs(
    serverItem?.updated_at || serverItem?.client_updated_at || serverItem?.created_at,
  )
  const overrideTs = parseTimestampMs(completedOverride?.timestamp)
  const overrideStatus = completedOverride?.status || null

  if (localItem) {
    const localTs = parseEventModifiedMs(localItem)
    const shouldKeepLocal = hasPendingSync || (Boolean(localItem.client_updated_at) && localTs > serverTs)
    if (shouldKeepLocal) {
      if (overrideStatus && overrideTs >= localTs) {
        return {
          ...localItem,
          status: overrideStatus,
          completed_at: overrideStatus === 'completed' ? (localItem.completed_at || new Date(overrideTs).toISOString()) : null,
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

  if (overrideStatus && (hasPendingSync || overrideTs >= serverTs)) {
    const winnerMs = Math.max(serverTs, overrideTs)
    const winnerIso = winnerMs > 0 ? new Date(winnerMs).toISOString() : serverItem?.updated_at
    return {
      ...alignedBase,
      status: overrideStatus,
      completed_at: overrideStatus === 'completed' ? (serverItem?.completed_at || winnerIso) : null,
      client_updated_at: winnerIso,
    }
  }

  return alignedBase
}

/**
 * Reconcile a newly created server event against a local temp item that may have
 * been toggled or edited while still queued as `local_...`.
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
      status: nextStatus,
      completed_at: nextStatus === 'completed' ? (localBefore.completed_at || new Date(winnerMs).toISOString()) : null,
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
