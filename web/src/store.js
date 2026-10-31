/**
 * Global reactive store — deliberately dependency-free (no Pinia) because the
 * app state is small: one event list, one status blob, a few UI flags.
 */
import { reactive } from 'vue'
import { api, ApiError, getSessionToken, getToken, isAuthError, setSessionToken, setToken } from './api'
import { dayKey, isEventEnded, todayKey } from './utils/datetime'

const THEME_KEY = 'campushub.theme'
const GRID_STYLE_KEY = 'campushub.week_grid_style'
const FROSTED_GLASS_KEY = 'campushub.frosted_glass_style'
const EVENTS_CACHE_KEY = 'campushub.events_cache.v1'
const WEEK_CACHE_KEY = 'campushub.week_cache.v1'
const USER_CACHE_KEY = 'campushub.user_cache.v1'
const CONFIG_CACHE_KEY = 'campushub.config_cache.v1'
const STATUS_CACHE_KEY = 'campushub.status_cache.v1'
const SYNC_QUEUE_KEY = 'campushub.offline_sync_queue.v1'
const DELETED_IDS_KEY = 'campushub.deleted_event_ids.v1'
const COMPLETED_OVERRIDES_KEY = 'campushub.completed_overrides.v1'
const BACKGROUND_CONFIG_KEY = 'campushub.background_config.v1'
const LOOKAHEAD_DAYS = 60

function readInitialBackgroundConfig() {
  const defaults = {
    enabled: false,
    lightUrl: '',
    darkUrl: '',
    opacity: 35, // 0 - 100%
    blur: 0,    // 0 - 20px
  }
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(BACKGROUND_CONFIG_KEY)
      if (raw) return { ...defaults, ...JSON.parse(raw) }
    }
  } catch {}
  return defaults
}

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

function readInitialEvents() {
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem('campushub.events_cache.v1')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed?.items) && parsed.items.length > 0) {
          return parsed.items
        }
      }
    }
  } catch (e) {}
  return []
}

function readInitialUser() {
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem('campushub.user_cache.v1')
      return raw ? JSON.parse(raw) : null
    }
  } catch (e) {}
  return null
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
  events: readInitialEvents(),
  total: readInitialEvents().length,
  filter: 'all', // all | class | deadline
  source: 'all',
  /* 搜索框：课程名 / 老师 / 地点 / 备注 / DDL 标题里命中哪个字都算 */
  query: '',
  includeCompleted: false,
  status: null,
  config: null,
  toast: null,
  theme: 'auto',
  /* 课表底色模式：'grid'（默认网格）或 'blank'（空白底） */
  weekGridStyle: (function () {
    try {
      return localStorage.getItem('campushub.week_grid_style') || 'grid'
    } catch (e) {
      return 'grid'
    }
  })(),
  /* 磨砂玻璃质感：'auto'（跟随系统智能识别） | 'on'（强制开启） | 'off'（关闭） */
  frostedGlassMode: (function () {
    try {
      return localStorage.getItem('campushub.frosted_glass_style') || 'auto'
    } catch (e) {
      return 'auto'
    }
  })(),
  isFrostedActive: false,
  systemInfo: { system: 'other', name: '通用系统', supportsBlur: false },
  /* 背景图配置：支持图床根据主题加载与自定义 URL、遮罩不透明度、模糊度 */
  backgroundConfig: readInitialBackgroundConfig(),
  isDarkTheme: false,
  /* accounts (see accounts.py): the session cookie is HttpOnly, so the app
     learns who it is by asking /api/auth/session, never by reading a cookie. */
  user: readInitialUser(),
  accounts: { enabled: true, registration_open: true, invite_required: false, captcha_required: true, password_min_length: 8 },
  accountsReady: Boolean(readInitialUser()),
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

export function setWeekGridStyle(style) {
  const s = style === 'blank' ? 'blank' : style === 'subgrid' ? 'subgrid' : 'grid'
  state.weekGridStyle = s
  try {
    localStorage.setItem(GRID_STYLE_KEY, s)
  } catch (error) {
    /* ignore */
  }
}

/** 检测设备是否满足 Android 15+ 或 iOS 自动开启磨砂玻璃条件 */
export function checkAutoFrostedSupport() {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return false
  }
  const ua = navigator.userAgent || ''
  const supportsBlur = Boolean(
    typeof CSS !== 'undefined' &&
      CSS.supports &&
      (CSS.supports('backdrop-filter', 'blur(10px)') || CSS.supports('-webkit-backdrop-filter', 'blur(10px)')),
  )
  if (!supportsBlur) return false

  const isApple = /iPad|iPhone|iPod|Macintosh/i.test(ua)
  const androidMatch = ua.match(/Android\s+([0-9]+)/i)
  const isAndroid15Plus = Boolean(androidMatch && parseInt(androidMatch[1], 10) >= 15)

  return isApple || isAndroid15Plus
}

export function initFrostedGlass() {
  let stored = 'auto'
  try {
    stored = localStorage.getItem(FROSTED_GLASS_KEY) || 'auto'
  } catch (e) {}
  state.frostedGlassMode = stored
  applyFrostedGlass(stored)
}

