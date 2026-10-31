<template>
  <div class="space-y-4 px-4">
    <div class="flex items-center gap-2">
      <button class="btn-ghost !px-2" title="向左平滑滑动" @click="scrollWeeks(-1)">
        <ChevronLeft :size="16" />
      </button>
      <div class="flex-1 text-center cursor-pointer" title="点击回到今天" @click="focusToday('smooth')">
        <div class="flex items-center justify-center gap-1.5">
          <p class="text-sm font-semibold">{{ currentVisibleWeekLabel }}</p>
          <span
            v-if="!isCurrentWeekCentered"
            class="chip border-brand-200 bg-brand-50 px-1.5 py-0 text-[10px] text-brand-700 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-300"
          >
            回今天
          </span>
        </div>
      </div>
      <button class="btn-ghost !px-2" title="向右平滑滑动" @click="scrollWeeks(1)">
        <ChevronRight :size="16" />
      </button>
    </div>

    <div class="card overflow-hidden">
      <div
        ref="scroller"
        data-testid="week-scroller"
        class="overflow-x-auto no-scrollbar scroll-smooth"
        @scroll.passive="onScrollerScroll"
      >
        <div class="flex flex-col min-w-fit">
          <!-- day header -->
          <div class="grid border-b border-slate-100 dark:border-slate-800" :style="gridStyle">
            <div
              class="sticky left-0 z-10 bg-white px-1 py-2 text-center text-[9px] text-slate-300 dark:bg-slate-900 dark:text-slate-600 select-none"
            >
              时间
            </div>
            <div
              v-for="day in days"
              :key="`head-${day.key}`"
              class="px-1 py-2 text-center"
              :class="[
                day.isMonday ? 'border-l-2 border-slate-300 dark:border-slate-700' : 'border-l border-slate-100 dark:border-slate-800',
                day.isToday ? 'bg-brand-50/60 dark:bg-brand-500/10' : ''
              ]"
            >
              <div v-if="day.isMonday" class="mb-0.5 whitespace-nowrap text-[9px] font-bold text-brand-600 dark:text-brand-400">
                {{ day.weekLabel }}
              </div>
              <p class="text-[11px]" :class="day.isToday ? 'font-semibold text-brand-600 dark:text-brand-400' : 'text-slate-500'">
                {{ day.weekday }}
              </p>
              <p class="text-xs font-semibold">{{ day.dayNum }}</p>
            </div>
          </div>

          <!-- time grid -->
          <div class="grid" :style="gridStyle">
            <!-- sticky so the hour labels stay visible while the week scrolls -->
            <div
              class="sticky left-0 z-10 bg-white dark:bg-slate-900"
              :style="{ height: `${GRID_HEIGHT}px` }"
            >
              <div
                v-for="hour in hours"
                :key="`tick-${hour}`"
                class="absolute right-1.5 -translate-y-1/2 text-[10px] text-slate-400"
                :style="{ top: pct(hour * 60) + '%' }"
              >
                {{ String(hour).padStart(2, '0') }}:00
              </div>

              <!-- 当前时间指示（呼吸闪烁） -->
              <div
                v-if="isNowVisible && hasTodayInView"
                data-testid="current-time-gutter"
                class="pointer-events-none absolute right-1 z-10 -translate-y-1/2 rounded bg-rose-500 px-1 py-0.5 text-[9px] font-bold text-white shadow animate-pulse"
                :style="{ top: `${nowPct}%` }"
              >
                {{ nowLabel }}
              </div>
            </div>

            <div
              v-for="day in days"
              :key="`col-${day.key}`"
              class="relative week-day-col"
              :class="[
                state.weekGridStyle === 'blank'
                  ? (day.isMonday ? 'border-l-2 border-slate-200/80 dark:border-slate-800' : 'border-l border-slate-100/60 dark:border-slate-800/50')
                  : (day.isMonday ? 'border-l-2 border-slate-300 dark:border-slate-700' : 'border-l border-slate-100 dark:border-slate-800'),
                day.isToday ? 'bg-brand-50/40 dark:bg-brand-500/5' : ''
              ]"
              :style="{ height: `${GRID_HEIGHT}px` }"
            >
              <!-- 水平整点与细分参考线：标准网格画整点，细分网格额外画半小时点虚线，空白底隐藏 -->
              <template v-if="state.weekGridStyle !== 'blank'">
                <template v-for="hour in hours" :key="`line-${day.key}-${hour}`">
                  <div
                    class="pointer-events-none absolute inset-x-0 border-t border-slate-100/90 dark:border-slate-800/60"
                    :style="{ top: pct(hour * 60) + '%' }"
                  />
                  <!-- 细分网格底：每半小时（XX:30）补充一条极轻量的点虚线 -->
                  <div
                    v-if="state.weekGridStyle === 'subgrid' && hour < 21"
                    class="pointer-events-none absolute inset-x-0 border-t border-dashed border-slate-100/60 dark:border-slate-800/40"
                    :style="{ top: pct(hour * 60 + 30) + '%' }"
                  />
                </template>
              </template>
              <!-- 当前时间线（仅今天且在 08:00–22:00 内展示，呼吸闪烁） -->
              <div
                v-if="day.isToday && isNowVisible"
                data-testid="current-time-line"
                class="pointer-events-none absolute inset-x-0 z-30 flex items-center animate-pulse"
                :style="{ top: `${nowPct}%` }"
              >
                <div class="-ml-1 h-2 w-2 rounded-full bg-rose-500 shadow-sm shadow-rose-500/50" />
                <div class="h-[2px] flex-1 bg-rose-500 shadow-sm shadow-rose-500/50" />
              </div>

              <template v-for="item in day.items" :key="item.event.id">
                <!-- 有结束时间：一个块（若与 DDL 重叠，加入轮换呼吸动画） -->
                <button
                  v-if="item.end !== null"
                  data-testid="class-block"
                  :data-day="day.key"
                  class="absolute inset-x-0 overflow-hidden rounded-lg border border-brand-200/70 bg-brand-100/80 px-px py-1
                         text-left text-[10px] leading-tight text-brand-900 transition-shadow hover:shadow-md
                         dark:border-brand-500/30 dark:bg-brand-500/20 dark:text-brand-100"
                  :class="[
                    item.event.is_deadline
                      ? 'border-amber-300/80 bg-amber-100/80 text-amber-900 dark:border-amber-400/30 dark:bg-amber-500/20 dark:text-amber-100'
                      : '',
                    item.hasConflict ? 'animate-breathe-alternate' : ''
                  ]"
                  :style="blockStyle(item)"
                  :aria-pressed="selected?.id === item.event.id"
                  @click="selected = selected?.id === item.event.id ? null : item.event"
                >
                  <span class="font-semibold text-[9px] leading-[10px] line-clamp-2">{{ item.event.title }}</span>
                  <span class="block whitespace-nowrap text-[9px] leading-[11px] tracking-tighter opacity-80">
                    {{ timeLabel(item.event.start_time) }}–{{ timeLabel(item.event.end_time) }}
                  </span>
                  <!-- 卡片上加上简短地点（用户要求：不加红色针头，省空间） -->
                  <span
                    v-if="item.event.location"
                    data-testid="class-block-location"
                    class="block truncate text-[8.5px] leading-[10px] font-medium text-brand-700/90 dark:text-brand-300/90"
                    :title="item.event.location"
                  >
                    {{ formatShortLocation(item.event.location) }}
                  </span>
                </button>

                <!-- 没有结束时间（DDL）：精准定位在时间轴上，若与其它 DDL 或课程重叠，依次轮流呼吸亮灭 -->
                <button
                  v-else
                  data-testid="line-event"
                  :data-day="day.key"
                  class="absolute inset-x-0 z-10 px-0 py-2 text-left"
                  :class="item.hasConflict ? 'animate-breathe-alternate' : ''"
                  :style="lineStyle(item)"
                  :aria-pressed="selected?.id === item.event.id"
                  @click="selected = selected?.id === item.event.id ? null : item.event"
                >
                  <span
                    class="absolute inset-x-0 top-2 block h-0 border-t-2 border-dashed"
                    :class="
                      item.event.is_deadline
                        ? 'border-amber-400 dark:border-amber-400/80'
                        : 'border-sky-400 dark:border-sky-400/80'
                    "
                  />
                  <span
                    class="pointer-events-none absolute top-0 left-0 max-w-full truncate rounded-sm bg-white/90 px-0.5
                           text-[9px] leading-[11px] font-medium"
                    :class="
                      item.event.is_deadline
                        ? 'text-amber-700 dark:bg-slate-900/85 dark:text-amber-300'
                        : 'text-sky-700 dark:bg-slate-900/85 dark:text-sky-300'
                    "
                  >
                    {{ item.event.title }}
                  </span>
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 格子里点击弹放大详情卡看全部（老师、周次、节次、备注、地点等） -->
    <ClassDetail :event="selected" @close="selected = null" />

    <section v-if="deadlines.length" data-testid="week-deadlines-section" class="space-y-2">
      <div class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <ListTodo :size="13" />
        <span>7 天内日程</span>
        <span
          v-if="overdueCount > 0"
          class="rounded bg-rose-100 px-1.5 py-0.2 text-[10px] font-semibold text-rose-600 dark:bg-rose-950/40 dark:text-rose-300"
        >
          含 {{ overdueCount }} 项延期
        </span>
        <span class="ml-auto text-[11px] font-normal normal-case text-slate-400">
          共 {{ deadlines.length }} 条
        </span>
      </div>
      <EventCard
        v-for="event in deadlines"
        :key="`ddl-${event.id}`"
        :event="event"
        @toggle="toggleCompleted"
        @remove="removeEvent"
      />
    </section>

    <EmptyState
      v-if="!loading && !classes.length && !deadlines.length"
      message="这一周没有安排，切换到其他周看看。"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, ListTodo, MapPin } from 'lucide-vue-next'
