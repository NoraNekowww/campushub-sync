/**
 * Global reactive store — deliberately dependency-free (no Pinia) because the
 * app state is small: one event list, one status blob, a few UI flags.
 */
import { reactive } from 'vue'
import { api, ApiError, getToken, isAuthError, setSessionToken, setToken } from './api'
import { dayKey, isEventEnded, todayKey } from './utils/datetime'
import { browserClasstable, browserLogin, TwtError } from './twt-sign'

const THEME_KEY = 'campushub.theme'
const EVENTS_CACHE_KEY = 'campushub.events_cache.v1'
const WEEK_CACHE_KEY = 'campushub.week_cache.v1'
const USER_CACHE_KEY = 'campushub.user_cache.v1'
const CONFIG_CACHE_KEY = 'campushub.config_cache.v1'
const STATUS_CACHE_KEY = 'campushub.status_cache.v1'
const SYNC_QUEUE_KEY = 'campushub.offline_sync_queue.v1'
const LOOKAHEAD_DAYS = 60

/** 判断当前是否在 Android 原生客户端壳环境中运行 */
export function isMobileNativeApp() {
  if (typeof window === 'undefined') return false
  return Boolean(
    window.NativeAuthBridge ||
    window.__CAMPUSHUB_CLIENT__ ||
    /CampusHubAndroid/i.test(navigator.userAgent || '') ||
    (/Android/i.test(navigator.userAgent || '') && /wv|WebView/i.test(navigator.userAgent || '')) ||
    (/Android/i.test(navigator.userAgent || '') && window.matchMedia?.('(display-mode: standalone)')?.matches)
  )
}

