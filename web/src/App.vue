<template>
  <div class="relative min-h-full">
    <!-- 全局背景图渲染层（首屏 0ms 读本地软件缓存/内置壁纸，课表视图全屏高斯模糊） -->
    <div
      v-if="state.backgroundConfig?.enabled && activeBgUrl"
      class="pointer-events-none fixed inset-0 z-0 overflow-hidden"
      data-testid="global-bg-layer"
      aria-hidden="true"
    >
      <img
        :src="activeBgUrl"
        alt=""
        class="absolute inset-0 h-full w-full object-cover"
        :style="bgLayerStyle"
        referrerpolicy="no-referrer"
        loading="eager"
        decoding="sync"
      />
      <!-- 物理微遮罩层：课表全屏高斯模糊模式下进一步柔化对比度，深浅色均通透清晰 -->
      <div
        class="absolute inset-0 transition-colors duration-300"
        :class="bgOverlayClass"
      />
    </div>
    <!-- 关闭壁纸时，课表全屏模式仍保持柔和弥散高斯底衬 -->
    <div
      v-else-if="state.view === 'week'"
      class="pointer-events-none fixed inset-0 z-0 bg-gradient-to-br from-slate-200/90 via-slate-200/85 to-brand-100/80 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950/40"
      aria-hidden="true"
    />

    <AuthGate v-if="showGate" />

    <template v-else>
      <UpdateNotification />

      <AppHeader />

      <main
        class="relative z-10"
        :class="state.view === 'week' ? 'w-full p-0' : 'mx-auto max-w-3xl pb-28 pt-3'"
      >
        <AgendaView v-show="state.view === 'agenda'" />
        <WeekView v-show="state.view === 'week'" />
        <TodoView v-show="state.view === 'todo' || state.view === 'history'" />
        <SettingsView v-show="state.view === 'settings'" />
      </main>

      <BottomNav />

      <FloatingAdd />

      <EventEditor />
      <TodoQuickAdd />
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
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import AppHeader from './components/AppHeader.vue'
import AuthGate from './components/AuthGate.vue'
import BottomNav from './components/BottomNav.vue'
import FloatingAdd from './components/FloatingAdd.vue'
import TodoQuickAdd from './components/TodoQuickAdd.vue'
import UpdateNotification from './components/UpdateNotification.vue'
import AgendaView from './views/AgendaView.vue'
import EventEditor from './components/EventEditor.vue'
import TodoView from './views/TodoView.vue'
import SettingsView from './views/SettingsView.vue'
import WeekView from './views/WeekView.vue'
import {
  applyBackgroundClass,
  autoRefreshTju,
  bootstrap,
  closeAuthGate,
  fetchSession,
  getCachedActiveBgUrl,
  initConnectivity,
  initFrostedGlass,
  initTheme,
  signInRequired,
  state,
} from './store'
import { dispatchAppBack, setBackFallback } from './utils/backNavigation'

const showGate = computed(() => signInRequired())

const activeBgUrl = computed(() => getCachedActiveBgUrl())

const bgLayerStyle = computed(() => {
  const cfg = state.backgroundConfig || {}
  const isWeek = state.view === 'week'
  const rawOpacity = Number(cfg.opacity ?? 75) / 100
  const opacity = (isWeek ? Math.max(0.62, rawOpacity) : Math.max(0.75, rawOpacity)).toFixed(2)
  // 课表全屏模式下背景启用高斯模糊（>= 20px），非课表页保持背景清晰锐利（由配置 blur 决定，默认 0）
  const blurPx = isWeek ? Math.max(20, Number(cfg.blur ?? 0)) : Number(cfg.blur ?? 0)
  return {
    opacity,
    filter: blurPx > 0 ? `blur(${blurPx}px)` : undefined,
    transform: blurPx > 0 ? 'translateZ(0) scale(1.08)' : 'translateZ(0)',
  }
})

const bgOverlayClass = computed(() => {
  if (state.view === 'week') {
    return state.isDarkTheme
      ? 'bg-slate-950/45 backdrop-blur-md'
      : 'bg-slate-900/[0.14] backdrop-blur-md'
  }
  return state.isDarkTheme ? 'bg-slate-950/30' : 'bg-slate-900/[0.06]'
})

const toastClass = computed(() => {
  const tone = state.toast?.tone
  if (tone === 'ok') return 'bg-emerald-600 text-white'
  if (tone === 'warn') return 'bg-amber-500 text-white'
  if (tone === 'danger') return 'bg-rose-600 text-white'
  return 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
})

async function runToastAction() {
  const action = state.toast?.action
  state.toast = null
  if (action?.run) await action.run()
}

let lastMainView = 'week'
watch(
  () => state.view,
  (next, prev) => {
    if (prev && prev !== 'settings' && prev !== 'history') {
      lastMainView = prev
    }
    if (next && next !== 'settings' && next !== 'history') {
      lastMainView = next
    }
  },
  { immediate: true },
)

setBackFallback(() => {
  if (state.forceAuth) {
    closeAuthGate()
    return true
  }
  if (state.view === 'settings') {
    if (state.settingsSubpage) {
      state.settingsSubpage = null
      return true
    }
    state.view = lastMainView || 'week'
    return true
  }
  if (state.view === 'history') {
    state.view = 'agenda'
    return true
  }
  return false
})

function onGlobalKeydown(e) {
  if (e.key === 'Escape' && !e.isComposing && dispatchAppBack()) {
    e.preventDefault()
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onGlobalKeydown)
  initTheme()
  initFrostedGlass()
  applyBackgroundClass()
  initConnectivity()
  await fetchSession()
  bootstrap()
  autoRefreshTju()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>