export function setFrostedGlassMode(mode) {
  const m = mode === 'on' ? 'on' : mode === 'off' ? 'off' : 'auto'
  state.frostedGlassMode = m
  try {
    localStorage.setItem(FROSTED_GLASS_KEY, m)
  } catch (e) {}
  applyFrostedGlass(m)
}

function applyFrostedGlass(mode) {
  let active = false
  if (mode === 'on') {
    active = true
  } else if (mode === 'off') {
    active = false
  } else {
    // 'auto' 模式：安卓 15 以上或 iOS 自动开启
    active = checkAutoFrostedSupport()
  }
  state.isFrostedActive = active
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('frosted-glass-active', active)
  }
}

function applyTheme(mode) {
  const prefersDark =
    typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
  const dark = mode === 'dark' || (mode === 'auto' && prefersDark)
  state.isDarkTheme = dark
  document.documentElement.classList.toggle('dark', dark)
}

export function saveBackgroundConfig(patch) {
  state.backgroundConfig = { ...state.backgroundConfig, ...patch }
  try {
    localStorage.setItem(BACKGROUND_CONFIG_KEY, JSON.stringify(state.backgroundConfig))
  } catch (e) {}
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

/** 已在本地明确删除的任务 ID 墓碑集合（防网络往返冲撞与左右脑互搏） */
function getDeletedEventIds() {
  try {
    const raw = localStorage.getItem(DELETED_IDS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function recordDeletedEventId(id) {
  try {
    const map = getDeletedEventIds()
    map[id] = Date.now()
    localStorage.setItem(DELETED_IDS_KEY, JSON.stringify(map))
  } catch {}
}

function unrecordDeletedEventId(id) {
  try {
    const map = getDeletedEventIds()
    delete map[id]
    localStorage.setItem(DELETED_IDS_KEY, JSON.stringify(map))
  } catch {}
}

/**
 * 本地完成态（划掉）覆盖保护机制：
 * 针对网络延迟、上传失败或离线时，用户在客户端划掉的任务，
 * 即使服务器尚未同步成功、返回旧数据，也坚决以本地划掉状态为准，彻底根治「回光返照」。
 */
function getCompletedOverrides() {
  try {
    const raw = localStorage.getItem(COMPLETED_OVERRIDES_KEY)
    if (!raw) return {}
    const map = JSON.parse(raw)
    const now = Date.now()
    const valid = {}
    // 保留 7 天以内的本地完成状态覆盖
    for (const [id, item] of Object.entries(map)) {
      if (item && typeof item === 'object' && item.status && now - (item.timestamp || 0) < 7 * 86400000) {
        valid[id] = item
      }
    }
    return valid
  } catch {
    return {}
  }
}

function recordCompletedOverride(id, status) {
  try {
    const map = getCompletedOverrides()
    map[id] = { status, timestamp: Date.now() }
    localStorage.setItem(COMPLETED_OVERRIDES_KEY, JSON.stringify(map))
  } catch {}
}

function unrecordCompletedOverride(id) {
  try {
    const map = getCompletedOverrides()
    delete map[id]
    localStorage.setItem(COMPLETED_OVERRIDES_KEY, JSON.stringify(map))
  } catch {}
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
        // 服务器确认成功写入后，移除本地覆盖保护
        if (item.payload?.status) {
          unrecordCompletedOverride(item.id)
        }
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
    const deletedMap = getDeletedEventIds()
    const completedOverrides = getCompletedOverrides()
    const rawItems = payload.items || []

    // 1. 过滤掉本地已显式删除的事件（墓碑机制）
    // 2. 强保护：若本地有尚未被服务器覆盖确认的完成状态（如刚刚划掉的任务），坚决以本地操作为准，彻底杜绝回光返照
    state.events = rawItems
      .filter((it) => !deletedMap[it.id])
      .map((it) => {
        const override = completedOverrides[it.id]
        if (override && override.status) {
          return { ...it, status: override.status }
        }
        return it
      })

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
  // 无论移动端还是网页端，如果启动前已从 LocalStorage 恢复了用户，保持 accountsReady 为 true，杜绝开屏闪现登录框
  if (state.user) {
    state.accountsReady = true
  }

  try {
    const payload = await api.session()
    // 只有当服务端明确返回了已认证用户时才覆盖本地；如果返回未登录，且本地有离线凭据，不要直接清空本地 user
    if (payload.authenticated && payload.user) {
      state.user = payload.user
      saveUserCache(state.user)
    } else if (!isMobile) {
      // 桌面网页端无凭据时同步置空
      state.user = null
      saveUserCache(null)
    }
    state.accounts = payload.accounts || state.accounts || { enabled: true }
    state.accountsReady = true
    return state.user
  } catch (error) {
    state.accountsReady = true
    state.accounts = state.accounts || { enabled: true }
    return state.user
  }
}

export const signInRequired = () => {
  // 1. 如果用户主动点击了登录、或收到了明确的 401/403 认证拒绝
  if (state.authRequired || state.forceAuth) return true

  // 2. 如果开启了账号系统，且当前本地既没有登录用户、也没有任何会话或管理令牌
  const accountsEnabled = Boolean(state.accounts?.enabled)
  const hasUserSession = Boolean(state.user) || Boolean(getSessionToken())
  const notLoggedIn = !hasUserSession && !hasToken()
  if (!accountsEnabled || !notLoggedIn) return false

  // 3. 若处于完全未登录状态且本地没有任何课程/日程数据（初次安装或数据已清空），才唤起登录界面
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

  // 核心：无论移动端还是网页端，立即登记墓碑并持久化，杜绝多端或周视图异步回写导致数据冲刷复活
  recordDeletedEventId(event.id)
  saveEventsCache(state.events, state.total)

  // 同时也更新周课表缓存
  try {
    const rawWeek = localStorage.getItem(WEEK_CACHE_KEY)
    if (rawWeek) {
      const parsed = JSON.parse(rawWeek)
      if (Array.isArray(parsed?.items)) {
        parsed.items = parsed.items.filter((it) => it.id !== event.id)
        localStorage.setItem(WEEK_CACHE_KEY, JSON.stringify(parsed))
      }
    }
  } catch (e) {}

  const isMobile = isMobileNativeApp()
  if (isMobile) {
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
    unrecordDeletedEventId(event.id)
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
    // 1. 优先将本地累积的待提交修改（如划掉的任务）刷入服务器
    await flushSyncQueue()
    // 2. 刷新本地界面，确保即时呈现最新事件
    await Promise.all([refresh({ silent: true }), loadStatus(), loadConfig()])
    // 3. 触发后端连接器后台同步（带 30s 宽裕超时）
    const outcome = await api.sync()
    await refresh({ silent: true })
    const summary = `新增 ${outcome.created ?? 0} · 更新 ${outcome.updated ?? 0} · 清理 ${outcome.pruned ?? 0}`
    notify(outcome.ok === false ? `同步部分完成：${summary}` : `同步完成：${summary}`, outcome.ok === false ? 'warn' : 'ok')
  } catch (error) {
    // 即使后端外部连接器偶尔超时，本地数据已安全刷新
    notify(error.message || '同步完成（部分连接器响应超时）', 'warn')
  } finally {
    state.syncing = false
  }
}

export async function toggleCompleted(event) {
  const next = event.status === 'completed' ? 'pending' : 'completed'
  const previous = event.status

  // 1. 乐观更新内存状态（0ms 响应）
  event.status = next

  // 2. 强保护：写入本地完成态覆盖记录与闪存缓存，彻底杜绝被服务器旧数据冲刷导致「回光返照」
  recordCompletedOverride(event.id, next)
  saveEventsCache(state.events, state.total)

  // 3. 打入离线同步队列
  appendSyncQueue({ type: 'patch', id: event.id, payload: { status: next } })

  const isMobile = isMobileNativeApp()
  if (isMobile) {
    // 移动端：静默后台异步提交，不阻塞 UI
    setTimeout(() => {
      flushSyncQueue().catch(() => {})
    }, 400)
    return
  }

  // 网页端：立即发起后台提交
  try {
    const updated = await api.patchEvent(event.id, { status: next })
    Object.assign(event, updated)
    // 提交成功，安全释放本地覆盖记录
    unrecordCompletedOverride(event.id)
  } catch (error) {
    // 仅在明确遇到未登录/权限拒绝（401/403）时才回滚状态
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      event.status = previous
      unrecordCompletedOverride(event.id)
      saveEventsCache(state.events, state.total)
      state.authRequired = true
      notify('请先登录账号后再操作', 'warn')
    } else {
      // 网络慢或临时连接异常：坚决保留用户的划掉状态，等待下次自动重试同步，绝不回光返照！
      console.warn('离线暂存完成态，稍后自动重试同步:', error.message)
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
/**
 * 天大课表主路径：教务系统 CAS 直连同步（sso.tju.edu.cn -> classes.tju.edu.cn/eams）
 * 彻底移除微北洋浏览器直连/本地 Token/手动导入等陈旧兜底。
 */
export async function autoRefreshTju({ maxAgeHours = 6, retryMinutes = 30 } = {}) {
  // 移动端强本地化：除非用户主动在界面上点击「同步」，否则开屏时不自主向教务发起静默请求，极速启动省电流畅
  if (isMobileNativeApp()) return null

  if (typeof window === 'undefined') return null
  if (!state.config?.tju?.import_meta?.courses) return null

  // 教务系统（CAS）在服务器上跑，公网可达，不依赖校园网 —— 有凭据就用它
  const jw = await loadJwStatus()
  if (jw?.credentials_saved) {
    try {
      const result = await jwRefresh()
      const courses = result?.detail?.import?.courses
      if (courses) notify(`课表已自动更新（${courses} 门）`, 'ok')
      return courses
    } catch (error) {
      return null
    }
  }
  return null
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
