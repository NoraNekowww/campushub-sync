<template>
  <div class="relative w-full overflow-hidden select-none" data-testid="week-fullscreen">
    <div
      ref="scroller"
      data-testid="week-scroller"
      class="w-full overflow-auto no-scrollbar"
      :style="scrollerViewportStyle"
      @scroll.passive="onScrollerScroll"
    >
      <div class="flex flex-col min-w-fit">
        <!-- 顶部吸顶星期栏：上下滑动浏览 0:00–24:00 时固定在顶栏下方，左右滑动与列完美硬件同步 -->
        <div
          ref="dayHeaderEl"
          class="sticky top-0 z-30 grid border-b border-white/45 bg-white/40 backdrop-blur-2xl
                 dark:border-white/10 dark:bg-slate-950/55"
          :style="gridStyle"
        >
          <div
            v-for="day in days"
            :key="`head-${day.key}`"
            data-testid="week-day-header"
            :data-day="day.key"
            :data-today="day.isToday ? 'true' : 'false'"
            class="px-1 py-1.5 text-center transition-colors"
            :class="[
              day.isMonday
                ? 'border-l-2 border-slate-300/80 dark:border-slate-600/80'
                : 'border-l border-white/35 dark:border-white/10',
              day.isToday ? 'bg-brand-500/15 dark:bg-brand-400/15' : '',
            ]"
          >
            <div class="h-3.5 flex items-center justify-center">
              <span
                v-if="day.isToday"
                class="rounded-full bg-brand-600 px-1.5 py-0 text-[9px] leading-[13px] font-bold text-white dark:bg-brand-500"
              >
                今天
              </span>
              <span
                v-else-if="day.isMonday"
                class="whitespace-nowrap text-[9px] font-bold text-brand-700 dark:text-brand-300"
              >
                {{ day.weekLabel }}
              </span>
            </div>
            <p
              class="text-[11px]"
              :class="
                day.isToday
                  ? 'font-bold text-brand-700 dark:text-brand-300'
                  : 'text-slate-600 dark:text-slate-400'
              "
            >
              {{ day.weekday }}
            </p>
            <p
              class="text-xs font-semibold"
              :class="day.isToday ? 'text-brand-700 dark:text-brand-200' : 'text-slate-800 dark:text-slate-100'"
            >
              {{ day.dayNum }}
            </p>
          </div>
        </div>

        <!-- 00:00 – 24:00 全天可上下拓展网格（默认视口自动锚定 08:00–21:xx 日间核心区） -->
        <div class="grid" :style="gridStyle">
          <div
            v-for="day in days"
            :key="`col-${day.key}`"
            class="relative week-day-col snap-start"
            :class="[
              state.weekGridStyle === 'blank'
                ? day.isMonday
                  ? 'border-l-2 border-white/30 dark:border-white/10'
                  : 'border-l border-white/15 dark:border-white/5'
                : day.isMonday
                  ? 'border-l-2 border-slate-300/75 dark:border-slate-700/80'
                  : 'border-l border-slate-200/45 dark:border-slate-800/65',
              day.isToday ? 'bg-brand-500/[0.06] dark:bg-brand-400/[0.06]' : '',
            ]"
            :style="{ height: `${gridHeight}px` }"
          >
            <!-- 水平整点与细分参考线（覆盖 00:00 - 24:00 全天 24 小时） -->
            <template v-if="state.weekGridStyle !== 'blank'">
              <template v-for="hour in hours" :key="`line-${day.key}-${hour}`">
                <div
                  class="pointer-events-none absolute inset-x-0 border-t"
                  :class="
                    hour === 8 || hour === 22
                      ? 'border-slate-300/70 dark:border-slate-700/80'
                      : 'border-slate-200/50 dark:border-slate-800/55'
                  "
                  :style="{ top: pct(hour * 60) + '%' }"
                />
                <div
                  v-if="state.weekGridStyle === 'subgrid'"
                  class="pointer-events-none absolute inset-x-0 border-t border-dashed border-slate-200/35 dark:border-slate-800/40"
                  :style="{ top: pct(hour * 60 + 30) + '%' }"
                />
              </template>
            </template>

            <!-- 当前时间红线（全天 00:00–24:00 实时精准定位） -->
            <div
              v-if="day.isToday && isNowVisible"
              data-testid="current-time-line"
              class="pointer-events-none absolute inset-x-0 z-30 flex -translate-y-1/2 items-center animate-pulse"
              :style="{ top: `${nowPct}%` }"
            >
              <div class="-ml-1 h-2 w-2 rounded-full bg-rose-500 shadow-sm shadow-rose-500/50" />
              <div class="h-[2px] flex-1 bg-rose-500 shadow-sm shadow-rose-500/50" />
            </div>

            <template v-for="item in day.items" :key="item.event.id">
              <!-- 有结束时间：课程 / 活动日程块 -->
              <button
                v-if="item.end !== null"
                type="button"
                data-testid="class-block"
                :data-day="day.key"
                class="absolute inset-x-0 overflow-hidden rounded-lg px-px py-1
                       text-left text-[10px] leading-tight text-slate-800 transition-all hover:scale-[1.01]
                       dark:text-slate-100"
                :class="[
                  item.event.is_deadline
                    ? 'border-amber-300/80 bg-amber-100/80 text-amber-900 dark:border-amber-400/30 dark:bg-amber-500/20 dark:text-amber-100'
                    : '',
                  isImportantEvent(item.event) ? 'is-important' : '',
                  isItemPastEntirely(day.key, item) ? 'is-past-entirely' : '',
                  item.hasConflict ? 'animate-breathe-alternate' : '',
                ]"
                :style="blockStyle(item)"
                :aria-pressed="selectedEvent?.id === item.event.id"
                @click="toggleSelect(item.event)"
              >
                <span class="font-bold text-[9.5px] leading-[10.5px] line-clamp-2 select-none tracking-tight">
                  <span v-if="isImportantEvent(item.event)" class="text-amber-500 font-extrabold mr-0.5">★</span>
                  {{ item.event.title }}
                </span>
                <span class="block whitespace-nowrap text-[8px] leading-[10px] font-mono font-medium tracking-tight opacity-90">
                  {{ timeLabel(item.event.start_time) }}-{{ timeLabel(item.event.end_time) }}
                </span>
                <span
                  v-if="item.event.location"
                  data-testid="class-block-location"
                  class="block truncate text-[8.5px] leading-[10px] font-semibold text-brand-700 dark:text-brand-300"
                  :title="item.event.location"
                >
                  {{ formatShortLocation(item.event.location) }}
                </span>
                <div
                  v-if="getItemPastProgress(day.key, item) > 0"
                  class="class-past-overlay"
                  :style="pastOverlayStyle(day.key, item)"
                />
              </button>

              <!-- 没有结束时间（DDL / 单时刻待办）：实线居中对齐物理时刻，24px 热区 + 可点击胶囊标签 -->
              <button
                v-else
                type="button"
                data-testid="line-event"
                :data-day="day.key"
                class="group absolute inset-x-0 z-20 -translate-y-1/2 h-6 text-left pointer-events-auto cursor-pointer focus:outline-none"
                :class="item.hasConflict ? 'animate-breathe-alternate' : ''"
                :style="lineStyle(item)"
                :aria-pressed="selectedEvent?.id === item.event.id"
                @click.stop="toggleSelect(item.event)"
              >
                <!-- 物理时间刻度实线：严格位于 24px 热区正中（top-1/2），像素级对齐真实截止时刻 -->
                <div
                  class="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 h-[2.5px] shadow-xs transition-transform group-hover:scale-y-125"
                  :class="
                    item.event.is_deadline
                      ? 'bg-amber-500 dark:bg-amber-400'
                      : 'bg-sky-500 dark:bg-sky-400'
                  "
                />
                <!-- 文字胶囊标签：同样可点击唤起详情弹窗进行编辑或划掉 -->
                <span
                  class="pointer-events-auto absolute left-0 max-w-full truncate rounded px-1
                         text-[9px] leading-[13px] font-semibold shadow-xs backdrop-blur-md select-none
                         transition-transform group-active:scale-95"
                  :class="[
                    item.start <= 25 ? 'top-3.5' : '-top-1.5',
                    item.event.is_deadline
                      ? 'bg-amber-50/95 text-amber-900 border border-amber-300/90 dark:bg-slate-900/95 dark:text-amber-200 dark:border-amber-400/60'
                      : 'bg-sky-50/95 text-sky-900 border border-sky-300/90 dark:bg-slate-900/95 dark:text-sky-200 dark:border-sky-400/60',
                  ]"
                >
                  {{ item.event.title }}
                </span>
              </button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 点击课程块或 DDL 实线均唤起详情弹窗（支持查看、标星、编辑、直接划掉完成、删除） -->
    <ClassDetail :event="selectedEvent" @close="selectedId = null" />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import ClassDetail from '../components/ClassDetail.vue'
