<template>
  <Teleport to="body">
    <div
      v-if="event"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/40 backdrop-blur-md animate-fade-in"
      data-testid="class-detail"
      @click.self="close"
    >
      <div
        class="max-h-[88vh] w-full max-w-lg overflow-y-auto rounded-3xl p-5 shadow-2xl transition-all
               border border-white/60 bg-white/80 dark:border-white/10 dark:bg-slate-900/85
               backdrop-blur-2xl [transform:translateZ(0)]"
      >
        <header class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <!-- 格子里只能挤下一行标题，这里放开：点一下就是为了看清楚 -->
            <p class="text-lg font-semibold leading-snug" data-testid="class-detail-title">
              {{ event.title }}
            </p>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400" data-testid="class-detail-time">
              {{ timeRange }}
            </p>
            <p v-if="event.location" class="mt-0.5 text-xs text-slate-400">
              {{ event.location }}
            </p>
          </div>
          <button class="btn-ghost !px-2" title="关闭" data-testid="class-detail-close" @click="close">
            <X :size="16" />
          </button>
        </header>

        <dl
          class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl bg-slate-50 p-3 text-xs dark:bg-slate-800/50"
        >
          <div v-if="periodText" class="flex gap-1.5">
            <dt class="shrink-0 text-slate-400">节次</dt>
            <dd>{{ periodText }}</dd>
          </div>
          <div v-if="event.week" class="flex gap-1.5">
            <dt class="shrink-0 text-slate-400">周次</dt>
            <dd>第 {{ event.week }} 周</dd>
          </div>
          <div class="flex gap-1.5">
            <dt class="shrink-0 text-slate-400">来源</dt>
            <dd class="min-w-0 truncate">{{ sourceText }}</dd>
          </div>
          <div v-if="event.reminder_minutes !== null && event.reminder_minutes !== undefined" class="flex gap-1.5">
            <dt class="shrink-0 text-slate-400">提醒</dt>
            <dd>{{ reminderText }}</dd>
          </div>
        </dl>

        <!-- 备注：老师、地点这些能编进 description 的都在这里；地点行已经被上层摘走了 -->
        <p
          v-if="noteText"
          class="mt-3 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-xs leading-relaxed dark:bg-slate-800/50"
          data-testid="class-detail-note"
        >
          {{ noteText }}
        </p>

        <!-- 云端附件列表（支持点击直接下载/在线预览） -->
        <div
          v-if="event.attachments && event.attachments.length"
          class="mt-3 space-y-1.5 rounded-xl bg-slate-50 p-3 text-xs dark:bg-slate-800/50"
          data-testid="class-detail-attachments"
        >
          <div class="flex items-center gap-1.5 font-medium text-slate-700 dark:text-slate-200">
            <Paperclip :size="13" class="text-brand-600 dark:text-brand-400" />
            <span>云端附件 ({{ event.attachments.length }})</span>
          </div>
          <div class="space-y-1 pt-1">
            <a
              v-for="att in event.attachments"
              :key="att.id"
              :href="api.attachmentUrl(att.id)"
              target="_blank"
              class="flex items-center justify-between gap-2 rounded-lg border border-slate-200/80 bg-white px-2.5 py-1.5 transition-colors hover:border-brand-300 hover:bg-brand-50/50 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500/40"
              :title="`下载附件：${att.name}`"
            >
              <div class="flex min-w-0 items-center gap-1.5">
                <FileText :size="13" class="shrink-0 text-slate-400" />
                <span class="truncate font-medium text-slate-700 dark:text-slate-200">{{ att.name }}</span>
              </div>
              <span class="shrink-0 font-mono text-[10px] text-slate-400">{{ formatAttachmentSize(att.size) }}</span>
            </a>
          </div>
        </div>

        <div class="mt-4 flex items-center gap-2">
          <button
            type="button"
            class="btn-ghost !text-amber-600 hover:!bg-amber-50 dark:!text-amber-400 dark:hover:!bg-amber-950/30 flex items-center gap-1 text-xs"
            @click="toggleStar"
          >
            <Star :size="14" :class="isImportant ? 'fill-current' : ''" />
            <span>{{ isImportant ? '取消重点' : '标为重点' }}</span>
          </button>
          <button
            class="btn-ghost !text-rose-600 dark:!text-rose-400"
            :disabled="busy"
            data-testid="class-detail-remove"
            @click="remove"
          >
            {{ removeLabel }}
          </button>
          <!-- 课表来源的课不给编辑：教务每次同步都会把本地改动盖回去（用户原话
               「编辑了没地方显示」）。要改就在教务/微软那边改。 -->
          <button
            v-if="editable"
            class="btn-primary ml-auto"
            data-testid="class-detail-edit"
            @click="edit"
          >
            <Pencil :size="14" />
            编辑
          </button>
          <p v-else class="ml-auto text-[11px] text-slate-400" data-testid="class-detail-locked">
            课表同步来的课不可编辑
          </p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, ref } from 'vue'
