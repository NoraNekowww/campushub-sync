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

        <!-- 自定义日程类型二选一：待办/DDL（带倒计时，划掉完成） vs 课程/活动（有起止时长，上完自动隐退） -->
        <div v-if="isCustom || !isEdit" class="grid grid-cols-2 gap-2 p-1 bg-slate-100/80 dark:bg-slate-800/60 rounded-xl text-xs">
          <button
            type="button"
            class="flex flex-col items-center justify-center gap-1 py-2 px-1 rounded-lg transition-all"
            :class="form.kind === 'deadline'
              ? 'bg-white dark:bg-slate-900 shadow-sm text-brand-600 dark:text-brand-400 font-semibold border border-brand-200 dark:border-brand-700/60'
              : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'"
            @click="setKind('deadline')"
          >
            <div class="flex items-center gap-1.5 font-medium">
              <Clock :size="13" />
              <span>待办 / DDL</span>
            </div>
            <span class="text-[10px] font-normal opacity-75">带倒计时，划掉完成</span>
          </button>
          <button
            type="button"
            class="flex flex-col items-center justify-center gap-1 py-2 px-1 rounded-lg transition-all"
            :class="form.kind === 'class'
              ? 'bg-white dark:bg-slate-900 shadow-sm text-brand-600 dark:text-brand-400 font-semibold border border-brand-200 dark:border-brand-700/60'
              : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'"
            @click="setKind('class')"
          >
            <div class="flex items-center gap-1.5 font-medium">
              <GraduationCap :size="13" />
              <span>课程 / 活动日程</span>
            </div>
            <span class="text-[10px] font-normal opacity-75">上完自动隐退，可划掉</span>
          </button>
        </div>

        <label class="block space-y-1 text-xs">
          <span class="text-slate-500 dark:text-slate-400">标题</span>
          <input
            v-model="form.title"
            class="input"
            required
            maxlength="120"
            :placeholder="form.kind === 'deadline' ? '例如：交大作业 / 实验报告' : '例如：临时加课 / 组会 / 自习'"
            data-testid="custom-title"
          />
        </label>

        <div class="grid grid-cols-2 gap-2">
          <label class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">{{ form.kind === 'deadline' ? '截止日期' : '活动日期' }}</span>
            <input v-model="form.date" type="date" class="input" required data-testid="custom-date" />
          </label>
          <label class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">地点（可空）</span>
            <input v-model="form.location" class="input" maxlength="80" placeholder="45楼B203" />
          </label>
        </div>

        <div class="grid grid-cols-2 gap-2">
          <label class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">{{ form.kind === 'deadline' ? '开始 / 截止时间' : '开始时间' }}</span>
            <input v-model="form.start" type="time" class="input" :disabled="form.allDay" required />
          </label>
          <label v-if="isCustom || !isEdit" class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">{{ form.kind === 'deadline' ? '时限模式' : '活动时长' }}</span>
            <select
              v-if="form.kind === 'class'"
              v-model.number="form.duration"
              class="input"
              data-testid="custom-duration"
            >
              <option :value="0.5">0.5 小时（30分钟）</option>
              <option :value="1">1 小时</option>
              <option :value="1.5">1.5 小时（标准大课）</option>
              <option :value="2">2 小时</option>
              <option :value="2.5">2.5 小时</option>
              <option :value="3">3 小时</option>
              <option :value="4">4 小时（半天活动）</option>
              <option :value="6">6 小时</option>
              <option :value="8">8 小时（全天活动）</option>
            </select>
            <div v-else class="flex items-center h-[34px] px-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/40">
              <label class="flex items-center gap-1.5 cursor-pointer text-xs">
                <input v-model="form.allDay" type="checkbox" class="accent-brand-600" />
                <span class="text-slate-600 dark:text-slate-300">全天 / 当截止日期用</span>
              </label>
            </div>
          </label>
          <label v-else class="block space-y-1 text-xs">
            <span class="text-slate-500 dark:text-slate-400">活动时长</span>
            <select
              v-model.number="form.duration"
              class="input"
              data-testid="custom-duration"
            >
              <option :value="0.5">0.5 小时</option>
              <option :value="1">1 小时</option>
              <option :value="1.5">1.5 小时</option>
              <option :value="2">2 小时</option>
              <option :value="2.5">2.5 小时</option>
              <option :value="3">3 小时</option>
              <option :value="4">4 小时</option>
            </select>
          </label>
        </div>

        <div v-if="form.kind === 'class'" class="rounded-lg bg-slate-50 dark:bg-slate-800/50 px-2.5 py-1.5 text-[11px] text-slate-500 dark:text-slate-400">
          💡 <strong>自动隐退说明</strong>：课程型日程上完（到达结束时间）后会自动从今日视图隐退；亦可在日程卡片上随时手动点击勾选划掉。
        </div>

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
            {{ busy ? '保存中…' : isEdit ? '保存' : '添加' }}
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
import { Clock, GraduationCap, Pencil, RotateCcw, X } from 'lucide-vue-next'
import { closeCustomEditor, removeCustomEvent, saveCustomEvent, state } from '../store'