import { api } from '../api'
import {
  isImportantEvent,
  isMobileNativeApp,
  matchesQuery,
  state,
  upsertServerEventsIntoStore,
} from '../store'
import { dayKey, minutesOfDay, timeLabel, todayKey, weekWindow } from '../utils/datetime'
import { projectColumnSnap, resolveScrollAxis } from '../utils/scrollLock'

/* 全天可滚动范围：00:00 - 24:00；默认首屏可视锚定范围：08:00 - 22:00（完整涵盖 8:00 至晚 21:40 第12节） */
const FULL_DAY_START = 0
const FULL_DAY_END = 24 * 60 // 1440
const DEFAULT_START_HOUR = 8 // 08:00
const DEFAULT_END_HOUR = 22  // 22:00（覆盖 8:00 - 21:xx 全段）
const DEFAULT_VISIBLE_HOURS = DEFAULT_END_HOUR - DEFAULT_START_HOUR // 14 小时
const LINE_MINUTES = 30
const hours = Array.from({ length: 24 }, (_, index) => index) // 0..23
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const loading = ref(false)
const selectedId = ref(null)
const scroller = ref(null)
const dayHeaderEl = ref(null)

/* 全屏视口高度测量：顶栏约 41px + 底栏约 47px = 88px */
const scrollerViewportStyle = {
  height: 'calc(100dvh - 88px - env(safe-area-inset-bottom, 0px))',
}

