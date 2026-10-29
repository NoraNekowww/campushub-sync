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
      <header class="sticky top-[49px] z-10 -mx-4 flex items-center gap-2 bg-slate-100/95 px-4 py-1.5
                     text-xs font-semibold uppercase tracking-wide text-slate-500
                     dark:bg-slate-900/95 dark:text-slate-400">
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

    <!-- 无日程且未接入时：显示接入卡片 -->
    <section
      v-if="!state.loading && !groups.length && !overdue.length && !hasConnected && !state.authRequired"
      class="card space-y-4 p-5 animate-fade-up"
      data-testid="onboarding-card-in-agenda"
    >
      <header class="space-y-1">
        <div class="flex items-center gap-2 text-brand-600 dark:text-brand-400 font-semibold text-sm">
          <Sparkles :size="16" />
          <span>接入你的日程与课表</span>
        </div>
        <p class="text-xs text-slate-500 dark:text-slate-400">
          当前还没有日程。连接学校教务或待办账号，课程和 DDL 会自动同步进来。
        </p>
      </header>

      <div class="space-y-2.5">
        <div class="flex flex-col justify-between rounded-xl border border-slate-200/80 bg-slate-50/60 p-3.5 dark:border-slate-800 dark:bg-slate-800/40">
          <div class="space-y-1">
            <div class="flex items-center gap-1.5 font-medium text-xs text-slate-800 dark:text-slate-200">
              <GraduationCap :size="15" class="text-brand-600 dark:text-brand-400" />
              <span>天津大学教务系统</span>
            </div>
            <p class="text-[11px] text-slate-500 dark:text-slate-400">
              一键同步全学期课表、教室地点与节次
            </p>
          </div>
          <button class="btn-primary !py-1 text-xs mt-3 w-full justify-center" @click="goToSection('tju-section')">
            去连接教务
          </button>
        </div>
      </div>

      <div class="pt-1 flex items-center justify-between text-xs text-slate-400 border-t border-slate-100 dark:border-slate-800">
        <span>或者手动添加个人安排：</span>
        <button class="btn-ghost !py-1 text-xs text-brand-600 dark:text-brand-400" @click="openCustomEditor()">
          <Plus :size="13" /> 添加自定义日程
        </button>
      </div>
    </section>

    <!-- 已接入但当前无日程时：显示常规空状态 -->
    <EmptyState
      v-else-if="!state.loading && !groups.length && !overdue.length"
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
import { AlertTriangle, GraduationCap, KeyRound, Plus, RefreshCw, Sparkles } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import EventCard from '../components/EventCard.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { filterEvents, notify, openCustomEditor, refresh, removeEvent, state, toggleCompleted } from '../store'
import { groupByDay, todayKey, dayKey } from '../utils/datetime'

const today = todayKey()
const visible = computed(() => filterEvents())

const overdue = computed(() =>
  visible.value.filter(
    (event) =>
      event.is_deadline &&
      event.status !== 'completed' &&
      dayKey(event.start_time) < today,
  ),
)

const groups = computed(() => {
  const overdueIds = new Set(overdue.value.map((event) => event.id))
  return groupByDay(visible.value.filter((event) => !overdueIds.has(event.id)))
})

const hasConnected = computed(() => {
  // 如果本地有课表或日程，说明已经处于正常使用状态，绝不呈现初次接入卡片
  if (state.events && state.events.length > 0) return true
  const connectors = state.status?.connectors || []
  const tjuOk = connectors.find((item) => item.name === 'tju_schedule')?.ok
  let hasTjuToken = false
  try {
    hasTjuToken = Boolean(localStorage.getItem('campushub.tju-token'))
  } catch {
    hasTjuToken = false
  }
  return Boolean(tjuOk || hasTjuToken)
})

function goToSection(anchorId) {
  state.view = 'settings'
  setTimeout(() => {
    const el = document.getElementById(anchorId)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 100)
}

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