const busy = ref(false)
const error = ref('')
const form = reactive({
  title: '',
  date: '',
  start: '09:00',
  /* kind: 'deadline'（带倒计时待办） | 'class'（活动日程，上完自动隐退） */
  kind: 'deadline',
  /* 结束时间由「时长」推算：0h = 无结束时间 */
  duration: 0,
  allDay: false,
  location: '',
  description: '',
  /* 重复任务支持：每几天/周/月重复一次，共生成几次 */
  recurring: false,
  repeatInterval: 1,
  repeatUnit: 'week',
  repeatCount: 5,
  /* 批量修改/删除范围：single (仅当前) | future (当前及后续) | all (全系列) */
  applyScope: 'single',
})

function setKind(k) {
  form.kind = k
  if (k === 'deadline') {
    form.duration = 0
  } else {
    form.allDay = false
    if (!form.duration || form.duration <= 0) form.duration = 1.5
  }
}

const editing = computed(() => state.customEditor.event)
const isEdit = computed(() => Boolean(editing.value))
const editingRecurrence = computed(() => editing.value?.recurrence)
// 来源决定这个弹窗的语气：自定义日程可以整个删掉；课表是外部来源
const source = computed(() => editing.value?.source || 'custom')
const isCustom = computed(() => source.value === 'custom')
const editorTitle = computed(() => {
  if (!isEdit.value) return '新建日程'
  if (source.value === 'tju_schedule') return '编辑这节课'
  if (editing.value?.is_deadline || source.value === 'microsoft_todo') return '编辑这条待办'
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
  return '自定义日程安全存储在服务器端数据库中，支持本地无网长期缓存离线查看。'
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
    const isDdl = event ? Boolean(event.is_deadline) : true
    form.kind = isDdl ? 'deadline' : 'class'
    form.title = event?.title || ''
    form.date = start ? start.slice(0, 10) : today()
    form.start = start ? start.slice(11, 16) : '09:00'
    // 结束时间由「时长」反推：活动型日程默认 1.5h
    const calculatedDuration = durationOf(start, (event?.end_time || '').slice(0, 16))
    form.duration = calculatedDuration > 0 ? calculatedDuration : (form.kind === 'class' ? 1.5 : 0)
    // 课表外部来源没有「全天」开关，时间照常可改
    const external = Boolean(event) && event.source !== 'custom'
    form.allDay = external ? false : (form.kind === 'deadline' && Boolean(event?.is_deadline && !event?.start_time?.slice(11, 16)))
    form.location = event?.location || ''
    form.description = event?.description || ''
    form.recurring = false
    form.repeatInterval = 1
    form.repeatUnit = 'week'
    form.repeatCount = 5
    form.applyScope = 'single'
  },
  { immediate: true },
)

function close() {
  closeCustomEditor()
}

async function submit() {
  error.value = ''
  busy.value = true
  const isDdl = form.kind === 'deadline' || form.allDay
  // 时长换算成结束时刻；活动型日程自动算结束时间，上完自动隐退
  const endTime =
    !isDdl && form.duration > 0 ? addHours(form.date, form.start, form.duration) : null

  const payload = {
    title: form.title.trim(),
    start_time: `${form.date}T${form.allDay ? '00:00' : form.start}:00`,
    // end_time 传 null 表示「不改」，所以想清空结束时间得靠 clear_end_time
    end_time: endTime,
    clear_end_time: !endTime,
    duration_hours: isDdl ? 0 : form.duration,
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
  if (isCustom.value || !isEdit.value) payload.is_deadline = isDdl

  const saved = await saveCustomEvent(payload)
  busy.value = false
  if (!saved) error.value = '没保存成功，请检查网络后重试'
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
