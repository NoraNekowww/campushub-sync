<template>
  <Teleport to="body">
    <div
      v-if="state.customEditor.open"
      class="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 backdrop-blur-sm sm:items-center sm:p-4"
      @click.self="close"
    >
      <form
        class="max-h-[92vh] w-full max-w-md space-y-3 overflow-y-auto rounded-t-2xl bg-white p-4 shadow-2xl dark:bg-slate-900 sm:rounded-2xl"
        data-testid="custom-event-editor"
        @submit.prevent="submit"
      >
        <header class="flex items-center gap-2">
          <Pencil :size="15" class="text-brand-600 dark:text-brand-400" />
          <h2 class="text-sm font-semibold">{{ isEdit ? '编辑日程' : '新建日程' }}</h2>
          <button type="button" class="btn-ghost ml-auto !px-2" @click="close"><X :size="15" /></button>
        </header>

        <label class="block space-y-1 text-xs">
          <span class="text-slate-500 dark:text-slate-400">标题</span>
          <input v-model="form.title" class="input" required maxlength="120" placeholder="例如：找导师签字" data-testid="custom-title" />
        </label>

        <div class="grid grid-cols-2 gap-2">
          <label class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">日期</span>
            <input v-model="form.date" type="date" class="input" required data-testid="custom-date" />
          </label>
          <label class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">地点（可空）</span>
            <input v-model="form.location" class="input" maxlength="80" placeholder="45楼B203" />
          </label>
        </div>

        <div class="grid grid-cols-2 gap-2">
          <label class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">开始</span>
            <input v-model="form.start" type="time" class="input" :disabled="form.allDay" required />
          </label>
          <label class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">结束（可空）</span>
            <input v-model="form.end" type="time" class="input" :disabled="form.allDay" />
          </label>
        </div>

        <label class="flex items-center gap-2 text-xs">
          <input v-model="form.allDay" type="checkbox" />
          <span class="text-slate-600 dark:text-slate-300">全天 / 当截止日期用</span>
        </label>

        <!-- 接了微软待办就默认同步过去（用户要求）；不想传的可以取消勾选 -->
        <div
          v-if="!isEdit && state.msConnected"
          class="space-y-2 rounded-xl bg-brand-50/70 p-2.5 text-xs dark:bg-brand-500/10"
        >
          <label class="flex items-center gap-2">
            <input v-model="form.toMs" type="checkbox" data-testid="custom-to-ms" />
            <span class="text-slate-700 dark:text-slate-200">同步到微软待办（手机待办里也会出现、会响提醒）</span>
          </label>
          <label v-if="form.toMs" class="block space-y-1">
            <span class="text-slate-500 dark:text-slate-400">放进哪个清单</span>
            <select v-model="form.listId" class="input" data-testid="custom-ms-list">
              <option value="">默认（第一个清单）</option>
              <option v-for="item in state.msLists" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
          </label>
          <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
            勾上 = 建在微软待办里（在这里划掉，手机那边也划掉）；取消勾选 = 只存本站，走自定义日程。
          </p>
        </div>

        <label class="block space-y-1 text-xs">
          <span class="text-slate-500 dark:text-slate-400">备注（可空）</span>
          <textarea v-model="form.description" class="input h-16 resize-none" maxlength="500" />
        </label>

        <p v-if="error" class="text-xs text-rose-600 dark:text-rose-400">{{ error }}</p>

        <div class="flex items-center gap-2 pt-1">
          <button v-if="isEdit" type="button" class="btn-ghost !text-rose-600 dark:!text-rose-400" :disabled="busy" @click="remove">
            删除
          </button>
          <button type="submit" class="btn-primary ml-auto" :disabled="busy || !form.title.trim()" data-testid="custom-save">
            {{ busy ? '保存中…' : isEdit ? '保存' : form.toMs ? '建到微软待办' : '添加' }}
          </button>
        </div>
        <p class="text-[11px] leading-relaxed text-slate-400">
          纯自定义日程归「自定义」来源，教务/微软同步永远不会删它或改它。
        </p>
      </form>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Pencil, X } from 'lucide-vue-next'
import { closeCustomEditor, fetchMsLists, removeCustomEvent, saveCustomEvent, saveMsTask, state } from '../store'

const busy = ref(false)
const error = ref('')
const form = reactive({
  title: '',
  date: '',
  start: '09:00',
  end: '',
  allDay: false,
  location: '',
  description: '',
  /* 接没接微软待办决定默认值：接了默认同步过去，可以直接取消（只存本站） */
  toMs: false,
  listId: '',
})

const editing = computed(() => state.customEditor.event)
const isEdit = computed(() => Boolean(editing.value))

function today() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

watch(
  () => [state.customEditor.open, state.customEditor.event],
  async () => {
    if (!state.customEditor.open) return
    error.value = ''
    const event = state.customEditor.event
    // start_time 已经是本地时区（后端按 Asia/Shanghai 回），前 16 位即 date+T HH:MM
    const start = (event?.start_time || '').slice(0, 16)
    const end = (event?.end_time || '').slice(0, 16)
    form.title = event?.title || ''
    form.date = start ? start.slice(0, 10) : today()
    form.start = start ? start.slice(11, 16) : '09:00'
    form.end = end ? end.slice(11, 16) : ''
    form.allDay = Boolean(event?.is_deadline)
    form.location = event?.location || ''
    form.description = event?.description || ''
    form.listId = ''
    // 新建时顺手问一次微软待办：连了就默认勾上「同步到待办」，并拿到清单列表
    form.toMs = event ? false : await fetchMsLists()
  },
  { immediate: true },
)

function close() {
  closeCustomEditor()
}

async function submit() {
  error.value = ''
  if (form.end && !form.allDay && form.end <= form.start) {
    error.value = '结束时间要晚于开始时间'
    return
  }
  busy.value = true

  // 勾了「同步到微软待办」：先建到 To Do，后端同时把它落成一条本地日程
  if (form.toMs && !isEdit.value) {
    const saved = await saveMsTask({
      title: form.title.trim(),
      // To Do 是「截止时间」制：全天日程按早上 9 点提醒
      start: `${form.date}T${form.allDay ? '09:00' : form.start}:00`,
      note: form.description.trim() || null,
      list_id: form.listId || null,
      importance: form.allDay ? 'high' : null,
    })
    busy.value = false
    if (!saved) error.value = '没建成功，看一眼上面的提示'
    return
  }

  const payload = {
    title: form.title.trim(),
    start_time: `${form.date}T${form.allDay ? '00:00' : form.start}:00`,
    end_time: form.allDay || !form.end ? null : `${form.date}T${form.end}:00`,
    is_deadline: form.allDay,
    location: form.location.trim() || null,
    description: form.description.trim() || null,
  }
  const saved = await saveCustomEvent(payload)
  busy.value = false
  if (!saved) error.value = '没保存成功，看一眼上面的提示'
}

async function remove() {
  if (!editing.value) return
  busy.value = true
  const removed = await removeCustomEvent(editing.value.id)
  busy.value = false
  if (!removed) error.value = '删除失败，看一眼上面的提示'
}
</script>
