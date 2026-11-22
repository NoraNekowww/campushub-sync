import { strEnc } from './tjuDes.js'

const CAS_BASE = 'https://sso.tju.edu.cn/cas'
const EAMS_BASE = 'https://classes.tju.edu.cn/eams'
const OCR_URL = 'https://learning.twt.edu.cn/ocr'

export function hasNativeTjuBridge() {
  return Boolean(
    typeof window !== 'undefined' &&
      window.NativeAuthBridge &&
      typeof window.NativeAuthBridge.nativeHttpRequest === 'function',
  )
}

function b64ToText(b64) {
  if (!b64) return ''
  try {
    const bin = atob(b64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    return new TextDecoder('utf-8').decode(bytes)
  } catch {
    return ''
  }
}

const pendingCalls = new Map()
if (typeof window !== 'undefined') {
  window.__nativeHttpResolve = (reqId, rawJson) => {
    const entry = pendingCalls.get(reqId)
    if (!entry) return
    pendingCalls.delete(reqId)
    try {
      entry.resolve(typeof rawJson === 'string' ? JSON.parse(rawJson) : rawJson)
    } catch (e) {
      entry.reject(e)
    }
  }
}

function nativeHttp({ sessionId, method = 'GET', url, form = null, followRedirects = true }) {
  return new Promise((resolve, reject) => {
    if (!hasNativeTjuBridge()) {
      return reject(new Error('仅 Android 客户端支持手机本机直连教务'))
    }
    const reqId = `nreq_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const timer = setTimeout(() => {
      pendingCalls.delete(reqId)
      reject(new Error('手机直连教务请求超时'))
    }, 22000)
    pendingCalls.set(reqId, {
      resolve: (val) => {
        clearTimeout(timer)
        resolve(val)
      },
      reject: (err) => {
        clearTimeout(timer)
        reject(err)
      },
    })
    const formStr = form ? new URLSearchParams(form).toString() : ''
    window.NativeAuthBridge.nativeHttpRequest(reqId, sessionId, method, url, formStr, Boolean(followRedirects))
  })
}

function nativeOcr(imageBase64) {
  return new Promise((resolve, reject) => {
    if (!window.NativeAuthBridge?.nativeUploadOcr) {
      return reject(new Error('OCR 桥接不可用'))
    }
    const reqId = `nocr_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const timer = setTimeout(() => {
      pendingCalls.delete(reqId)
      reject(new Error('验证码识别服务超时'))
    }, 15000)
    pendingCalls.set(reqId, {
      resolve: (val) => {
        clearTimeout(timer)
        resolve(val)
      },
      reject: (err) => {
        clearTimeout(timer)
        reject(err)
      },
    })
    window.NativeAuthBridge.nativeUploadOcr(reqId, OCR_URL, imageBase64)
  })
}

// 暂存本机手动验证码登录上下文
const pendingSessions = new Map()

function makeError(message, kind = 'protocol') {
  const err = new Error(message)
  err.detail = { kind, message }
  return err
}

function stripTags(html) {
  return String(html || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function extractLoginError(html) {
  const span = /id="errormsghide"[^>]*>(.*?)<\/span>/is.exec(html) || /<div[^>]*id="msg"[^>]*>(.*?)<\/div>/is.exec(html)
  if (span) {
    const clean = span[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
    if (clean) return clean
  }
  for (const phrase of ['验证码错误', '验证码不正确', '验证码已失效', '用户名或密码错误', '密码错误', '用户名不存在', '账号不存在']) {
    if (html.includes(phrase)) return phrase
  }
  return ''
}

/** Parse semesters from EAMS semesterCalendar JSON or JS literal (matches backend tju_cas._parse_semesters). */
export function parseSemesters(raw) {
  const found = []
  const text = String(raw || '')
  const walk = (node) => {
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node)) {
      for (const item of node) walk(item)
      return
    }
    if ('id' in node && 'schoolYear' in node && (String(node.name) === '1' || String(node.name) === '2')) {
      found.push({
        id: String(node.id),
        schoolYear: String(node.schoolYear),
        name: String(node.name),
      })
      return
    }
    for (const val of Object.values(node)) walk(val)
  }

  try {
    walk(JSON.parse(text))
  } catch {}

  if (!found.length) {
    for (const m of text.matchAll(/id:\s*(\d+)\s*,\s*schoolYear:\s*"(\d+)-(\d+)"\s*,\s*name:\s*"(1|2)"/g)) {
      found.push({ id: m[1], schoolYear: `${m[2]}-${m[3]}`, name: m[4] })
    }
  }
  if (!found.length) {
    for (const m of text.matchAll(/\{"id":\s*(\d+)[^{}]*?"schoolYear":\s*"(\d+)-(\d+)"[^{}]*?"name":\s*"(1|2)"/g)) {
      found.push({ id: m[1], schoolYear: `${m[2]}-${m[3]}`, name: m[4] })
    }
  }

  const seen = new Set()
  return found.filter((item) => {
    const key = `${item.id}|${item.schoolYear}|${item.name}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** Pick current academic semester (matches backend tju_cas.pick_semester). */
export function pickSemester(semesters, today = new Date()) {
  if (!semesters || !semesters.length) return null
  const month = today.getMonth() + 1
  const year = today.getFullYear()
  let wantYear
  let wantName
  if (month > 7) {
    wantYear = `${year}-${year + 1}`
    wantName = '1'
  } else if (month < 2) {
    wantYear = `${year - 1}-${year}`
    wantName = '1'
  } else {
    wantYear = `${year - 1}-${year}`
    wantName = '2'
  }
  const exact = semesters.find((item) => item.schoolYear === wantYear && item.name === wantName)
  return exact || semesters[semesters.length - 1]
}

export async function nativeFetchCaptcha() {
  const sessionId = `cas_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  const loginRes = await nativeHttp({ sessionId, method: 'GET', url: `${CAS_BASE}/login`, followRedirects: false })
  if (!loginRes?.ok) throw makeError(loginRes?.error || '连接天大统一身份认证失败', 'network')
  const html = b64ToText(loginRes.bodyBase64)
  const execMatch = /name="execution"\s+value="([^"]+)"/.exec(html)
  const ltMatch = /name="lt"\s+value="([^"]+)"/.exec(html)
  if (!execMatch || !ltMatch) throw makeError('拿不到 CAS 登录参数', 'protocol')

  const imgRes = await nativeHttp({ sessionId, method: 'GET', url: `${CAS_BASE}/code`, followRedirects: false })
  if (!imgRes?.ok || imgRes.status >= 400 || !imgRes.bodyBase64) {
    throw makeError('拉取教务验证码图片失败', 'protocol')
  }
  pendingSessions.set(sessionId, { execution: execMatch[1], lt: ltMatch[1] })
  return {
    captcha_id: sessionId,
    image: `data:image/jpeg;base64,${imgRes.bodyBase64}`,
  }
}

export async function nativeFetchEamsHtml({ username, password, captcha = '', captchaId = '' }) {
  const user = String(username || '').trim()
  const pass = String(password || '')
  if (!user || !pass) throw makeError('请填写学号和教务系统密码', 'auth_required')

  const sessionId = captchaId && pendingSessions.has(captchaId)
    ? captchaId
    : `cas_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  let sessionMeta = captchaId ? pendingSessions.get(captchaId) : null
  if (captchaId) pendingSessions.delete(captchaId)

  const attempts = captcha ? 1 : 3
  let loggedIn = false
  let lastErr = null

  try {
    for (let i = 0; i < attempts; i++) {
      let execution
      let lt
      let imgB64
      if (sessionMeta) {
        execution = sessionMeta.execution
        lt = sessionMeta.lt
        sessionMeta = null
      } else {
        const loginRes = await nativeHttp({ sessionId, method: 'GET', url: `${CAS_BASE}/login`, followRedirects: false })
        if (!loginRes?.ok) throw makeError(loginRes?.error || '手机连接天大认证超时，请检查网络', 'network')
        const html = b64ToText(loginRes.bodyBase64)
        const em = /name="execution"\s+value="([^"]+)"/.exec(html)
        const lm = /name="lt"\s+value="([^"]+)"/.exec(html)
        if (!em || !lm) throw makeError('拿不到 CAS 登录参数', 'protocol')
        execution = em[1]
        lt = lm[1]

        const imgRes = await nativeHttp({ sessionId, method: 'GET', url: `${CAS_BASE}/code`, followRedirects: false })
        if (!imgRes?.ok || !imgRes.bodyBase64) throw makeError('取教务验证码失败', 'protocol')
        imgB64 = imgRes.bodyBase64
      }

      let code = String(captcha || '').trim()
      if (!code) {
        try {
          const ocrRes = await nativeOcr(imgB64)
          const ocrTxt = b64ToText(ocrRes?.bodyBase64)
          const parsed = ocrTxt ? JSON.parse(ocrTxt) : null
          if (parsed?.code === 200 && parsed?.data) code = String(parsed.data).trim()
        } catch {}
        if (!code) {
          throw makeError('验证码自动识别未返回结果，请手动输入验证码', 'captcha')
        }
      }

      const rsa = strEnc(`${user}${pass}${lt}`, '1', '2', '3')
      const postRes = await nativeHttp({
        sessionId,
        method: 'POST',
        url: `${CAS_BASE}/login`,
        followRedirects: false,
        form: {
          code,
          ul: String(user.length),
          pl: String(pass.length),
          lt,
          rsa,
          execution,
          _eventId: 'submit',
        },
      })
      if (!postRes?.ok) throw makeError(postRes?.error || '登录请求失败', 'network')

      const postHtml = b64ToText(postRes.bodyBase64)
      let ok = [301, 302, 303].includes(postRes.status) || /var\s+remind_strong_pwd\s*=\s*'true'/.test(postHtml)
      if (!ok) {
        const probe = await nativeHttp({ sessionId, method: 'GET', url: `${CAS_BASE}/login`, followRedirects: false })
        if (probe?.ok && [301, 302, 303].includes(probe.status)) ok = true
      }

      if (ok) {
        loggedIn = true
        break
      }

      const msg = extractLoginError(postHtml) || `CAS 返回 HTTP ${postRes.status}`
      const isCap = msg.includes('验证码')
      const isAuth = ['密码', '账号', '帐号', '用户名', '不存在', '锁定'].some((w) => msg.includes(w))
      lastErr = makeError(`CAS 登录失败：${msg}`, isCap ? 'captcha' : isAuth ? 'auth_required' : 'protocol')
      if (!isCap || i === attempts - 1) break
    }

    if (!loggedIn) {
      throw lastErr || makeError('CAS 登录失败', 'protocol')
    }

    // 1. EAMS handshake (302 -> CAS service ticket -> EAMS JSESSIONID)
    await nativeHttp({
      sessionId,
      method: 'POST',
      url: `${EAMS_BASE}/dataQuery.action`,
      form: { entityId: '' },
      followRedirects: true,
    })

    // 2. Semester calendar -> pick CURRENT semester
    const calRes = await nativeHttp({
      sessionId,
      method: 'POST',
      url: `${EAMS_BASE}/dataQuery.action`,
      form: { dataType: 'semesterCalendar' },
      followRedirects: true,
    })
    const calendarRaw = b64ToText(calRes?.bodyBase64)
    const semesters = parseSemesters(calendarRaw)
    if (!semesters.length && (calendarRaw.includes('本次会话已经被过期') || stripTags(calendarRaw).includes('登录'))) {
      throw makeError('教务会话未建立成功，请重试一次', 'session')
    }
    const picked = pickSemester(semesters)
    const semesterId = picked?.id || ''

    // 3. Per projectId (1 = 本科生, 22 = 研究生): index -> innerIndex -> courseTable
    let coursesHtml = ''
    for (const projectId of [1, 22]) {
      await nativeHttp({
        sessionId,
        method: 'GET',
        url: `${EAMS_BASE}/courseTableForStd!index.action?projectId=${projectId}`,
        followRedirects: true,
      })
      const idxRes = await nativeHttp({
        sessionId,
        method: 'GET',
        url: `${EAMS_BASE}/courseTableForStd!innerIndex.action?projectId=${projectId}`,
        followRedirects: true,
      })
      const idxHtml = b64ToText(idxRes?.bodyBase64)
      const idsMatch = /"ids","([^"]+)"/.exec(idxHtml)
      if (!idsMatch) continue
      const ids = idsMatch[1]

      const tblRes = await nativeHttp({
        sessionId,
        method: 'POST',
        url: `${EAMS_BASE}/courseTableForStd!courseTable.action`,
        form: {
          ignoreHead: '1',
          'setting.kind': 'std',
          startWeek: '',
          'semester.id': semesterId,
          ids,
        },
        followRedirects: true,
      })
      const html = b64ToText(tblRes?.bodyBase64)
      if (html && /TaskActivity/.test(html)) {
        coursesHtml = html
        break
      }
      if (html && !coursesHtml) {
        coursesHtml = html
      }
    }

    if (!coursesHtml) throw makeError('未能从教务系统读取到课表页面', 'empty')
    return {
      courses_html: coursesHtml,
      calendar_raw: calendarRaw,
      term: picked ? `${picked.schoolYear} ${picked.name}` : undefined,
    }
  } finally {
    try {
      window.NativeAuthBridge.nativeHttpClose?.(sessionId)
    } catch {}
  }
}
