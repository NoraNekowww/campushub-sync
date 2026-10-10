<template>
  <div class="mx-auto max-w-3xl overflow-x-auto px-4 pb-2 no-scrollbar">
    <div class="flex items-center gap-2 whitespace-nowrap">
      <button
        v-for="option in kinds"
        :key="option.value"
        class="chip"
        :class="state.filter === option.value ? 'chip-active' : 'chip-idle'"
        @click="state.filter = option.value"
      >
        <component :is="option.icon" :size="12" />
        {{ option.label }}
      </button>

      <span class="mx-1 h-4 w-px bg-slate-200 dark:bg-slate-700" />

      <button
        v-for="option in sources"
        :key="option.value"
        class="chip"
        :class="state.source === option.value ? 'chip-active' : 'chip-idle'"
        @click="state.source = option.value"
      >
        {{ option.label }}
      </button>

      <span class="mx-1 h-4 w-px bg-slate-200 dark:bg-slate-700" />

      <label class="chip chip-idle cursor-pointer select-none">
        <input v-model="state.includeCompleted" type="checkbox" class="accent-brand-600" />
        显示已完成
      </label>
    </div>
  </div>
</template>

<script setup>
import { CalendarRange, GraduationCap, ListTodo } from 'lucide-vue-next'
import { state } from '../store'

const kinds = [
  { value: 'all', label: '全部', icon: CalendarRange },
  { value: 'class', label: '课程', icon: GraduationCap },
  { value: 'deadline', label: 'DDL', icon: ListTodo },
]

const sources = [
  { value: 'all', label: '全部来源' },
  { value: 'tju_schedule', label: '天津大学' },
  { value: 'microsoft_todo', label: 'To Do' },
  { value: 'custom', label: '自定义' },
]
</script>
