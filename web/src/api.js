/**
 * Thin API client.
 *
 * Auth is layered: a signed-in account uses an HttpOnly session cookie
 * (`credentials: 'include'`), while a read-only device can still paste the
 * shared token from the subscription link — both are accepted by the backend,
 * so no code path needs to know which one is in play.
 */
const TOKEN_KEY = 'campushub.adminToken'
const USER_SESSION_TOKEN_KEY = 'campushub.userSessionToken'

export function getSessionToken() {
  try {
    return localStorage.getItem(USER_SESSION_TOKEN_KEY) || ''
  } catch (error) {
    return ''
  }
}

export function setSessionToken(value) {
  try {
    if (value) localStorage.setItem(USER_SESSION_TOKEN_KEY, value)
    else localStorage.removeItem(USER_SESSION_TOKEN_KEY)
  } catch (error) {
    /* private mode */
  }
}

function detectBase() {
  const explicit = import.meta.env.VITE_API_BASE
  if (explicit) return explicit.replace(/\/$/, '')
  // 如果运行在 Android 原生客户端壳中（无论本地虚拟域还是同源拦截），API 必须严格走绝对 HTTPS 远程后端地址
  if (
    typeof window !== 'undefined' &&
    (window.NativeAuthBridge ||
      window.__CAMPUSHUB_CLIENT__ ||
      /CampusHubAndroid/i.test(navigator.userAgent || '') ||
      window.location.protocol === 'file:' ||
      window.location.host === 'appassets.androidplatform.net' ||
      !window.location.host)
  ) {
    return 'https://nzlab.online/schedule/api'
  }
  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
  return `${base}/api`
}

export const API_BASE = detectBase()

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch (error) {
    return ''
  }
}

export function setToken(value) {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  } catch (error) {
    /* private mode — ignore */
  }
}

export class ApiError extends Error {
  /**
   * `detail` keeps the structured body FastAPI sent, when there was one: the
   * 教务 / 微北洋 import routes answer `{kind, message, detail, status}` so the
   * caller can branch (e.g. `kind === 'captcha'` → 让用户手填一张图) instead of
   * having to parse Chinese prose out of the message.
   */
  constructor(message, status, detail = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export const isAuthError = (error) =>
  error instanceof ApiError && (error.status === 401 || error.status === 403)

async function request(path, { method = 'GET', body, headers = {}, raw = false, timeoutMs, retries = 1 } = {}) {
  const token = getToken()
  const sessionToken = getSessionToken()
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData

  // 常规请求 12s 超时，sync 等长任务 30s 超时
  const timeout = timeoutMs || (path.startsWith('/sync') || path.startsWith('/schedule/import') ? 30000 : 12000)

  let response
  let lastErr = null
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    const timer = controller ? setTimeout(() => controller.abort(), timeout) : null

    try {
      response = await fetch(`${API_BASE}${path}`, {
        method,
        credentials: 'include',
        signal: controller?.signal,
        headers: {
          ...(body && !isForm ? { 'Content-Type': 'application/json' } : {}),
          // 携带登录会话 Token，解决 Android 原生环境拦截导致的 Cookie 隔离问题
          ...(sessionToken ? { 'X-Session-Token': sessionToken } : {}),
          // One field, two roles: the admin token drives reads *and* writes, the
          // subscribe token only unlocks reads (see backend require_read). Sending
          // both headers means a read-only device just works.
          ...(token ? { 'X-Admin-Token': token, 'X-Subscribe-Token': token } : {}),
          ...headers,
        },
        body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
      })
      if (timer) clearTimeout(timer)
      break
    } catch (err) {
      if (timer) clearTimeout(timer)
      lastErr = err
      const isAbort = err.name === 'AbortError'
      // 仅在 GET 请求且还有重试机会时重试一次
      if (method === 'GET' && attempt < retries) {
        await new Promise((r) => setTimeout(r, 600))
        continue
      }
      throw new ApiError(
        isAbort ? '网络请求超时，请检查网络或稍后重试' : `网络连接失败：${err.message || '请检查网络或后端状态'}`,
        0,
      )
    }
  }

  /**
   * FastAPI's `detail` is either a plain string or a richer object/dict — the
   * 教务 import routes use `{kind, message, detail, status}`. Surface both so a
   * caller can show `error.message` and still branch on `error.detail.kind`.
   */
  async function readError(fallback) {
    let message = fallback
    let structured = null
    try {
      const contentType = response.headers.get('content-type') || ''
      if (contentType.includes('application/json')) {
        const payload = await response.json()
        structured = payload?.detail ?? null
        if (typeof structured === 'string') message = structured
        else if (Array.isArray(structured)) {
          message = structured.map((item) => item?.msg || JSON.stringify(item)).join('；')
        } else if (structured && typeof structured === 'object') {
          message = structured.message || structured.detail || JSON.stringify(structured)
        } else if (structured != null) message = String(structured)
      } else {
        const text = await response.text()
        if (text && text.length < 200) message = text
      }
    } catch (error) {
      /* keep the fallback text */
    }
    return new ApiError(message, response.status, structured)
  }

  if (!response.ok) {
    throw await readError(
      response.status === 401 || response.status === 403
        ? '账号或密码不正确'
        : `请求失败 (${response.status})`
    )
  }
  if (raw) return response
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    const text = await response.text()
    throw new ApiError(`接口返回了非 JSON 内容 (${response.status}): ${text.slice(0, 100)}`, response.status)
  }
  return response.json()
}