export const state = reactive({
  // 进去之后默认显示课程表（WeekView）
  view: 'week',
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
  /* 搜索框：课程名 / 老师 / 地点 / 备注 / DDL 标题里命中哪个字都算 */
  query: '',
  includeCompleted: false,
  status: null,
  config: null,
  toast: null,
  theme: 'auto',
  /* accounts (see accounts.py): the session cookie is HttpOnly, so the app
     learns who it is by asking /api/auth/session, never by reading a cookie. */
  user: null,
  accounts: { enabled: true, registration_open: true, invite_required: false, captcha_required: false, password_min_length: 6 },
  accountsReady: false,
  viewerAdmin: false,
  authBusy: false,
  authError: '',
  authNotice: '',
  /* 图形验证码最近一次拉取失败的原因（只在提示语里露面，方便诊断）。 */
  captchaError: '',
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

/**
 * 弹一条提示。``options.action`` 可以带一个按钮（比如删除后的「撤销」）。
 */
export function notify(text, tone = 'info', options = {}) {
  const { action = null, duration = 3200 } = options
  state.toast = { text, tone, action }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    state.toast = null
  }, duration)
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

function loadCachedData() {
  try {
    const rawEvents = localStorage.getItem(EVENTS_CACHE_KEY)
    if (rawEvents) {
      const parsed = JSON.parse(rawEvents)
      if (Array.isArray(parsed?.items) && parsed.items.length > 0) {
        state.events = parsed.items
        state.total = parsed.total ?? parsed.items.length
        if (parsed.timestamp) {
          state.lastUpdated = new Date(parsed.timestamp)
        }
      }
    }
  } catch (e) {
    /* ignore */
  }

  try {
    const rawUser = localStorage.getItem(USER_CACHE_KEY)
    if (rawUser) {
      const parsedUser = JSON.parse(rawUser)
      if (parsedUser && typeof parsedUser === 'object') {
        state.user = parsedUser
      }
    }
  } catch (e) {
    /* ignore */
  }

  try {
    const rawConfig = localStorage.getItem(CONFIG_CACHE_KEY)
    if (rawConfig) {
      const parsedConfig = JSON.parse(rawConfig)
      if (parsedConfig && typeof parsedConfig === 'object') {
        state.config = parsedConfig
        state.viewerAdmin = Boolean(parsedConfig?.viewer?.admin)
        if (parsedConfig?.accounts) {
          state.accounts = { ...(state.accounts || {}), ...parsedConfig.accounts }
        }
      }
    }
  } catch (e) {
    /* ignore */
  }

  try {
    const rawStatus = localStorage.getItem(STATUS_CACHE_KEY)
    if (rawStatus) {
      const parsedStatus = JSON.parse(rawStatus)
      if (parsedStatus && typeof parsedStatus === 'object') {
        state.status = parsedStatus
      }
    }
  } catch (e) {
    /* ignore */
  }
}

function saveEventsCache(items, total) {
  try {
    localStorage.setItem(
      EVENTS_CACHE_KEY,
      JSON.stringify({
        items,
        total,
        timestamp: Date.now(),
      })
    )
  } catch (e) {
    /* ignore storage quota errors */
  }
}

function saveConfigCache(config) {
  try {
    if (config) {
      localStorage.setItem(CONFIG_CACHE_KEY, JSON.stringify(config))
    }
  } catch (e) {}
}

function saveStatusCache(status) {
  try {
    if (status) {
      localStorage.setItem(STATUS_CACHE_KEY, JSON.stringify(status))
    }
  } catch (e) {}
}

/** 离线待同步操作队列管理 */
function getSyncQueue() {
  try {
    const raw = localStorage.getItem(SYNC_QUEUE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function appendSyncQueue(action) {
  try {
    const queue = getSyncQueue()
    queue.push({ ...action, timestamp: Date.now() })
    localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(queue))
  } catch {}
}

function clearSyncQueue() {
  try {
    localStorage.removeItem(SYNC_QUEUE_KEY)
  } catch {}
}

/** 异步向服务器回写离线操作队列（仅在手动或后台同步时触发） */
export async function flushSyncQueue() {
  const queue = getSyncQueue()
  if (!queue.length) return
  const remaining = []
  for (const item of queue) {
    try {
      if (item.type === 'create') {
        await api.createEvent(item.payload)
      } else if (item.type === 'patch') {
        await api.patchEvent(item.id, item.payload)
      } else if (item.type === 'delete') {
        await api.deleteEvent(item.id, item.options || {})
      }
    } catch (e) {
      remaining.push(item)
    }
  }
  try {
    if (remaining.length) {
      localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(remaining))
    } else {
      clearSyncQueue()
    }
  } catch {}
}

function saveUserCache(user) {
  try {
    if (user) {
      localStorage.setItem(USER_CACHE_KEY, JSON.stringify(user))
    } else {
      localStorage.removeItem(USER_CACHE_KEY)
    }
  } catch (e) {
    /* ignore */
  }
}

export async function refresh({ silent = false } = {}) {
  // 如果本地有缓存的课表数据，则无需展示全屏 loading 转圈，实现视觉无感秒出
  if (!silent && (!state.events || state.events.length === 0)) {
    state.loading = true
  }
  try {
    const payload = await api.events(fetchParams())
    state.events = payload.items || []
    state.total = payload.total ?? state.events.length
    state.error = ''
    state.authRequired = false
    state.lastUpdated = new Date()
    // 异步更新本地离线缓存
    saveEventsCache(state.events, state.total)
  } catch (error) {
    if (isAuthError(error)) {
      state.authRequired = true
      state.error = ''
    } else {
      // 若已有缓存课表展示，网络报错仅在控制台或弱提示，不冲垮已渲染的课表
      if (!state.events || state.events.length === 0) {
        state.error = error.message || '加载失败'
      }
    }
  } finally {
    state.loading = false
  }
}

export async function loadStatus() {
  try {
    state.status = await api.status()
    state.statusLocked = false
    saveStatusCache(state.status)
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
    saveConfigCache(state.config)
  } catch (error) {
    if (isAuthError(error)) {
      state.statusLocked = true
    }
  }
}

export async function bootstrap() {
  // 1. 毫秒级闪存恢复全部状态：课表、日程、配置、用户信息全部就绪，0 延迟
  loadCachedData()

  // 2. 移动端强本地化策略：如果本地已有缓存数据，则首屏完全不阻塞等待网络请求
  const isMobile = isMobileNativeApp()
  const hasLocalData = state.events && state.events.length > 0

  if (isMobile && hasLocalData) {
    // 移动端在后台静默尝试同步离线队列，不阻塞 UI 渲染和用户交互
    setTimeout(() => {
      flushSyncQueue().catch(() => {})
    }, 1500)
    return
  }

  // 3. 首次启动或 Web 页面下并行拉取更新
  await Promise.all([refresh(), loadStatus(), loadConfig()])
}

/* --------------------------------------------------------------- accounts */

/** Ask the backend who we are; safe to call when signed out. */
export async function fetchSession() {
  const isMobile = isMobileNativeApp()
  // 移动端：若本地已有用户信息缓存，优先快速标记就绪，杜绝开屏白屏或被网络请求阻塞
  if (isMobile && state.user) {
    state.accountsReady = true
    return state.user
  }

  try {
    const payload = await api.session()
    state.user = payload.user || null
    state.accounts = payload.accounts || state.accounts || { enabled: true }
    state.accountsReady = true
    saveUserCache(state.user)
    return state.user
  } catch (error) {
    state.accountsReady = true
    state.accounts = state.accounts || { enabled: true }
    return null
  }
}

export const signInRequired = () => {
  // 如果开启了账号系统，且既没有已登录用户、也没有 ADMIN_TOKEN
  const accountsEnabled = Boolean(state.accounts?.enabled)
  const notLoggedIn = !state.user && !hasToken()
  if (!accountsEnabled || !notLoggedIn) return false

  // 1. 明确被要求认证（如请求返回 401/403 或用户主动点击登录门）
  if (state.authRequired || state.forceAuth) return true

  // 2. 本地完全没有课程/日程缓存数据（全新初次启动或已清空所有数据），直接呼出登录/注册页
  const noLocalEvents = !state.events || state.events.length === 0
  if (noLocalEvents) return true

  return false
}

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
    if (payload.token) {
      setSessionToken(payload.token)
    }
    state.authRequired = false
    state.forceAuth = false
    saveUserCache(state.user)
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
    state.captchaError = ''
    return payload?.enabled === false ? null : payload
  } catch (error) {
    // A captcha we cannot load must not block the form: the server still
    // enforces it, and the user retries once the network is back.
    // 记下失败原因，登录页会把它显示在提示里（否则只有「没有图」这一种症状）。
    state.captchaError = error?.message || '网络错误'
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
  const isMobile = isMobileNativeApp()

  // 1. 移动端秒存：纯本地立即生成或更新内存与闪存，无需等待服务器返回
  if (isMobile) {
    let localItem = null
    if (existing) {
      localItem = { ...existing, ...payload, updated_at: new Date().toISOString() }
      const idx = state.events.findIndex((e) => e.id === existing.id)
      if (idx >= 0) state.events.splice(idx, 1, localItem)
      appendSyncQueue({ type: 'patch', id: existing.id, payload })
    } else {
      const tempId = `local_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
      localItem = {
        id: tempId,
        source: 'custom',
        status: 'pending',
        created_at: new Date().toISOString(),
        ...payload,
      }
      state.events.unshift(localItem)
      state.total += 1
      appendSyncQueue({ type: 'create', payload })
    }
    // 立即写回本地永久缓存
    saveEventsCache(state.events, state.total)
    closeCustomEditor()
    notify(existing ? '日程已在本地更新' : '日程已在本地添加', 'ok')

    // 后台静默将变更回传服务器，用户无需等待
    setTimeout(() => {
      flushSyncQueue().catch(() => {})
    }, 500)
    return localItem
  }

  // 2. 网页端维持向服务器即时请求
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

export async function removeCustomEvent(id, options = {}) {
  const target = state.events.find((item) => item.id === id)
  const applyScope = options.apply_scope || 'single'
  const isMobile = isMobileNativeApp()

  if (isMobile) {
    // 移动端：直接从本地状态剔除并存入同步队列
    const index = state.events.findIndex((e) => e.id === id)
    if (index >= 0) {
      state.events.splice(index, 1)
      state.total = Math.max(0, state.total - 1)
      saveEventsCache(state.events, state.total)
    }
    closeCustomEditor()
    appendSyncQueue({ type: 'delete', id, options })
    notify(`已在本地移除${target ? `「${target.title}」` : '这条日程'}`, 'info')
    setTimeout(() => flushSyncQueue().catch(() => {}), 500)
    return true
  }

  try {
    await api.deleteEvent(id, { apply_scope: applyScope })
    closeCustomEditor()
    const scopeNote = applyScope === 'all' ? '（系列全部）' : applyScope === 'future' ? '（当前及后续）' : ''
    notify(`已移除${target ? `「${target.title}」` : '这条日程'}${scopeNote}`, 'info', {
      action: { label: '撤销', run: () => restoreEvent(id) },
      duration: 6000,
    })
    await refresh({ silent: true })
    return true
  } catch (error) {
    notify(error.message || '删除失败', 'danger')
    return false
  }
}

/* ------------------------------------------------------- 删除（可撤销） */

/**
 * 右滑删除日程。
 *
 * 删掉 = 软删除：这条日程从时间线、以及对外订阅的日历（ICS）里一起消失，
 * 同步也不会再把它拉回来。所以撤销只要把 hidden 抹掉。
 */
export function loadWeekCache() {
  try {
    const raw = localStorage.getItem(WEEK_CACHE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed?.items) && parsed.items.length > 0) {
        return parsed.items
      }
    }
  } catch (e) {
    /* ignore */
  }
  return []
}

export function saveWeekCache(items) {
  try {
    if (Array.isArray(items) && items.length > 0) {
      localStorage.setItem(
        WEEK_CACHE_KEY,
        JSON.stringify({
          items,
          timestamp: Date.now(),
        })
      )
    }
  } catch (e) {
    /* ignore storage quota */
  }
}

export async function removeEvent(event) {
  const index = state.events.findIndex((item) => item.id === event.id)
  const snapshot = index >= 0 ? state.events[index] : null
  if (index >= 0) {
    state.events.splice(index, 1) // 先动 UI，本地立即移除
    state.total = Math.max(0, state.total - 1)
  }

  const isMobile = isMobileNativeApp()
  if (isMobile) {
    saveEventsCache(state.events, state.total)
    appendSyncQueue({ type: 'delete', id: event.id, options: {} })
    notify(removedText(event), 'info', {
      action: { label: '撤销', run: () => restoreEvent(event.id, event.title) },
      duration: 6000,
    })
    setTimeout(() => flushSyncQueue().catch(() => {}), 500)
    return true
  }

  try {
    await api.deleteEvent(event.id)
    notify(removedText(event), 'info', {
      action: { label: '撤销', run: () => restoreEvent(event.id, event.title) },
      duration: 6000,
    })
    await refresh({ silent: true })
    return true
  } catch (error) {
    if (snapshot) {
      state.events.splice(index, 0, snapshot)
      state.total += 1
    }
    notify(error.message || '删除失败', 'danger')
    return false
  }
}

function removedText(event) {
  return `已移除「${event.title}」`
}

/** 撤销删除：恢复回时间线与订阅日历。 */
export async function restoreEvent(id, title = '') {
  try {
    await api.patchEvent(id, { hidden: false })
    notify(title ? `已恢复「${title}」` : '已恢复', 'info')
    await refresh({ silent: true })
    return true
  } catch (error) {
    notify(error.message || '恢复失败', 'danger')
    return false
  }
}

export function clearAllLocalData() {
  try {
    localStorage.clear()
    sessionStorage.clear()
  } catch (e) {}
  setSessionToken('')
  state.events = []
  state.total = 0
  state.user = null
  state.status = null
  state.config = null
  state.authRequired = true
  state.forceAuth = true
  state.error = ''
}

export async function logout() {
  try {
    await api.logout()
  } catch (error) {
    /* clearing a cookie we cannot reach is fine */
  }
  // 彻底清除本地持久化缓存
  clearAllLocalData()
  navigator.serviceWorker?.controller?.postMessage('clear-data-cache')
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
    // 移动端在执行全量同步前，先将本地累积的离线队列刷入服务器
    await flushSyncQueue()
    const outcome = await api.sync()
    await Promise.all([refresh({ silent: true }), loadStatus(), loadConfig()])
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
  event.status = next // 乐观更新内存状态

  const isMobile = isMobileNativeApp()
  if (isMobile) {
    // 移动端：立即更新本地存储与闪存缓存，0 毫秒等待
    saveEventsCache(state.events, state.total)
    appendSyncQueue({ type: 'patch', id: event.id, payload: { status: next } })
    // 静默在后台将状态回写服务器
    setTimeout(() => {
      flushSyncQueue().catch(() => {})
    }, 600)
    return
  }

  // 网页端：发送 PATCH 请求
  try {
    const updated = await api.patchEvent(event.id, { status: next })
    Object.assign(event, updated)
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

// 彻底移除微软待办相关残留方法与状态
export async function fetchMsLists() {
  return false
}

export async function saveMsTask(payload, { silent = false } = {}) {
  return { ok: false, error: '微软待办已下线' }
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

/* ------------------------------------------------ 微北洋课表（一键导入）*/

/*
 * 课表接口 open.twt.edu.cn 只对校园网开放，所以抓取必须发生在**用户自己的浏览器**里：
 * 服务器只拿到最终 JSON，密码从不经过服务器。本机只记住微北洋返回的令牌（可清除），
 * 于是「一键导入」与「打开 App 自动续一次」都不用重新输密码。
 */
const TJU_TOKEN_KEY = 'campushub.twt.token'
const TJU_IMPORT_KEY = 'campushub.twt.lastImport'
const TJU_TRY_KEY = 'campushub.twt.lastTry'

export function readTjuToken() {
  try {
    return localStorage.getItem(TJU_TOKEN_KEY) || ''
  } catch (error) {
    return ''
  }
}

/** 传空串 = 忘掉本机登录（换账号、令牌失效时用）。 */
export function rememberTjuToken(token) {
  try {
    if (token) localStorage.setItem(TJU_TOKEN_KEY, token)
    else localStorage.removeItem(TJU_TOKEN_KEY)
  } catch (error) {
    /* 隐私模式写不了 localStorage —— 退化成每次都输密码，不影响功能 */
  }
}

const readStamp = (key) => {
  try {
    return Number(localStorage.getItem(key) || 0) || 0
  } catch (error) {
    return 0
  }
}
const writeStamp = (key) => {
  try {
    localStorage.setItem(key, String(Date.now()))
  } catch (error) {
    /* 同上 */
  }
}

/**
 * 在用户浏览器里抓课表并导入：有令牌就直接用，否则用学号+密码换一个令牌。
 * 成功后刷新本地 config，调用方随后跑一次 runSync() 就能看到新日程。
 */
export async function tjuBrowserImport({ token = '', username = '', password = '' } = {}) {
  let live = token || readTjuToken()
  if (!live) {
    if (!username || !password) {
      throw new TwtError('需要学号 + 微北洋密码（只在你本机用，不会上传）', 'credentials')
    }
    live = await browserLogin(username, password)
  }
  rememberTjuToken(live)
  let payload
  try {
    payload = await browserClasstable(live)
  } catch (error) {
    writeStamp(TJU_TRY_KEY)
    // 令牌过期/被踢：本机的记录立刻作废，下次用密码重来，避免一直撞墙。
    if (error instanceof TwtError && error.kind === 'credentials') rememberTjuToken('')
    throw error
  }
  const result = await api.tjuImport({ payload, source: 'browser' })
  writeStamp(TJU_IMPORT_KEY)
  writeStamp(TJU_TRY_KEY)
  await Promise.all([loadConfig(), refresh({ silent: true })])
  return { result, courses: payload?.data?.data?.length ?? 0 }
}

/**
 * 打开 App 时静默续一次课表：距上次成功超过 maxAgeHours、且距上次尝试超过 retryMinutes 才真发请求。
 * 优先走**服务器上的教务凭据**（不用校园网）；没有才退回本机微北洋令牌。失败静默放弃，不打扰用户。
 */
export async function autoRefreshTju({ maxAgeHours = 6, retryMinutes = 30 } = {}) {
  // 移动端强本地化：除非用户主动在界面上点击「同步」，否则开屏时不自主向教务发起静默请求，极速启动省电流畅
  if (isMobileNativeApp()) return null

  if (typeof window === 'undefined') return null
  if (!state.config?.tju?.import_meta?.courses) return null
  const now = Date.now()
  if (now - readStamp(TJU_TRY_KEY) < retryMinutes * 60 * 1000) return null
  if (now - readStamp(TJU_IMPORT_KEY) < maxAgeHours * 3600 * 1000) return null

  // 教务系统（CAS）在服务器上跑，不依赖校园网 —— 有凭据就用它。
  const jw = await loadJwStatus()
  if (jw?.credentials_saved) {
    try {
      const result = await jwRefresh()
      const courses = result?.detail?.import?.courses
      if (courses) notify(`课表已自动更新（${courses} 门）`, 'ok')
      return courses
    } catch (error) {
      writeStamp(TJU_TRY_KEY)
      return null
    }
  }

  // 兜底：本机微北洋令牌（只有校园网里能成，失败就安静地算了）。
  if (!readTjuToken()) return null
  try {
    const { courses } = await tjuBrowserImport({})
    if (courses) notify(`课表已自动更新（${courses} 门）`, 'ok')
    return courses
  } catch (error) {
    return null
  }
}

/* --------------------------------------- 教务系统（CAS 直连，主路径）*/

/*
 * 这两条路的区别（决定了普通用户到底能不能用）：
 *
 *   微北洋 open.twt.edu.cn  —— 只对校园网开放，而且是**浏览器跨站请求**，会被 CORS 拦；
 *                              官方那条 get_classes 现在还对所有账号回「学期解析失败」。
 *                              → 校园网里也经常失败，只能当兜底。
 *   教务系统 sso.tju.edu.cn —— 统一身份认证，**公网可达**（海外 VPS 实测能到），
 *                              classes.tju.edu.cn/eams 同样可达。所以放在服务器上跑：
 *                              不受校园网、浏览器跨站限制，只要学号 + 教务密码
 *                              （+ 一次图形验证码，服务器先替你 OCR）。
 */

/** 服务器上有没有存着教务凭据 / 上次导入结果（不含任何密码）。 */
export async function loadJwStatus() {
  try {
    return await api.jwStatus()
  } catch (error) {
    return null
  }
}

/**
 * 用学号 + 教务密码导入课表（服务器直连 CAS）。
 * 需要人工验证码时抛 ApiError，`error.detail.kind === 'captcha'`。
 */
export async function jwImport(payload) {
  const result = await api.jwImport(payload)
  writeStamp(TJU_IMPORT_KEY)
  writeStamp(TJU_TRY_KEY)
  await Promise.all([loadConfig(), refresh({ silent: true })])
  return result
}

/** 用服务器上已保存的教务凭据免密续一次（不需要校园网、不需要本机令牌）。 */
export async function jwRefresh() {
  const result = await api.jwRefresh()
  writeStamp(TJU_IMPORT_KEY)
  writeStamp(TJU_TRY_KEY)
  await Promise.all([loadConfig(), refresh({ silent: true })])
  return result
}

export async function forgetJw() {
  const result = await api.jwForget()
  await loadConfig()
  return result
}

/* -------------------------------------------------------------- filtering */

/** 搜索命中判定：标题、老师、地点、备注、来源，大小写不敏感。 */
export function matchesQuery(event, query = state.query) {
  const needle = String(query || '').trim().toLowerCase()
  if (!needle) return true
  return [event.title, event.teacher, event.location, event.description, event.source]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .includes(needle)
}

export function filterEvents(events = state.events) {
  const today = todayKey()
  const nowTs = Date.now()
  return events.filter((event) => {
    if (state.filter === 'class' && event.is_deadline) return false
    if (state.filter === 'deadline' && !event.is_deadline) return false
    // 划掉的 DDL 一律不占课表（用户原话「划掉的 ddl 就不要显示在里面了」）。
    if (event.is_deadline && event.status === 'completed') return false
    // 已经结束的课不再显示在列表里（用户原话「已经结束的课不再显示在课表和列表里」）
    if (!state.includeCompleted && isEventEnded(event, nowTs)) return false
    if (!state.includeCompleted && event.status === 'completed') return false
    if (state.source !== 'all' && event.source !== state.source) return false
    // keep overdue deadlines visible, drop long-finished classes
    const reference = dayKey(event.end_time || event.start_time)
    if (reference < today && event.is_deadline && event.status === 'completed') return false
    return matchesQuery(event)
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
