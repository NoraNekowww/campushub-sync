<template>
  <header
    class="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95
           dark:border-slate-800/80 dark:bg-slate-950/95 [transform:translateZ(0)]"
  >
    <!-- 搜索模式：整条顶部栏让给搜索，标题 / 按钮一起让位 -->
    <div v-if="searching" class="mx-auto flex max-w-3xl items-center gap-2 px-4 py-2.5">
      <button class="btn-ghost !px-2.5" title="退出搜索" data-testid="search-close" @click="closeSearch">
        <ArrowLeft :size="16" />
      </button>
      <label
        class="flex min-w-0 flex-1 items-center gap-2 rounded-lg bg-slate-100 px-3 py-1.5 dark:bg-slate-800"
      >
        <Search :size="14" class="shrink-0 opacity-60" />
        <input
          ref="searchInput"
          v-model="state.query"
          type="search"
          data-testid="search-input"
          placeholder="搜课程 / 老师 / 地点"
          class="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
        />
        <button
          v-if="state.query"
          type="button"
          class="shrink-0 opacity-60 hover:opacity-100"
          title="清空搜索"
          data-testid="search-clear"
          @click="state.query = ''"
        >
          <X :size="14" />
        </button>
      </label>
    </div>

    <template v-else>
      <div class="mx-auto flex max-w-3xl items-center gap-2.5 px-4 py-2.5">
        <div class="flex min-w-0 flex-1 items-center gap-2">
          <h1 class="truncate text-base font-semibold">CampusHub Sync</h1>
          <span
            v-if="!state.online"
            class="chip border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700/60 dark:bg-amber-900/30 dark:text-amber-300"
          >
            <WifiOff :size="12" /> 离线
          </span>
        </div>

        <button
          class="btn-ghost !px-2.5"
          title="搜索"
          data-testid="search-open"
          @click="openSearch"
        >
          <Search :size="16" />
        </button>

        <button class="btn-primary !py-1.5" :disabled="state.syncing" @click="runSync()">
          <RefreshCw :size="15" :class="state.syncing ? 'animate-spin' : ''" />
          <span class="hidden sm:inline">{{ state.syncing ? '同步中' : '同步' }}</span>
        </button>

        <button
          class="btn-ghost !px-2 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
          :class="state.view === 'settings' ? '!text-brand-600 dark:!text-brand-400' : ''"
          title="系统设置"
          data-testid="header-settings-btn"
          @click="toggleSettings"
        >
          <Settings :size="16" />
        </button>
      </div>
    </template>
  </header>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { ArrowLeft, RefreshCw, Search, Settings, WifiOff, X } from 'lucide-vue-next'
import { state, runSync } from '../store'

const searching = ref(false)
const searchInput = ref(null)

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
