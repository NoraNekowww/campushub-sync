/**
 * Global reactive store — deliberately dependency-free (no Pinia) because the
 * app state is small: one event list, one status blob, a few UI flags.
 */
import { reactive } from 'vue'
import { api, ApiError, getToken, isAuthError, setToken } from './api'
import { dayKey, todayKey } from './utils/datetime'

const THEME_KEY = 'campushub.theme'
const LOOKAHEAD_DAYS = 60

export const state = reactive({
  view: 'agenda',
  loading: false,
  syncing: false,
  error: '',
  authRequired: false,
  statusLocked: false,
  lastUpdated: null,
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  offlineSince: null,
  events: [],
  total: 0,
  filter: 'all', // all | class | deadline
  source: 'all',
  includeCompleted: true,
  /* 微软待办（反向写入）：清单列表 + 是否已授权，给「新建到微软」下拉用 */
  msLists: [],
  msConnected: false,
  status: null,
  config: null,
  toast: null,
  theme: 'auto',
  /* accounts (see accounts.py): the session cookie is HttpOnly, so the app
     learns who it is by asking /api/auth/session, never by reading a cookie. */
  user: null,
  accounts: null,
  accountsReady: false,
  viewerAdmin: false,
  authBusy: false,
  authError: '',
  authNotice: '',
  forceAuth: false,
  customEditor: { open: false, event: null },
})

let toastTimer = null

/**
 * `?token=…` magic link (the subscription URL doubles as a share link): keep
 * the token, then strip it from the address bar so it does not leak into
 * screenshots, bookmarks or the browser history.
 */
export function ingestUrlToken() {
  try {
    const url = new URL(window.location.href)
    const token = url.searchParams.get('token')
    if (!token) return false
    setToken(token.trim())
    url.searchParams.delete('token')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    // silent on purpose: a magic link should not cover the agenda with a toast
    return true
  } catch (error) {
    return false
  }
}

export function notify(text, tone = 'info') {
  state.toast = { text, tone }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    state.toast = null
  }, 3200)
}

/* ------------------------------------------------------------------ theme */

export function initTheme() {
  let stored = 'auto'
  try {
    stored = localStorage.getItem(THEME_KEY) || 'auto'
  } catch (error) {
    /* ignore */
  }
  state.theme = stored
  applyTheme(stored)
}

export function setTheme(mode) {
  state.theme = mode
  try {
    localStorage.setItem(THEME_KEY, mode)
  } catch (error) {
    /* ignore */
  }
  applyTheme(mode)
}

function applyTheme(mode) {
  const prefersDark =
    typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
  const dark = mode === 'dark' || (mode === 'auto' && prefersDark)
  document.documentElement.classList.toggle('dark', dark)
}

/* ------------------------------------------------------------- event feed */

function fetchParams() {
  const start = dayKey(new Date(Date.now() - 86400000))
  const end = dayKey(new Date(Date.now() + LOOKAHEAD_DAYS * 86400000))
  return {
    start_date: start,
    end_date: end,
    limit: 800,
    source: state.source === 'all' ? undefined : state.source,
  }
}

export async function refresh({ silent = false } = {}) {
  if (!silent) state.loading = true
  try {
    const payload = await api.events(fetchParams())
    state.events = payload.items || []
    state.total = payload.total ?? state.events.length
    state.error = ''
    state.authRequired = false
    state.lastUpdated = new Date()
  } catch (error) {
    if (isAuthError(error)) {
      state.authRequired = true
      state.error = ''
    } else {
      state.error = error.message || '加载失败'
    }
  } finally {
    state.loading = false
  }
}

export async function loadStatus() {
  try {
    state.status = await api.status()
    state.statusLocked = false
  } catch (error) {
    if (isAuthError(error)) {
      // the timeline itself is public; only status/config/actions need auth
      state.statusLocked = true
    }
  }
}

export async function loadConfig() {
  try {
    state.config = await api.config()
    state.viewerAdmin = Boolean(state.config?.viewer?.admin)
    if (state.config?.accounts) {
      state.accounts = { ...(state.accounts || {}), ...state.config.accounts }
    }
    state.statusLocked = false
  } catch (error) {
    if (isAuthError(error)) {
      state.statusLocked = true
    }
  }
}

