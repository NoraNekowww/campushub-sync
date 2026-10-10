<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 backdrop-blur
           dark:border-slate-800 dark:bg-slate-950/95"
    style="padding-bottom: env(safe-area-inset-bottom)"
  >
    <div class="mx-auto flex max-w-3xl">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        data-testid="nav-tab"
        :data-tab="tab.value"
        :aria-current="state.view === tab.value ? 'page' : 'false'"
        class="flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[11px] font-medium transition-colors"
        :class="
          state.view === tab.value
            ? 'text-brand-600 dark:text-brand-400'
            : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-200'
        "
        @click="state.view = tab.value"
      >
        <component :is="tab.icon" :size="20" :stroke-width="state.view === tab.value ? 2.4 : 2" />
        {{ tab.label }}
      </button>
    </div>
  </nav>
</template>

<script setup>
import { CalendarRange, LayoutGrid, Settings2 } from 'lucide-vue-next'
import { state } from '../store'

const tabs = [
  { value: 'agenda', label: '日程', icon: CalendarRange },
  { value: 'week', label: '课表', icon: LayoutGrid },
  { value: 'settings', label: '设置', icon: Settings2 },
]
</script>