const visibleBodyHeight = ref(560)
const hourHeight = computed(() => Math.max(38, visibleBodyHeight.value / DEFAULT_VISIBLE_HOURS))
const gridHeight = computed(() => Math.round(hourHeight.value * 24))

const selectedEvent = computed(() => {
  if (!selectedId.value) return null
  return (state.events || []).find((ev) => ev.id === selectedId.value && !ev.hidden) || null
})

function toggleSelect(event) {
  if (!event?.id) return
  selectedId.value = selectedId.value === event.id ? null : event.id
}

/* 当前时间线：实时走动 */
const now = ref(new Date())
let nowTimer = null

const nowMinutes = computed(() => {
  const d = now.value
  return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60
})
const isNowVisible = computed(() => nowMinutes.value >= FULL_DAY_START && nowMinutes.value <= FULL_DAY_END)
const nowPct = computed(() => pct(nowMinutes.value))

/* 无极滚动多周构建：从上上周(-2) 到未来第六周(+6)，共 9 周 = 63 天 */
const WEEKS_PAST = 2
const WEEKS_FUTURE = 6

const multiWeekWindow = computed(() => {
  const nowTs = Date.now()
  const today = todayKey()
  const allDays = []
  for (let w = -WEEKS_PAST; w <= WEEKS_FUTURE; w++) {
    const anchor = new Date(nowTs + w * 7 * 86400000)
    const win = weekWindow(anchor)
    win.days.forEach((key, idx) => {
      allDays.push({
        key,
        weekday: WEEKDAYS[idx],
        dayNum: Number(key.slice(8, 10)),
        isToday: key === today,
        isMonday: idx === 0,
        weekOffset: w,
        weekLabel: w === 0 ? '本周' : w === 1 ? '下周' : w === -1 ? '上周' : `第 ${w > 0 ? '+' : ''}${w} 周`,
      })
    })
  }
  return allDays
})

/* 统一以全局唯一事件库 state.events 渲染，彻底根治双缓存不同步、修改后新老并存及复活问题 */
const days = computed(() => {
  const sourceEvents = Array.isArray(state.events) ? state.events : []
  return multiWeekWindow.value.map((d) => {
    const items = sourceEvents
      .filter(
        (event) =>
          !event.hidden &&
          dayKey(event.start_time) === d.key &&
          matchesQuery(event) &&
          !event.is_undated &&
          !(event.is_deadline && event.status === 'completed'),
      )
      .map((event) => ({
        event,
        start: minutesOfDay(event.start_time),
        end: minutesOfDay(event.end_time),
      }))
      .filter((item) => item.start !== null)
    layoutItems(items)
    return {
      ...d,
      items,
    }
  })
})