import ClassDetail from '../components/ClassDetail.vue'
import EmptyState from '../components/EmptyState.vue'
import EventCard from '../components/EventCard.vue'
import { api } from '../api'
import { isMobileNativeApp, loadWeekCache, matchesQuery, removeEvent, saveWeekCache, state, toggleCompleted } from '../store'
import { dayKey, dayLabel, isEventEnded, minutesOfDay, periodLabel, timeLabel, todayKey, weekOffsetOf, weekWindow } from '../utils/datetime'

const DAY_START = 8 * 60 // 08:00
const DAY_END = 22 * 60 // 22:00（晚上 11-12 节连着上，最晚到 21:40）
// 上下微微压缩适应手机长屏比例（从 620 降至 540），文字依然留有充足内边距不溢出
const GRID_HEIGHT = 540
/* 没有结束时间的条目（DDL / 只填了开始的自定义日程）画一条横贯整列的线。
   LINE_MINUTES 只是它在「没有 end 时」的兜底高度。 */
const LINE_MINUTES = 30
const hours = Array.from({ length: 14 }, (_, index) => index + 8) // 08..21
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const loading = ref(false)
const events = ref(loadWeekCache())
const selected = ref(null)
const scroller = ref(null)

/* 当前时间线：实时走动，呼吸闪烁 */
const now = ref(new Date())
let nowTimer = null

