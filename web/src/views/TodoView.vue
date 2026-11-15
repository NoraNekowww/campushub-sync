<template>
  <div class="space-y-4 px-4 pt-1">
    <SkeletonList v-if="state.loading && !items.length" :rows="4" />

    <div v-else-if="!items.length" class="card space-y-3 p-5 text-center">
      <div class="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
        <ListTodo :size="20" />
      </div>
      <p class="text-sm font-medium text-slate-700 dark:text-slate-200">暂时没有可办事项</p>
      <p class="text-xs leading-relaxed text-slate-500 dark:text-slate-400">
        想到什么先记下来，这里不设截止时间，也不占 DDL 列表和课表。
      </p>
      <button
        type="button"
        class="btn-primary mx-auto inline-flex items-center gap-1.5 px-4 py-2 text-xs"
        data-testid="todo-empty-add"
        @click="openTodoQuickAdd()"
      >
        <Plus :size="14" /> 记一条
      </button>
    </div>

    <template v-else>
      <EventCard
        v-for="item in items"
        :key="item.id"
        :event="item"
        @toggle="toggleCompleted"
        @remove="removeEvent"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ListTodo, Plus } from 'lucide-vue-next'
import EventCard from '../components/EventCard.vue'
import SkeletonList from '../components/SkeletonList.vue'
import { openTodoQuickAdd, removeEvent, state, toggleCompleted } from '../store'

/* 可办事项 = 无截止时间、还没划掉的待办；不按天分组，直接按建立时间倒序 */
const items = computed(() => {
  const createdOf = (event) => new Date(event.created_at || event.start_time).getTime() || 0
  return (state.events || [])
    .filter((event) => event.is_undated && event.status !== 'completed' && !event.hidden)
    .slice()
    .sort((a, b) => createdOf(b) - createdOf(a))
})
</script>
