/**
 * Global reactive store — deliberately dependency-free (no Pinia) because the
 * app state is small: one event list, one status blob, a few UI flags.
 */
import { reactive } from 'vue'
import { api, ApiError, getServerClockOffsetMs, getSessionToken, getToken, isAuthError, isOfflineMode, noteServerTime, setOfflineMode as persistOfflineMode, setSessionToken, setToken } from './api'
import { dayKey, formatShanghaiIso, isEventEnded, toDate, todayKey } from './utils/datetime'
import { applyThemeColor, getSavedThemeColor } from './utils/themeColors'
import { dedupeEvents } from './utils/dedupe'
import {
  computeNextMutationIso,
  generateClientSourceId,
  makeCustomEventId,
  mergeServerEventWithLocal,
  mergeSyncedCreateResult,
  parseEventModifiedMs,
  parseTimestampMs,
  reconcileEventCollections,
  shouldApplySyncedPatchResult,
} from './utils/lww'
import {
  clearWallpaperSnapshots,
  ensureWallpapersCached,
  getInstantWallpaperSrc,
} from './utils/wallpaperCache'

const nextMutationIso = (existingEvent = null) =>
  computeNextMutationIso(existingEvent, getServerClockOffsetMs())

const THEME_KEY = 'campushub.theme'
const GRID_STYLE_KEY = 'campushub.week_grid_style'
const WEEK_ANCHOR_KEY = 'campushub.week_anchor_mode'
const FROSTED_GLASS_KEY = 'campushub.frosted_glass_style'
const EVENTS_CACHE_KEY = 'campushub.events_cache.v1'
const WEEK_CACHE_KEY = 'campushub.week_cache.v1'
const USER_CACHE_KEY = 'campushub.user_cache.v1'
const CONFIG_CACHE_KEY = 'campushub.config_cache.v1'
const STATUS_CACHE_KEY = 'campushub.status_cache.v1'
const SYNC_QUEUE_KEY = 'campushub.offline_sync_queue.v1'
const DELETED_IDS_KEY = 'campushub.deleted_event_ids.v1'
const COMPLETED_OVERRIDES_KEY = 'campushub.completed_overrides.v1'
const IMPORTANT_IDS_KEY = 'campushub.important_ids.v1'
const BACKGROUND_CONFIG_KEY = 'campushub.background_config.v1'
const LOOKBACK_DAYS = 60
const LOOKAHEAD_DAYS = 180

function readInitialImportantIds() {
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(IMPORTANT_IDS_KEY)
      return raw ? new Set(JSON.parse(raw)) : new Set()
    }
  } catch (e) {}
  return new Set()
}

const importantEventIds = reactive(readInitialImportantIds())

export function isImportantEvent(eventOrId) {
  if (!eventOrId) return false
  const id = typeof eventOrId === 'string' ? eventOrId : eventOrId?.id
  if (id && importantEventIds.has(id)) return true
  if (typeof eventOrId === 'object' && eventOrId?.priority === 1) return true
  return false
}

export function toggleImportantEvent(event) {
  if (!event || !event.id) return false
  const id = event.id
  const currentlyImportant = isImportantEvent(event)
  const nextImportant = !currentlyImportant

  if (nextImportant) {
    importantEventIds.add(id)
  } else {
    importantEventIds.delete(id)
  }

  try {
    localStorage.setItem(IMPORTANT_IDS_KEY, JSON.stringify([...importantEventIds]))
  } catch (e) {}

  // 若为自定义事件或待办，同步向服务端持久化 priority 字段 (1=高优先级重点，5=普通)
  const nowIso = nextMutationIso(event)
  event.priority = nextImportant ? 1 : 5
  event.updated_at = nowIso
  event.client_updated_at = nowIso
  saveEventsCache(state.events, state.total)
  if (!state.offlineMode && event.source === 'custom') {
    const qid = appendSyncQueue({ type: 'patch', id, payload: { priority: event.priority, client_updated_at: nowIso } })
    if (!String(id).startsWith('local_')) {
      api.patchEvent(id, { priority: event.priority, client_updated_at: nowIso })
        .then(() => removeSyncQueueItem(qid))
        .catch(() => {})
    }
  }

  return nextImportant
}

