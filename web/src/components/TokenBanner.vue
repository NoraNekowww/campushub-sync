<template>
  <div class="border-b border-amber-200 bg-amber-50 px-4 py-2 dark:border-amber-700/50 dark:bg-amber-900/30">
    <div class="mx-auto flex max-w-3xl items-center gap-2 text-xs text-amber-800 dark:text-amber-200">
      <ShieldAlert :size="14" class="shrink-0" />
      <span class="min-w-0 flex-1">后端要求访问令牌，修改日程与同步功能已锁定。</span>
      <button class="btn-ghost !border-amber-300 !bg-transparent !px-2 !py-1 text-[11px] dark:!border-amber-700" @click="state.view = 'settings'">
        去设置
      </button>
    </div>
  </div>
</template>

<script setup>
import { ShieldAlert } from 'lucide-vue-next'
import { state } from '../store'
</script>
