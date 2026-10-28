<template>
  <div class="space-y-4 px-4 pb-12">
    <!-- 顶部统计与操作栏 -->
    <header class="flex flex-wrap items-center justify-between gap-3 pt-1">
      <div>
        <h2 class="text-base font-semibold text-slate-800 dark:text-slate-100 flex items-center gap-2">
          <History :size="18" class="text-brand-600 dark:text-brand-400" />
          <span>历史完成归档</span>
        </h2>
        <p class="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
          共记录 {{ completedEvents.length }} 条已完结的日程与待办
        </p>
      </div>

      <div class="flex items-center gap-2">
        <label class="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 cursor-pointer">
          <Filter :size="13" />
          <select
            v-model="filterSource"
            class="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none dark:border-slate-800 dark:bg-slate-900"
          >
            <option value="all">全部来源</option>
            <option value="custom">个人日程 / 待办</option>
            <option value="tju_schedule">课程记录</option>
          </select>
        </label>
      </div>
    </header>

    <!-- 骨架屏加载 -->
    <SkeletonList v-if="state.loading && !filteredCompleted.length" :rows="4" />

    <!-- 空状态 -->
    <div
      v-else-if="!filteredCompleted.length"
      class="card flex flex-col items-center justify-center p-12 text-center text-slate-400 dark:text-slate-500"
    >
      <CheckCircle2 :size="36" class="mb-2.5 opacity-30 text-emerald-500" />
      <p class="text-sm font-medium">暂无已完成的历史日程</p>
      <p class="text-xs opacity-75 mt-1">在日程列表勾选完成的待办和已上完的课程会归档在此处</p>
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
        @toggle="toggleCompleted"
        @remove="removeEvent"
      />
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { CheckCircle2, Filter, History } from 'lucide-vue-next'
import EventCard from '../components/EventCard.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { removeEvent, state, toggleCompleted } from '../store'
import { groupByDay, isEventEnded } from '../utils/datetime'

const filterSource = ref('all')

/**
 * 历史完成过的所有日程：
 * 1. 状态为 completed 的日程 / 待办；
 * 2. 或者已经自然结束（已上完）的课程/日程活动。
 */
const completedEvents = computed(() => {
  const nowTs = Date.now()
  return (state.events || []).filter((event) => {
    const isTicked = event.status === 'completed'
    const isEnded = isEventEnded(event, nowTs)
    return isTicked || isEnded
  })
})

const filteredCompleted = computed(() => {
  return completedEvents.value.filter((event) => {
    if (filterSource.value !== 'all' && event.source !== filterSource.value) return false
    return true
  })
})

const groups = computed(() => {
  return groupByDay(filteredCompleted.value)
})
</script>
