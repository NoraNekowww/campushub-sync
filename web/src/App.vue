<template>
  <div class="relative min-h-full">
    <!-- 全局背景图渲染层（图床按主题动态联动 + 遮罩与模糊度控制，与磨砂玻璃深度融合） -->
    <div
      v-if="state.backgroundConfig?.enabled && activeBgUrl"
      class="pointer-events-none fixed inset-0 z-0 overflow-hidden"
      aria-hidden="true"
    >
      <div
        class="absolute inset-0 bg-cover bg-center transition-all duration-700 ease-out"
        :style="bgLayerStyle"
      />
      <!-- 物理微遮罩层：保证深浅色模式下课表文字与排版的高对比度清晰度 -->
      <div
        class="absolute inset-0 transition-colors duration-500"
        :class="state.isDarkTheme ? 'bg-slate-950/35' : 'bg-white/20'"
      />
    </div>

    <AuthGate v-if="showGate" />

    <template v-else>
      <UpdateNotification />
      <!-- 已全面采用账号体系与会话管理，取消全局 TokenBanner 阻断横幅 -->

      <AppHeader />

      <main class="relative z-10 mx-auto max-w-3xl pb-28 pt-3">
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
// TokenBanner 已停用，全局统一由 AuthGate 与 Session 处理
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
  initFrostedGlass,
  initTheme,
  signInRequired,
  state,
} from './store'

/* The login wall only appears when the server says "accounts are on", the
   visitor has no session *and* no shared token, and an API call was refused —
   so an open deployment never sees it. */
const showGate = computed(() => signInRequired())

const activeBgUrl = computed(() => {
  const cfg = state.backgroundConfig
  if (!cfg?.enabled) return ''
  if (state.isDarkTheme) {
    return cfg.darkUrl || cfg.lightUrl || ''
  }
  return cfg.lightUrl || cfg.darkUrl || ''
})

const bgLayerStyle = computed(() => {
  const cfg = state.backgroundConfig || {}
  const opacity = (Number(cfg.opacity ?? 35) / 100).toFixed(2)
  const blurPx = Number(cfg.blur ?? 0)
  return {
    backgroundImage: `url(${activeBgUrl.value})`,
    opacity,
    filter: blurPx > 0 ? `blur(${blurPx}px)` : undefined,
    transform: blurPx > 0 ? 'scale(1.05)' : undefined,
  }
})

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
  initFrostedGlass()
  initConnectivity()
  await fetchSession()
  bootstrap()
  // 打开 App 时静默续一次课表（本机记住了微北洋令牌、且上次抓取超过 6 小时才会真的发请求）。
  autoRefreshTju()
})
</script>
