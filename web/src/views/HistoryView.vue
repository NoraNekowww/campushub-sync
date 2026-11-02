<template>
  <div class="space-y-4 px-4 pb-12 pt-1">
    <!-- 骨架屏加载 -->
    <SkeletonList v-if="state.loading && !completedEvents.length" :rows="4" />

    <!-- 空状态 -->
    <div
      v-else-if="!completedEvents.length"
      class="card flex flex-col items-center justify-center p-12 text-center text-slate-400 dark:text-slate-500"
    >
      <CheckCircle2 :size="36" class="mb-2.5 opacity-30 text-emerald-500" />
      <p class="text-sm font-medium">暂无已完成的历史日程</p>
      <p class="text-xs opacity-75 mt-1">在日程列表勾选完成的个人待办和日程会在此倒序归档</p>
    </div>

    <!-- 按日期分组的历史日程（动态分批按需渲染，从近到久倒序排列） -->
    <section
      v-for="group in displayedGroups"
      :key="group.key"
      class="space-y-2"
      data-testid="history-day-group"
    >
      <header
        class="sticky top-[41px] z-10 mx-0 my-1 flex items-center gap-2 rounded-xl
               border border-white/60 bg-white/50 px-3.5 py-1.5 text-xs font-bold
               uppercase tracking-wide text-slate-900 shadow-xs backdrop-blur-md
               dark:border-white/10 dark:bg-slate-900/50 dark:text-slate-100"
      >
        <span>{{ group.label }}</span>
        <span class="ml-auto font-semibold normal-case tracking-normal text-slate-600 dark:text-slate-300">
          {{ group.events.length }} 条
        </span>
      </header>

      <EventCard
        v-for="event in group.events"
        :key="`hist-${event.id}`"
        :event="event"
        :allow-delete="true"
        :show-priority="false"
        @toggle="toggleCompleted"
        @remove="removeEvent"
      />
    </section>

    <!-- 动态按需加载触底探针与加载更多 -->
    <div
      v-if="hasMoreGroups"
      ref="sentinelEl"
      class="flex justify-center py-4 text-xs text-slate-500 dark:text-slate-400"
    >
      <button class="btn-ghost !py-1 text-xs" @click="loadMoreGroups">
        加载更多历史归档 (已显示 {{ displayedGroups.length }} / {{ groups.length }} 组)
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CheckCircle2, History } from 'lucide-vue-next'
import EventCard from '../components/EventCard.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { fetchHistoryEvents, removeEvent, state, toggleCompleted } from '../store'
import { dayDiff, dayLabel, isEventEnded, todayKey } from '../utils/datetime'

// 进入历史归档页面时主动从服务器全量拉取已完成归档记录，确保换设备/清缓存后 100% 留存不丢失
onMounted(() => {
  fetchHistoryEvents()
})

/**
 * 历史完成过的所有日程：
 * 1. 彻底排除天大课表自带课程（event.source === 'tju_schedule'），只归档个人待办与自定义日程；
 * 2. 状态为 completed 的日程 / 待办，或者已经自然结束的个人自定义活动；
 * 3. 严格按从近到久排序（今天、明天、后天、更远）。
 */
const completedEvents = computed(() => {
  const nowTs = Date.now()
  return (state.events || [])
    .filter((event) => {
      // 核心：彻底排除天大课表自带课程
      if (event.source === 'tju_schedule') return false

      const isTicked = event.status === 'completed'
      const isEnded = isEventEnded(event, nowTs)
      return isTicked || isEnded
    })
    .sort((a, b) => {
      const tA = new Date(a.end_time || a.start_time).getTime() || 0
      const tB = new Date(b.end_time || b.start_time).getTime() || 0
      return tB - tA
    })
})

function getHistoryGroupLabel(when, refTime, diff) {
  if (diff === 0) return '今天'
  if (diff === 1) return '明天'
  if (diff === 2) return '后天'
  if (diff > 2) return `更远 · ${dayLabel(refTime)}`
  if (diff === -1) return '昨天'
  if (diff === -2) return '前天'
  return `更早 · ${dayLabel(refTime)}`
}

function getGroupSortRank(diff) {
  // 严格按今天 (0) -> 明天 (1) -> 后天 (2) -> 更远 (10+diff) 从近到久排序
  if (diff === 0) return 0
  if (diff === 1) return 1
  if (diff === 2) return 2
  if (diff > 2) return 10 + diff
  // 过去完成的按离今天最近排序（昨天 -> 前天 -> 更早）
  if (diff < 0) return 1000 + Math.abs(diff)
  return 9999
}

const groups = computed(() => {
  const today = todayKey()
  const buckets = new Map()

  completedEvents.value.forEach((event) => {
    const refTime = event.end_time || event.start_time
    const when = refTime ? String(refTime).slice(0, 10) : ''
    if (!when) return
    if (!buckets.has(when)) {
      const diff = dayDiff(when, today)
      buckets.set(when, {
        key: when,
        diff,
        rank: getGroupSortRank(diff),
        label: getHistoryGroupLabel(when, refTime, diff),
        events: []
      })
    }
    buckets.get(when).events.push(event)
  })

  // 严格按：今天，明天，后天，更远 从近到久排序
  return [...buckets.values()]
    .sort((a, b) => a.rank - b.rank)
    .map((bucket) => ({
      ...bucket,
      // 组内同样按完成/结束时间倒序排列（最新完成的在最前）
      events: bucket.events.sort((a, b) => {
        const tA = new Date(a.end_time || a.start_time).getTime() || 0
        const tB = new Date(b.end_time || b.start_time).getTime() || 0
        return tB - tA
      }),
    }))
})

/* ----------------------------------------------------------- 动态按需渲染逻辑 */
const renderedGroupLimit = ref(8)
const displayedGroups = computed(() => groups.value.slice(0, renderedGroupLimit.value))
const hasMoreGroups = computed(() => displayedGroups.value.length < groups.value.length)

function loadMoreGroups() {
  renderedGroupLimit.value += 8
}

const sentinelEl = ref(null)
let observer = null

function setupObserver() {
  if (observer) {
    observer.disconnect()
    observer = null
  }
  if (!sentinelEl.value || !hasMoreGroups.value) return
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) {
        loadMoreGroups()
      }
    },
    { rootMargin: '240px' },
  )
  observer.observe(sentinelEl.value)
}

watch([sentinelEl, hasMoreGroups], () => {
  setupObserver()
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})
</script>
