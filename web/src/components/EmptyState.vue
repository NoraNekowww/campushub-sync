<template>
  <div class="card flex flex-col items-center gap-2 px-6 py-10 text-center">
    <component :is="icon" :size="26" class="text-slate-400" />
    <p class="text-sm font-medium">{{ title }}</p>
    <p class="max-w-xs text-xs text-slate-500 dark:text-slate-400">{{ message }}</p>
    <slot />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { CalendarOff, CloudOff, KeyRound, PartyPopper } from 'lucide-vue-next'

const props = defineProps({
  kind: { type: String, default: 'empty' }, // empty | offline | auth
  message: { type: String, default: '' },
})

const icon = computed(
  () => ({ empty: PartyPopper, offline: CloudOff, auth: KeyRound })[props.kind] || CalendarOff,
)
const title = computed(
  () =>
    ({ empty: '这周很干净', offline: '当前离线', auth: '需要访问令牌' })[props.kind] || '暂无内容',
)
</script>