import { FileText, Paperclip, Pencil, Star, X } from 'lucide-vue-next'
import { api } from '../api'
import { isImportantEvent, openCustomEditor, removeEvent, toggleImportantEvent } from '../store'
import { splitNoteMeta } from '../utils/note'

const isImportant = computed(() => isImportantEvent(props.event))

function toggleStar() {
  if (props.event) {
    toggleImportantEvent(props.event)
  }
}

function formatAttachmentSize(size) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

const props = defineProps({
  event: { type: Object, default: null },
})
const emit = defineEmits(['close'])

const busy = ref(false)

const pad = (value) => String(value).padStart(2, '0')

/** `2026-10-13T18:30:00` -> `18:30`；只有日期的时间（00:00）不写具体钟点。 */
function clock(value) {
  if (!value) return ''
  const text = String(value)
  const hhmm = text.slice(11, 16)
  if (!hhmm) return ''
  return hhmm === '00:00' ? '' : hhmm
}

/** 只给日期的条目（微软待办常见）不显示「00:00」，免得看着像半夜的任务。 */
const dateText = computed(() => {
  const start = props.event?.start_time || ''
  const ymd = start.slice(0, 10)
  if (!ymd) return ''
  const [, mm, dd] = ymd.split('-')
  return `${Number(mm)}月${Number(dd)}日`
})

const timeRange = computed(() => {
  const event = props.event
  if (!event) return ''
  const from = clock(event.start_time)
  const to = clock(event.end_time)
  if (!from) return `${dateText.value} · 全天`
  return to ? `${dateText.value} ${from}–${to}` : `${dateText.value} ${from}`
})

const periodText = computed(() => {
  // periods 是**扁平的一对**起止节次，如 [4, 5]（一节课就是 [4]）——
  // 别写成 spans.map(([a, b]) => ...)，那会去解构数字 4。
  const spans = props.event?.periods
  if (Array.isArray(spans) && spans.length) {
    const from = spans[0]
    const to = spans.length > 1 ? spans[spans.length - 1] : from
    return from === to ? `第 ${from} 节` : `第 ${from}-${to} 节`
  }
  const raw = props.event?.period_text || props.event?.periods
  return typeof raw === 'string' ? raw : ''
})

const sourceText = computed(() => {
  const source = props.event?.source
  if (source === 'tju_schedule') return '天津大学课表'
  return '个人日程'
})

const reminderText = computed(() => {
  const minutes = Number(props.event?.reminder_minutes)
  if (!Number.isFinite(minutes)) return ''
  if (minutes === 0) return '准时提醒'
  if (minutes < 60) return `提前 ${minutes} 分钟`
  const hours = minutes / 60
  return `提前 ${Number.isInteger(hours) ? hours : hours.toFixed(1)} 小时`
})

/** 备注里除了地点行，还有「时长」那行也是我们自己写进去的，不往回显示。 */
const noteText = computed(() => splitNoteMeta(props.event?.description || '').note)

// 课表来源的课不给编辑：教务每次同步都会把本地改动盖回去（用户原话「编辑了没地方显示」）。
const editable = computed(() => props.event?.source !== 'tju_schedule')

const removeLabel = computed(() => {
  const source = props.event?.source
  if (source === 'tju_schedule') return '移除这次课'
  return '删除'
})

function close() {
  emit('close')
}

function edit() {
  const event = props.event
  close()
  openCustomEditor(event)
}

async function remove() {
  const event = props.event
  if (!event) return
  busy.value = true
  await removeEvent(event)
  busy.value = false
  close()
}

/* pad 目前只在日期拼接里用到，留着方便以后加「星期几」*/
void pad
</script>
