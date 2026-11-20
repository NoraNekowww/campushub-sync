/**
 * Global reactive store — deliberately dependency-free (no Pinia) because the
 * app state is small: one event list, one status blob, a few UI flags.
 */
import { reactive } from 'vue'
import { api, ApiError, getSessionToken, getToken, isAuthError, isOfflineMode, setOfflineMode as persistOfflineMode, setSessionToken, setToken } from './api'
import { dayKey, formatShanghaiIso, isEventEnded, toDate, todayKey } from './utils/datetime'
import { applyThemeColor, getSavedThemeColor } from './utils/themeColors'
import { dedupeEvents } from './utils/dedupe'
import {
  mergeServerEventWithLocal,
  mergeSyncedCreateResult,
  parseEventModifiedMs,
  parseTimestampMs,
  shouldApplySyncedPatchResult,
} from './utils/lww'

const nowClientIso = () => new Date().toISOString()

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
const IMPORTANT_IDS_KEY = 'campushub.important_ids.v1'
const BACKGROUND_CONFIG_KEY = 'campushub.background_config.v1'
const LOOKAHEAD_DAYS = 60

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
  event.priority = nextImportant ? 1 : 5
  if (event.source === 'custom') {
    api.patchEvent(id, { priority: event.priority }).catch(() => {})
  }

  return nextImportant
}

