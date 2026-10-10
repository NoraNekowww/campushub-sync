<template>
  <div class="space-y-4 px-4">
    <!-- overdue deadlines stay pinned at the top, whatever the day grouping says -->
    <section v-if="overdue.length" class="space-y-2">
      <header class="flex items-center gap-2 pt-1 text-xs font-semibold uppercase tracking-wide text-rose-500">
        <AlertTriangle :size="13" /> 已逾期
        <span class="chip border-transparent bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300">
          {{ overdue.length }}
        </span>
      </header>
      <EventCard
        v-for="event in overdue"
        :key="`overdue-${event.id}`"
        :event="event"
        @toggle="toggleCompleted"
        @remove="removeEvent"
      />
    </section>

    <SkeletonList v-if="state.loading && !groups.length" :rows="5" />

    <section
      v-for="group in groups"
      :key="group.key"
      class="space-y-2"
      data-testid="day-group"
      :data-day="group.key"
    >
      <header class="sticky top-[112px] z-10 -mx-4 flex items-center gap-2 bg-slate-100/90 px-4 py-1.5
                     text-xs font-semibold uppercase tracking-wide text-slate-500 backdrop-blur
                     dark:bg-slate-900/90 dark:text-slate-400">
        <span :class="group.key === today ? 'text-brand-600 dark:text-brand-400' : ''">
          {{ group.label }}
        </span>
        <span v-if="group.key === today" class="chip border-transparent bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300">
          今天
        </span>
        <span class="ml-auto font-normal normal-case tracking-normal text-slate-400">
          {{ group.events.length }} 条
        </span>
      </header>
      <EventCard
        v-for="event in group.events"
        :key="event.id"
        :event="event"
        @toggle="toggleCompleted"
        @remove="removeEvent"
      />
    </section>

    <EmptyState
      v-if="!state.loading && !groups.length && !overdue.length"
      :kind="emptyKind"
      :message="emptyMessage"
    >
      <button v-if="state.authRequired" class="btn-primary mt-1" @click="state.view = 'settings'">
        <KeyRound :size="14" /> 去设置令牌
      </button>
      <button v-else-if="!state.online" class="btn-ghost mt-1" @click="refresh()">
        <RefreshCw :size="14" /> 重试
      </button>
    </EmptyState>

    <p v-if="state.error" class="pb-2 text-center text-xs text-rose-500">{{ state.error }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { AlertTriangle, KeyRound, RefreshCw } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import EventCard from '../components/EventCard.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { filterEvents, notify, refresh, removeEvent, state, toggleCompleted } from '../store'
import { groupByDay, todayKey } from '../utils/datetime'

const today = todayKey()
const visible = computed(() => filterEvents())

const now = () => Date.now()
const overdue = computed(() =>
  visible.value.filter(
    (event) =>
      event.is_deadline &&
      event.status !== 'completed' &&
      new Date(event.start_time).getTime() < now() &&
      String(event.start_time).slice(0, 10) !== today,
  ),
)

const groups = computed(() => {
  const overdueIds = new Set(overdue.value.map((event) => event.id))
  return groupByDay(visible.value.filter((event) => !overdueIds.has(event.id)))
})

const emptyKind = computed(() => (state.authRequired ? 'auth' : state.online ? 'empty' : 'offline'))
const emptyMessage = computed(() => {
  if (state.authRequired) return '后端已开启访问保护，填写 ADMIN_TOKEN 后即可同步与修改。'
  if (!state.online) return '正在显示离线缓存，恢复网络后会自动刷新。'
  return '没有课程，也没有临近的 DDL。点右上角同步看看。'
})

/* 触摸屏上「卡片可以左右滑开删掉」不是自明的，第一次用提示一次。 */
onMounted(() => {
  if (!window.matchMedia?.('(pointer: coarse)')?.matches) return
  try {
    if (localStorage.getItem('campushub.swipe-hint')) return
    localStorage.setItem('campushub.swipe-hint', '1')
  } catch {
    return
  }
  setTimeout(() => notify('左滑或右滑日程卡片，可以把它删掉', 'info', { duration: 5000 }), 1200)
})
</script>