function readInitialBackgroundConfig() {
  const defaults = {
    enabled: true, // 默认开启深空摄影背景图与通透微晶磨砂深度融合
    // 默认分类：深空天文与轨道摄影
    category: 'astronomy',
    lightUrl: 'https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?auto=format&fit=crop&w=1920&q=85',
    darkUrl: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1920&q=85',
    wallpaperTitle: '轨道地球与夜色灯火',
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
          return dedupeEvents(parsed.items.filter((it) => it && !it.hidden))
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
  /* 课表列对齐偏好：默认 'today_second'（今天固定在第二列，昨天在第一列），可选 'monday_first'（周一至周日整周） */
  weekAnchorMode: (function () {
    try {
      const saved = localStorage.getItem('campushub.week_anchor_mode')
      return saved === 'monday_first' ? 'monday_first' : 'today_second'
    } catch (e) {
      return 'today_second'
    }
  })(),
  /* 设置二级子菜单路由（null = 设置首页一级菜单） */
  settingsSubpage: null,
  /* 壁纸本地缓存完成信号（驱动首屏后无感升级高清缓存） */
  bgCacheTick: 0,
  /* 全局自定义主题主色调（预设 id 或自定义 hex） */
  themeColor: getSavedThemeColor(),
  /* 当前课表可视周次标签与居中状态 */
  weekLabel: '第 1 周',
  isCurrentWeekCentered: true,
  /* 磨砂玻璃质感：默认关闭 'off'，保留纯净自然的轻量半透明质感 */
  frostedGlassMode: (function () {
    try {
      return localStorage.getItem('campushub.frosted_glass_style') || 'off'
    } catch (e) {
      return 'off'
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
  /* 离线模式：不登录、不联网，数据只在本机（本地账号） */
  offlineMode: isOfflineMode(),
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
  /* 「可办」页的极简新建：只有标题 + 备注，跟日程编辑器彻底分开 */
  todoQuickAdd: { open: false },
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
  // 初始化全局主题配色
  applyThemeColor(state.themeColor)
  warmupBackgroundCache()
}

export function setThemeColor(colorIdOrHex) {
  state.themeColor = colorIdOrHex
  applyThemeColor(colorIdOrHex)
}

export function setTheme(mode) {
  state.theme = mode
  try {
    localStorage.setItem(THEME_KEY, mode)
  } catch (error) {
    /* ignore */
  }
  applyTheme(mode)
  warmupBackgroundCache()
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

export function setWeekAnchorMode(mode) {
  const m = mode === 'monday_first' ? 'monday_first' : 'today_second'
  state.weekAnchorMode = m
  try {
    localStorage.setItem(WEEK_ANCHOR_KEY, m)
  } catch (error) {
    /* ignore */
  }
}

export function openSettingsSubpage(subpage = null) {
  state.view = 'settings'
  state.settingsSubpage = subpage
}

/** 检测设备是否满足自动开启磨砂玻璃条件 (只要浏览器/WebView 支持 CSS backdrop-filter 即全量开启) */
export function checkAutoFrostedSupport() {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return false
  }
  const supportsBlur = Boolean(
    typeof CSS !== 'undefined' &&
      CSS.supports &&
      (CSS.supports('backdrop-filter', 'blur(10px)') || CSS.supports('-webkit-backdrop-filter', 'blur(10px)')),
  )
  return supportsBlur
}

export function initFrostedGlass() {
  let stored = 'off'
  try {
    stored = localStorage.getItem(FROSTED_GLASS_KEY) || 'off'
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

export function applyBackgroundClass() {
  if (typeof document !== 'undefined') {
    const enabled = Boolean(state.backgroundConfig?.enabled)
    document.documentElement.classList.toggle('has-custom-bg', enabled)
  }
}

export function warmupBackgroundCache() {
  const cfg = state.backgroundConfig
  if (!cfg?.enabled) return
  ensureWallpapersCached(
    {
      lightUrl: cfg.lightUrl,
      darkUrl: cfg.darkUrl,
      isDark: state.isDarkTheme,
    },
    () => {
      state.bgCacheTick += 1
    },
  )
}

export function getCachedActiveBgUrl() {
  // Touch reactive tick so UI upgrades seamlessly when full-HD CacheStorage blob resolves
  void state.bgCacheTick
  const cfg = state.backgroundConfig
  if (!cfg?.enabled) return ''
  const targetUrl = state.isDarkTheme
    ? cfg.darkUrl || cfg.lightUrl || ''
    : cfg.lightUrl || cfg.darkUrl || ''
  return getInstantWallpaperSrc(targetUrl, state.isDarkTheme)
}

export function saveBackgroundConfig(patch) {
  if (patch && patch.enabled === false && patch.lightUrl === '' && patch.darkUrl === '') {
    clearWallpaperSnapshots()
  }
  state.backgroundConfig = { ...state.backgroundConfig, ...patch }
  try {
    localStorage.setItem(BACKGROUND_CONFIG_KEY, JSON.stringify(state.backgroundConfig))
  } catch (e) {}
  applyBackgroundClass()
  warmupBackgroundCache()
}

/* ------------------------------------------------------------- event feed */

function fetchParams() {
  // 往前拉取 60 天、往后拉取 180 天，附带 include_hidden=true 墓碑同步，确保全学期课表与自定义日程按 ID+最后修改时间完整对齐
  const start = dayKey(new Date(Date.now() - LOOKBACK_DAYS * 86400000))
  const end = dayKey(new Date(Date.now() + LOOKAHEAD_DAYS * 86400000))
  return {
    start_date: start,
    end_date: end,
    limit: 2000,
    include_hidden: true,
    source: state.source === 'all' ? undefined : state.source,
  }
}

/**
 * 从服务器全量拉取已完成的历史归档日程（不受 start_date 限制）
 * 确保换设备、清缓存后历史归档 100% 留存于服务器数据库且能随时拉回
 */
export async function fetchHistoryEvents() {
  if (state.offlineMode) return
  try {
    const [datedRes, undatedRes] = await Promise.all([
      api.events({ status: 'completed', include_hidden: true, limit: 1000 }),
      api.events({ status: 'completed', undated: true, include_hidden: true, limit: 1000 }).catch((err) => {
        if (isAuthError(err)) throw err
        return { items: [] }
      }),
    ])
    const historyItems = [...(datedRes?.items || []), ...(undatedRes?.items || [])]
    if (!historyItems.length) return
    const deletedMap = getDeletedEventIds()
    const completedOverrides = getCompletedOverrides()
    const pendingIds = getPendingSyncIdSet()
    const { activeEvents, nextDeletedMap } = reconcileEventCollections({
      localEvents: state.events,
      serverItems: historyItems,
      pendingIds,
      completedOverrides,
      deletedMap,
      serverWindowComplete: false,
    })
    saveDeletedEventIdsMap(nextDeletedMap)
    state.events = dedupeEvents(activeEvents)
    saveEventsCache(state.events, state.total)
  } catch (e) {
    console.warn('拉取服务器历史归档异常:', e.message)
  }
}

/**
 * 定时段的任务逻辑：过期自动划掉（status = 'completed'）
 * 针对所有个人自定义日程/待办，凡是结束时间已过（now > end_time），自动标记为已划掉完成，
 * 并持久化落盘同步提交至服务器，自动移出课表占用并流转至历史归档
 */
export function autoExpireEndedCustomTasks() {
  const nowTs = Date.now()
  const toPatch = []
  ;(state.events || []).forEach((ev) => {
    // 排除教务课表原生课程，仅针对个人安排的自定义日程与任务；无截止待办没有「结束」概念
    if (ev.source !== 'tju_schedule' && ev.status !== 'completed' && !ev.is_undated && !ev.hidden) {
      if (isEventEnded(ev, nowTs)) {
        const mutIso = nextMutationIso(ev)
        const mutMs = parseTimestampMs(mutIso) || nowTs
        ev.status = 'completed'
        ev.completed_at = ev.completed_at || mutIso
        ev.updated_at = mutIso
        ev.client_updated_at = mutIso
        recordCompletedOverride(ev.id, 'completed', mutMs)
        toPatch.push({ id: ev.id, mutIso })
      }
    }
  })
  if (toPatch.length > 0) {
    saveEventsCache(state.events, state.total)
    toPatch.forEach(({ id, mutIso }) => {
      const qid = appendSyncQueue({ type: 'patch', id, payload: { status: 'completed', client_updated_at: mutIso } })
      if (!state.offlineMode && !String(id).startsWith('local_')) {
        api.patchEvent(id, { status: 'completed', client_updated_at: mutIso })
          .then((updated) => {
            removeSyncQueueItem(qid)
            const cur = (state.events || []).find((e) => e.id === id)
            if (cur && updated && shouldApplySyncedPatchResult(cur, mutIso)) {
              Object.assign(cur, updated, { client_updated_at: updated.updated_at || mutIso })
              unrecordCompletedOverride(id)
              saveEventsCache(state.events, state.total)
            }
          })
          .catch(() => {})
      }
    })
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

/** 已在本地明确删除的任务 ID 墓碑集合（携带单调删除时间戳，保留 30 天防多端往返冲撞复活） */
function getDeletedEventIds() {
  try {
    const raw = localStorage.getItem(DELETED_IDS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    const now = Date.now()
    const valid = {}
    for (const [id, ts] of Object.entries(parsed || {})) {
      const num = Number(ts) || 0
      if (num > 0 && now - num < 30 * 86400000) valid[id] = num
    }
    return valid
  } catch {
    return {}
  }
}

function saveDeletedEventIdsMap(map) {
  try {
    localStorage.setItem(DELETED_IDS_KEY, JSON.stringify(map || {}))
  } catch {}
}

export function isEventDeleted(id) {
  if (!id) return false
  return Boolean(getDeletedEventIds()[id])
}

function recordDeletedEventId(id, ts = Date.now()) {
  try {
    const map = getDeletedEventIds()
    map[id] = Math.max(map[id] || 0, Number(ts) || Date.now())
    saveDeletedEventIdsMap(map)
  } catch {}
}

function unrecordDeletedEventId(id) {
  try {
    const map = getDeletedEventIds()
    delete map[id]
    saveDeletedEventIdsMap(map)
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

function recordCompletedOverride(id, status, timestamp = Date.now()) {
  try {
    const map = getCompletedOverrides()
    map[id] = { status, timestamp }
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
    const _qid = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    queue.push({
      ...action,
      _qid,
      timestamp: Date.now(),
    })
    localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(queue))
    return _qid
  } catch {
    return ''
  }
}

function removeSyncQueueItem(qid) {
  if (!qid) return
  try {
    const next = getSyncQueue().filter((q) => q._qid !== qid)
    if (next.length) localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(next))
    else clearSyncQueue()
  } catch {}
}

function getPendingSyncIdSet(queue = getSyncQueue()) {
  const ids = new Set()
  for (const q of queue) {
    if (!q) continue
    if (q.id) ids.add(q.id)
    if (q.temp_id) ids.add(q.temp_id)
    if (Array.isArray(q.temp_ids)) {
      for (const tid of q.temp_ids) {
        if (tid) ids.add(tid)
      }
    }
  }
  return ids
}

function clearSyncQueue() {
  try {
    localStorage.removeItem(SYNC_QUEUE_KEY)
  } catch {}
}

let activeFlushPromise = null
let flushAgainRequested = false

/** 异步向服务器回写离线操作队列（仅在手动或后台同步时触发，单飞串行防止重复提交或覆盖新入队项） */
export async function flushSyncQueue() {
  // 离线模式：永不回传服务器
  if (state.offlineMode) return
  if (activeFlushPromise) {
    flushAgainRequested = true
    return activeFlushPromise
  }
  activeFlushPromise = (async () => {
    const tempIdMap = new Map()
    try {
      do {
        flushAgainRequested = false
        const queue = getSyncQueue()
        if (!queue.length) break
        const processedQids = new Set(queue.map((q) => q._qid).filter(Boolean))
        const remaining = []
        for (const item of queue) {
          const resolvedId = item.id && tempIdMap.has(item.id) ? tempIdMap.get(item.id) : item.id
          try {
            if (item.type === 'create') {
              const res = await api.createEvent(item.payload)
              // 服务器确认创建成功：支持单事件与重复事件批量返回
              if (res && item.temp_id) {
                if (Array.isArray(res.items) && res.items.length > 0) {
                  const tempIds = Array.isArray(item.temp_ids) && item.temp_ids.length
                    ? item.temp_ids
                    : [item.temp_id]
                  for (let i = 0; i < res.items.length; i++) {
                    const serverEv = res.items[i]
                    const matchedTempId = tempIds[i]
                    if (matchedTempId && serverEv?.id) {
                      tempIdMap.set(matchedTempId, serverEv.id)
                    }
                    let idx = matchedTempId ? state.events.findIndex((e) => e.id === matchedTempId) : -1
                    if (idx < 0 && i > 0) {
                      idx = state.events.findIndex(
                        (e) => String(e.id).startsWith('local_') && e.recurrence?.index === i + 1,
                      )
                    }
                    if (idx >= 0) {
                      state.events.splice(idx, 1, serverEv)
                    } else if (!state.events.some((e) => e.id === serverEv.id)) {
                      state.events.push(serverEv)
                    }
                  }
                  saveEventsCache(state.events, state.total)
                } else if (res.id) {
                  tempIdMap.set(item.temp_id, res.id)
                  const idx = state.events.findIndex((e) => e.id === item.temp_id)
                  const overridesSnapshot = getCompletedOverrides()
                  const tempOverride = overridesSnapshot[item.temp_id] || null
                  const localBefore = idx >= 0 ? state.events[idx] : null
                  const mergedCreated = mergeSyncedCreateResult(res, localBefore, {
                    createClientUpdatedAt: item.payload?.client_updated_at,
                    completedOverride: tempOverride,
                  })
                  if (tempOverride?.status) {
                    recordCompletedOverride(res.id, tempOverride.status, tempOverride.timestamp)
                    unrecordCompletedOverride(item.temp_id)
                  }
                  if (idx >= 0) {
                    state.events.splice(idx, 1, mergedCreated)
                    saveEventsCache(state.events, state.total)
                  }
                }
              }
            } else if (item.type === 'patch') {
              if (String(resolvedId || '').startsWith('local_')) {
                remaining.push(item)
                continue
              }
              const serverEv = await api.patchEvent(resolvedId, item.payload)
              const idx = state.events.findIndex((e) => e.id === resolvedId || e.id === item.id)
              const localCurrent = idx >= 0 ? state.events[idx] : null
              const canApplyResult = !localCurrent || shouldApplySyncedPatchResult(localCurrent, item.payload?.client_updated_at)
              if (idx >= 0 && serverEv && canApplyResult) {
                state.events.splice(idx, 1, {
                  ...localCurrent,
                  ...serverEv,
                  client_updated_at: serverEv.updated_at || item.payload?.client_updated_at || localCurrent.client_updated_at,
                })
                saveEventsCache(state.events, state.total)
              }
              // 只有在没有更新的本地改动覆盖时，才安全移除本地完成态保护
              if (item.payload?.status && canApplyResult) {
                unrecordCompletedOverride(resolvedId)
                unrecordCompletedOverride(item.id)
              }
            } else if (item.type === 'delete') {
              if (String(resolvedId || '').startsWith('local_')) {
                continue
              }
              await api.deleteEvent(resolvedId, item.options || {})
            }
          } catch (e) {
            // 400/404/422 属于永久性参数/对象无效，不再无限重试卡死队列
            if (e instanceof ApiError && (e.status === 400 || e.status === 404 || e.status === 422)) {
              console.warn('同步队列丢弃无效操作:', item.type, resolvedId, e.message)
            } else {
              remaining.push(resolvedId !== item.id ? { ...item, id: resolvedId } : item)
            }
          }
        }
        // 合并请求期间新入队的操作，避免直接 clearSyncQueue 误删并发写入的日程
        try {
          const latestQueue = getSyncQueue()
          const newlyAppended = latestQueue
            .filter((q) => !q._qid || !processedQids.has(q._qid))
            .map((q) => (q.id && tempIdMap.has(q.id) ? { ...q, id: tempIdMap.get(q.id) } : q))
          const nextQueue = [...remaining, ...newlyAppended]
          if (nextQueue.length) {
            localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(nextQueue))
          } else {
            clearSyncQueue()
          }
          if (newlyAppended.length > 0) {
            flushAgainRequested = true
          }
        } catch {}
      } while (flushAgainRequested)
    } finally {
      activeFlushPromise = null
    }
  })()
  return activeFlushPromise
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
  // 离线模式：不联网，直接以本机数据渲染
  if (state.offlineMode) return
  // 如果本地有缓存的课表数据，则无需展示全屏 loading 转圈，实现视觉无感秒出
  if (!silent && (!state.events || state.events.length === 0)) {
    state.loading = true
  }
  try {
    const params = fetchParams()
    const [payload, undatedPayload] = await Promise.all([
      api.events(params),
      api.events({
        undated: true,
        include_hidden: true,
        limit: 2000,
        source: state.source === 'all' ? undefined : state.source,
      }).catch((err) => {
        if (isAuthError(err)) throw err
        return { items: [] }
      }),
    ])
    const deletedMap = getDeletedEventIds()
    const completedOverrides = getCompletedOverrides()
    const queuedSnapshot = getSyncQueue()
    const pendingIds = getPendingSyncIdSet(queuedSnapshot)
    const datedItems = payload?.items || []
    const undatedItems = undatedPayload?.items || []
    const rawItems = [...datedItems, ...undatedItems]

    const { activeEvents, nextDeletedMap } = reconcileEventCollections({
      localEvents: state.events || [],
      serverItems: rawItems,
      pendingIds,
      completedOverrides,
      deletedMap,
      windowStartKey: params.start_date,
      windowEndKey: params.end_date,
      queriedUndated: true,
      serverWindowComplete: datedItems.length < (params.limit || 2000) && state.source === 'all',
    })

    saveDeletedEventIdsMap(nextDeletedMap)
    state.events = dedupeEvents(activeEvents)

    // 对历史遗留未同步至云端的 local_ 临时日程自动加入补推同步队列
    for (const local of state.events) {
      if (local.id && String(local.id).startsWith('local_')) {
        const alreadyQueued = queuedSnapshot.some(
          (item) =>
            item.temp_id === local.id ||
            (Array.isArray(item.temp_ids) && item.temp_ids.includes(local.id)),
        )
        if (!alreadyQueued) {
          const {
            repeat_frequency,
            repeat_interval,
            repeat_count,
            clear_end_time,
            duration_hours,
            _endTs,
            ...cleanPayload
          } = local
          appendSyncQueue({ type: 'create', temp_id: local.id, payload: cleanPayload })
        }
      }
    }
    if (state.events.some((l) => l.id && String(l.id).startsWith('local_'))) {
      setTimeout(() => flushSyncQueue().catch(() => {}), 500)
    }

    state.total = state.events.length
    state.error = ''
    state.authRequired = false
    state.lastUpdated = new Date()
    saveEventsCache(state.events, state.total)
    autoExpireEndedCustomTasks()
  } catch (error) {
    if (isAuthError(error)) {
      state.authRequired = true
      state.error = ''
    } else {
      if (!state.events || state.events.length === 0) {
        state.error = error.message || '加载失败'
      }
    }
  } finally {
    state.loading = false
  }
}

/** 供周课表等扩展窗口拉取结果统一按 ID + LWW 合并进唯一事件库，彻底消除双数据源互搏 */
export function upsertServerEventsIntoStore(serverItems = []) {
  if (!Array.isArray(serverItems) || !serverItems.length) return
  const deletedMap = getDeletedEventIds()
  const completedOverrides = getCompletedOverrides()
  const pendingIds = getPendingSyncIdSet()
  const { activeEvents, nextDeletedMap } = reconcileEventCollections({
    localEvents: state.events || [],
    serverItems,
    pendingIds,
    completedOverrides,
    deletedMap,
    serverWindowComplete: false,
  })
  saveDeletedEventIdsMap(nextDeletedMap)
  state.events = dedupeEvents(activeEvents)
  state.total = state.events.length
  saveEventsCache(state.events, state.total)
}

export async function loadStatus() {
  if (state.offlineMode) return
  try {
    state.status = await api.status()
    if (state.status?.server_time) noteServerTime(state.status.server_time)
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
  if (state.offlineMode) return
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

  // 2. 检查定时段任务是否已到期，到期自动划掉归档并持久化至服务器
  autoExpireEndedCustomTasks()
  if (typeof window !== 'undefined' && !window.__autoExpireTimer) {
    window.__autoExpireTimer = setInterval(autoExpireEndedCustomTasks, 60000)
  }

  // 离线模式：不登录、不做云同步，但保留真实的物理网络状态以支持联网导课表
  if (state.offlineMode) {
    state.accountsReady = true
    state.online = typeof navigator === 'undefined' ? true : navigator.onLine
    return
  }

  // 3. 移动端强本地化策略：如果本地已有缓存数据，则首屏完全不阻塞等待网络请求
  const isMobile = isMobileNativeApp()
  const hasLocalData = state.events && state.events.length > 0

  if (isMobile && hasLocalData) {
    // 移动端在后台静默同步离线队列并按 ID + LWW 对齐云端最新状态，不阻塞首屏 UI 渲染
    setTimeout(async () => {
      try {
        await flushSyncQueue()
        await Promise.all([refresh({ silent: true }), loadConfig()])
      } catch {}
    }, 800)
    return
  }

  // 4. 首次启动或 Web 页面下并行拉取更新
  await Promise.all([refresh(), loadStatus(), loadConfig()])
}

/* --------------------------------------------------------------- accounts */

/**
 * 离线模式（本地账号）：不登录云端账号、不做云端日程同步，所有数据写在本机 localStorage；
 * 物理网络保持真实在线状态，仍可导入课表与检查更新。
 */
export function enableOfflineMode() {
  persistOfflineMode(true)
  state.offlineMode = true
  state.online = typeof navigator === 'undefined' ? true : navigator.onLine
  state.authRequired = false
  state.forceAuth = false
  state.authError = ''
  state.authNotice = ''
  state.accountsReady = true
  state.loading = false
  closeCustomEditor()
  saveEventsCache(state.events, state.total)
  notify('已进入离线模式：日程保存在本机', 'ok')
}

/** 退出离线模式，重新连接云端（需要登录才能同步）。 */
export async function disableOfflineMode() {
  persistOfflineMode(false)
  state.offlineMode = false
  state.accountsReady = false
  notify('已退出离线模式，正在连接云端', 'info')
  try {
    await fetchSession()
    if (!state.user && !hasToken()) {
      openAuthGate()
      return
    }
    await Promise.all([refresh({ silent: true }), loadStatus(), loadConfig()])
  } catch (error) {
    /* 离线队列会兜底，不打断用户 */
  }
}

/** Ask the backend who we are; safe to call when signed out. */
export async function fetchSession() {
  if (state.offlineMode) {
    state.accountsReady = true
    return state.user
  }
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
  // 0. 离线模式（本地账号）永不弹登录框
  if (state.offlineMode) return false
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
  if (state.offlineMode) {
    persistOfflineMode(false)
    state.offlineMode = false
    state.online = typeof navigator === 'undefined' ? true : navigator.onLine
    fetchSession().catch(() => {})
  }
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

/* ------ 「可办」页极简新建（标题 + 备注，仅此而已） */

export function openTodoQuickAdd() {
  state.todoQuickAdd.open = true
}

export function closeTodoQuickAdd() {
  state.todoQuickAdd.open = false
}

/** 保存一条可办事项：本机补齐「无截止、非日程」的字段，用户只填标题和备注。 */
export async function saveQuickTodo({ title, description = '' } = {}) {
  const name = String(title || '').trim()
  if (!name) return null
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const localStamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}:00`
  // 极简新建永远新建一条，别被上一次编辑的对象带偏
  state.customEditor.event = null
  const saved = await saveCustomEvent({
    title: name,
    description: String(description || '').trim(),
    start_time: localStamp,
    end_time: null,
    clear_end_time: true,
    duration_hours: 0,
    location: '',
    attachments: [],
    is_deadline: true,
    is_undated: true,
  })
  if (saved) state.todoQuickAdd.open = false
  return saved
}

/** 在 Asia/Shanghai (+08:00) 日历下安全地增加指定月数（月末自动回拨到当月最后一天）。 */
function addMonthsShanghai(baseDate, months) {
  const shifted = new Date(baseDate.getTime() + 8 * 3600000)
  const year0 = shifted.getUTCFullYear()
  const month0 = shifted.getUTCMonth()
  const day0 = shifted.getUTCDate()
  const hh = shifted.getUTCHours()
  const mm = shifted.getUTCMinutes()
  const ss = shifted.getUTCSeconds()
  const targetYear = year0 + Math.floor((month0 + months) / 12)
  const targetMonth = ((month0 + months) % 12 + 12) % 12
  const maxDay = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate()
  const targetDay = Math.min(day0, maxDay)
  return new Date(Date.UTC(targetYear, targetMonth, targetDay, hh, mm, ss) - 8 * 3600000)
}

export async function saveCustomEvent(payload) {
  const existing = state.customEditor.event
  const isExisting = Boolean(existing && !existing.is_draft && existing.id)
  const nowIso = nextMutationIso(isExisting ? existing : null)

  // 统一本地优先 + 确定性主键架构（无论移动端、网页端、在线或离线）：
  // 1. 新建日程在客户端直接生成确定性 source_id 与 32 位主键 id（与服务端 make_event_id 100% 一致），彻底消灭临时 id 与正式 id 并存产生双份日程；
  // 2. 编辑日程原地按唯一主键 id 更新并推进单调修改时间（updated_at / client_updated_at），杜绝新老日程共存或回退。
  let targetResult = null

  if (isExisting) {
    const applyScope = payload.apply_scope || 'single'
    const groupId = existing?.recurrence?.group_id
    const { _endTs, ...cleanExisting } = existing
    const { clear_end_time, duration_hours, apply_scope, ...cleanFields } = payload
    const normalizedStart = formatShanghaiIso(toDate(payload.start_time)) || payload.start_time
    const normalizedEnd = payload.end_time
      ? formatShanghaiIso(toDate(payload.end_time)) || payload.end_time
      : null

    if (payload.status === 'pending') {
      unrecordCompletedOverride(existing.id)
    }

    // 同步更新重复系列兄弟项（若选择了 all / future）
    if (groupId && (applyScope === 'all' || applyScope === 'future')) {
      const oldStartMs = toDate(existing.start_time)?.getTime() ?? 0
      const newStartMs = toDate(normalizedStart)?.getTime() ?? oldStartMs
      const deltaMs = newStartMs - oldStartMs
      const newDurMs = normalizedEnd ? Math.max(0, (toDate(normalizedEnd)?.getTime() ?? newStartMs) - newStartMs) : null

      state.events = state.events.map((ev) => {
        if (ev.recurrence?.group_id !== groupId) return ev
        const evStartMs = toDate(ev.start_time)?.getTime() ?? 0
        if (applyScope === 'future' && evStartMs < oldStartMs) return ev
        const shiftedStartMs = evStartMs + deltaMs
        const sibStartIso = formatShanghaiIso(new Date(shiftedStartMs))
        let sibEndIso = null
        if (!payload.clear_end_time) {
          if (newDurMs !== null) {
            sibEndIso = formatShanghaiIso(new Date(shiftedStartMs + newDurMs))
          } else if (ev.end_time) {
            const oldDur = Math.max(0, (toDate(ev.end_time)?.getTime() ?? evStartMs) - evStartMs)
            sibEndIso = formatShanghaiIso(new Date(shiftedStartMs + oldDur))
          }
        }
        return {
          ...ev,
          ...cleanFields,
          start_time: sibStartIso,
          end_time: sibEndIso,
          updated_at: nowIso,
          client_updated_at: nowIso,
        }
      })
      targetResult = state.events.find((e) => e.id === existing.id) || existing
    } else {
      const updatedLocal = {
        ...cleanExisting,
        ...cleanFields,
        id: existing.id,
        start_time: normalizedStart,
        end_time: normalizedEnd,
        updated_at: nowIso,
        client_updated_at: nowIso,
      }
      const idx = state.events.findIndex((e) => e.id === existing.id)
      if (idx >= 0) state.events.splice(idx, 1, updatedLocal)
      else state.events.unshift(updatedLocal)
      targetResult = updatedLocal
    }

    state.events = dedupeEvents(state.events)
    state.total = state.events.length
    saveEventsCache(state.events, state.total)
    closeCustomEditor()

    if (state.offlineMode) {
      notify('已在本机更新', 'ok')
      return targetResult
    }

    const patchPayload = { ...payload, client_updated_at: nowIso }
    const qid = appendSyncQueue({ type: 'patch', id: existing.id, payload: patchPayload })
    if (isMobileNativeApp()) {
      notify('已更新日程', 'ok')
      setTimeout(() => flushSyncQueue().catch(() => {}), 300)
      return targetResult
    }

    try {
      const saved = await api.patchEvent(existing.id, patchPayload)
      removeSyncQueueItem(qid)
      const curIdx = state.events.findIndex((e) => e.id === existing.id)
      const cur = curIdx >= 0 ? state.events[curIdx] : null
      if (saved?.id && (!cur || shouldApplySyncedPatchResult(cur, nowIso))) {
        const merged = { ...(cur || {}), ...saved, client_updated_at: saved.updated_at || nowIso }
        if (curIdx >= 0) state.events.splice(curIdx, 1, merged)
        saveEventsCache(state.events, state.total)
      }
      if (applyScope === 'all' || applyScope === 'future') {
        await refresh({ silent: true })
      }
      notify('日程已更新', 'ok')
      return saved || targetResult
    } catch (error) {
      if (error instanceof ApiError && (error.status === 400 || error.status === 422 || error.status === 401 || error.status === 403)) {
        removeSyncQueueItem(qid)
        notify(error.message || '保存失败', 'danger')
        await refresh({ silent: true })
        return null
      }
      notify('网络波动，修改已暂存本机并将在后台自动同步', 'info')
      setTimeout(() => flushSyncQueue().catch(() => {}), 600)
      return targetResult
    }
  }

  // 新建日程（单条或按周期重复生成）
  const isRecurring = Boolean(
    payload.repeat_frequency &&
      ['day', 'week', 'month'].includes(payload.repeat_frequency) &&
      payload.repeat_count > 1,
  )
  const repeatFreq = payload.repeat_frequency
  const repeatInterval = Math.max(1, payload.repeat_interval || 1)
  const repeatCount = Math.max(1, Math.min(100, payload.repeat_count || 1))
  const seriesGroupId = `rec_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
  const baseStart = toDate(payload.start_time) || new Date()
  const baseEnd = payload.end_time ? toDate(payload.end_time) : null
  const durationMs = baseEnd ? Math.max(0, baseEnd.getTime() - baseStart.getTime()) : null

  const {
    repeat_frequency,
    repeat_interval,
    repeat_count,
    clear_end_time,
    duration_hours,
    ...cleanFields
  } = payload

  const count = isRecurring ? repeatCount : 1
  const clientIds = []
  const createdItems = []

  for (let i = 0; i < count; i++) {
    const sourceId = generateClientSourceId(isRecurring ? String(i + 1) : '')
    const canonicalId = makeCustomEventId(sourceId)
    clientIds.push(sourceId)

    let curStart = new Date(baseStart.getTime())
    if (isRecurring && i > 0) {
      if (repeatFreq === 'day') {
        curStart = new Date(baseStart.getTime() + i * repeatInterval * 86400000)
      } else if (repeatFreq === 'week') {
        curStart = new Date(baseStart.getTime() + i * repeatInterval * 7 * 86400000)
      } else if (repeatFreq === 'month') {
        curStart = addMonthsShanghai(baseStart, i * repeatInterval)
      }
    }
    const curStartIso = formatShanghaiIso(curStart)
    const curEndIso = durationMs != null ? formatShanghaiIso(new Date(curStart.getTime() + durationMs)) : null

    createdItems.push({
      id: canonicalId,
      source: 'custom',
      source_id: sourceId,
      status: 'pending',
      hidden: false,
      local_override: true,
      created_at: nowIso,
      updated_at: nowIso,
      client_updated_at: nowIso,
      ...cleanFields,
      start_time: curStartIso,
      end_time: curEndIso,
      recurrence: isRecurring
        ? {
            group_id: seriesGroupId,
            freq: repeatFreq,
            interval: repeatInterval,
            index: i + 1,
            total: repeatCount,
          }
        : null,
    })
  }

  for (const it of [...createdItems].reverse()) {
    const existIdx = state.events.findIndex((e) => e.id === it.id)
    if (existIdx >= 0) state.events.splice(existIdx, 1, it)
    else state.events.unshift(it)
  }
  state.events = dedupeEvents(state.events)
  state.total = state.events.length
  targetResult = createdItems[0]
  saveEventsCache(state.events, state.total)
  closeCustomEditor()

  if (state.offlineMode) {
    notify('已保存在本机', 'ok')
    return targetResult
  }

  const createPayload = {
    ...payload,
    client_id: clientIds[0],
    client_ids: isRecurring ? clientIds : undefined,
    client_updated_at: nowIso,
  }
  const qid = appendSyncQueue({
    type: 'create',
    temp_id: targetResult.id,
    temp_ids: createdItems.map((it) => it.id),
    payload: createPayload,
  })

  if (isMobileNativeApp()) {
    notify('日程已添加', 'ok')
    setTimeout(() => flushSyncQueue().catch(() => {}), 300)
    return targetResult
  }

  try {
    const saved = await api.createEvent(createPayload)
    removeSyncQueueItem(qid)
    const savedList = Array.isArray(saved?.items) ? saved.items : saved?.id ? [saved] : []
    if (savedList.length > 0) {
      const overridesSnapshot = getCompletedOverrides()
      for (let i = 0; i < savedList.length; i++) {
        const srv = savedList[i]
        const expectedId = createdItems[i]?.id || srv.id
        const idx = state.events.findIndex((e) => e.id === srv.id || e.id === expectedId)
        const localBefore = idx >= 0 ? state.events[idx] : null
        const merged = mergeSyncedCreateResult(srv, localBefore, {
          createClientUpdatedAt: nowIso,
          completedOverride: overridesSnapshot[srv.id] || overridesSnapshot[expectedId] || null,
        })
        if (idx >= 0) state.events.splice(idx, 1, merged)
        else state.events.unshift(merged)
      }
      state.events = dedupeEvents(state.events)
      state.total = state.events.length
      saveEventsCache(state.events, state.total)
    }
    notify('日程已添加', 'ok')
    return saved || targetResult
  } catch (error) {
    if (error instanceof ApiError && (error.status === 400 || error.status === 422 || error.status === 401 || error.status === 403)) {
      removeSyncQueueItem(qid)
      const removeSet = new Set(createdItems.map((it) => it.id))
      state.events = state.events.filter((e) => !removeSet.has(e.id))
      state.total = state.events.length
      saveEventsCache(state.events, state.total)
      notify(error.message || '保存失败', 'danger')
      return null
    }
    notify('已保存在本机，待网络恢复后自动同步', 'info')
    setTimeout(() => flushSyncQueue().catch(() => {}), 600)
    return targetResult
  }
}

export async function removeCustomEvent(id, options = {}) {
  const target = state.events.find((item) => item.id === id)
  const applyScope = options.apply_scope || 'single'
  const nowIso = nextMutationIso(target)
  const nowMs = parseTimestampMs(nowIso) || Date.now()

  const groupId = target?.recurrence?.group_id
  const toRemoveIds = new Set([id])
  if (groupId && (applyScope === 'all' || applyScope === 'future')) {
    const targetTs = toDate(target.start_time)?.getTime() ?? 0
    state.events.forEach((ev) => {
      if (ev.recurrence?.group_id !== groupId) return
      if (applyScope === 'all' || (toDate(ev.start_time)?.getTime() ?? 0) >= targetTs) {
        toRemoveIds.add(ev.id)
      }
    })
  }

  state.events = state.events.filter((e) => !toRemoveIds.has(e.id))
  state.total = state.events.length
  toRemoveIds.forEach((removedId) => recordDeletedEventId(removedId, nowMs))
  saveEventsCache(state.events, state.total)
  closeCustomEditor()

  const scopeNote = applyScope === 'all' ? '（系列全部）' : applyScope === 'future' ? '（当前及后续）' : ''
  const deleteOpts = { apply_scope: applyScope, client_updated_at: nowIso }

  if (state.offlineMode) {
    notify(`已在本地移除${target ? `「${target.title}」` : '这条日程'}${scopeNote}`, 'info')
    return true
  }

  const qid = appendSyncQueue({ type: 'delete', id, options: deleteOpts })
  if (isMobileNativeApp()) {
    setTimeout(() => flushSyncQueue().catch(() => {}), 300)
    notify(`已移除${target ? `「${target.title}」` : '这条日程'}${scopeNote}`, 'info', {
      action: { label: '撤销', run: () => restoreEvent(id, target?.title || '', target) },
      duration: 6000,
    })
    return true
  }

  try {
    await api.deleteEvent(id, deleteOpts)
    removeSyncQueueItem(qid)
    notify(`已移除${target ? `「${target.title}」` : '这条日程'}${scopeNote}`, 'info', {
      action: { label: '撤销', run: () => restoreEvent(id, target?.title || '', target) },
      duration: 6000,
    })
    return true
  } catch (error) {
    setTimeout(() => flushSyncQueue().catch(() => {}), 600)
    notify(`已移除${target ? `「${target.title}」` : '这条日程'}${scopeNote}`, 'info')
    return true
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
  const snapshot = index >= 0 ? { ...state.events[index] } : { ...event }
  const nowIso = nextMutationIso(snapshot)
  const nowMs = parseTimestampMs(nowIso) || Date.now()

  if (index >= 0) {
    state.events.splice(index, 1)
    state.total = state.events.length
  }

  // 立即登记携带单调时间戳的墓碑并持久化，杜绝多端或异步请求返回旧数据导致复活
  recordDeletedEventId(event.id, nowMs)
  saveEventsCache(state.events, state.total)

  const deleteOpts = { client_updated_at: nowIso }

  if (state.offlineMode) {
    notify(removedText(event), 'info', {
      action: { label: '撤销', run: () => restoreEvent(event.id, event.title, snapshot) },
      duration: 6000,
    })
    return true
  }

  const qid = appendSyncQueue({ type: 'delete', id: event.id, options: deleteOpts })
  if (isMobileNativeApp()) {
    setTimeout(() => flushSyncQueue().catch(() => {}), 300)
    notify(removedText(event), 'info', {
      action: { label: '撤销', run: () => restoreEvent(event.id, event.title, snapshot) },
      duration: 6000,
    })
    return true
  }

  try {
    await api.deleteEvent(event.id, deleteOpts)
    removeSyncQueueItem(qid)
    notify(removedText(event), 'info', {
      action: { label: '撤销', run: () => restoreEvent(event.id, event.title, snapshot) },
      duration: 6000,
    })
    return true
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      removeSyncQueueItem(qid)
      unrecordDeletedEventId(event.id)
      if (snapshot && !state.events.some((e) => e.id === snapshot.id)) {
        state.events.splice(Math.max(0, index), 0, snapshot)
        state.total = state.events.length
        saveEventsCache(state.events, state.total)
      }
      notify(error.message || '删除失败', 'danger')
      return false
    }
    setTimeout(() => flushSyncQueue().catch(() => {}), 600)
    notify(removedText(event), 'info', {
      action: { label: '撤销', run: () => restoreEvent(event.id, event.title, snapshot) },
      duration: 6000,
    })
    return true
  }
}

function removedText(event) {
  return `已移除「${event.title}」`
}

/** 撤销删除：清除墓碑、推进单调时间戳并恢复回时间线与云端。 */
export async function restoreEvent(id, title = '', snapshot = null) {
  const restoreIso = nextMutationIso(snapshot)
  unrecordDeletedEventId(id)

  if (snapshot && !state.events.some((item) => item.id === id)) {
    state.events.unshift({
      ...snapshot,
      hidden: false,
      updated_at: restoreIso,
      client_updated_at: restoreIso,
    })
    state.events = dedupeEvents(state.events)
    state.total = state.events.length
    saveEventsCache(state.events, state.total)
  } else {
    const target = state.events.find((item) => item.id === id)
    if (target) {
      target.hidden = false
      target.updated_at = restoreIso
      target.client_updated_at = restoreIso
      saveEventsCache(state.events, state.total)
    }
  }

  if (state.offlineMode) {
    notify(title ? `已恢复「${title}」` : '已恢复', 'info')
    return true
  }

  const qid = appendSyncQueue({ type: 'patch', id, payload: { hidden: false, client_updated_at: restoreIso } })
  try {
    await api.patchEvent(id, { hidden: false, client_updated_at: restoreIso })
    removeSyncQueueItem(qid)
    notify(title ? `已恢复「${title}」` : '已恢复', 'info')
    await refresh({ silent: true })
    return true
  } catch (error) {
    setTimeout(() => flushSyncQueue().catch(() => {}), 600)
    notify(title ? `已恢复「${title}」` : '已恢复', 'info')
    return true
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
  if (api.patchUser) {
    await api.patchUser(userId, { is_active: isActive })
  } else if (api.updateUser) {
    await api.updateUser(userId, { is_active: isActive })
  }
  notify(isActive ? '已启用该账号' : '已停用该账号', 'ok')
}

export async function deleteMyAccount() {
  await api.deleteMyAccount()
  notify('您的账号及数据已成功注销', 'ok')
  clearAllLocalData()
  state.user = null
  openAuthGate()
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
  const target = state.events.find((e) => e.id === event?.id) || event
  if (!target) return
  const next = target.status === 'completed' ? 'pending' : 'completed'
  const previous = target.status
  const prevCompletedAt = target.completed_at ?? null
  const prevUpdatedAt = target.updated_at
  const prevClientUpdatedAt = target.client_updated_at
  const nowIso = nextMutationIso(target)
  const nowMs = parseTimestampMs(nowIso) || Date.now()

  // 1. 乐观更新内存状态并记录单调最后修改时间（0ms 响应 + 抗时钟偏差 LWW 对齐）
  target.status = next
  target.completed_at = next === 'completed' ? nowIso : null
  target.updated_at = nowIso
  target.client_updated_at = nowIso
  if (event !== target) {
    event.status = next
    event.completed_at = target.completed_at
    event.updated_at = nowIso
    event.client_updated_at = nowIso
  }

  // 2. 强保护：写入本地完成态覆盖记录（含单调修改时间戳）与闪存缓存，彻底杜绝云端旧数据冲刷复活
  recordCompletedOverride(target.id, next, nowMs)
  saveEventsCache(state.events, state.total)

  // 离线模式：完成态只记在本机，不回传服务器
  if (state.offlineMode) return

  const patchPayload = { status: next, client_updated_at: nowIso }

  // 3. 打入离线同步队列双重保险
  const qid = appendSyncQueue({ type: 'patch', id: target.id, payload: patchPayload })

  // 临时本地 id 尚未落库时，走队列串行等待 create 返回真实 id 后再回写 PATCH
  if (String(target.id || '').startsWith('local_')) {
    setTimeout(() => {
      flushSyncQueue().catch(() => {})
    }, 300)
    return
  }

  // 4. 立即向服务器发起 PATCH 写入落盘（带 client_updated_at 防止旧状态倒流）
  try {
    const updated = await api.patchEvent(target.id, patchPayload)
    removeSyncQueueItem(qid)
    // 只有期间没有更新的本地再次操作时，才对齐服务器时间戳（保留单调高水位，防并发在途旧 GET 覆盖）
    if (shouldApplySyncedPatchResult(target, nowIso)) {
      const alignedMs = Math.max(nowMs, parseTimestampMs(updated?.updated_at))
      const alignedIso = new Date(alignedMs).toISOString()
      Object.assign(target, updated, {
        updated_at: alignedIso,
        client_updated_at: alignedIso,
      })
      saveEventsCache(state.events, state.total)
    }
  } catch (error) {
    // 仅在明确遇到未登录/权限拒绝（401/403）时才回滚状态
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      removeSyncQueueItem(qid)
      target.status = previous
      target.completed_at = prevCompletedAt
      target.updated_at = prevUpdatedAt
      target.client_updated_at = prevClientUpdatedAt
      unrecordCompletedOverride(target.id)
      saveEventsCache(state.events, state.total)
      state.authRequired = true
      notify('请先登录账号后再操作', 'warn')
    } else {
      // 网络慢或临时离线：坚决保留用户的划掉状态与最新时间戳，等待离线队列自动重试同步
      console.warn('离线暂存完成态，稍后自动重试同步:', error.message)
      setTimeout(() => {
        flushSyncQueue().catch(() => {})
      }, 500)
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

/**
 * 离线模式导入课表：服务器只负责「登录教务 + 抓课表 + 换算成事件」，
 * 解析结果原样回到本机、由本机自己存 —— 云端不建账号、不落库、不保存密码。
 */
export function importLocalEventsBatch(fresh, { courses = 0, source = 'local', semester = {}, termStart = '' } = {}) {
  const incoming = Array.isArray(fresh) ? fresh : []
  const keep = (state.events || []).filter((event) => event.source !== 'tju_schedule')
  state.events = [...keep, ...incoming]
  state.total = state.events.length

  state.config = {
    ...(state.config || {}),
    tju_schedule: {
      ...(state.config?.tju_schedule || {}),
      semester: { ...(state.config?.tju_schedule?.semester || {}), ...semester, start_date: semester.start_date || termStart || state.config?.tju_schedule?.semester?.start_date || '' },
      import_meta: {
        courses,
        imported_at: new Date().toISOString(),
        source,
      },
    },
  }

  saveConfigCache(state.config)
  saveEventsCache(state.events, state.total)
  return { courses, count: incoming.length }
}

export function saveLocalSemester(semesterPatch) {
  state.config = {
    ...(state.config || {}),
    tju_schedule: {
      ...(state.config?.tju_schedule || {}),
      semester: {
        ...(state.config?.tju_schedule?.semester || {}),
        ...semesterPatch,
      },
    },
  }
  saveConfigCache(state.config)
}

export async function jwImportLocal(payload) {
  const result = await api.jwLocalImport(payload)
  const detail = result?.detail || {}
  const fresh = Array.isArray(detail.events) ? detail.events : []
  const semester = detail.semester || {}
  importLocalEventsBatch(fresh, {
    courses: detail.courses || 0,
    source: 'local',
    semester,
    termStart: detail.term_start || '',
  })
  notify(`课表已存入本机：${detail.courses || 0} 门课`, 'ok')
  return result
}

/** 清掉本机导入的课表（离线模式没有服务器可删）。 */
export function clearLocalTimetable() {
  const before = (state.events || []).length
  state.events = (state.events || []).filter((event) => event.source !== 'tju_schedule')
  state.total = state.events.length
  if (state.config?.tju_schedule) {
    state.config = {
      ...state.config,
      tju_schedule: { ...state.config.tju_schedule, import_meta: {} },
    }
    saveConfigCache(state.config)
  }
  saveEventsCache(state.events, state.total)
  return { removed: before - state.events.length }
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

export function filterEvents(events = state.events, options = {}) {
  // include_undated：只在「无截止 / 可办事项」这类视图里打开，其余视图一律看不到
  const includeUndated = Boolean(options.include_undated)
  const today = todayKey()
  const nowTs = Date.now()
  return events.filter((event) => {
    // 无截止时间待办只在「可办事项」里出现：不进 DDL 列表、不进课表、不进日程时间线
    if (event.is_undated) {
      if (!includeUndated) return false
      if (event.status === 'completed') return false
      return matchesQuery(event)
    }
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
