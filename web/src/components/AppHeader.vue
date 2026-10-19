<template>
  <header
    class="sticky top-0 z-20 border-b border-slate-200/80 bg-white/85 backdrop-blur
           dark:border-slate-800/80 dark:bg-slate-950/80"
  >
    <!-- 搜索模式：整条顶部栏让给搜索，标题 / 按钮 / 筛选条一起让位 -->
    <div v-if="searching" class="mx-auto flex max-w-3xl items-center gap-2 px-4 py-3">
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
          title="搜索"
          data-testid="search-open"
          @click="openSearch"
        >
          <Search :size="16" />
        </button>

        <button class="btn-primary" :disabled="state.syncing" @click="runSync()">
          <RefreshCw :size="16" :class="state.syncing ? 'animate-spin' : ''" />
          <span class="hidden sm:inline">{{ state.syncing ? '同步中' : '同步' }}</span>
        </button>
      </div>

      <FilterBar />
    </template>
  </header>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ArrowLeft, RefreshCw, Search, WifiOff, X } from 'lucide-vue-next'
import FilterBar from './FilterBar.vue'
import { haveEvents, subtitleText } from '../composables/useHeader'
import { state, runSync } from '../store'

const subtitle = computed(() => subtitleText(state, haveEvents(state)))

/* 主题切换已经挪进设置（「外观与离线」那节），这里只留搜索。
   放大镜一点，整条顶部栏换成搜索框 —— 手机上比在筛选条里挤一个小输入框好按得多。 */
const searching = ref(false)
const searchInput = ref(null)

function openSearch() {
  searching.value = true
  nextTick(() => searchInput.value?.focus())
}

function closeSearch() {
  searching.value = false
}
</script>
