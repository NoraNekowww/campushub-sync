/**
 * Thin API client.
 *
 * Auth is layered: a signed-in account uses an HttpOnly session cookie
 * (`credentials: 'include'`), while a read-only device can still paste the
 * shared token from the subscription link — both are accepted by the backend,
 * so no code path needs to know which one is in play.
 */
const TOKEN_KEY = 'campushub.adminToken'

function detectBase() {
  const explicit = import.meta.env.VITE_API_BASE
  if (explicit) return explicit.replace(/\/$/, '')
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
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const isAuthError = (error) =>
  error instanceof ApiError && (error.status === 401 || error.status === 403)

async function request(path, { method = 'GET', body, headers = {}, raw = false } = {}) {
  const token = getToken()
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'include',
    headers: {
      ...(body && !isForm ? { 'Content-Type': 'application/json' } : {}),
      // One field, two roles: the admin token drives reads *and* writes, the
      // subscribe token only unlocks reads (see backend require_read). Sending
      // both headers means a read-only device just works.
      ...(token ? { 'X-Admin-Token': token, 'X-Subscribe-Token': token } : {}),
      ...headers,
    },
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  })

  if (response.status === 401 || response.status === 403) {
    let detail = '需要登录或访问令牌'
    try {
      const payload = await response.json()
      if (typeof payload.detail === 'string') detail = payload.detail
    } catch (error) {
      /* keep default */
    }
    throw new ApiError(detail, response.status)
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const payload = await response.json()
      detail =
        typeof payload.detail === 'string'
          ? payload.detail
          : Array.isArray(payload.detail)
            ? payload.detail.map((item) => item.msg || JSON.stringify(item)).join('；')
            : JSON.stringify(payload.detail)
    } catch (error) {
      /* keep statusText */
    }
    throw new ApiError(detail, response.status)
  }
  if (raw) return response
  if (response.status === 204) return null
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
  deleteEvent: (id) => request(`/events/${id}`, { method: 'DELETE' }),
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
}
