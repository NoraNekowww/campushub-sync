import { projectColumnSnap, resolveScrollAxis } from '../src/utils/scrollLock.js'
import {
  clearNativeStoreAll,
  readCompletedOverridesDual,
  readDeletedIdsDual,
  readEventsCacheDual,
  readSyncQueueDual,
  writeDualJson,
} from '../src/utils/dualStorage.js'

let passed = 0
const fails = []

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed')
}

function check(name, fn) {
  try {
    fn()
    passed += 1
  } catch (err) {
    fails.push(`${name}: ${err?.stack || err?.message || err}`)
  }
}

check('resolveScrollAxis enforces deadzone and single-axis intent locking', () => {
  assert(resolveScrollAxis(2, 3, 6) === null, 'small delta inside deadzone should return null')
  assert(resolveScrollAxis(5, 0, 6) === null, 'below threshold 6 should return null')
  assert(resolveScrollAxis(12, 4, 6) === 'x', 'horizontal drag must lock to x')
  assert(resolveScrollAxis(-18, 9, 6) === 'x', 'negative horizontal drag must lock to x')
  assert(resolveScrollAxis(3, 15, 6) === 'y', 'vertical drag must lock to y')
  assert(resolveScrollAxis(10, -11, 6) === 'y', 'vertical dominance must lock to y')
  assert(resolveScrollAxis(10, 10, 6) === 'x', '45 degree diagonal tie resolves deterministically to x')
})

check('projectColumnSnap clamps to column grid and projects horizontal velocity', () => {
  const colW = 58.85
  const totalCols = 63
  assert(projectColumnSnap(0, 1.5, colW, totalCols) === 0, 'clamps left boundary to 0')
  assert(
    projectColumnSnap(60 * colW, -2.0, colW, totalCols) === Math.round((totalCols - 7) * colW),
    'clamps right boundary to maxCols - 7',
  )
  // Current col 7 (7 * 58.85 = 411.95), finger flicked left (vx = -0.8 px/ms -> projected +128px -> +2 cols -> col 9)
  const projected = projectColumnSnap(7 * colW, -0.8, colW, totalCols)
  assert(projected === Math.round(9 * colW), `expected col 9 (${Math.round(9 * colW)}), got ${projected}`)
})

check('Android dual-storage mirrors events, sync queue, tombstones & recovers cleanly if localStorage is empty', () => {
  const lsMem = new Map()
  const nativeMem = new Map()

  globalThis.localStorage = {
    getItem: (k) => (lsMem.has(k) ? lsMem.get(k) : null),
    setItem: (k, v) => lsMem.set(k, String(v)),
    removeItem: (k) => lsMem.delete(k),
    clear: () => lsMem.clear(),
  }
  globalThis.window = {
    NativeAuthBridge: {
      readNativeStore: (k) => (nativeMem.has(k) ? nativeMem.get(k) : ''),
      writeNativeStore: (k, v) => {
        nativeMem.set(k, String(v))
        return true
      },
      removeNativeStore: (k) => nativeMem.delete(k),
      clearNativeStore: () => nativeMem.clear(),
    },
  }

  const ev1 = {
    id: 'ev-native-1',
    title: '退出前新建的高数日程',
    start_time: '2026-11-27T10:00:00+08:00',
    end_time: '2026-11-27T11:30:00+08:00',
    updated_at: '2026-11-26T18:50:00.000Z',
    client_updated_at: '2026-11-26T18:50:00.000Z',
  }
  const evNewer = {
    id: 'ev-native-1',
    title: '修改后的高数日程（仅落入原生原子文件）',
    start_time: '2026-11-27T10:00:00+08:00',
    end_time: '2026-11-27T11:30:00+08:00',
    updated_at: '2026-11-26T18:51:00.000Z',
    client_updated_at: '2026-11-26T18:51:00.000Z',
  }

  writeDualJson('events_cache', 'campushub.events_cache.v1', { items: [ev1], total: 1, timestamp: 1000 })
  writeDualJson('sync_queue', 'campushub.offline_sync_queue.v1', [
    { _qid: 'q1', type: 'create', temp_id: ev1.id, timestamp: 1000 },
  ])
  writeDualJson('deleted_ids', 'campushub.deleted_event_ids.v1', { 'old-del': Date.now() })
  writeDualJson('completed_overrides', 'campushub.completed_overrides.v1', {
    'done-1': { status: 'completed', timestamp: Date.now() },
  })

  // Simulate Android killing WebView before Chromium LevelDB flushed localStorage!
  lsMem.clear()

  const recoveredEvents = readEventsCacheDual('campushub.events_cache.v1')
  assert(
    recoveredEvents.items.length === 1 && recoveredEvents.items[0].title === '退出前新建的高数日程',
    'must recover event from Android native atomic file when localStorage is empty',
  )
  const recoveredQueue = readSyncQueueDual('campushub.offline_sync_queue.v1')
  assert(recoveredQueue.length === 1 && recoveredQueue[0]._qid === 'q1', 'must recover sync queue from native store')
  const recoveredDel = readDeletedIdsDual('campushub.deleted_event_ids.v1')
  assert(Boolean(recoveredDel['old-del']), 'must recover deleted tombstones from native store')
  const recoveredDone = readCompletedOverridesDual('campushub.completed_overrides.v1')
  assert(recoveredDone['done-1']?.status === 'completed', 'must recover completed overrides from native store')

  // Simulate both layers diverging: newer native version vs stale localStorage version
  lsMem.set('campushub.events_cache.v1', JSON.stringify({ items: [ev1], total: 1, timestamp: 1000 }))
  nativeMem.set('events_cache', JSON.stringify({ items: [evNewer], total: 1, timestamp: 2000 }))
  const merged = readEventsCacheDual('campushub.events_cache.v1')
  assert(
    merged.items.length === 1 && merged.items[0].title === evNewer.title,
    'must reconcile both layers picking newer LWW timestamp',
  )

  clearNativeStoreAll()
  assert(nativeMem.size === 0, 'clearNativeStoreAll must clear native atomic store')
})

console.log(`v300 scroll & persistence tests: ${passed} passed, ${fails.length} failed`)
if (fails.length) {
  for (const f of fails) console.error('FAIL:', f)
  process.exit(1)
}
