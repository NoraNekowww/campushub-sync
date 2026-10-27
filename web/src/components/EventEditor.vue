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
          <h2 class="text-sm font-semibold">{{ editorTitle }}</h2>
          <span
            v-if="editingRecurrence"
            class="rounded-md bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300"
          >
            第 {{ editingRecurrence.index }} / {{ editingRecurrence.total }} 次
          </span>
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
            <span class="text-slate-500 dark:text-slate-400">时长（默认 0h）</span>
            <select
              v-model.number="form.duration"
              class="input"
              :disabled="form.allDay"
              data-testid="custom-duration"
            >
              <option :value="0">0h（不写结束时间）</option>
              <option :value="0.5">0.5h</option>
              <option :value="1">1h</option>
              <option :value="1.5">1.5h</option>
              <option :value="2">2h</option>
              <option :value="2.5">2.5h</option>
              <option :value="3">3h</option>
              <option :value="4">4h</option>
              <option :value="6">6h</option>
              <option :value="8">8h</option>
            </select>
          </label>
        </div>

        <label v-if="isCustom || !isEdit" class="flex items-center gap-2 text-xs">
          <input v-model="form.allDay" type="checkbox" />
          <span class="text-slate-600 dark:text-slate-300">全天 / 当截止日期用</span>
        </label>

        <!-- 重复任务设置（支持按天/周/月重复，重复几次） -->
        <div
          v-if="!isEdit"
          class="space-y-2 rounded-xl border border-slate-200/80 bg-slate-50/70 p-2.5 text-xs dark:border-slate-800 dark:bg-slate-800/40"
        >
          <label class="flex cursor-pointer items-center gap-2 font-medium">
            <input
              v-model="form.recurring"
              type="checkbox"
              data-testid="custom-recurring-toggle"
              class="accent-brand-600"
            />
            <span>开启重复任务（按周期自动生成）</span>
          </label>
          <div v-if="form.recurring" class="space-y-2 pt-1.5">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-slate-500 dark:text-slate-400">每</span>
              <input
                v-model.number="form.repeatInterval"
                type="number"
                min="1"
                max="99"
                class="input w-16 !py-1 text-center"
                data-testid="custom-repeat-interval"
              />
              <select v-model="form.repeatUnit" class="input w-20 !py-1" data-testid="custom-repeat-unit">
                <option value="day">天</option>
                <option value="week">周</option>
                <option value="month">个月</option>
              </select>
              <span class="text-slate-500 dark:text-slate-400">重复一次，共</span>
              <input
                v-model.number="form.repeatCount"
                type="number"
                min="2"
                max="60"
                class="input w-16 !py-1 text-center"
                data-testid="custom-repeat-count"
              />
              <span class="text-slate-500 dark:text-slate-400">次</span>
            </div>
            <p class="text-[11px] text-brand-600 dark:text-brand-400">
              从 {{ form.date || '今天' }} 起，每 {{ form.repeatInterval || 1 }} {{ form.repeatUnit === 'day' ? '天' : form.repeatUnit === 'week' ? '周' : '个月' }} 生成一条，共 {{ form.repeatCount || 2 }} 次
            </p>
          </div>
        </div>

        <!-- 接了微软待办就默认同步过去（用户要求）；不想传的可以取消勾选 -->
        <div
          v-if="!isEdit && state.msConnected"
          class="space-y-2 rounded-xl bg-brand-50/70 p-2.5 text-xs dark:bg-brand-500/10"
        >
          <label class="flex items-center gap-2">
            <input v-model="form.toMs" type="checkbox" data-testid="custom-to-ms" @change="onToMsChange" />
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

        <!-- 批量修改应用范围切换（当编辑对象为批量生成的重复任务时展示） -->
        <div
          v-if="isEdit && editingRecurrence"
          data-testid="batch-scope-selector"
          class="space-y-2 rounded-xl border border-indigo-100 bg-indigo-50/60 p-2.5 text-xs dark:border-indigo-900/40 dark:bg-indigo-950/20"
        >
          <div class="flex items-center gap-1.5 font-semibold text-indigo-700 dark:text-indigo-300">
            <RotateCcw :size="13" />
            <span>此任务属于重复系列，请选择修改/删除范围：</span>
          </div>
          <div class="grid grid-cols-3 gap-1.5 text-center text-[11px]">
            <button
              type="button"
              data-testid="scope-single"
              class="rounded-lg border px-2 py-1.5 transition-colors"
              :class="
                form.applyScope === 'single'
                  ? 'border-indigo-600 bg-indigo-600 font-semibold text-white'
                  : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
              "
              @click="form.applyScope = 'single'"
            >
              仅当前日程
            </button>
            <button
              type="button"
              data-testid="scope-future"
              class="rounded-lg border px-2 py-1.5 transition-colors"
              :class="
                form.applyScope === 'future'
                  ? 'border-indigo-600 bg-indigo-600 font-semibold text-white'
                  : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
              "
              @click="form.applyScope = 'future'"
            >
              此项及后续
            </button>
            <button
              type="button"
              data-testid="scope-all"
              class="rounded-lg border px-2 py-1.5 transition-colors"
              :class="
                form.applyScope === 'all'
                  ? 'border-indigo-600 bg-indigo-600 font-semibold text-white'
                  : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
              "
              @click="form.applyScope = 'all'"
            >
              全部重复项
            </button>
          </div>
          <p class="text-[10px] text-indigo-600/90 dark:text-indigo-300/80">
            {{
              form.applyScope === 'single'
                ? '只改动这一天，其他周期的任务保持不变'
                : form.applyScope === 'future'
                ? `将同步修改当前（第 ${editingRecurrence.index} 次）及后续所有重复日程`
                : `将对该系列全部 ${editingRecurrence.total} 次重复日程同步修改`
            }}
          </p>
        </div>

        <p v-if="error" class="text-xs text-rose-600 dark:text-rose-400">{{ error }}</p>

        <div class="flex items-center gap-2 pt-1">
          <button v-if="isEdit" type="button" class="btn-ghost !text-rose-600 dark:!text-rose-400" :disabled="busy" @click="remove">
            {{ removeLabel }}
          </button>
          <button type="submit" class="btn-primary ml-auto" :disabled="busy || !form.title.trim()" data-testid="custom-save">
            {{ busy ? '保存中…' : isEdit ? '保存' : form.toMs ? '建到微软待办' : '添加' }}
          </button>
        </div>
        <p class="text-[11px] leading-relaxed text-slate-400">
          {{ footerNote }}
        </p>
      </form>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Pencil, RotateCcw, X } from 'lucide-vue-next'
