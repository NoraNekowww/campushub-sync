<template>
  <Teleport to="body">
    <div
      v-if="state.todoQuickAdd.open"
      class="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/40 p-4 backdrop-blur-md animate-fade-in sm:items-center"
      @click.self="closeTodoQuickAdd"
    >
      <form
        class="w-full max-w-md space-y-3 rounded-3xl border border-white/60 bg-white/85 p-5 shadow-2xl
               backdrop-blur-2xl dark:border-white/10 dark:bg-slate-900/85 [transform:translateZ(0)]"
        data-testid="todo-quick-add"
        @submit.prevent="submit"
      >
        <header class="flex items-center gap-2">
          <ListTodo :size="15" class="text-brand-600 dark:text-brand-400" />
          <h2 class="text-base font-semibold text-slate-800 dark:text-slate-100">新建可办事项</h2>
          <button type="button" class="btn-ghost ml-auto !px-2" @click="closeTodoQuickAdd">
            <X :size="15" />
          </button>
        </header>

        <label class="block space-y-1 text-xs">
          <span class="text-slate-500 dark:text-slate-400">标题</span>
          <input
            ref="titleInput"
            v-model="title"
            class="input"
            maxlength="80"
            placeholder="要办的事"
            data-testid="todo-quick-title"
            autocomplete="off"
          />
        </label>

        <label class="block space-y-1 text-xs">
          <span class="text-slate-500 dark:text-slate-400">备注（可空）</span>
          <textarea
            v-model="notes"
            class="input min-h-[92px] resize-y"
            maxlength="2000"
            placeholder="细节、链接、联系人…"
            data-testid="todo-quick-notes"
          />
        </label>

        <p v-if="error" class="rounded-xl bg-rose-50 p-2 text-[11px] text-rose-600 dark:bg-rose-500/10 dark:text-rose-300">
          {{ error }}
        </p>

        <button type="submit" class="btn-primary w-full !py-2 text-sm" :disabled="busy || !title.trim()">
          {{ busy ? '保存中…' : '保存' }}
        </button>
      </form>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { ListTodo, X } from 'lucide-vue-next'
import { closeTodoQuickAdd, saveQuickTodo, state } from '../store'
import { useBackHandler } from '../utils/backNavigation'

const title = ref('')
const notes = ref('')
const busy = ref(false)
const error = ref('')
const titleInput = ref(null)
useBackHandler(() => state.todoQuickAdd.open, closeTodoQuickAdd)

watch(
  () => state.todoQuickAdd.open,
  async (open) => {
    if (!open) return
    title.value = ''
    notes.value = ''
    error.value = ''
    await nextTick()
    titleInput.value?.focus()
  },
)

async function submit() {
  if (!title.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const saved = await saveQuickTodo({ title: title.value, description: notes.value })
    if (!saved) error.value = '没保存成功，请检查网络后重试'
  } finally {
    busy.value = false
  }
}
</script>
