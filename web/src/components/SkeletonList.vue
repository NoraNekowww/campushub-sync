<template>
  <div class="space-y-2">
    <div v-for="index in rows" :key="index" class="card animate-pulse p-3.5">
      <div class="flex gap-3">
        <div class="h-10 w-10 rounded-xl bg-slate-200 dark:bg-slate-800" />
        <div class="flex-1 space-y-2 py-0.5">
          <div class="h-3.5 w-2/5 rounded bg-slate-200 dark:bg-slate-800" />
          <div class="h-3 w-3/5 rounded bg-slate-100 dark:bg-slate-800/70" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ rows: { type: Number, default: 4 } })
</script>
