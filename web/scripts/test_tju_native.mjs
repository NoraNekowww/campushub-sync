function toB64(str) {
  return Buffer.from(String(str), 'utf8').toString('base64')
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed')
}

let passed = 0
const fails = []

async function check(name, fn) {
  try {
    await fn()
    passed += 1
  } catch (err) {
    fails.push(`${name}: ${err?.stack || err?.message || err}`)
  }
}

// Install global window BEFORE importing tjuNativeClient.js so __nativeHttpResolve binds.
globalThis.window = globalThis

const {
  hasNativeTjuBridge,
  parseSemesters,
  pickSemester,
  nativeFetchEamsHtml,
} = await import('../src/utils/tjuNativeClient.js')

const SAMPLE_JS_CALENDAR = `{semesters:{y0:[{id:221,schoolYear:"2025-2026",name:"1"},{id:222,schoolYear:"2025-2026",name:"2"},{id:241,schoolYear:"2026-2027",name:"1"},{id:242,schoolYear:"2026-2027",name:"2"},{id:241,schoolYear:"2026-2027",name:"1"}]}}`

await check('parseSemesters parses JS literal, JSON, and deduplicates', () => {
  const sems1 = parseSemesters(SAMPLE_JS_CALENDAR)
  assert(sems1.length === 4, `expected 4 deduplicated semesters, got ${sems1.length}`)
  assert(sems1[2].id === '241' && sems1[2].schoolYear === '2026-2027' && sems1[2].name === '1', 'mismatch on 2026-2027 1')

  const jsonPayload = JSON.stringify({
    semesters: {
      y0: [
        { id: 241, schoolYear: '2026-2027', name: '1' },
        { id: 242, schoolYear: '2026-2027', name: '2' },
      ],
    },
  })
  const sems2 = parseSemesters(jsonPayload)
  assert(sems2.length === 2, `expected 2 JSON semesters, got ${sems2.length}`)
  assert(sems2[0].id === '241' && sems2[1].id === '242', 'JSON ids mismatch')
})

await check('pickSemester selects active academic semester rather than future term', () => {
  const sems = parseSemesters(SAMPLE_JS_CALENDAR)
  const nov = pickSemester(sems, new Date('2026-11-22T09:00:00+08:00'))
  assert(nov?.id === '241', `Nov 2026 expected id 241, got ${nov?.id}`)

  const jan = pickSemester(sems, new Date('2027-01-15T09:00:00+08:00'))
  assert(jan?.id === '241', `Jan 2027 expected id 241, got ${jan?.id}`)

  const apr = pickSemester(sems, new Date('2026-04-15T09:00:00+08:00'))
  assert(apr?.id === '222', `Apr 2026 expected id 222, got ${apr?.id}`)

  const fallback = pickSemester([{ id: '999', schoolYear: '2020-2021', name: '1' }], new Date('2026-11-22T09:00:00+08:00'))
  assert(fallback?.id === '999', 'fallback should pick last element')
})

await check('hasNativeTjuBridge reflects window.NativeAuthBridge availability', () => {
  delete globalThis.window.NativeAuthBridge
  assert(hasNativeTjuBridge() === false, 'expected false without bridge')
  globalThis.window.NativeAuthBridge = { nativeHttpRequest() {} }
  assert(hasNativeTjuBridge() === true, 'expected true with bridge')
})

function installMockBridge(handler) {
  const calls = []
  const closed = []
  globalThis.window.NativeAuthBridge = {
    nativeHttpRequest(reqId, sessionId, method, url, formStr, followRedirects) {
      calls.push({ sessionId, method, url, formStr, followRedirects })
      queueMicrotask(() => {
        const res = handler({ reqId, sessionId, method, url, formStr, followRedirects })
        globalThis.window.__nativeHttpResolve(reqId, JSON.stringify(res))
      })
    },
    nativeUploadOcr(reqId) {
      queueMicrotask(() => {
        globalThis.window.__nativeHttpResolve(reqId, JSON.stringify({ ok: true, bodyBase64: toB64(JSON.stringify({ code: 200, data: 'ab12' })) }))
      })
    },
    nativeHttpClose(sessionId) {
      closed.push(sessionId)
    },
  }
  return { calls, closed }
}

