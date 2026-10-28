<template>
  <div class="min-h-full">
    <AuthGate v-if="showGate" />

    <template v-else>
      <UpdateNotification />
      <TokenBanner v-if="state.authRequired" />

      <AppHeader />

      <main class="mx-auto max-w-3xl pb-28 pt-3">
        <AgendaView v-show="state.view === 'agenda'" />
        <WeekView v-show="state.view === 'week'" />
        <HistoryView v-show="state.view === 'history'" />
        <SettingsView v-show="state.view === 'settings'" />
      </main>

      <BottomNav />

      <!-- 新建日程挪到右下角悬浮按钮（顶栏那个小 + 手机上够不着） -->
      <FloatingAdd />

      <EventEditor />
    </template>

    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="translate-y-3 opacity-0"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="translate-y-2 opacity-0"
    >
      <div v-if="state.toast" class="pointer-events-none fixed inset-x-0 bottom-24 z-40 flex justify-center px-4">
        <div class="toast pointer-events-auto flex items-center gap-2" :class="toastClass">
          <span>{{ state.toast.text }}</span>
          <button
            v-if="state.toast.action"
            type="button"
            class="shrink-0 rounded-lg border border-current px-2 py-0.5 text-xs font-semibold
                   opacity-90 transition-opacity hover:opacity-100"
            data-testid="toast-action"
            @click="runToastAction"
          >
            {{ state.toast.action.label }}
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import AppHeader from './components/AppHeader.vue'
import AuthGate from './components/AuthGate.vue'
import BottomNav from './components/BottomNav.vue'
import FloatingAdd from './components/FloatingAdd.vue'
import TokenBanner from './components/TokenBanner.vue'
import UpdateNotification from './components/UpdateNotification.vue'
import AgendaView from './views/AgendaView.vue'
import EventEditor from './components/EventEditor.vue'
import HistoryView from './views/HistoryView.vue'
import SettingsView from './views/SettingsView.vue'
import WeekView from './views/WeekView.vue'
import {
  autoRefreshTju,
  bootstrap,
  fetchSession,
  initConnectivity,
  initTheme,
  signInRequired,
  state,
} from './store'

/* The login wall only appears when the server says "accounts are on", the
   visitor has no session *and* no shared token, and an API call was refused —
   so an open deployment never sees it. */
const showGate = computed(() => signInRequired())

const toastClass = computed(() => {
  const tone = state.toast?.tone
  if (tone === 'ok') return 'bg-emerald-600 text-white'
  if (tone === 'warn') return 'bg-amber-500 text-white'
  if (tone === 'danger') return 'bg-rose-600 text-white'
  return 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
})

/* 左右滑动切页已移除：课表自己就要横向滚动，手势会打架（用户明确要求删掉）。
   横向手势只用在日程卡片上：左右拖开 = 露出删除按钮（EventCard.vue）。 */

/* 提示条上的动作按钮（比如删除后的「撤销」）：点一下就跑，然后收起提示。 */
async function runToastAction() {
  const action = state.toast?.action
  state.toast = null
  if (action?.run) await action.run()
}

onMounted(async () => {
  initTheme()
  initConnectivity()
  await fetchSession()
  bootstrap()
  // 打开 App 时静默续一次课表（本机记住了微北洋令牌、且上次抓取超过 6 小时才会真的发请求）。
  autoRefreshTju()
})
</script>
