import { existsSync, readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (
      (specifier.startsWith('./') || specifier.startsWith('../')) &&
      !specifier.endsWith('.js') &&
      context.parentURL?.includes('/web/src/')
    ) {
      const candidate = new URL(`${specifier}.js`, context.parentURL)
      if (existsSync(fileURLToPath(candidate))) {
        return nextResolve(candidate.href, context)
      }
    }
    return nextResolve(specifier, context)
  },
})

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))

const lsMem = new Map()
const nativeMem = new Map()
const nativeWrites = []

globalThis.localStorage = {
  getItem: (k) => (lsMem.has(k) ? lsMem.get(k) : null),
  setItem: (k, v) => lsMem.set(k, String(v)),
  removeItem: (k) => lsMem.delete(k),
  clear: () => lsMem.clear(),
}
globalThis.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {},
}
globalThis.window = {
  NativeAuthBridge: {
    readNativeStore: (k) => (nativeMem.has(k) ? nativeMem.get(k) : ''),
    writeNativeStore: (k, v) => {
      nativeMem.set(k, String(v))
      nativeWrites.push(k)
      return true
    },
    removeNativeStore: (k) => nativeMem.delete(k),
    clearNativeStore: () => nativeMem.clear(),
    syncAuthTokens: () => {},
  },
  location: { href: 'https://nzlab.online/schedule/', host: 'nzlab.online', protocol: 'https:' },
  addEventListener: () => {},
  removeEventListener: () => {},
}
Object.defineProperty(globalThis, 'navigator', {
  value: { userAgent: 'CampusHubAndroid/1.0', onLine: true },
  configurable: true,
})

let nextFetchResponder = async () => new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } })
globalThis.fetch = async (url, opts) => nextFetchResponder(url, opts)

const datetime = await import('../src/utils/datetime.js')
const dualStorage = await import('../src/utils/dualStorage.js')
const store = await import('../src/store.js')

let passed = 0
const fails = []

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed')
}

async function check(name, fn) {
  try {
    await fn()
    passed += 1
  } catch (err) {
    fails.push(`${name}: ${err?.stack || err?.message || err}`)
  }
}

await check('datetime.js fast-path and cached Intl formatters behave accurately', () => {
  assert(datetime.timeLabel('2026-11-27T08:05:00+08:00') === '08:05', 'fast-path +08:00 timeLabel')
  assert(datetime.timeLabel('2026-11-27 9:30') === '09:30', 'fast-path naive space-separated timeLabel')
  assert(datetime.timeLabel('2026-11-27T00:30:00Z') === '08:30', 'UTC Z converts to Asia/Shanghai')
  assert(datetime.dayKey('2026-11-27T23:30:00Z') === '2026-11-28', 'UTC Z near midnight shifts dayKey')
  assert(datetime.minutesOfDay('2026-11-27T18:30:00+08:00') === 1110, 'minutesOfDay fast-path')
  const md = datetime.formatMonthDayTime('2026-11-27T14:05:00+08:00')
  assert(md.includes('11') && md.includes('27') && md.includes('14:05'), `unexpected formatMonthDayTime: ${md}`)
  const win = datetime.weekWindow('2026-11-27T12:00:00+08:00')
  assert(win.days.length === 7 && win.start === '2026-11-23' && win.end === '2026-11-29', 'weekWindow Monday-Sunday')
  const lbl = datetime.dayLabel('2026-11-27T12:00:00+08:00')
  assert(typeof lbl === 'string' && lbl.length > 0, 'dayLabel returns non-empty label')
})

await check('dualStorage.readImportantIdsDual unions localStorage and native store', () => {
  lsMem.set('campushub.important_ids.v1', JSON.stringify(['ev-a', 'ev-b']))
  nativeMem.set('important_ids', JSON.stringify(['ev-b', 'ev-c', '']))
  const merged = dualStorage.readImportantIdsDual('campushub.important_ids.v1')
  assert(
    merged.length === 3 && merged.includes('ev-a') && merged.includes('ev-b') && merged.includes('ev-c'),
    `expected union of 3 ids, got ${JSON.stringify(merged)}`,
  )
})

