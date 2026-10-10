<template>
  <div class="space-y-4 px-4">
    <div class="flex items-center gap-2">
      <button class="btn-ghost !px-2" title="上一周" @click="shift(-1)">
        <ChevronLeft :size="16" />
      </button>
      <div class="flex-1 text-center">
        <p class="text-sm font-semibold">{{ rangeLabel }}</p>
        <p class="text-[11px] text-slate-500 dark:text-slate-400">
          {{ classes.length }} 节课 · {{ deadlines.length }} 个 DDL
          <span v-if="loading"> · 加载中…</span>
        </p>
      </div>
      <button class="btn-ghost !px-2" title="下一周" @click="shift(1)">
        <ChevronRight :size="16" />
      </button>
    </div>

    <div class="card overflow-hidden">
      <div ref="scroller" data-testid="week-scroller" class="overflow-x-auto no-scrollbar">
        <div class="min-w-[600px]">
          <!-- day header -->
          <div class="grid border-b border-slate-100 dark:border-slate-800" :style="gridStyle">
            <div
              class="sticky left-0 z-20 bg-white px-1 py-2 text-center text-[10px] text-slate-400 dark:bg-slate-900"
            >
              时间
            </div>
            <div
              v-for="day in days"
              :key="`head-${day.key}`"
              class="border-l border-slate-100 px-1 py-2 text-center dark:border-slate-800"
              :class="day.isToday ? 'bg-brand-50/60 dark:bg-brand-500/10' : ''"
            >
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
            </div>

            <div
              v-for="day in days"
              :key="`col-${day.key}`"
              class="relative border-l border-slate-100 dark:border-slate-800"
              :class="day.isToday ? 'bg-brand-50/40 dark:bg-brand-500/5' : ''"
              :style="{ height: `${GRID_HEIGHT}px` }"
            >
              <div
                v-for="hour in hours"
                :key="`line-${hour}`"
                class="absolute inset-x-0 border-t border-dashed border-slate-100 dark:border-slate-800/80"
                :style="{ top: pct(hour * 60) + '%' }"
              />
              <button
                v-for="block in day.blocks"
                :key="block.id"
                data-testid="class-block"
                :data-day="day.key"
                class="absolute inset-x-0.5 overflow-hidden rounded-lg border border-brand-200/70 bg-brand-100/80 px-1.5 py-1
                       text-left text-[10px] leading-tight text-brand-900 transition-shadow hover:shadow-md
                       dark:border-brand-500/30 dark:bg-brand-500/20 dark:text-brand-100"
                :style="blockStyle(block)"
                @click="selected = block"
              >
                <span class="block truncate font-semibold">{{ block.title }}</span>
                <span class="block truncate opacity-80">
                  {{ timeLabel(block.start_time) }}–{{ timeLabel(block.end_time) }}
                </span>
                <span v-if="block.location" class="block truncate opacity-70">{{ block.location }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <section v-if="deadlines.length" class="space-y-2">
      <h2 class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <ListTodo :size="13" /> 本周截止
      </h2>
      <EventCard
        v-for="event in deadlines"
        :key="`ddl-${event.id}`"
        :event="event"
        @toggle="toggleCompleted"
      />
    </section>

    <EmptyState
      v-if="!loading && !classes.length && !deadlines.length"
      message="这一周没有安排，切换到其他周看看。"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, ListTodo } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import EventCard from '../components/EventCard.vue'
import { api } from '../api'
import { state, toggleCompleted } from '../store'
import { dayKey, minutesOfDay, timeLabel, todayKey, weekWindow } from '../utils/datetime'

const DAY_START = 8 * 60 // 08:00
const DAY_END = 21 * 60 + 30 // 21:30
const GRID_HEIGHT = 620
const hours = Array.from({ length: 14 }, (_, index) => index + 8) // 08..21
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const offset = ref(0)
const loading = ref(false)
const events = ref([])
const selected = ref(null)
const scroller = ref(null)

