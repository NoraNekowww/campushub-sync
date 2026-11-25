import { createHash } from 'node:crypto'
import {
  computeNextMutationIso,
  generateClientSourceId,
  makeCustomEventId,
  parseEventModifiedMs,
  reconcileEventCollections,
  sha256Hex,
} from '../src/utils/lww.js'
import { dedupeEvents } from '../src/utils/dedupe.js'
import {
  DEFAULT_REMOTE_DARK,
  DEFAULT_REMOTE_LIGHT,
  getInstantWallpaperSrc,
} from '../src/utils/wallpaperCache.js'

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
    fails.push(`${name}: ${err.message}`)
  }
}

check('sha256Hex and makeCustomEventId match Node/Python SHA-256 exactly', () => {
  for (const sample of ['', 'abc', 'custom:custom-1764079-a1b2', '中文日程标题测试 🚀 08:30-21:00']) {
    const expected = createHash('sha256').update(sample, 'utf8').digest('hex')
    const actual = sha256Hex(sample)
    assert(actual === expected, `sha256 mismatch on ${sample}: got ${actual}, want ${expected}`)
  }
  const sid = generateClientSourceId()
  const expectedId = createHash('sha256').update(`custom:${sid}`, 'utf8').digest('hex').slice(0, 32)
  assert(makeCustomEventId(sid) === expectedId, 'makeCustomEventId must match backend make_event_id')
})

check('computeNextMutationIso is strictly monotonic even when client clock lags behind server', () => {
  const futureServerIso = new Date(Date.now() + 60_000).toISOString()
  const existing = { id: 'ev1', updated_at: futureServerIso }
  const nextIso = computeNextMutationIso(existing, 0)
  assert(
    new Date(nextIso).getTime() > new Date(futureServerIso).getTime(),
    `expected ${nextIso} > ${futureServerIso}`,
  )
  const nextIso2 = computeNextMutationIso({ id: 'ev1', updated_at: nextIso }, 0)
  assert(new Date(nextIso2).getTime() > new Date(nextIso).getTime(), 'consecutive mutations must advance')
})

check('reconcileEventCollections updates edited events in-place by id without old+new coexistence', () => {
  const id = makeCustomEventId('custom-edit-1')
  const localEdited = {
    id,
    source: 'custom',
    title: '修改后的高数答疑',
    start_time: '2026-11-26T15:00:00+08:00',
    end_time: '2026-11-26T16:30:00+08:00',
    is_deadline: false,
    status: 'pending',
    updated_at: '2026-11-25T14:10:00Z',
    client_updated_at: '2026-11-25T14:10:00Z',
  }
  const staleServer = {
    id,
    source: 'custom',
    title: '修改前的高数答疑',
    start_time: '2026-11-26T10:00:00+08:00',
    end_time: '2026-11-26T11:30:00+08:00',
    is_deadline: false,
    status: 'pending',
    updated_at: '2026-11-25T14:05:00Z',
  }

  const { activeEvents } = reconcileEventCollections({
    localEvents: [localEdited],
    serverItems: [staleServer],
  })
  const final = dedupeEvents(activeEvents)
  assert(final.length === 1, `expected 1 item, got ${final.length}`)
  assert(final[0].title === '修改后的高数答疑', 'newer local edit must win')
  assert(final[0].start_time === '2026-11-26T15:00:00+08:00', 'newer local time must win')

  // Now simulate newer remote edit arriving from another device
  const newerCloud = {
    ...staleServer,
    title: '云端最新修改的答疑',
    start_time: '2026-11-26T19:00:00+08:00',
    updated_at: '2026-11-25T14:20:00Z',
  }
  const res2 = reconcileEventCollections({
    localEvents: final,
    serverItems: [newerCloud],
  })
  const final2 = dedupeEvents(res2.activeEvents)
  assert(final2.length === 1, `expected 1 item after cloud edit, got ${final2.length}`)
  assert(final2[0].title === '云端最新修改的答疑', 'newer cloud edit must win')
})

