<template>
  <div class="space-y-4 px-4 pb-12">
    <!-- 顶部统计栏（纯粹归档，去除非必要下拉） -->
    <header class="flex flex-wrap items-center justify-between gap-3 pt-1">
      <div>
        <h2 class="text-base font-semibold text-slate-800 dark:text-slate-100 flex items-center gap-2">
          <History :size="18" class="text-brand-600 dark:text-brand-400" />
          <span>历史完成归档</span>
        </h2>
        <p class="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
          共记录 {{ completedEvents.length }} 条已完结的个人日程与待办
        </p>
      </div>
    </header>

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

    <!-- 按日期分组的历史日程（全量显示，按日期与时间严格倒序排列） -->
    <section
      v-for="group in groups"
      :key="group.key"
      class="space-y-2"
      data-testid="history-day-group"
    >
      <header
        class="sticky top-[49px] z-10 -mx-4 flex items-center gap-2 bg-slate-100/95 px-4 py-1.5
               text-xs font-semibold uppercase tracking-wide text-slate-500
               dark:bg-slate-900/95 dark:text-slate-400"
      >
        <span>{{ group.label }}</span>
        <span class="ml-auto font-normal normal-case tracking-normal text-slate-400">
          {{ group.events.length }} 条
        </span>
      </header>

      <EventCard
        v-for="event in group.events"
        :key="`hist-${event.id}`"
        :event="event"
        :allow-delete="false"
        :show-priority="false"
        @toggle="toggleCompleted"
      />
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { CheckCircle2, History } from 'lucide-vue-next'
import EventCard from '../components/EventCard.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { state, toggleCompleted } from '../store'
import { dayDiff, dayLabel, isEventEnded, todayKey } from '../utils/datetime'

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
</script>