import { closeCustomEditor, fetchMsLists, notify, removeCustomEvent, saveCustomEvent, saveMsTask, state } from '../store'

const busy = ref(false)
const error = ref('')
const form = reactive({
  title: '',
  date: '',
  start: '09:00',
  /* 结束时间改成一个「时长」：0h = 不写结束时间（课表里就画一条线）。
     用户不想手算 18:30 + 1.5h，选个时长就完了。 */
  duration: 0,
  allDay: false,
  location: '',
  description: '',
  /* 接没接微软待办决定默认值：接了默认同步过去，可以直接取消（只存本站） */
  toMs: false,
  listId: '',
  /* 重复任务支持：每几天/周/月重复一次，共生成几次 */
  recurring: false,
  repeatInterval: 1,
  repeatUnit: 'week',
  repeatCount: 5,
  /* 批量修改/删除范围：single (仅当前) | future (当前及后续) | all (全系列) */
  applyScope: 'single',
})

const editing = computed(() => state.customEditor.event)
const isEdit = computed(() => Boolean(editing.value))
const editingRecurrence = computed(() => editing.value?.recurrence)
// 来源决定这个弹窗的语气：自定义日程可以整个删掉；课表 / 待办是外部来源，
// 只能「改这一条」或「从日历里移除」（同步永远不动用户改过的字段）。
const source = computed(() => editing.value?.source || 'custom')
const isCustom = computed(() => source.value === 'custom')
const editorTitle = computed(() => {
  if (!isEdit.value) return '新建日程'
  if (source.value === 'tju_schedule') return '编辑这节课'
  if (source.value === 'microsoft_todo') return '编辑这条待办'
  return '编辑日程'
})
const removeLabel = computed(() => {
  if (isCustom.value) return '删除'
  return source.value === 'tju_schedule' ? '移除这次课' : '从日历里移除'
})
const footerNote = computed(() => {
  if (source.value === 'tju_schedule') {
    return '改的是这一周的这节课（还可以顺手写备注，比如带什么书）；改过的字段不会被下次课表同步覆盖。'
  }
  if (source.value === 'microsoft_todo') {
    return '改动会推回微软待办，手机上的待办跟着变；「从日历里移除」只在日历里拿掉，待办 App 里还留着。'
  }
  if (isEdit.value) {
    return '纯自定义日程归「自定义」来源，教务/微软同步永远不会删它或改它。'
  }
  return '纯自定义日程归「自定义」来源，教务/微软同步永远不会删它或改它。'
})