/* 自适应列宽：一屏正好容纳完整 7 列，左右边缘对齐整数格 */
const colWidth = ref(56)
const gridStyle = computed(() => ({
  gridTemplateColumns: `repeat(${days.value.length}, ${colWidth.value}px)`,
}))

let resizeObserver = null
let hasAlignedInitial = false

function getAnchorColIndex() {
  const todayIdx = days.value.findIndex((day) => day.isToday)
  if (state.weekAnchorMode === 'today_third') {
    // 「今天在第三列」：第一列前天、第二列昨天、第三列今天
    return todayIdx >= 0 ? Math.max(0, todayIdx - 2) : 0
  }
  // 默认「本周视图」：本周一在第一列（周一至周日）
  const mondayIdx = days.value.findIndex((day) => day.weekOffset === 0 && day.isMonday)
  return mondayIdx >= 0 ? mondayIdx : Math.max(0, todayIdx)
}

function measureViewport({ resetPosition = false } = {}) {
  const el = scroller.value
  if (!el || !el.clientWidth) return
  const hdrH = dayHeaderEl.value?.offsetHeight || 48
  const bodyH = Math.max(380, (el.clientHeight || 608) - hdrH)
  const prevHourH = hourHeight.value
  const prevScrollTop = el.scrollTop
  visibleBodyHeight.value = bodyH

  const nextWidth = el.clientWidth / 7
  const prevWidth = colWidth.value
  if (Math.abs(nextWidth - prevWidth) > 0.05) {
    colWidth.value = nextWidth
    if (!resetPosition && prevWidth > 0 && hasAlignedInitial) {
      const firstCol = Math.round(el.scrollLeft / prevWidth)
      el.scrollLeft = Math.max(0, Math.round(firstCol * nextWidth))
    }
  }

  if (resetPosition || !hasAlignedInitial) {
    hasAlignedInitial = true
    nextTick(() => focusToday('auto', { resetVertical: true }))
  } else if (prevHourH > 0 && Math.abs(hourHeight.value - prevHourH) > 0.2) {
    const prevTopMinutes = (prevScrollTop / prevHourH) * 60
    nextTick(() => {
      if (scroller.value) {
        scroller.value.scrollTop = Math.round((prevTopMinutes / 60) * hourHeight.value)
      }
    })
  }
}

/* 课表无极滚动实时感知当前视窗对应的教学周与是否偏离锚点 */
const centeredWeekOffset = ref(0)
const isAtAnchorCol = ref(true)

const currentTeachingWeek = computed(() => {
  const startRaw = state.config?.tju_schedule?.semester?.start_date
  let startDate
  if (startRaw) {
    startDate = new Date(startRaw)
  } else {
    const cur = new Date()
    const year = cur.getMonth() >= 7 ? cur.getFullYear() : cur.getFullYear() - 1
    startDate = new Date(year, 7, 31)
    startDate.setDate(startDate.getDate() - ((startDate.getDay() + 6) % 7))
  }
  const today = new Date()
  const diffDays = Math.floor((today.getTime() - startDate.getTime()) / 86400000)
  return Math.max(1, Math.floor(diffDays / 7) + 1)
})

const currentVisibleWeekLabel = computed(() => {
  const offset = centeredWeekOffset.value
  const weekNum = currentTeachingWeek.value + offset
  return `第 ${weekNum} 周`
})

watch(
  currentVisibleWeekLabel,
  (val) => {
    state.weekLabel = val
  },
  { immediate: true },
)

watch(
  isAtAnchorCol,
  (val) => {
    state.isCurrentWeekCentered = val
  },
  { immediate: true },
)

let scrollRaf = null
function onScrollerScroll() {
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null
    const el = scroller.value
    if (!el || !colWidth.value) return
    const firstCol = Math.round(el.scrollLeft / colWidth.value)
    const anchorCol = getAnchorColIndex()
    isAtAnchorCol.value = Math.abs(firstCol - anchorCol) === 0

    // 在「今天在第三列」模式下取第三列（firstCol + 2）计算周次，避免周一/周二时前两列属于上周导致周数误跳
    const refOffsetInViewport = state.weekAnchorMode === 'today_third' ? 2 : 3
    const refIndex = Math.max(0, Math.min(days.value.length - 1, firstCol + refOffsetInViewport))
    const refDay = days.value[refIndex]
    if (refDay && refDay.weekOffset !== centeredWeekOffset.value) {
      centeredWeekOffset.value = refDay.weekOffset
    }
  })
}