await check('toggleImportantEvent handles custom & TJU events, cloned refs, rapid 30x toggling without queue bloat', async () => {
  store.state.offlineMode = false
  const customEv = {
    id: 'custom-star-1',
    source: 'custom',
    title: '重点研讨会',
    start_time: '2026-11-27T14:00:00+08:00',
    end_time: '2026-11-27T15:30:00+08:00',
    priority: 5,
  }
  const tjuEv = {
    id: 'tju-star-1',
    source: 'tju_schedule',
    title: '高等数学',
    start_time: '2026-11-27T08:30:00+08:00',
    end_time: '2026-11-27T10:05:00+08:00',
    priority: 5,
  }
  store.state.events = [customEv, tjuEv]
  nativeMem.clear()
  lsMem.clear()

  // Rapid 30x stress toggle while network is failing transiently (500)
  nextFetchResponder = async () => new Response('err', { status: 500 })
  for (let i = 0; i < 30; i++) {
    const cloned = { ...customEv }
    const expected = i % 2 === 0
    const res = store.toggleImportantEvent(cloned)
    assert(res === expected, `iteration ${i}: expected ${expected}, got ${res}`)
    assert(store.isImportantEvent(customEv) === expected, `iteration ${i}: isImportantEvent mismatch`)
  }
  await new Promise((r) => setTimeout(r, 20))

  // Verify sync_queue coalesced priority-only patches to 1 item instead of 30!
  const qRaw = nativeMem.get('sync_queue') || '[]'
  const queue = JSON.parse(qRaw)
  const customPatches = queue.filter((q) => q.id === customEv.id && q.type === 'patch')
  assert(customPatches.length === 1, `expected coalesced queue size 1, got ${customPatches.length}`)
  assert(customPatches[0].payload.priority === 5, 'final coalesced priority after 30 toggles (even count) must be 5')

  // TJU event toggle works locally without crashing or hitting API
  assert(store.toggleImportantEvent(tjuEv) === true, 'TJU star must return true')
  assert(store.isImportantEvent(tjuEv) === true, 'TJU event must be marked important')
  const savedIds = JSON.parse(nativeMem.get('important_ids') || '[]')
  assert(savedIds.includes(tjuEv.id), 'important_ids must persist to Android native store')

  // 404 on patch must clean up sync queue item cleanly
  nextFetchResponder = async () =>
    new Response(JSON.stringify({ detail: 'event not found' }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    })
  assert(store.toggleImportantEvent(customEv) === true, 'custom star on')
  await new Promise((r) => setTimeout(r, 20))
  const after404Queue = JSON.parse(nativeMem.get('sync_queue') || '[]')
  assert(
    after404Queue.filter((q) => q.id === customEv.id).length === 0,
    '404 patch must drop stale queued item cleanly',
  )

  // clearAllLocalData clears importantEventMap & dual store
  store.clearAllLocalData()
  assert(store.isImportantEvent(tjuEv.id) === false, 'clearAllLocalData must clear important map')
  assert(!nativeMem.has('important_ids'), 'clearAllLocalData must clear native important_ids')
})

await check('static CSS and template checks enforce GPU crash fixes & light-mode contrast tuning', () => {
  const styleCss = readFileSync(join(ROOT, 'src/style.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  const appVue = readFileSync(join(ROOT, 'src/App.vue'), 'utf8')
  const weekVue = readFileSync(join(ROOT, 'src/views/WeekView.vue'), 'utf8')
  const cardVue = readFileSync(join(ROOT, 'src/components/EventCard.vue'), 'utf8')
  const detailVue = readFileSync(join(ROOT, 'src/components/ClassDetail.vue'), 'utf8')
  const editorVue = readFileSync(join(ROOT, 'src/components/EventEditor.vue'), 'utf8')
  const authVue = readFileSync(join(ROOT, 'src/components/AuthGate.vue'), 'utf8')

  assert(!/backdrop-filter:[^;]*saturate\(/i.test(styleCss), 'style.css must not use compound saturate() in backdrop-filter')
  const pastOverlayBlock = styleCss.match(/\.class-past-overlay\s*\{[\s\S]*?\}/)?.[0] || ''
  assert(!/backdrop-filter/i.test(pastOverlayBlock), '.class-past-overlay must not nest backdrop-filter')
  assert(!/filter:\s*grayscale/i.test(styleCss), 'must not stack filter:grayscale on backdrop-filtered class-block')
  assert(styleCss.includes('header[data-testid="app-header"]'), 'header glass must scope to data-testid="app-header"')
  assert(styleCss.includes('nav[data-testid="bottom-nav"]'), 'nav glass must scope to data-testid="bottom-nav"')
  assert(!/(?:frosted-glass-active|has-custom-bg)\s+(?:header|nav)\s*[,{]/m.test(styleCss), 'must not apply glass to unscoped header/nav')
  assert(styleCss.includes('.week-col-in-view [data-testid="class-block"]'), 'blur must be viewport-scoped via .week-col-in-view')
  assert(styleCss.includes('backdrop-filter: blur(22px)'), 'timetable glass cards must use blur(22px)')
  assert(styleCss.includes('rgba(255, 255, 255, 0.36)'), 'light-mode normal frosted card specular gradient missing')
  assert(styleCss.includes('rgba(255, 255, 255, 0.34)'), 'light-mode event card translucent specular gradient missing')

  assert(appVue.includes('!showGate.value'), 'App.vue must disable week-view blur while AuthGate is visible')
  assert(authVue.includes('relative z-10'), 'AuthGate must sit above global-bg-layer (z-10 > z-0)')

  assert(appVue.includes("bg-slate-900/[0.14] backdrop-blur-md"), 'App.vue must dim light-mode week background with nested blur')
  assert(appVue.includes("bg-slate-900/[0.06]"), 'App.vue non-week light background must stay crisp and unblurred')
  assert(!appVue.includes("bg-white/30 backdrop-blur-xl"), 'App.vue must remove bright white/30 overlay')
  assert(!appVue.includes('saturate(125%)'), 'App.vue bgLayerStyle must use single-kernel blur')

  assert(!weekVue.includes('transition-all'), 'WeekView class-block must not use transition-all')
  assert(
    cardVue.includes('transition-[border-color,background-color,box-shadow] duration-150'),
    'EventCard article must use targeted transition instead of transition-all',
  )
  assert(detailVue.includes('backdrop-blur-2xl'), 'ClassDetail inner card must have nested frosted glass blur')
  assert(editorVue.includes('backdrop-blur-2xl'), 'EventEditor inner form must have nested frosted glass blur')
})

console.log(`v301 important & perf tests: ${passed} passed, ${fails.length} failed`)
if (fails.length) {
  for (const f of fails) console.error('FAIL:', f)
  process.exit(1)
}