check('crossed-off event never resurrects from stale server snapshot and remote hidden tombstone removes local item', () => {
  const id1 = makeCustomEventId('custom-ddl-1')
  const id2 = makeCustomEventId('custom-del-2')
  const local = [
    {
      id: id1,
      source: 'custom',
      title: '交实验报告',
      is_deadline: true,
      status: 'completed',
      start_time: '2026-11-26T21:00:00+08:00',
      updated_at: '2026-11-25T14:15:00Z',
      client_updated_at: '2026-11-25T14:15:00Z',
    },
    {
      id: id2,
      source: 'custom',
      title: '另一台设备已删除的日程',
      is_deadline: true,
      status: 'pending',
      start_time: '2026-11-27T21:00:00+08:00',
      updated_at: '2026-11-25T14:00:00Z',
    },
  ]
  const server = [
    {
      id: id1,
      source: 'custom',
      title: '交实验报告',
      is_deadline: true,
      status: 'pending',
      hidden: false,
      start_time: '2026-11-26T21:00:00+08:00',
      updated_at: '2026-11-25T14:10:00Z',
    },
    {
      id: id2,
      source: 'custom',
      title: '另一台设备已删除的日程',
      is_deadline: true,
      status: 'pending',
      hidden: true,
      start_time: '2026-11-27T21:00:00+08:00',
      updated_at: '2026-11-25T14:18:00Z',
    },
  ]
  const { activeEvents, nextDeletedMap } = reconcileEventCollections({
    localEvents: local,
    serverItems: server,
  })
  assert(activeEvents.length === 1, `expected only 1 active item, got ${activeEvents.length}`)
  assert(activeEvents[0].id === id1 && activeEvents[0].status === 'completed', 'crossed-off item must stay completed')
  assert(Boolean(nextDeletedMap[id2]), 'remote soft-deleted item must record tombstone')
})

check('dedupeEvents preserves distinct custom IDs with identical title/time while collapsing legacy local_ temp item', () => {
  const a = {
    id: makeCustomEventId('c1'),
    source: 'custom',
    title: '背单词',
    is_deadline: true,
    start_time: '2026-11-26T21:00:00+08:00',
    updated_at: '2026-11-25T10:00:00Z',
  }
  const b = {
    id: makeCustomEventId('c2'),
    source: 'custom',
    title: '背单词',
    is_deadline: true,
    start_time: '2026-11-26T21:00:00+08:00',
    updated_at: '2026-11-25T10:01:00Z',
  }
  const kept = dedupeEvents([a, b])
  assert(kept.length === 2, `distinct custom IDs must both be preserved, got ${kept.length}`)

  const legacyTemp = { ...a, id: 'local_1764000_0_abc' }
  const collapsed = dedupeEvents([legacyTemp, a])
  assert(collapsed.length === 1 && collapsed[0].id === a.id, 'legacy local_ temp must collapse into canonical server ID')
})

check('getInstantWallpaperSrc returns bundled local wallpaper synchronously for defaults and snapshot for cached URLs', () => {
  const store = new Map()
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  }

  const lightDefault = getInstantWallpaperSrc(DEFAULT_REMOTE_LIGHT, false)
  const darkDefault = getInstantWallpaperSrc(DEFAULT_REMOTE_DARK, true)
  assert(lightDefault.endsWith('wallpapers/default-light.jpg'), `unexpected light default: ${lightDefault}`)
  assert(darkDefault.endsWith('wallpapers/default-dark.jpg'), `unexpected dark default: ${darkDefault}`)

  const customRemote = 'https://example.com/custom-astro.jpg'
  store.set(
    'campushub.bg_snap_dark.v1',
    JSON.stringify({ sourceUrl: customRemote, dataUrl: 'data:image/jpeg;base64,AAAA' }),
  )
  assert(
    getInstantWallpaperSrc(customRemote, true) === 'data:image/jpeg;base64,AAAA',
    'cached snapshot DataURL must resolve synchronously in 0ms',
  )
})

console.log(`v298 sync & cache tests: ${passed} passed, ${fails.length} failed`)
if (fails.length) {
  for (const f of fails) console.error('FAIL:', f)
  process.exit(1)
}