function focusToday(behavior = 'smooth', { resetVertical = true } = {}) {
  const el = scroller.value
  if (!el || !el.clientWidth) return
  const hdrH = dayHeaderEl.value?.offsetHeight || 48
  const bodyH = Math.max(380, (el.clientHeight || 608) - hdrH)
  visibleBodyHeight.value = bodyH

  const nextWidth = el.clientWidth / 7
  if (Math.abs(nextWidth - colWidth.value) > 0.05) {
    colWidth.value = nextWidth
  }
  const targetIdx = getAnchorColIndex()
  const left = Math.max(0, Math.round(targetIdx * colWidth.value))
  const defaultTop = Math.max(0, Math.round(DEFAULT_START_HOUR * hourHeight.value))

  if (behavior === 'auto') {
    el.scrollLeft = left
    if (resetVertical) el.scrollTop = defaultTop
  } else {
    el.scrollTo({
      left,
      top: resetVertical ? defaultTop : el.scrollTop,
      behavior,
    })
  }
  centeredWeekOffset.value = 0
  isAtAnchorCol.value = true
}

onMounted(() => nextTick(() => measureViewport({ resetPosition: true })))

watch(
  () => state.view,
  (view) => {
    if (view === 'week') nextTick(() => measureViewport({ resetPosition: true }))
  },
)

watch(
  () => state.weekAnchorMode,
  () => {
    if (state.view === 'week') {
      nextTick(() => focusToday('smooth', { resetVertical: false }))
    } else {
      hasAlignedInitial = false
    }
  },
)

function formatShortLocation(loc) {
  if (!loc) return ''
  const clean = loc.replace(/\s*[（(][^）)]*[）)]\s*/g, '').trim()
  return clean || loc
}

const pct = (minutes) => {
  const clamped = Math.min(Math.max(minutes, FULL_DAY_START), FULL_DAY_END)
  return ((clamped - FULL_DAY_START) / (FULL_DAY_END - FULL_DAY_START)) * 100
}

function hasSubstantialConflict(a, b) {
  if (a.end === null && b.end === null) {
    return Math.abs(a.start - b.start) < 10
  }
  const course = a.end !== null ? a : b
  const ddl = a.end === null ? a : b
  if (course.end !== null && ddl.end === null) {
    const cStart = course.start
    const cEnd = course.end
    if (ddl.start <= cStart + 10 || ddl.start >= cEnd) {
      return false
    }
    return true
  }
  const overlap = Math.min(a.end, b.end) - Math.max(a.start, b.start)
  return overlap > 10
}

function layoutItems(items) {
  const sorted = [...items].sort((a, b) => a.start - b.start)
  const visited = new Set()
  for (let i = 0; i < sorted.length; i++) {
    const item = sorted[i]
    if (visited.has(item)) continue

    const group = [item]
    visited.add(item)
    for (let j = 0; j < sorted.length; j++) {
      if (i === j) continue
      const other = sorted[j]
      if (group.some((g) => hasSubstantialConflict(g, other))) {
        if (!visited.has(other)) {
          visited.add(other)
          group.push(other)
        }
      }
    }

    if (group.length > 1) {
      const groupSize = group.length
      group.forEach((member, idx) => {
        member.hasConflict = true
        member.overlapCycleSize = groupSize
        member.overlapCycleIndex = idx
      })
    } else {
      item.hasConflict = false
      item.overlapCycleSize = 1
      item.overlapCycleIndex = 0
    }
  }
  return sorted
}

function getItemPastProgress(dayKeyVal, item) {
  const today = todayKey()
  if (dayKeyVal < today) return 100
  if (dayKeyVal > today) return 0
  if (item.end === null) return 0
  const startMin = Math.min(Math.max(item.start, FULL_DAY_START), FULL_DAY_END)
  let endMin = Math.min(Math.max(item.end, FULL_DAY_START), FULL_DAY_END)
  if (endMin <= startMin) endMin = Math.min(startMin + LINE_MINUTES, FULL_DAY_END)
  const cur = nowMinutes.value
  if (cur >= endMin) return 100
  if (cur <= startMin) return 0
  const pctVal = ((cur - startMin) / (endMin - startMin)) * 100
  return Math.min(100, Math.max(0, Number(pctVal.toFixed(2))))
}

