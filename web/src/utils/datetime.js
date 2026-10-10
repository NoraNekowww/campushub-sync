/**
 * Date helpers. Everything on the wire is ISO-8601 with an explicit offset
 * (Asia/Shanghai), and every render forces that zone so the UI is identical no
 * matter what the device clock is set to.
 */
export const TZ = 'Asia/Shanghai'

const dateFmt = (options) =>
  new Intl.DateTimeFormat('zh-CN', { timeZone: TZ, ...options })

const DAY_MS = 86400000

export function toDate(value) {
  if (!value) return null
  const parsed = value instanceof Date ? value : new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function timeLabel(value) {
  const date = toDate(value)
  return date ? dateFmt({ hour: '2-digit', minute: '2-digit', hour12: false }).format(date) : ''
}

export function weekdayLabel(value) {
  const date = toDate(value)
  return date ? dateFmt({ weekday: 'short' }).format(date) : ''
}

/** Local (Asia/Shanghai) calendar day key: YYYY-MM-DD. */
export function dayKey(value) {
  const date = toDate(value)
  if (!date) return ''
  // en-CA renders ISO-like YYYY-MM-DD
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(date)
}

export function todayKey() {
  return dayKey(new Date())
}

export function dayLabel(value) {
  const key = dayKey(value)
  const today = todayKey()
  const tomorrow = dayKey(new Date(Date.now() + DAY_MS))
  if (key === today) return '今天'
  if (key === tomorrow) return '明天'
  const date = toDate(value)
  const month = dateFmt({ month: 'numeric', day: 'numeric' }).format(date)
  // Calendar weeks (Monday-based), not "the next 6 days": the week grid uses the
  // same boundaries, so both views must agree on what 本周 means.
  const offset = weekOffsetOf(key, today)
  const head =
    offset === 0 ? '本周' : offset === -1 ? '上周' : offset === 1 ? '下周' : `${offset > 0 ? '+' : ''}${offset} 周`
  return `${head} · ${weekdayLabel(date)} ${month}`
}

/** Whole-week distance between two YYYY-MM-DD keys (Monday-based weeks). */
export function weekOffsetOf(key, reference = todayKey()) {
  const mondayKey = (value) => {
    const date = new Date(`${value}T00:00:00Z`)
    date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7))
    return date.toISOString().slice(0, 10)
  }
  return Math.round(
    (Date.parse(`${mondayKey(key)}T00:00:00Z`) - Date.parse(`${mondayKey(reference)}T00:00:00Z`)) / (7 * DAY_MS),
  )
}

export function dayDiff(keyA, keyB) {
  const a = new Date(`${keyA}T00:00:00Z`).getTime()
  const b = new Date(`${keyB}T00:00:00Z`).getTime()
  return Math.round((a - b) / DAY_MS)
}

/** Minutes since midnight in Asia/Shanghai (device timezone independent). */
export function minutesOfDay(value) {
  const date = toDate(value)
  if (!date) return null
  const parts = dateFmt({ hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(date)
  const hour = Number(parts.find((part) => part.type === 'hour')?.value ?? 0)
  const minute = Number(parts.find((part) => part.type === 'minute')?.value ?? 0)
  return hour * 60 + minute
}

export function durationMinutes(start, end) {
  const a = toDate(start)
  const b = toDate(end)
  if (!a || !b) return null
  return Math.max(0, Math.round((b - a) / 60000))
}

export function durationLabel(start, end, periods) {
  const minutes = durationMinutes(start, end)
  if (minutes === null || minutes === 0) return ''
  const range = periodRange(periods)
  const head = range ? `${periodLabel(periods)} · ${range[1] - range[0] + 1} 节 · ` : ''
  if (minutes < 60) return `${head}${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return `${head}${hours} 小时${rest ? ` ${rest} 分` : ''}`
}

/** Countdown copy + tone for deadlines. */
export function countdown(value) {
  const date = toDate(value)
  if (!date) return null
  const diffMs = date.getTime() - Date.now()
  const hours = Math.round(diffMs / 3600000)
  if (diffMs < 0) return { text: `已逾期 ${Math.abs(Math.round(hours / 24)) || 1} 天`, tone: 'danger', overdue: true }
  if (hours < 1) return { text: '不到 1 小时', tone: 'danger', overdue: false }
  if (hours < 24) return { text: `剩 ${hours} 小时`, tone: 'warn', overdue: false }
  const days = Math.round(hours / 24)
  if (days === 1) return { text: '明天截止', tone: 'warn', overdue: false }
  return { text: `剩 ${days} 天`, tone: days <= 3 ? 'warn' : 'muted', overdue: false }
}

/** 真实节次 ``[起, 止]``（后端 ``event.periods``，1 起）；拿不到返回 null。
 *
 * 以前 UI 是拿「时长 ÷ 45 分钟」猜节数的：第 1-4 节 08:30-12:00 = 210 分钟（含课间
 * 休息）会被吼成 5 节 —— 所以后端把真实节次透出来，估算只当兜底。 */
export function periodRange(periods) {
  const list = Array.isArray(periods) ? periods.map(Number).filter(Number.isFinite) : []
  if (list.length === 1 && list[0] >= 1) return [list[0], list[0]]
  if (list.length < 2 || list[1] < list[0] || list[0] < 1) return null
  return [list[0], list[1]]
}

/** "第 5-8 节" / "第 5 节" */
export function periodLabel(periods) {
  const range = periodRange(periods)
  if (!range) return ''
  return range[1] === range[0] ? `第 ${range[0]} 节` : `第 ${range[0]}-${range[1]} 节`
}

/** 徽章里的短标签："4 节"；没有真实节次（个人日程/待办）就不编造。 */
export function periodsShort(start, end, periods) {
  const range = periodRange(periods)
  return range ? `${range[1] - range[0] + 1} 节` : ''
}

export function groupByDay(events) {
  const buckets = new Map()
  events.forEach((event) => {
    const when = dayKey(event.start_time)
    if (!buckets.has(when)) buckets.set(when, { key: when, label: dayLabel(event.start_time), events: [] })
    buckets.get(when).events.push(event)
  })
  return [...buckets.values()]
    .sort((a, b) => a.key.localeCompare(b.key))
    .map((bucket) => ({
      ...bucket,
      events: bucket.events.sort((a, b) => String(a.start_time).localeCompare(String(b.start_time))),
    }))
}

/** Monday-based week window (Asia/Shanghai) used by the week grid + fetches. */
export function weekWindow(reference = new Date()) {
  const key = dayKey(reference)
  const weekday = new Intl.DateTimeFormat('en-US', { timeZone: TZ, weekday: 'short' }).format(toDate(reference))
  const order = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 }
  const offset = order[weekday] ?? 0
  const start = new Date(new Date(`${key}T00:00:00Z`).getTime() - offset * DAY_MS)
  const days = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start.getTime() + index * DAY_MS)
    return day.toISOString().slice(0, 10)
  })
  return { start: days[0], end: days[6], days }
}