export async function bootstrap() {
  await Promise.all([refresh(), loadStatus(), loadConfig()])
}

/* --------------------------------------------------------------- accounts */

/** Ask the backend who we are; safe to call when signed out. */
export async function fetchSession() {
  try {
    const payload = await api.session()
    state.user = payload.user || null
    state.accounts = payload.accounts || null
    state.accountsReady = true
    return state.user
  } catch (error) {
    // Endpoint missing (old backend) or unreachable → treat accounts as absent
    // so the app never trades a working timeline for a login wall.
    state.accountsReady = true
    state.accounts = state.accounts || { enabled: false }
    return null
  }
}

export const signInRequired = () =>
  Boolean(state.accounts?.enabled) &&
  !state.user &&
  !hasToken() &&
  (state.authRequired || state.forceAuth)

/** Show the login gate even though the timeline happens to be readable. */
export function openAuthGate() {
  state.forceAuth = true
  state.authError = ''
}

export function closeAuthGate() {
  state.forceAuth = false
  state.authError = ''
}

async function authAction(run, successText) {
  if (state.authBusy) return false
  state.authBusy = true
  state.authError = ''
  try {
    const payload = await run()
    state.user = payload.user || null
    state.authRequired = false
    state.authNotice = successText || payload.message || ''
    notify(state.authNotice, 'ok')
    await bootstrap()
    return true
  } catch (error) {
    state.authError = error.message || '操作失败'
    return false
  } finally {
    state.authBusy = false
  }
}

export function login(username, password) {
  return authAction(() => api.login({ username: username.trim(), password }), '登录成功')
}

export function register(username, password, inviteCode, displayName, captcha) {
  return authAction(
    () =>
      api.register({
        username: username.trim(),
        password,
        invite_code: inviteCode ? inviteCode.trim() : null,
        display_name: displayName ? displayName.trim() : null,
        captcha_token: captcha?.token || null,
        captcha_answer: captcha?.answer ? captcha.answer.trim() : null,
      }),
    '注册成功',
  )
}

/** Fresh image challenge for the sign-up form (self-hosted, no third party). */
export async function loadCaptcha() {
  try {
    const payload = await api.captcha()
    return payload?.enabled === false ? null : payload
  } catch (error) {
    // A captcha we cannot load must not block the form: the server still
    // enforces it, and the user retries once the network is back.
    return null
  }
}

export async function loadRegistrationSettings() {
  return api.registration()
}

export async function saveRegistrationSettings(payload) {
  const result = await api.updateRegistration(payload)
  notify('注册设置已更新', 'info')
  await fetchSession()
  return result?.settings || null
}

/* ------------------------------------------------------------ custom events */

/** Open the editor; pass an event to edit it, nothing to create a new one. */
export function openCustomEditor(event = null) {
  state.customEditor.open = true
  state.customEditor.event = event
}

export function closeCustomEditor() {
  state.customEditor.open = false
  state.customEditor.event = null
}

export async function saveCustomEvent(payload) {
  const existing = state.customEditor.event
  try {
    const saved = existing
      ? await api.patchEvent(existing.id, payload)
      : await api.createEvent(payload)
    closeCustomEditor()
    notify(existing ? '日程已更新' : '日程已添加', 'ok')
    await refresh({ silent: true })
    return saved
  } catch (error) {
    notify(error.message || '保存失败', 'danger')
    return null
  }
}

export async function removeCustomEvent(id) {
  try {
    await api.deleteEvent(id)
    closeCustomEditor()
    notify('日程已删除', 'info')
    await refresh({ silent: true })
    return true
  } catch (error) {
    notify(error.message || '删除失败', 'danger')
    return false
  }
}

export async function logout() {
  try {
    await api.logout()
  } catch (error) {
    /* clearing a cookie we cannot reach is fine */
  }
  // Drop this account's timeline from the offline cache before switching users.
  navigator.serviceWorker?.controller?.postMessage('clear-data-cache')
  state.user = null
  state.authRequired = false
  state.forceAuth = false
  state.error = ''
  notify('已退出登录', 'info')
  await bootstrap()
}

export async function changePassword(oldPassword, newPassword) {
  if (state.authBusy) return false
  state.authBusy = true
  state.authError = ''
  try {
    await api.changePassword({ old_password: oldPassword, new_password: newPassword })
    notify('密码已更新', 'ok')
    return true
  } catch (error) {
    state.authError = error.message || '修改失败'
    return false
  } finally {
    state.authBusy = false
  }
}