function pastOverlayStyle(dayKeyVal, item) {
  const pctVal = getItemPastProgress(dayKeyVal, item)
  if (pctVal >= 100) {
    return { top: '-1px', height: 'calc(100% + 2px)' }
  }
  const borderCompPx = ((2 * pctVal) / 100).toFixed(2)
  return {
    top: '-1px',
    height: `calc(${pctVal}% + ${borderCompPx}px)`,
  }
}

function isItemPastEntirely(dayKeyVal, item) {
  return getItemPastProgress(dayKeyVal, item) >= 100
}

function blockStyle(item) {
  const startMin = Math.min(Math.max(item.start, FULL_DAY_START), FULL_DAY_END)
  let endMin =
    item.end === null ? startMin + LINE_MINUTES : Math.min(Math.max(item.end, FULL_DAY_START), FULL_DAY_END)
  if (endMin <= startMin) endMin = Math.min(startMin + LINE_MINUTES, FULL_DAY_END)
  const height = Math.max(1.9, ((endMin - startMin) / (FULL_DAY_END - FULL_DAY_START)) * 100)

  const style = {
    top: `${pct(item.start)}%`,
    height: `${height}%`,
  }

  if (item.hasConflict && item.overlapCycleSize > 1) {
    const cycleDuration = 4.0
    const delaySec = ((item.overlapCycleIndex || 0) * (cycleDuration / item.overlapCycleSize)).toFixed(2)
    style.animationDelay = `${delaySec}s`
    style.zIndex = 5 + (item.overlapCycleIndex || 0)
  }

  return style
}

function lineStyle(item) {
  const topPct = pct(item.start)
  const style = {
    top: `${topPct}%`,
  }

  if (item.hasConflict && item.overlapCycleSize > 1) {
    const cycleDuration = 4.0
    const delaySec = ((item.overlapCycleIndex || 0) * (cycleDuration / item.overlapCycleSize)).toFixed(2)
    style.animationDelay = `${delaySec}s`
    style.zIndex = 20 + (item.overlapCycleIndex || 0)
  } else {
    style.zIndex = 20
  }

  return style
}

async function loadWeek(force = false) {
  if (state.offlineMode) return
  const isMobile = isMobileNativeApp()
  if (!force && isMobile && state.events && state.events.length > 0) {
    return
  }

  if (!state.events || state.events.length === 0) {
    loading.value = true
  }
  try {
    const list = multiWeekWindow.value
    if (!list.length) return
    const start = list[0].key
    const end = list[list.length - 1].key
    const payload = await api.events({ start_date: start, end_date: end, include_hidden: true, limit: 1500 })
    if (Array.isArray(payload?.items) && payload.items.length > 0) {
      upsertServerEventsIntoStore(payload.items)
    }
  } catch (error) {
    if (!state.events || state.events.length === 0) {
      state.error = error.message || '加载失败'
    }
  } finally {
    loading.value = false
  }
}

const handleGlobalFocusToday = () => focusToday('smooth', { resetVertical: true })

/* 单轴意图锁定滑动引擎：根据初始滑动手势方向锁定纯水平或纯竖直，绝不斜向漂移 */
let lockedAxis = null
let touchStartX = 0
let touchStartY = 0
let touchStartLeft = 0
let touchStartTop = 0
let touchSamples = []
let inertiaRaf = null

function cancelInertia() {
  if (inertiaRaf) {
    cancelAnimationFrame(inertiaRaf)
    inertiaRaf = null
  }
}

function recordTouchSample(x, y) {
  const nowTs = typeof performance !== 'undefined' ? performance.now() : Date.now()
  touchSamples.push({ t: nowTs, x, y })
  const cutoff = nowTs - 120
  while (touchSamples.length > 5 || (touchSamples.length > 1 && touchSamples[0].t < cutoff)) {
    touchSamples.shift()
  }
}

function onTouchStart(e) {
  cancelInertia()
  const el = scroller.value
  if (!el || e.touches.length !== 1) {
    lockedAxis = null
    return
  }
  const t = e.touches[0]
  touchStartX = t.clientX
  touchStartY = t.clientY
  touchStartLeft = el.scrollLeft
  touchStartTop = el.scrollTop
  lockedAxis = null
  touchSamples = []
  recordTouchSample(t.clientX, t.clientY)
}