function today() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/* 下拉里能选的档位；反推时长时也往这些档位上靠，免得算出个 1.4999 选不中 */
const DURATION_OPTIONS = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 6, 8]

/** 从「开始 / 结束」两个 `YYYY-MM-DDTHH:MM` 串算时长（小时），坏数据给 0。 */
function durationOf(start, end) {
  if (!start || !end) return 0
  const hours = (new Date(end) - new Date(start)) / 3600000
  if (!Number.isFinite(hours) || hours <= 0) return 0
  return DURATION_OPTIONS.reduce(
    (best, option) => (Math.abs(option - hours) < Math.abs(best - hours) ? option : best),
    0,
  )
}

/** `${date}T${hhmm}` 往后推 hours 小时，返回同格式串（跨天照算）。 */
function addHours(date, hhmm, hours) {
  const [hour, minute] = hhmm.split(':').map(Number)
  const pad = (value) => String(value).padStart(2, '0')
  const base = new Date(
    `${date}T${pad(hour || 0)}:${pad(minute || 0)}:00`,
  )
  const later = new Date(base.getTime() + Math.round(hours * 3600000))
  return `${later.getFullYear()}-${pad(later.getMonth() + 1)}-${pad(later.getDate())}T${pad(
    later.getHours(),
  )}:${pad(later.getMinutes())}:00`
}

watch(
  () => [state.customEditor.open, state.customEditor.event],
  async () => {
    if (!state.customEditor.open) return
    error.value = ''
    const event = state.customEditor.event
    // start_time 已经是本地时区（后端按 Asia/Shanghai 回），前 16 位即 date+T HH:MM
    const start = (event?.start_time || '').slice(0, 16)
    form.title = event?.title || ''
    form.date = start ? start.slice(0, 10) : today()
    form.start = start ? start.slice(11, 16) : '09:00'
    // 结束时间不再单独编辑，由「时长」反推：老数据有 end_time 就算出来，没有就是 0h
    form.duration = durationOf(start, (event?.end_time || '').slice(0, 16))
    // 课表 / 待办这些外部来源没有「全天」开关（勾了也发不出去），时间照常可改
    const external = Boolean(event) && event.source !== 'custom'
    form.allDay = external ? false : Boolean(event?.is_deadline)
    form.location = event?.location || ''
    form.description = event?.description || ''
    form.listId = ''
    form.recurring = false
    form.repeatInterval = 1
    form.repeatUnit = 'week'
    form.repeatCount = 5
    form.applyScope = 'single'
    // 新建时探测微软待办列表；默认不强行捆绑外部网络，遵循用户明确偏好且微软服务真实畅通
    const msConnected = await fetchMsLists()
    let prefToMs = false
    try {
      const stored = localStorage.getItem('campushub.pref.toMs')
      prefToMs = stored !== null ? (stored === '1' && msConnected) : false
    } catch (e) {
      prefToMs = false
    }
    form.toMs = event ? false : prefToMs
  },
  { immediate: true },
)

function onToMsChange() {
  try {
    localStorage.setItem('campushub.pref.toMs', form.toMs ? '1' : '0')
  } catch (e) {}
}

function close() {
  closeCustomEditor()
}

