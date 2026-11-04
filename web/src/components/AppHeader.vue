<template>
  <header
    class="sticky top-0 z-20 border-b border-white/60 bg-white/70 backdrop-blur-xl
           dark:border-white/10 dark:bg-slate-950/70 [transform:translateZ(0)]"
  >
    <!-- 搜索模式：整条顶部栏让给搜索，标题 / 按钮一起让位 -->
    <div v-if="searching" class="mx-auto flex max-w-3xl items-center gap-2 px-4 py-1">
      <button class="btn-ghost !h-8 !px-2" title="退出搜索" data-testid="search-close" @click="closeSearch">
        <ArrowLeft :size="15" />
      </button>
      <label
        class="flex min-w-0 flex-1 items-center gap-2 rounded-lg bg-slate-100 px-2.5 py-1 dark:bg-slate-800"
      >
        <Search :size="13" class="shrink-0 opacity-60" />
        <input
          ref="searchInput"
          v-model="state.query"
          type="search"
          data-testid="search-input"
          placeholder="搜课程 / 老师 / 地点"
          class="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-slate-400"
        />
        <button
          v-if="state.query"
          type="button"
          class="shrink-0 opacity-60 hover:opacity-100"
          title="清空搜索"
          data-testid="search-clear"
          @click="state.query = ''"
        >
          <X :size="13" />
        </button>
      </label>
    </div>

    <template v-else>
      <div class="mx-auto flex max-w-3xl items-center gap-2 px-4 py-1">
        <div class="flex min-w-0 flex-1 items-center gap-1.5">
          <h1
            class="truncate text-sm font-semibold tracking-tight select-none"
            :class="state.view === 'week' ? 'cursor-pointer hover:text-brand-600 dark:hover:text-brand-400 transition-colors' : ''"
            :title="state.view === 'week' ? '点击回到本周' : ''"
            @click="state.view === 'week' && triggerFocusToday()"
          >
            {{ currentSectionTitle }}
          </h1>
          <button
            v-if="state.view === 'week' && !state.isCurrentWeekCentered"
            type="button"
            class="chip cursor-pointer border-brand-200 bg-brand-50 px-1.5 py-0 text-[10px] text-brand-700 hover:bg-brand-100 transition-colors dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-300 dark:hover:bg-brand-500/20"
            title="回到当前周"
            @click="triggerFocusToday()"
          >
            回今天
          </button>
          <span
            v-if="!state.online"
            class="chip border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700/60 dark:bg-amber-900/30 dark:text-amber-300"
          >
            <WifiOff :size="11" /> 离线
          </span>
        </div>

        <button
          class="btn-ghost !h-8 !px-2"
          title="搜索"
          data-testid="search-open"
          @click="openSearch"
        >
          <Search :size="15" />
        </button>

        <button class="btn-primary !h-8 !py-0 px-2.5 flex items-center justify-center gap-1.5 text-xs" :disabled="state.syncing" @click="runSync()">
          <RefreshCw :size="13" :class="state.syncing ? 'animate-spin' : ''" />
          <span class="hidden sm:inline">{{ state.syncing ? '同步中' : '同步' }}</span>
        </button>

        <button
          class="btn-ghost !h-8 !px-2 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
          :class="state.view === 'settings' ? '!text-brand-600 dark:!text-brand-400' : ''"
          title="系统设置"
          data-testid="header-settings-btn"
          @click="toggleSettings"
        >
          <Settings :size="15" />
        </button>
      </div>
    </template>
  </header>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ArrowLeft, RefreshCw, Search, Settings, WifiOff, X } from 'lucide-vue-next'
import { state, runSync } from '../store'

const searching = ref(false)
const searchInput = ref(null)

const currentSectionTitle = computed(() => {
  switch (state.view) {
    case 'agenda':
      return '日程'
    case 'week':
      return state.weekLabel || '第 1 周'
    case 'history':
      return '历史归档'
    case 'settings':
      return '系统设置'
    default:
      return 'CampusHub'
  }
})

function triggerFocusToday() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('campushub:focus-today'))
  }
}

function openSearch() {
  searching.value = true
  nextTick(() => searchInput.value?.focus())
}

function closeSearch() {
  searching.value = false
}

function toggleSettings() {
  if (state.view === 'settings') {
    state.view = 'agenda'
  } else {
    state.view = 'settings'
  }
}
</script>