function onTouchMove(e) {
  const el = scroller.value
  if (!el || e.touches.length !== 1) return
  const t = e.touches[0]
  const dx = t.clientX - touchStartX
  const dy = t.clientY - touchStartY
  if (!lockedAxis) {
    lockedAxis = resolveScrollAxis(dx, dy, 6)
    if (!lockedAxis) return
  }
  e.preventDefault()
  recordTouchSample(t.clientX, t.clientY)
  if (lockedAxis === 'x') {
    const maxLeft = Math.max(0, el.scrollWidth - el.clientWidth)
    el.scrollLeft = Math.max(0, Math.min(maxLeft, touchStartLeft - dx))
    el.scrollTop = touchStartTop
  } else {
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight)
    el.scrollTop = Math.max(0, Math.min(maxTop, touchStartTop - dy))
    el.scrollLeft = touchStartLeft
  }
}

function onTouchEnd() {
  const el = scroller.value
  const axis = lockedAxis
  lockedAxis = null
  if (!el || !axis) return

  let vx = 0
  let vy = 0
  if (touchSamples.length >= 2) {
    const first = touchSamples[0]
    const last = touchSamples[touchSamples.length - 1]
    const dt = Math.max(1, last.t - first.t)
    vx = (last.x - first.x) / dt
    vy = (last.y - first.y) / dt
  }

  if (axis === 'x') {
    const targetLeft = projectColumnSnap(el.scrollLeft, vx, colWidth.value, days.value.length)
    el.scrollTo({ left: targetLeft, top: touchStartTop, behavior: 'smooth' })
  } else if (Math.abs(vy) > 0.08) {
    let v = -vy // 手指向上滑（vy < 0）对应 scrollTop 增加
    let prevTs = typeof performance !== 'undefined' ? performance.now() : Date.now()
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight)
    const step = (nowTs) => {
      const curEl = scroller.value
      if (!curEl) {
        inertiaRaf = null
        return
      }
      const dt = Math.min(32, Math.max(1, nowTs - prevTs))
      prevTs = nowTs
      const nextTop = Math.max(0, Math.min(maxTop, curEl.scrollTop + v * dt))
      curEl.scrollTop = nextTop
      curEl.scrollLeft = touchStartLeft
      v *= Math.pow(0.94, dt / 16)
      if (Math.abs(v) < 0.03 || nextTop <= 0 || nextTop >= maxTop) {
        inertiaRaf = null
        return
      }
      inertiaRaf = requestAnimationFrame(step)
    }
    inertiaRaf = requestAnimationFrame(step)
  }
}

function onWheel(e) {
  const el = scroller.value
  if (!el) return
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 0) {
    e.preventDefault()
    const maxLeft = Math.max(0, el.scrollWidth - el.clientWidth)
    el.scrollLeft = Math.max(0, Math.min(maxLeft, el.scrollLeft + e.deltaX))
  } else if (Math.abs(e.deltaY) > 0) {
    e.preventDefault()
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight)
    el.scrollTop = Math.max(0, Math.min(maxTop, el.scrollTop + e.deltaY))
  }
}

onMounted(() => {
  loadWeek()
  if (typeof ResizeObserver !== 'undefined' && scroller.value) {
    resizeObserver = new ResizeObserver(() => measureViewport())
    resizeObserver.observe(scroller.value)
  }
  const el = scroller.value
  if (el) {
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
    el.addEventListener('touchcancel', onTouchEnd, { passive: true })
    el.addEventListener('wheel', onWheel, { passive: false })
  }
  nowTimer = setInterval(() => {
    now.value = new Date()
  }, 30000)
  if (typeof window !== 'undefined') {
    window.addEventListener('campushub:focus-today', handleGlobalFocusToday)
  }
})

onUnmounted(() => {
  cancelInertia()
  const el = scroller.value
  if (el) {
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMove)
    el.removeEventListener('touchend', onTouchEnd)
    el.removeEventListener('touchcancel', onTouchEnd)
    el.removeEventListener('wheel', onWheel)
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (nowTimer) clearInterval(nowTimer)
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
  if (typeof window !== 'undefined') {
    window.removeEventListener('campushub:focus-today', handleGlobalFocusToday)
  }
})
</script>