const qs = (params) => {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '' || value === 'all') return
    if (Array.isArray(value)) value.forEach((entry) => search.append(key, entry))
    else search.append(key, value)
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  health: () => request('/health'),
  status: () => request('/status'),
  config: () => request('/config'),
  events: (params) => request(`/events${qs(params)}`),
  patchEvent: (id, patch) => request(`/events/${id}`, { method: 'PATCH', body: patch }),
  createEvent: (payload) => request('/events', { method: 'POST', body: payload }),
  deleteEvent: (id, params = {}) => request(`/events/${id}${qs(params)}`, { method: 'DELETE' }),
  sync: () => request('/sync', { method: 'POST' }),
  syncLogs: (limit = 10) => request(`/sync/logs${qs({ limit })}`),
  /* ------------------------------------------------------------- accounts */
  session: () => request('/auth/session'),
  me: () => request('/auth/me'),
  login: (payload) => request('/auth/login', { method: 'POST', body: payload }),
  register: (payload) => request('/auth/register', { method: 'POST', body: payload }),
  captcha: () => request('/auth/captcha'),
  registration: () => request('/auth/registration'),
  updateRegistration: (payload) => request('/auth/registration', { method: 'PUT', body: payload }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  changePassword: (payload) => request('/auth/password', { method: 'POST', body: payload }),
  users: () => request('/auth/users'),
  patchUser: (id, payload) => request(`/auth/users/${id}`, { method: 'PATCH', body: payload }),
  authStorage: () => request('/auth/storage'),
  optimizeStorage: () => request('/auth/storage/optimize', { method: 'POST' }),
  appVersion: () => request('/version'),
  /* ------------------------------------------------ microsoft / schedule */
  msStatus: () => request('/auth/ms/status'),
  msLists: () => request('/events/ms/lists'),
  createMsTask: (payload) => request('/events/ms/task', { method: 'POST', body: payload }),
  msStartDevice: () => request('/auth/ms/device/start', { method: 'POST' }),
  msPollDevice: () => request('/auth/ms/device/poll', { method: 'POST' }),
  msSignOut: () => request('/auth/ms/tokens', { method: 'DELETE' }),
  schedulePreview: () => request('/schedule/preview'),
  uploadIcs: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/schedule/upload', { method: 'POST', body: form })
  },
  removeIcs: () => request('/schedule/upload', { method: 'DELETE' }),
  getSemester: () => request('/schedule/semester'),
  putSemester: (payload) => request('/schedule/semester', { method: 'PUT', body: payload }),
  /* --------------------------------------------------------- 微北洋 / TJU */
  tjuStatus: (probe = false) => request(`/tju/status${probe ? '?probe=true' : ''}`),
  tjuSaveCredentials: (payload) => request('/tju/credentials', { method: 'POST', body: payload }),
  tjuClearCredentials: () => request('/tju/credentials', { method: 'DELETE' }),
  tjuServerSync: () => request('/tju/sync', { method: 'POST' }),
  tjuImport: (payload) => request('/tju/import', { method: 'POST', body: payload }),
  tjuClearImport: () => request('/tju/import', { method: 'DELETE' }),
  /* --------------------------------------------- 教务系统（CAS 直连，主路径）*/
  jwStatus: () => request('/tju/jw/status'),
  jwImport: (payload) => request('/tju/jw/import', { method: 'POST', body: payload }),
  jwCaptcha: () => request('/tju/jw/captcha', { method: 'POST' }),
  jwRefresh: () => request('/tju/jw/refresh', { method: 'POST' }),
  jwForget: () => request('/tju/jw/credentials', { method: 'DELETE' }),
}
