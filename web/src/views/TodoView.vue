<template>
  <div class="space-y-4 px-4 pt-1">
    <!-- 顶部说明：这一页只放「没有截止时间」的事，按记下来的先后倒序 -->
    <header class="flex items-end justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold text-slate-800 dark:text-slate-100">可办事项</h2>
        <p class="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
          没有截止时间的待办都收在这里，按建立时间从新到旧
        </p>
      </div>
      <span class="chip shrink-0 border-transparent bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
        {{ items.length }} 项
      </span>
    </header>

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