const gridStyle = { gridTemplateColumns: '42px repeat(7, minmax(78px, 1fr))' }

const window_ = computed(() => {
  const anchor = new Date(Date.now() + offset.value * 7 * 86400000)
  return weekWindow(anchor)
})

const days = computed(() =>
  window_.value.days.map((key, index) => {
    const blocks = events.value
      .filter((event) => !event.is_deadline && dayKey(event.start_time) === key)
      .sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)))
    return {
      key,
      weekday: WEEKDAYS[index],
      dayNum: Number(key.slice(8, 10)),
      isToday: key === todayKey(),
      blocks,
    }
  }),
)

const classes = computed(() => events.value.filter((event) => !event.is_deadline))
const deadlines = computed(() =>
  events.value
    .filter((event) => event.is_deadline)
    .sort((a, b) => String(a.start_time).localeCompare(String(b.start_time))),
)

const GUTTER = 42 // width of the time-label column, see gridStyle above

/**
 * The grid is wider than a phone, so on a Saturday you would stare at an empty
 * Monday. Centre today's column whenever the view appears or the week changes.
 * Declared after `days` on purpose — `watch` evaluates its source eagerly.
 */
function focusToday(behavior = 'auto') {
  const el = scroller.value
  const index = days.value.findIndex((day) => day.isToday)
  if (!el || index < 0 || !el.clientWidth) return
  const column = (el.scrollWidth - GUTTER) / 7
  const left = GUTTER + index * column - (el.clientWidth - column) / 2
  el.scrollTo({ left: Math.max(0, left), behavior })
}

onMounted(() => nextTick(() => focusToday()))
watch(
  () => state.view,
  (view) => {
    if (view === 'week') nextTick(() => focusToday())
  },
)
watch(
  () => days.value.map((day) => day.key).join(),
  () => focusToday('smooth'),
)

const rangeLabel = computed(() => {
  const { start, end } = window_.value
  const fmt = (key) => `${Number(key.slice(5, 7))}月${Number(key.slice(8, 10))}日`
  const weeks = offset.value === 0 ? '本周' : offset.value === 1 ? '下周' : offset.value === -1 ? '上周' : `第 ${offset.value > 0 ? '+' : ''}${offset.value} 周`
  return `${weeks} · ${fmt(start)} – ${fmt(end)}`
})

const pct = (minutes) => {
  const clamped = Math.min(Math.max(minutes, DAY_START), DAY_END)
  return ((clamped - DAY_START) / (DAY_END - DAY_START)) * 100
}

function blockStyle(block) {
  const rawStart = minutesOfDay(block.start_time)
  const rawEnd = minutesOfDay(block.end_time) ?? (rawStart === null ? null : rawStart + 45)
  if (rawStart === null) return { display: 'none' }
  const startMin = Math.min(Math.max(rawStart, DAY_START), DAY_END)
  let endMin = rawEnd === null ? startMin + 45 : Math.min(Math.max(rawEnd, DAY_START), DAY_END)
  if (endMin <= startMin) endMin = Math.min(startMin + 45, DAY_END)
  const top = ((startMin - DAY_START) / (DAY_END - DAY_START)) * 100
  const height = Math.max(3.4, ((endMin - startMin) / (DAY_END - DAY_START)) * 100)
  return { top: `${top}%`, height: `${height}%` }
}

async function loadWeek() {
  loading.value = true
  try {
    const { start, end } = window_.value
    const payload = await api.events({ start_date: start, end_date: end, limit: 800 })
    events.value = payload.items || []
  } catch (error) {
    events.value = []
    state.error = error.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function shift(delta) {
  offset.value = Math.max(-1, Math.min(8, offset.value + delta))
}

watch(offset, loadWeek)
watch(() => state.lastUpdated, loadWeek)
onMounted(loadWeek)
</script>