function readInitialBackgroundConfig() {
  const defaults = {
    enabled: true, // 默认开启深空摄影背景图与通透微晶磨砂深度融合
    // 默认分类：真正的深空摄影（韦伯/哈勃深场、超新星与星系）
    category: 'astronomy',
    lightUrl: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1920&q=85',
    darkUrl: 'https://images.unsplash.com/photo-1462331940025-496dfbfc7564?auto=format&fit=crop&w=1920&q=85',
    wallpaperTitle: '宇宙深场与微光星系',
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

export function saveBackgroundConfig(patch) {
  state.backgroundConfig = { ...state.backgroundConfig, ...patch }
  try {
    localStorage.setItem(BACKGROUND_CONFIG_KEY, JSON.stringify(state.backgroundConfig))
  } catch (e) {}
  applyBackgroundClass()
}

/* ------------------------------------------------------------- event feed */

function fetchParams() {
  // 往前拉取 30 天，确保近期的日程与已完成归档在常规刷新中也能即时拉回
  const start = dayKey(new Date(Date.now() - 30 * 86400000))
  const end = dayKey(new Date(Date.now() + LOOKAHEAD_DAYS * 86400000))
  return {
    start_date: start,
    end_date: end,
    limit: 1000,
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
      api.events({ status: 'completed', limit: 800 }),
      api.events({ status: 'completed', undated: true, limit: 800 }).catch((err) => {
        if (isAuthError(err)) throw err
        return { items: [] }
      }),
    ])
    const historyMap = new Map()
    for (const item of [...(datedRes?.items || []), ...(undatedRes?.items || [])]) {
      if (item?.id) historyMap.set(item.id, item)
    }
    const historyItems = [...historyMap.values()]
    if (!historyItems.length) return
    const deletedMap = getDeletedEventIds()
    const completedOverrides = getCompletedOverrides()
    const pendingIds = getPendingSyncIdSet()
    const eventMap = new Map((state.events || []).map((e) => [e.id, e]))
    historyItems.forEach((item) => {
      if (deletedMap[item.id]) return
      const local = eventMap.get(item.id)
      const merged = mergeServerEventWithLocal(
        { ...item, status: 'completed' },
        local,
        {
          hasPendingSync: pendingIds.has(item.id),
          completedOverride: completedOverrides[item.id] || null,
        },
      )
      eventMap.set(item.id, merged)
    })
    state.events = [...eventMap.values()]
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
  const nowIso = nowClientIso()
  const toPatch = []
  ;(state.events || []).forEach((ev) => {
    // 排除教务课表原生课程，仅针对个人安排的自定义日程与任务；无截止待办没有「结束」概念
    if (ev.source !== 'tju_schedule' && ev.status !== 'completed' && !ev.is_undated) {
      if (isEventEnded(ev, nowTs)) {
        ev.status = 'completed'
        ev.completed_at = ev.completed_at || nowIso
        ev.updated_at = nowIso
        ev.client_updated_at = nowIso
        recordCompletedOverride(ev.id, 'completed', nowTs)
        toPatch.push(ev.id)
      }
    }
  })
  if (toPatch.length > 0) {
    saveEventsCache(state.events, state.total)
    toPatch.forEach((id) => {
      const qid = appendSyncQueue({ type: 'patch', id, payload: { status: 'completed', client_updated_at: nowIso } })
      if (!state.offlineMode && !String(id).startsWith('local_')) {
        api.patchEvent(id, { status: 'completed', client_updated_at: nowIso })
          .then((updated) => {
            removeSyncQueueItem(qid)
            const cur = (state.events || []).find((e) => e.id === id)
            if (cur && updated && shouldApplySyncedPatchResult(cur, nowIso)) {
              Object.assign(cur, updated, { client_updated_at: updated.updated_at || nowIso })
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

/** 已在本地明确删除的任务 ID 墓碑集合（防网络往返冲撞与左右脑互搏） */
function getDeletedEventIds() {
  try {
    const raw = localStorage.getItem(DELETED_IDS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

export function isEventDeleted(id) {
  if (!id) return false
  return Boolean(getDeletedEventIds()[id])
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
    const [payload, undatedPayload] = await Promise.all([
      api.events(fetchParams()),
      api.events({
        undated: true,
        limit: 1000,
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
    const rawMap = new Map()
    for (const it of [...(payload?.items || []), ...(undatedPayload?.items || [])]) {
      if (it?.id) rawMap.set(it.id, it)
    }
    const rawItems = [...rawMap.values()]

    // 1. 过滤掉本地已显式删除的事件（墓碑机制）
    // 2. 强保护：若本地有待提交操作或尚未确认的完成态（如刚刚划掉的可办事项），以最后修改时间对齐裁决，绝不回光返照
    // 3. 冲突解决：Last-Write-Wins，本地最后修改时间严格晚于服务器（或有待同步队列/完成态覆盖）时保留本地版本
    const localEventMap = new Map((state.events || []).map((e) => [e.id, e]))
    const serverIdSet = new Set(rawItems.map((it) => it.id))
    const mergedServerItems = rawItems
      .filter((it) => !deletedMap[it.id])
      .map((it) =>
        mergeServerEventWithLocal(it, localEventMap.get(it.id), {
          hasPendingSync: pendingIds.has(it.id),
          completedOverride: completedOverrides[it.id] || null,
        }),
      )

    // 4. 本地日程优先保留：云端没有返回但本地依然存在的未删除日程（同步队列尚未落库或超出查询窗口）
    const localList = Array.isArray(state.events) ? state.events : []
    const preservedLocalItems = localList
      .filter((local) => {
        if (!local || !local.id) return false
        if (deletedMap[local.id]) return false
        if (serverIdSet.has(local.id)) return false
        return true
      })
      .map((local) => {
        const override = completedOverrides[local.id]
        if (override?.status && parseTimestampMs(override.timestamp) >= parseEventModifiedMs(local)) {
          return {
            ...local,
            status: override.status,
            client_updated_at: new Date(parseTimestampMs(override.timestamp)).toISOString(),
          }
        }
        return local
      })

    // 5. 内容去重：同一节课如果被同步器和直连导入各建了一次（两个 id），这里只留一份
    state.events = dedupeEvents([...preservedLocalItems, ...mergedServerItems])

    // 对本地未同步至云端的自建/临时日程自动加入补推同步队列
    for (const local of preservedLocalItems) {
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
    if (preservedLocalItems.some((l) => l.id && String(l.id).startsWith('local_'))) {
      setTimeout(() => flushSyncQueue().catch(() => {}), 500)
    }

    state.total = payload.total ?? state.events.length
    state.error = ''
    state.authRequired = false
    state.lastUpdated = new Date()
    // 异步更新本地离线缓存
    saveEventsCache(state.events, state.total)
    // 定时段任务到期自动划掉检测与同步
    autoExpireEndedCustomTasks()
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
  if (state.offlineMode) return
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

  // 离线模式：只吃本机闪存，绝不联网（隐私优先）
  if (state.offlineMode) {
    state.accountsReady = true
    state.online = false
    return
  }

  // 3. 移动端强本地化策略：如果本地已有缓存数据，则首屏完全不阻塞等待网络请求
  const isMobile = isMobileNativeApp()
  const hasLocalData = state.events && state.events.length > 0

  if (isMobile && hasLocalData) {
    // 移动端在后台静默尝试同步离线队列，不阻塞 UI 渲染和用户交互
    setTimeout(() => {
      flushSyncQueue().catch(() => {})
    }, 1500)
    return
  }

  // 4. 首次启动或 Web 页面下并行拉取更新
  await Promise.all([refresh(), loadStatus(), loadConfig()])
}

/* --------------------------------------------------------------- accounts */

/**
 * 离线模式（本地账号）：不登录、不联网，所有数据只写在本机 localStorage。
 * 账号栏显示「本地账号」，云同步 / 教务抓取 / 微软待办全部停用。
 */
export function enableOfflineMode() {
  persistOfflineMode(true)
  state.offlineMode = true
  state.online = false
  state.authRequired = false
  state.forceAuth = false
  state.authError = ''
  state.authNotice = ''
  state.accountsReady = true
  state.loading = false
  closeCustomEditor()
  saveEventsCache(state.events, state.total)
  notify('已进入离线模式：数据只保存在本机', 'ok')
}

/** 退出离线模式，重新连接云端（需要登录才能同步）。 */
export async function disableOfflineMode() {
  persistOfflineMode(false)
  state.offlineMode = false
  state.accountsReady = false
  notify('已退出离线模式，正在连接云端', 'info')
  try {
    await fetchSession()
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
  const isMobile = isMobileNativeApp() || state.offlineMode
  const nowIso = nowClientIso()
  const payloadWithMeta = { ...payload, client_updated_at: nowIso }

  // 1. 移动端 / 离线模式秒存：纯本地立即生成或更新内存与闪存，无需等待服务器返回
  if (isMobile) {
    let localItem = null
    if (isExisting) {
      const { _endTs, ...cleanExisting } = existing
      const { clear_end_time, duration_hours, ...cleanFields } = payload
      const normalizedStart = formatShanghaiIso(toDate(payload.start_time)) || payload.start_time
      const normalizedEnd = payload.end_time
        ? (formatShanghaiIso(toDate(payload.end_time)) || payload.end_time)
        : null
      localItem = {
        ...cleanExisting,
        ...cleanFields,
        start_time: normalizedStart,
        end_time: normalizedEnd,
        updated_at: nowIso,
        client_updated_at: nowIso,
      }
      if (payload.status === 'pending') {
        unrecordCompletedOverride(existing.id)
      }
      const idx = state.events.findIndex((e) => e.id === existing.id)
      if (idx >= 0) state.events.splice(idx, 1, localItem)
      if (!state.offlineMode) appendSyncQueue({ type: 'patch', id: existing.id, payload: payloadWithMeta })
    } else {
      const isRecurring = Boolean(
        payload.repeat_frequency &&
        ['day', 'week', 'month'].includes(payload.repeat_frequency) &&
        payload.repeat_count > 1
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

      const createdItems = []
      const count = isRecurring ? repeatCount : 1

      for (let i = 0; i < count; i++) {
        const tempId = `local_${Date.now()}_${i}_${Math.random().toString(36).slice(2, 7)}`
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
        // 使用 +08:00 (Asia/Shanghai) ISO 字符串，确保课表网格立刻精确对齐真实时刻，无需等服务器回写纠偏
        const curStartIso = formatShanghaiIso(curStart)
        const curEndIso = durationMs != null ? formatShanghaiIso(new Date(curStart.getTime() + durationMs)) : null

        const item = {
          id: tempId,
          source: 'custom',
          status: 'pending',
          created_at: nowIso,
          updated_at: nowIso,
          client_updated_at: nowIso,
          ...cleanFields,
          start_time: curStartIso,
          end_time: curEndIso,
          recurrence: isRecurring ? {
            group_id: seriesGroupId,
            freq: repeatFreq,
            interval: repeatInterval,
            index: i + 1,
            total: repeatCount,
          } : null,
        }
        createdItems.push(item)
      }

      for (const it of [...createdItems].reverse()) {
        state.events.unshift(it)
      }
      state.total += createdItems.length
      localItem = createdItems[0]
      if (!state.offlineMode) {
        appendSyncQueue({
          type: 'create',
          temp_id: localItem.id,
          temp_ids: createdItems.map((it) => it.id),
          payload: payloadWithMeta,
        })
      }
    }
    // 立即写回本地永久缓存
    saveEventsCache(state.events, state.total)
    closeCustomEditor()
    notify(isExisting ? '已在本机更新' : '已保存在本机', 'ok')

    // 后台静默将变更回传服务器，用户无需等待（离线模式不回传）
    if (!state.offlineMode) {
      setTimeout(() => {
        flushSyncQueue().catch(() => {})
      }, 500)
    }
    return localItem
  }

  // 2. 网页端维持向服务器即时请求
  try {
    const saved = isExisting
      ? await api.patchEvent(existing.id, payloadWithMeta)
      : await api.createEvent(payloadWithMeta)
    if (isExisting && payload.status === 'pending') {
      unrecordCompletedOverride(existing.id)
    }
    const savedList = Array.isArray(saved?.items) ? saved.items : saved?.id ? [saved] : []
    if (savedList.length > 0) {
      if (isExisting) {
        const idx = state.events.findIndex((e) => e.id === existing.id)
        if (idx >= 0) state.events.splice(idx, 1, savedList[0])
        else state.events.unshift(savedList[0])
      } else {
        for (const item of [...savedList].reverse()) {
          if (!state.events.some((e) => e.id === item.id)) {
            state.events.unshift(item)
          }
        }
        state.total += savedList.length
      }
      saveEventsCache(state.events, state.total)
    }
    closeCustomEditor()
    notify(isExisting ? '日程已更新' : '日程已添加', 'ok')
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
  const isMobile = isMobileNativeApp() || state.offlineMode

  if (isMobile) {
    // 移动端 / 离线模式：直接从本地状态剔除、登记墓碑并存入同步队列
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
    const beforeLen = state.events.length
    state.events = state.events.filter((e) => !toRemoveIds.has(e.id))
    const removedCount = beforeLen - state.events.length
    state.total = Math.max(0, state.total - removedCount)
    toRemoveIds.forEach((removedId) => recordDeletedEventId(removedId))
    saveEventsCache(state.events, state.total)
    closeCustomEditor()
    if (!state.offlineMode) {
      appendSyncQueue({ type: 'delete', id, options })
      setTimeout(() => flushSyncQueue().catch(() => {}), 500)
    }
    notify(`已在本地移除${target ? `「${target.title}」` : '这条日程'}`, 'info')
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

  const isMobile = isMobileNativeApp() || state.offlineMode
  if (isMobile) {
    if (!state.offlineMode) {
      appendSyncQueue({ type: 'delete', id: event.id, options: {} })
      setTimeout(() => flushSyncQueue().catch(() => {}), 500)
    }
    notify(removedText(event), 'info', {
      action: { label: '撤销', run: () => restoreEvent(event.id, event.title) },
      duration: 6000,
    })
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
  if (state.offlineMode) {
    const target = state.events.find((item) => item.id === id)
    if (target) {
      target.hidden = false
      unrecordDeletedEventId(id)
      saveEventsCache(state.events, state.total)
    }
    notify(title ? `已恢复「${title}」` : '已恢复', 'info')
    return true
  }
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
  const next = event.status === 'completed' ? 'pending' : 'completed'
  const previous = event.status
  const prevCompletedAt = event.completed_at ?? null
  const prevUpdatedAt = event.updated_at
  const prevClientUpdatedAt = event.client_updated_at
  const nowIso = nowClientIso()
  const nowMs = parseTimestampMs(nowIso) || Date.now()

  // 1. 乐观更新内存状态并记录最后修改时间（0ms 响应 + LWW 对齐）
  event.status = next
  event.completed_at = next === 'completed' ? nowIso : null
  event.updated_at = nowIso
  event.client_updated_at = nowIso

  // 2. 强保护：写入本地完成态覆盖记录（含修改时间戳）与闪存缓存，彻底杜绝云端旧数据冲刷
  recordCompletedOverride(event.id, next, nowMs)
  saveEventsCache(state.events, state.total)

  // 离线模式：完成态只记在本机，不回传服务器
  if (state.offlineMode) return

  const patchPayload = { status: next, client_updated_at: nowIso }

  // 3. 打入离线同步队列双重保险
  const qid = appendSyncQueue({ type: 'patch', id: event.id, payload: patchPayload })

  // 临时本地 id 尚未落库时，走队列串行等待 create 返回真实 id 后再回写 PATCH
  if (String(event.id || '').startsWith('local_')) {
    setTimeout(() => {
      flushSyncQueue().catch(() => {})
    }, 300)
    return
  }

  // 4. 立即向服务器发起 PATCH 写入落盘（带 client_updated_at 防止旧状态倒流）
  try {
    const updated = await api.patchEvent(event.id, patchPayload)
    removeSyncQueueItem(qid)
    // 只有期间没有更新的本地再次操作时，才用服务器权威时间戳对齐本地状态
    if (shouldApplySyncedPatchResult(event, nowIso)) {
      Object.assign(event, updated)
      event.client_updated_at = updated?.updated_at || nowIso
      unrecordCompletedOverride(event.id)
      saveEventsCache(state.events, state.total)
    }
  } catch (error) {
    // 仅在明确遇到未登录/权限拒绝（401/403）时才回滚状态
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      removeSyncQueueItem(qid)
      event.status = previous
      event.completed_at = prevCompletedAt
      event.updated_at = prevUpdatedAt
      event.client_updated_at = prevClientUpdatedAt
      unrecordCompletedOverride(event.id)
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
export async function jwImportLocal(payload) {
  const result = await api.jwLocalImport(payload)
  const detail = result?.detail || {}
  const fresh = Array.isArray(detail.events) ? detail.events : []
  const keep = (state.events || []).filter((event) => event.source !== 'tju_schedule')
  state.events = [...keep, ...fresh]
  state.total = state.events.length

  const semester = detail.semester || {}
  state.config = {
    ...(state.config || {}),
    tju_schedule: {
      ...(state.config?.tju_schedule || {}),
      semester: { ...semester, start_date: semester.start_date || detail.term_start || '' },
      import_meta: {
        courses: detail.courses || 0,
        imported_at: new Date().toISOString(),
        source: 'local',
      },
    },
  }

  saveConfigCache(state.config)
  saveEventsCache(state.events, state.total)
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