export async function listUsers() {
  const payload = await api.users()
  return payload.items || []
}

export async function setUserActive(userId, isActive) {
  await api.updateUser(userId, { is_active: isActive })
  notify(isActive ? '已启用该账号' : '已停用该账号', 'ok')
}

export function aboutMe() {
  return state.user
}

export const isAdmin = () => Boolean(state.user?.is_admin) || Boolean(state.viewerAdmin)

/* ------------------------------------------------------------ interactions */

export async function runSync() {
  if (state.syncing) return
  state.syncing = true
  try {
    const outcome = await api.sync()
    await Promise.all([refresh({ silent: true }), loadStatus()])
    const summary = `新增 ${outcome.created ?? 0} · 更新 ${outcome.updated ?? 0} · 清理 ${outcome.pruned ?? 0}`
    notify(outcome.ok === false ? `同步部分失败：${summary}` : `同步完成：${summary}`, outcome.ok === false ? 'warn' : 'ok')
  } catch (error) {
    notify(error.message || '同步失败', 'danger')
  } finally {
    state.syncing = false
  }
}

export async function toggleCompleted(event) {
  const next = event.status === 'completed' ? 'pending' : 'completed'
  const previous = event.status
  event.status = next // optimistic
  try {
    const updated = await api.patchEvent(event.id, { status: next })
    Object.assign(event, updated)
    // 微软来源的日程会把「划掉」推回 To Do；推失败只提示，本地照样算完成。
    const push = updated.ms_sync
    if (push && !push.ok) notify(`本地已${next === 'completed' ? '划掉' : '恢复'}，微软那边没同步上：${push.error}`, 'warn')
  } catch (error) {
    event.status = previous
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      state.authRequired = true
      notify('需要访问令牌才能修改状态', 'warn')
    } else {
      notify(error.message || '更新失败', 'danger')
    }
  }
}

/* ---------------------------------------------- 微软待办（反向写入）*/

/** 拉一次微软待办的清单列表（同时探出有没有授权）。 */
export async function fetchMsLists() {
  try {
    const payload = await api.msLists()
    state.msLists = payload?.lists || []
    state.msConnected = Boolean(payload?.connected)
  } catch (error) {
    state.msLists = []
    state.msConnected = false
    if (isAuthError(error)) state.authRequired = true
  }
  return state.msConnected
}

/** 在微软待办里新建一条日程：微软先建，成功后再刷新本地（后端已就地落库）。 */
export async function saveMsTask(payload) {
  try {
    await api.createMsTask(payload)
    notify('已建到微软待办，手机待办里也会显示', 'ok')
    closeCustomEditor()
    await refresh({ silent: true })
    return true
  } catch (error) {
    if (isAuthError(error)) state.authRequired = true
    notify(error.message || '微软待办写入失败', 'danger')
    return false
  }
}

export function saveToken(value) {
  setToken(value)
  if (value) {
    state.authRequired = false
    notify('令牌已保存', 'ok')
    bootstrap()
  } else {
    notify('已清除令牌', 'info')
  }
}

export const hasToken = () => Boolean(getToken())

/** Raw token for pre-filling the settings input. */
export const getTokenSafe = () => getToken()

/* -------------------------------------------------------------- filtering */

export function filterEvents(events = state.events) {
  const today = todayKey()
  return events.filter((event) => {
    if (state.filter === 'class' && event.is_deadline) return false
    if (state.filter === 'deadline' && !event.is_deadline) return false
    if (!state.includeCompleted && event.status === 'completed' && !event.is_deadline) return false
    if (state.source !== 'all' && event.source !== state.source) return false
    // keep overdue deadlines visible, drop long-finished classes
    const reference = dayKey(event.end_time || event.start_time)
    if (reference < today && event.is_deadline && event.status === 'completed') return false
    return true
  })
}

export function initConnectivity() {
  if (typeof window === 'undefined') return
  window.addEventListener('online', () => {
    state.online = true
    notify('网络已恢复，正在刷新', 'ok')
    refresh({ silent: true })
  })
  window.addEventListener('offline', () => {
    state.online = false
    notify('已离线，显示缓存数据', 'warn')
  })
}
