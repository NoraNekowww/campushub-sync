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

    <!-- 按日期分组的历史日程 -->
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
import { dayLabel, isEventEnded } from '../utils/datetime'

/**
 * 历史完成过的所有日程：
 * 1. 过滤掉天大课表自带课程（event.source === 'tju_schedule'），只归档个人待办与自定义日程；
 * 2. 状态为 completed 的日程 / 待办，或者已经自然结束的个人自定义活动；
 * 3. 排序逻辑：优先显示最近的（降序倒排）。
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
      // 优先按结束时间（或开始时间）倒序，最近完成/结束的排最前
      const tA = new Date(a.end_time || a.start_time).getTime() || 0
      const tB = new Date(b.end_time || b.start_time).getTime() || 0
      return tB - tA
    })
})

const groups = computed(() => {
  // groupByDay 保持降序倒排（最近的日期在最上方）
  const buckets = new Map()
  completedEvents.value.forEach((event) => {
    // 优先采用 end_time 反映「完成/下课」日期，若无则使用 start_time
    const refTime = event.end_time || event.start_time
    const when = refTime ? String(refTime).slice(0, 10) : ''
    if (!when) return
    if (!buckets.has(when)) {
      buckets.set(when, { key: when, label: dayLabel(refTime), events: [] })
    }
    buckets.get(when).events.push(event)
  })
  // 日期从近到远排序（降序：今天/昨天在最前）
  return [...buckets.values()]
    .sort((a, b) => b.key.localeCompare(a.key))
    .map((bucket) => ({
      ...bucket,
      // 组内同样按完成/结束时间倒序排列（晚完成的在最前）
      events: bucket.events.sort((a, b) => {
        const tA = new Date(a.end_time || a.start_time).getTime() || 0
        const tB = new Date(b.end_time || b.start_time).getTime() || 0
        return tB - tA
      }),
    }))
})
</script>