async function submit() {
  error.value = ''
  busy.value = true
  // 时长换算成结束时刻；0h = 不写结束时间（课表里画一条线）
  const endTime =
    !form.allDay && form.duration > 0 ? addHours(form.date, form.start, form.duration) : null

  const payload = {
    title: form.title.trim(),
    start_time: `${form.date}T${form.allDay ? '00:00' : form.start}:00`,
    // end_time 传 null 表示「不改」，所以想清空结束时间得靠 clear_end_time
    end_time: endTime,
    clear_end_time: !endTime,
    duration_hours: form.allDay ? 0 : form.duration,
    // 空串 = 清空（null 会被后端当成「这一项不动」，地点和备注就删不掉了）
    location: form.location.trim(),
    description: form.description.trim(),
  }
  if (!isEdit.value && form.recurring) {
    payload.repeat_frequency = form.repeatUnit
    payload.repeat_interval = form.repeatInterval || 1
    payload.repeat_count = Math.max(1, Math.min(60, form.repeatCount || 1))
  }
  if (isEdit.value && editingRecurrence.value) {
    payload.apply_scope = form.applyScope || 'single'
  }
  // 只有自定义日程有「全天 / 当截止日期用」这个概念；外部来源发过去也会被忽略
  if (isCustom.value) payload.is_deadline = form.allDay

  // 勾了「同步到微软待办」：先建到 To Do，后端同时把它落成一条本地日程
  if (form.toMs && !isEdit.value) {
    const totalRuns = form.recurring ? Math.max(1, Math.min(60, form.repeatCount || 1)) : 1
    let msResult = { ok: false }
    for (let i = 0; i < totalRuns; i++) {
      let curDate = form.date
      if (i > 0) {
        const [y, m, d] = form.date.split('-').map(Number)
        const dateObj = new Date(y, m - 1, d)
        if (form.repeatUnit === 'day') dateObj.setDate(dateObj.getDate() + i * (form.repeatInterval || 1))
        else if (form.repeatUnit === 'week') dateObj.setDate(dateObj.getDate() + i * (form.repeatInterval || 1) * 7)
        else if (form.repeatUnit === 'month') dateObj.setMonth(dateObj.getMonth() + i * (form.repeatInterval || 1))
        const pad = (n) => String(n).padStart(2, '0')
        curDate = `${dateObj.getFullYear()}-${pad(dateObj.getMonth() + 1)}-${pad(dateObj.getDate())}`
      }
      msResult = await saveMsTask({
        title: form.title.trim(),
        // To Do 是「截止时间」制：全天日程按早上 9 点提醒
        start: `${curDate}T${form.allDay ? '09:00' : form.start}:00`,
        // 待办任务没有地点字段：后端把地点并进备注（读回来时再摘出去当 location）
        location: form.location.trim() || null,
        note: form.description.trim() || null,
        list_id: form.listId || null,
        importance: form.allDay ? 'high' : null,
        // 有结束时间的话，时长也写进备注（`⏱ 1h`），网页端会把那行隐藏掉
        duration_hours: form.allDay ? 0 : form.duration,
      })
    }

    if (msResult.ok) {
      busy.value = false
      return
    }

    // 关键降级兜底：微软待办如果网络超时或写入失败，绝不丢弃用户的日程，自动无缝保存为本站日程！
    const fallbackSaved = await saveCustomEvent(payload)
    busy.value = false
    if (fallbackSaved) {
      notify(`已为您保存到本地日程；同步到微软待办失败（${msResult.error || '网络连接超时'}）`, 'warn', { duration: 6000 })
    } else {
      error.value = '保存失败，请检查网络后重试'
    }
    return
  }

  const saved = await saveCustomEvent(payload)
  busy.value = false
  if (!saved) error.value = '没保存成功，看一眼上面的提示'
}

async function remove() {
  if (!editing.value) return
  busy.value = true
  const removed = await removeCustomEvent(editing.value.id, {
    apply_scope: form.applyScope || 'single',
  })
  busy.value = false
  if (!removed) error.value = '删除失败，看一眼上面的提示'
}
</script>
