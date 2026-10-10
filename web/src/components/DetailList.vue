<template>
  <div class="space-y-1.5">
    <div v-for="row in rows" :key="row.key" class="flex items-start justify-between gap-3 text-xs">
      <span class="shrink-0 text-slate-500 dark:text-slate-400">{{ row.label }}</span>
      <span class="min-w-0 text-right font-medium">
        <span v-if="row.kind === 'bool'" :class="row.value ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'">
          {{ row.value ? '是' : '否' }}
        </span>
        <span v-else-if="row.kind === 'state'" class="chip border-transparent" :class="row.classes">
          {{ row.value }}
        </span>
        <span v-else class="break-all">{{ row.value }}</span>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  labels: { type: Object, default: () => ({}) },
  keys: { type: Array, default: null },
})

const rows = computed(() => {
  const source = props.data || {}
  const entries = props.keys ? props.keys.map((key) => [key, source[key]]) : Object.entries(source)
  return entries
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => {
      const label = props.labels[key] || key
      if (typeof value === 'boolean') return { key, label, value, kind: 'bool' }
      if (value === null) return { key, label, value: '—', kind: 'text' }
      if (Array.isArray(value)) return { key, label, value: value.join(' · ') || '—', kind: 'text' }
      if (typeof value === 'object') return { key, label, value: JSON.stringify(value), kind: 'text' }
      if (key === 'state' || key === 'status') {
        const ok = ['authorized', 'ok', 'ready', 'enabled'].includes(String(value))
        return {
          key,
          label,
          value: String(value),
          kind: 'state',
          classes: ok
            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
            : 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
        }
      }
      return { key, label, value: String(value), kind: 'text' }
    })
})
</script>
