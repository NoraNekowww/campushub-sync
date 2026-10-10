<template>
  <header
    class="sticky top-0 z-20 border-b border-slate-200/80 bg-white/85 backdrop-blur
           dark:border-slate-800/80 dark:bg-slate-950/80"
  >
    <div class="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <h1 class="truncate text-base font-semibold">CampusHub Sync</h1>
          <span
            v-if="!state.online"
            class="chip border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700/60 dark:bg-amber-900/30 dark:text-amber-300"
          >
            <WifiOff :size="12" /> 离线
          </span>
        </div>
        <p class="truncate text-xs text-slate-500 dark:text-slate-400">
          {{ subtitle }}
        </p>
      </div>

      <button
        class="btn-ghost !px-2.5"
        title="新建自定义日程"
        data-testid="new-custom-event"
        @click="openCustomEditor()"
      >
        <Plus :size="16" />
      </button>

      <button
        class="btn-ghost !px-2.5"
        :title="`主题：${themeLabel}`"
        @click="cycleTheme"
      >
        <component :is="themeIcon" :size="16" />
      </button>

      <button class="btn-primary" :disabled="state.syncing" @click="runSync()">
        <RefreshCw :size="16" :class="state.syncing ? 'animate-spin' : ''" />
        <span class="hidden sm:inline">{{ state.syncing ? '同步中' : '同步' }}</span>
      </button>
    </div>

    <FilterBar />
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { Monitor, Moon, Plus, RefreshCw, Sun, WifiOff } from 'lucide-vue-next'
import FilterBar from './FilterBar.vue'
import { haveEvents, subtitleText } from '../composables/useHeader'
import { openCustomEditor, setTheme, state, runSync } from '../store'

const themeLabel = computed(() => ({ dark: '深色', light: '浅色', auto: '跟随系统' })[state.theme])
const themeIcon = computed(
  () => ({ dark: Moon, light: Sun, auto: Monitor })[state.theme] || Monitor,
)
const subtitle = computed(() => subtitleText(state, haveEvents(state)))

function cycleTheme() {
  const order = ['auto', 'light', 'dark']
  setTheme(order[(order.indexOf(state.theme) + 1) % order.length])
}
</script>
