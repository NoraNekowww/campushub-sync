<template>
  <div class="space-y-4 px-4">
    <!-- 列表模式切换：仅 DDL / 仅日程 / 含课表 / 历史归档（窄屏可横向滑动） -->
    <div class="space-y-1 pt-1">
      <div
        class="no-scrollbar flex items-center gap-0.5 overflow-x-auto rounded-xl border border-slate-200/60 bg-slate-100/90 p-0.5 text-xs shadow-2xs backdrop-blur-md dark:border-slate-700/60 dark:bg-slate-800/80"
        role="tablist"
        aria-label="日程展示模式"
      >
        <button
          v-for="tab in AGENDA_TABS"
          :key="tab.key"
          type="button"
          role="tab"
          :aria-selected="agendaMode === tab.key"
          class="shrink-0 rounded-lg px-2.5 py-1 font-medium transition-all"
          :class="
            agendaMode === tab.key
              ? 'bg-white text-brand-600 shadow-xs dark:bg-slate-700 dark:text-brand-300'
              : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
          "
          @click="setAgendaMode(tab.key)"
        >
          {{ tab.label }}
        </button>
      </div>

      <p class="text-right text-[11px] font-medium text-slate-500 dark:text-slate-400">
        {{ countLabel }}
      </p>
    </div>

    <!-- 历史归档：从底部导航挪进日程栏，与「仅 DDL」这些筛选并列 -->
    <ArchiveList v-if="agendaMode === 'archive'" />

    <!-- overdue deadlines stay pinned at the top, whatever the day grouping says -->
    <section v-if="overdue.length && agendaMode !== 'archive'" class="space-y-2">
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

    <SkeletonList v-if="state.loading && !groups.length && agendaMode !== 'archive'" :rows="5" />

    <section
      v-for="group in renderedGroups"
      :key="group.key"
      class="space-y-2"
      data-testid="day-group"
      :data-day="group.key"
    >
      <header class="sticky top-[41px] z-10 mx-0 my-1 flex items-center gap-2 rounded-xl
                     border border-white/60 bg-white/50 px-3.5 py-1.5 text-xs font-semibold
                     uppercase tracking-wide text-slate-700 shadow-xs backdrop-blur-md
                     dark:border-white/10 dark:bg-slate-900/50 dark:text-slate-300">
        <span :class="group.key === today ? 'text-brand-600 dark:text-brand-400 font-bold' : ''">
          {{ group.label }}
        </span>
        <span class="ml-auto font-normal normal-case tracking-normal text-slate-500 dark:text-slate-400">
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

    <!-- 动态按需加载：滚动触底自动追加后续日程批次，避免数百张卡片同时进入 DOM 造成卡顿 -->
    <div
      v-if="hasMoreGroups && agendaMode !== 'archive'"
      ref="sentinelEl"
      class="flex justify-center py-3 text-xs text-slate-500 dark:text-slate-400"
    >
      <button class="btn-ghost !py-1 text-xs" @click="loadMoreGroups">
        加载更多日程 (已显示 {{ displayedGroups.length }} / {{ groups.length }} 天)
      </button>
    </div>

    <!-- 无日程且未接入时：显示接入卡片 -->
    <section
      v-if="!state.loading && !groups.length && !overdue.length && !hasConnected && !state.authRequired && agendaMode !== 'archive'"
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
      v-else-if="!state.loading && !groups.length && !overdue.length && agendaMode !== 'archive'"
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AlertTriangle, GraduationCap, KeyRound, Plus, RefreshCw, Sparkles } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import ArchiveList from '../components/ArchiveList.vue'
import EventCard from '../components/EventCard.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { filterEvents, notify, openCustomEditor, refresh, removeEvent, state, toggleCompleted } from '../store'
import { dedupeEvents } from '../utils/dedupe'
import { groupByDay, todayKey, dayKey } from '../utils/datetime'

const today = todayKey()

const AGENDA_MODE_KEY = 'campushub.agenda_mode'
const AGENDA_MODES = ['ddl', 'schedule', 'all', 'archive']
const agendaMode = ref(
  (function () {
    try {
      const saved = localStorage.getItem(AGENDA_MODE_KEY)
      // 旧版本存过「无截止」这一类，现在归「可办事项」页，这里回落到默认值
      return AGENDA_MODES.includes(saved) ? saved : 'ddl'
    } catch (e) {
      return 'ddl'
    }
  })(),
)

function setAgendaMode(mode) {
  agendaMode.value = mode
  try {
    localStorage.setItem(AGENDA_MODE_KEY, mode)
  } catch (e) {}
}

function isRangeTask(event) {
  if (!event) return false
  if (Array.isArray(event.periods) && event.periods.length > 0) return true
  if (event.end_time && event.start_time && event.end_time !== event.start_time) return true
  return false
}

// 线性列表展示逻辑：仅 DDL / 仅日程 / 含课表 / 历史归档
// （无截止待办不在日程栏出现——它归「可办事项」页，两种逻辑彻底分开）
const AGENDA_TABS = [
  { key: 'ddl', label: '仅 DDL' },
  { key: 'schedule', label: '仅日程' },
  { key: 'all', label: '含课表' },
  { key: 'archive', label: '历史归档' },
]

const visible = computed(() => {
  const list = dedupeEvents(filterEvents(undefined, { include_undated: false }))
  if (agendaMode.value === 'ddl') {
    return list.filter((event) => event.is_deadline && !isRangeTask(event))
  }
  if (agendaMode.value === 'schedule') {
    // 仅日程：包含待办 DDL 以及用户自定义的时间段日程，过滤掉教务课表 (tju_schedule)
    return list.filter((event) => event.source !== 'tju_schedule')
  }
  return list
})

const countLabel = computed(() => {
  if (agendaMode.value === 'archive') {
    return '按完成时间倒序，从近到久'
  }
  const unit = agendaMode.value === 'ddl' ? '待办' : agendaMode.value === 'schedule' ? '日程' : '全部安排'
  return `${visible.value.length} 条${unit}`
})

const overdue = computed(() =>
  visible.value.filter(
    (event) =>
      event.is_deadline &&
      !event.is_undated &&
      event.status !== 'completed' &&
      dayKey(event.start_time) < today,
  ),
)

const groups = computed(() => {
  const overdueIds = new Set(overdue.value.map((event) => event.id))
  return groupByDay(visible.value.filter((event) => !overdueIds.has(event.id)))
})

/* ----------------------------------------------------------- 动态按需渲染逻辑 */
const renderedGroupLimit = ref(10)
const displayedGroups = computed(() => groups.value.slice(0, renderedGroupLimit.value))
const renderedGroups = computed(() => (agendaMode.value === 'archive' ? [] : displayedGroups.value))
const hasMoreGroups = computed(() => displayedGroups.value.length < groups.value.length)

function loadMoreGroups() {
  renderedGroupLimit.value += 10
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
  if (agendaMode.value === 'all') return '当前没有日程安排。点右上角同步看看。'
  return '当前没有待办与临近的 DDL。点右上角同步或右下角 + 添加。'
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