await check('nativeFetchEamsHtml uses index -> innerIndex -> POST courseTable with setting.kind=std and current semester', async () => {
  const expectedPicked = pickSemester(parseSemesters(SAMPLE_JS_CALENDAR))
  const { calls, closed } = installMockBridge(({ method, url }) => {
    if (url.endsWith('/cas/login') && method === 'GET') {
      return {
        ok: true,
        status: 200,
        bodyBase64: toB64('<input name="execution" value="e1s1"/><input name="lt" value="LT-123"/>'),
      }
    }
    if (url.endsWith('/cas/code') && method === 'GET') {
      return { ok: true, status: 200, bodyBase64: toB64('FAKECAPTCHA') }
    }
    if (url.endsWith('/cas/login') && method === 'POST') {
      return { ok: true, status: 302, bodyBase64: '' }
    }
    if (url.endsWith('/eams/dataQuery.action') && method === 'POST') {
      return { ok: true, status: 200, bodyBase64: toB64(SAMPLE_JS_CALENDAR) }
    }
    if (url.includes('courseTableForStd!index.action?projectId=1')) {
      return { ok: true, status: 200, bodyBase64: toB64('<html>index ok</html>') }
    }
    if (url.includes('courseTableForStd!innerIndex.action?projectId=1')) {
      return { ok: true, status: 200, bodyBase64: toB64('bg.form.addInput(form,"ids","std-98765");') }
    }
    if (url.includes('courseTableForStd!courseTable.action')) {
      return {
        ok: true,
        status: 200,
        bodyBase64: toB64('<script>var activity = new TaskActivity("t1","高数","45B201");</script>'),
      }
    }
    return { ok: true, status: 200, bodyBase64: '' }
  })

  const res = await nativeFetchEamsHtml({ username: '3023000001', password: 'secret', captcha: 'abcd' })
  assert(res.courses_html.includes('TaskActivity'), 'expected TaskActivity HTML')
  assert(res.calendar_raw === SAMPLE_JS_CALENDAR, 'calendar_raw mismatch')
  assert(res.term === `${expectedPicked.schoolYear} ${expectedPicked.name}`, `unexpected term ${res.term}`)
  assert(closed.length === 1, 'nativeHttpClose should be called')

  const idxCall = calls.findIndex((c) => c.url.includes('courseTableForStd!index.action?projectId=1'))
  const innerCall = calls.findIndex((c) => c.url.includes('courseTableForStd!innerIndex.action?projectId=1'))
  const tblCallIdx = calls.findIndex((c) => c.url.includes('courseTableForStd!courseTable.action'))
  assert(idxCall !== -1 && innerCall === idxCall + 1 && tblCallIdx === innerCall + 1, 'wrong EAMS call sequence')

  const formParams = new URLSearchParams(calls[tblCallIdx].formStr)
  assert(formParams.get('setting.kind') === 'std', `expected setting.kind=std, got ${formParams.get('setting.kind')}`)
  assert(formParams.get('settingKind') === null, 'settingKind must not be sent')
  assert(formParams.get('ignoreHead') === '1', 'ignoreHead must be 1')
  assert(formParams.get('startWeek') === '', 'startWeek must be empty')
  assert(formParams.get('semester.id') === expectedPicked.id, `expected semester.id=${expectedPicked.id}, got ${formParams.get('semester.id')}`)
  assert(formParams.get('ids') === 'std-98765', `expected ids=std-98765, got ${formParams.get('ids')}`)
})

await check('nativeFetchEamsHtml falls back to projectId=22 and prefers TaskActivity HTML', async () => {
  const { calls } = installMockBridge(({ method, url }) => {
    if (url.endsWith('/cas/login') && method === 'GET') {
      return { ok: true, status: 200, bodyBase64: toB64('<input name="execution" value="e1s1"/><input name="lt" value="LT-1"/>') }
    }
    if (url.endsWith('/cas/code') && method === 'GET') {
      return { ok: true, status: 200, bodyBase64: toB64('FAKECAPTCHA') }
    }
    if (url.endsWith('/cas/login') && method === 'POST') {
      return { ok: true, status: 302, bodyBase64: '' }
    }
    if (url.endsWith('/eams/dataQuery.action')) {
      return { ok: true, status: 200, bodyBase64: toB64(SAMPLE_JS_CALENDAR) }
    }
    if (url.includes('courseTableForStd!innerIndex.action?projectId=1')) {
      return { ok: true, status: 200, bodyBase64: toB64('no ids for undergrad') }
    }
    if (url.includes('courseTableForStd!innerIndex.action?projectId=22')) {
      return { ok: true, status: 200, bodyBase64: toB64('bg.form.addInput(form,"ids","grad-456");') }
    }
    if (url.includes('courseTableForStd!courseTable.action')) {
      return { ok: true, status: 200, bodyBase64: toB64('<script>new TaskActivity("grad");</script>') }
    }
    return { ok: true, status: 200, bodyBase64: '' }
  })

  const res = await nativeFetchEamsHtml({ username: '2023000001', password: 'secret', captcha: '1234' })
  assert(res.courses_html.includes('TaskActivity'), 'expected projectId=22 TaskActivity')
  assert(calls.some((c) => c.url.includes('index.action?projectId=22')), 'should hit index.action?projectId=22')
  const tbl = calls.find((c) => c.url.includes('courseTableForStd!courseTable.action'))
  assert(new URLSearchParams(tbl.formStr).get('ids') === 'grad-456', 'expected grad-456 ids')
})

await check('nativeFetchEamsHtml throws kind=session when EAMS reports expired session', async () => {
  installMockBridge(({ method, url }) => {
    if (url.endsWith('/cas/login') && method === 'GET') {
      return { ok: true, status: 200, bodyBase64: toB64('<input name="execution" value="e1s1"/><input name="lt" value="LT-1"/>') }
    }
    if (url.endsWith('/cas/code') && method === 'GET') {
      return { ok: true, status: 200, bodyBase64: toB64('FAKECAPTCHA') }
    }
    if (url.endsWith('/cas/login') && method === 'POST') {
      return { ok: true, status: 302, bodyBase64: '' }
    }
    if (url.endsWith('/eams/dataQuery.action')) {
      return { ok: true, status: 200, bodyBase64: toB64('<div>本次会话已经被过期</div>') }
    }
    return { ok: true, status: 200, bodyBase64: '' }
  })

  let caught = null
  try {
    await nativeFetchEamsHtml({ username: '3023000001', password: 'secret', captcha: '1234' })
  } catch (err) {
    caught = err
  }
  assert(caught && caught.detail?.kind === 'session', `expected kind=session, got ${caught?.detail?.kind}`)
})

console.log(`passed=${passed} fails=${fails.length}`)
if (fails.length) {
  for (const f of fails) console.error('FAIL:', f)
  process.exit(1)
}