const nowMinutes = computed(() => {
  const d = now.value
  return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60
})
const isNowVisible = computed(() => nowMinutes.value >= DAY_START && nowMinutes.value <= DAY_END)
const nowPct = computed(() => pct(nowMinutes.value))
const nowLabel = computed(() => {
  const h = String(now.value.getHours()).padStart(2, '0')
  const m = String(now.value.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
})

/* 无极滚动多周构建：从上上周(-2) 到未来第六周(+6)，共 9 周 = 63 天 */
const WEEKS_PAST = 2
const WEEKS_FUTURE = 6
const totalWeeks = WEEKS_PAST + WEEKS_FUTURE + 1

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

const days = computed(() => {
  return multiWeekWindow.value.map((d) => {
    const items = events.value
      .filter(
        (event) =>
          dayKey(event.start_time) === d.key &&
          matchesQuery(event) &&
          // 划掉的 DDL 不占课表
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

const hasTodayInView = computed(() => days.value.some((d) => d.isToday))

const GUTTER = 34
const COL_WIDTH = 54
const gridStyle = computed(() => ({
  gridTemplateColumns: `${GUTTER}px repeat(${days.value.length}, ${COL_WIDTH}px)`,
}))

/* 课表无极滚动实时感知当前视窗居中的周次 */
const centeredWeekOffset = ref(0)
const isCurrentWeekCentered = computed(() => centeredWeekOffset.value === 0)

const currentTeachingWeek = computed(() => {
  const startRaw = state.config?.tju_schedule?.semester?.start_date
  let startDate
  if (startRaw) {
    startDate = new Date(startRaw)
  } else {
    // 默认校历基准
    const now = new Date()
    const year = now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1
    startDate = new Date(year, 7, 31) // 8月31日
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

let scrollRaf = null
function onScrollerScroll() {
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null
    const el = scroller.value
    if (!el) return
    const centerLeft = el.scrollLeft + el.clientWidth / 2 - GUTTER
    const colIndex = Math.floor(centerLeft / COL_WIDTH)
    const clampedIndex = Math.max(0, Math.min(days.value.length - 1, colIndex))
    const centerDay = days.value[clampedIndex]
    if (centerDay && centerDay.weekOffset !== centeredWeekOffset.value) {
      centeredWeekOffset.value = centerDay.weekOffset
    }
  })
}

function scrollWeeks(delta) {
  const el = scroller.value
  if (!el) return
  el.scrollBy({ left: delta * COL_WIDTH * 7, behavior: 'smooth' })
}

function focusToday(behavior = 'smooth') {
  const el = scroller.value
  const index = days.value.findIndex((day) => day.isToday)
  if (!el || index < 0 || !el.clientWidth) return
  const left = GUTTER + index * COL_WIDTH - (el.clientWidth - COL_WIDTH) / 2
  el.scrollTo({ left: Math.max(0, left), behavior })
  centeredWeekOffset.value = 0
}

const classes = computed(() => {
  return events.value.filter(
    (event) => !event.is_deadline && matchesQuery(event),
  )
})

/* 课表下方日程：7 天内日程（包括所有过去延期的未完成任务） */
const deadlines = computed(() => {
  const horizonDate = new Date(Date.now() + 7 * 86400000)
  const horizonKey = dayKey(horizonDate)

  return events.value
    .filter((event) => {
      if (!event.is_deadline || event.status === 'completed') return false
      if (!matchesQuery(event)) return false
      const k = dayKey(event.start_time)
      // 包含过去所有延期的 (k < todayKey) 以及未来 7 天内截止的 (k <= horizonKey)
      return k <= horizonKey
    })
    .sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)))
})

const overdueCount = computed(() => {
  const today = todayKey()
  return deadlines.value.filter((ev) => dayKey(ev.start_time) < today).length
})

onMounted(() => nextTick(() => focusToday('auto')))
watch(
  () => state.view,
  (view) => {
    if (view === 'week') nextTick(() => focusToday('auto'))
  },
)

function formatShortLocation(loc) {
  if (!loc) return ''
  // 简短化地点，去掉括号里的多余描述
  const clean = loc.replace(/\s*[（(][^）)]*[）)]\s*/g, '').trim()
  return clean || loc
}

const pct = (minutes) => {
  const clamped = Math.min(Math.max(minutes, DAY_START), DAY_END)
  return ((clamped - DAY_START) / (DAY_END - DAY_START)) * 100
}

const STACK_STEP_PX = 15
const LINE_PAD_PX = 8

function spansOverlap(a, b) {
  const aEnd = a.end === null ? a.start + LINE_MINUTES : a.end
  const bEnd = b.end === null ? b.start + LINE_MINUTES : b.end
  return a.start < bEnd && b.start < aEnd
}

function layoutItems(items) {
  const sorted = [...items].sort((a, b) => a.start - b.start)
  let cluster = []
  let clusterEnd = -Infinity
  const flush = () => {
    if (!cluster.length) return
    cluster.forEach((item, index) => {
      const priors = cluster.slice(0, index).filter((other) => spansOverlap(other, item))
      item.stack = priors.length ? Math.max(...priors.map((other) => other.stack)) + 1 : 0
    })
    cluster = []
    clusterEnd = -Infinity
  }
  for (const item of sorted) {
    if (cluster.length && item.start >= clusterEnd) flush()
    cluster.push(item)
    clusterEnd = Math.max(clusterEnd, item.end === null ? item.start + LINE_MINUTES : item.end)
  }
  flush()

  // 针对 DDL 与其它 DDL、以及 DDL 与课程之间的空间重叠关系进行分组计算：
  // 1. DDL 之间：时间在 ±15 分钟内视为重叠；
  // 2. DDL 与课程之间：若 DDL 的截止时间落在某节课的 [start - 5, end + 5] 分钟区间内，
  //    则该 DDL 与该课程共享呼吸交替周期，依次轮流呼吸亮灭。
  const ddlItems = sorted.filter((it) => it.end === null)
  const classItems = sorted.filter((it) => it.end !== null)

  ddlItems.forEach((ddl) => {
    // 找出与当前 DDL 时间重叠的其它 DDL
    const overlapDdls = ddlItems.filter((other) => Math.abs(other.start - ddl.start) <= 15)
    // 找出与当前 DDL 在时间轴上穿插的课程
    const overlapClasses = classItems.filter((c) => {
      const cStart = Math.max(c.start, DAY_START)
      const cEnd = c.end !== null ? Math.min(c.end, DAY_END) : cStart + LINE_MINUTES
      return ddl.start >= cStart - 8 && ddl.start <= cEnd + 8
    })

    // 构建该冲突区域内的全部轮换实体列表（优先排课程，再排各个 DDL）
    const allColliding = [...new Set([...overlapClasses, ...overlapDdls])]
    if (allColliding.length > 1) {
      const groupSize = allColliding.length
      const myIndex = allColliding.indexOf(ddl)
      ddl.hasConflict = true
      ddl.overlapCycleSize = groupSize
      ddl.overlapCycleIndex = myIndex >= 0 ? myIndex : 0

      // 同时给冲突的课程打上标记与轮换索引
      overlapClasses.forEach((c) => {
        const cIndex = allColliding.indexOf(c)
        c.hasConflict = true
        c.overlapCycleSize = Math.max(c.overlapCycleSize || 0, groupSize)
        if (c.overlapCycleIndex === undefined) {
          c.overlapCycleIndex = cIndex >= 0 ? cIndex : 0
        }
      })
    } else {
      ddl.hasConflict = false
      ddl.overlapCycleSize = 1
      ddl.overlapCycleIndex = 0
    }
  })

  return sorted
}

function blockStyle(item) {
  const startMin = Math.min(Math.max(item.start, DAY_START), DAY_END)
  let endMin =
    item.end === null ? startMin + LINE_MINUTES : Math.min(Math.max(item.end, DAY_START), DAY_END)
  if (endMin <= startMin) endMin = Math.min(startMin + LINE_MINUTES, DAY_END)
  const height = Math.max(3.4, ((endMin - startMin) / (DAY_END - DAY_START)) * 100)
  const push = (item.stack || 0) * STACK_STEP_PX

  const style = {
    top: `calc(${pct(item.start)}% + ${push}px)`,
    height: `${height}%`,
  }

  // 若与 DDL 冲突，参与轮流呼吸交替，计算对应的错位延迟
  if (item.hasConflict && item.overlapCycleSize > 1) {
    const cycleDuration = 4.0
    const delaySec = ((item.overlapCycleIndex || 0) * (cycleDuration / item.overlapCycleSize)).toFixed(2)
    style.animationDelay = `${delaySec}s`
    style.zIndex = 5 + (item.overlapCycleIndex || 0)
  }

  return style
}

function lineStyle(item) {
  // DDL 严格定位在真实时间轴位置上（根据其具体分钟数计算百分比）
  const topPct = pct(item.start)
  const style = {
    top: `${topPct}%`,
  }

  // 若与其它 DDL 或课程重叠，计算均匀错位延迟，依次轮流呼吸亮灭
  if (item.hasConflict && item.overlapCycleSize > 1) {
    const cycleDuration = 4.0
    const delaySec = ((item.overlapCycleIndex || 0) * (cycleDuration / item.overlapCycleSize)).toFixed(2)
    style.animationDelay = `${delaySec}s`
    style.zIndex = 10 + (item.overlapCycleIndex || 0)
  } else {
    style.zIndex = 10
  }

  return style
}

async function loadWeek(force = false) {
  // 如果本地已经有持久化课表缓存，且属于移动端环境，且非主动强制刷新，优先保留已有数据
  const isMobile = isMobileNativeApp()
  if (!force && isMobile && events.value && events.value.length > 0) {
    return
  }

  if (!events.value || events.value.length === 0) {
    loading.value = true
  }
  try {
    const list = multiWeekWindow.value
    if (!list.length) return
    const start = list[0].key
    const end = list[list.length - 1].key
    const payload = await api.events({ start_date: start, end_date: end, limit: 1200 })
    events.value = payload.items || []
    saveWeekCache(events.value)
  } catch (error) {
    if (!events.value || events.value.length === 0) {
      events.value = []
      state.error = error.message || '加载失败'
    }
  } finally {
    loading.value = false
  }
}

/**
 * 核心联动同步：
 * 1. 当用户在日程页创建、修改、删除或划掉日程时，立刻在本地同步响应式变更到课表；
 * 2. 避免因为 loadWeek() 中 isMobile 缓存阻断导致周课表数据迟迟不刷新的问题；
 * 3. 彻底防左右脑互搏：若 globalEvents 发生删除（元素减少），必须严格剔除，不能用 currentList 盲目逆向补充复活。
 */
watch(
  () => state.events,
  (newGlobalEvents) => {
    if (!Array.isArray(newGlobalEvents)) return
    const globalIds = new Set(newGlobalEvents.map((e) => e.id))
    const currentList = Array.isArray(events.value) ? events.value : []
    
    // 只保留：当前全局列表中仍在的项目 + 属于非个人自定义课程（即天大教务自带课程，日程页可能未全量拉取）
    const merged = [
      ...newGlobalEvents,
      ...currentList.filter((item) => !globalIds.has(item.id) && item.source === 'tju_schedule'),
    ]
    events.value = merged
    saveWeekCache(events.value)
  },
  { deep: true },
)

watch(() => state.lastUpdated, () => loadWeek(true))
onMounted(() => {
  loadWeek()
  nowTimer = setInterval(() => {
    now.value = new Date()
  }, 30000)
})
onUnmounted(() => {
  if (nowTimer) clearInterval(nowTimer)
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
})
</script>
