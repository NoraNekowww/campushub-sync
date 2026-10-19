<script>
// 同一屏只留一张卡片停在「露出删除」的状态：滑开第二张时，第一张自动收回。
let currentCloser = null
function claimSwipe(closer) {
  if (currentCloser && currentCloser !== closer) currentCloser()
  currentCloser = closer
}
function releaseSwipe(closer) {
  if (currentCloser === closer) currentCloser = null
}
</script>

<template>
  <div
    class="swipe-row relative overflow-hidden rounded-2xl"
    data-testid="event-card-row"
    @focusin="revealForFocus"
  >
    <!-- 卡片底下那层：往左或往右拖开才看得到的「删除」 -->
    <div
      class="absolute inset-y-0 flex items-center px-1.5"
      :class="offset > 0 ? 'left-0' : 'right-0'"
    >
      <button
        type="button"
        class="inline-flex h-[calc(100%-0.75rem)] min-w-[72px] flex-col items-center justify-center gap-1
               rounded-xl bg-rose-500 px-3 text-xs font-semibold text-white
               transition-colors hover:bg-rose-600 disabled:opacity-60"
        :aria-label="`删除日程：${event.title}`"
        data-testid="swipe-delete"
        :disabled="busy"
        @click.stop="remove"
      >
        <Trash2 :size="15" />
        删除
      </button>
    </div>

    <div class="swipe-pane" :style="cardStyle" data-testid="event-swipe-pane">
      <article
        ref="cardEl"
        class="card animate-fade-up"
        :class="[accentBar, event.status === 'completed' ? 'opacity-60' : '']"
        data-testid="event-card"
        :data-kind="event.is_deadline ? 'deadline' : 'class'"
        :data-source="event.source"
        :data-status="event.status"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @click.capture="onClickCapture"
      >
      <div class="flex gap-3 p-3.5">
        <!-- real checkbox for deadlines (native focus/space-key/AT semantics) -->
        <label v-if="event.is_deadline" class="mt-0.5 shrink-0 cursor-pointer" :title="event.status === 'completed' ? '标记为未完成' : '标记为已完成'">
          <input
            type="checkbox"
            :checked="event.status === 'completed'"
            :aria-label="`${event.status === 'completed' ? '标记为未完成' : '标记为已完成'}：${event.title}`"
            class="peer sr-only"
            @change="$emit('toggle', event)"
          />
          <CheckCircle2 v-if="event.status === 'completed'" :size="20" class="text-emerald-500" />
          <Circle
            v-else
            :size="20"
            class="text-slate-300 transition-colors peer-focus-visible:text-brand-500 dark:text-slate-600"
          />
        </label>

        <div
          class="min-w-0 flex-1"
          :class="collapsible ? 'cursor-pointer' : ''"
          :role="collapsible ? 'button' : undefined"
          :tabindex="collapsible ? 0 : undefined"
          :aria-expanded="collapsible ? expanded : undefined"
          data-testid="event-body"
          @click="toggleExpanded"
          @keydown.enter.prevent="toggleExpanded"
          @keydown.space.prevent="toggleExpanded"
        >
          <div class="flex items-start gap-2">
            <!-- 标题要能看全：长课名/长待办名换行显示，而不是被截成一行省略号 -->
            <h3
              class="min-w-0 flex-1 break-words text-sm font-semibold leading-snug"
              :class="event.status === 'completed' ? 'line-through decoration-slate-400' : ''"
            >
              {{ event.title }}
            </h3>
            <span
              v-if="event.is_deadline && priority"
              class="chip shrink-0 border-transparent"
              :class="priority.classes"
            >
              {{ priority.label }}
            </span>
            <ChevronDown
              v-if="collapsible"
              :size="15"
              class="mt-0.5 shrink-0 text-slate-400 transition-transform"
              :class="expanded ? 'rotate-180' : ''"
              aria-hidden="true"
            />
          </div>

          <!-- 折叠态就「时间区间 + 地点」：课表卡片一排排扫过去要能一眼看完 -->
          <div
            v-if="collapsible"
            class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400"
            data-testid="event-basics"
          >
            <span class="inline-flex items-center gap-1">
              <Clock :size="12" />{{ timeLabel(event.start_time) }}–{{ endLabel }}
            </span>
            <span v-if="noteLocation" class="inline-flex items-center gap-1">
              <MapPin :size="12" />{{ noteLocation }}
            </span>
            <!-- 折叠态也要能改：调课、换教室、加备注都从这里进 -->
            <button
              v-if="event.source !== 'tju_schedule'"
              class="inline-flex items-center gap-1 text-slate-400 hover:text-brand-600 dark:hover:text-brand-400"
              :aria-label="`编辑：${event.title}`"
              data-testid="edit-custom-event"
              @click.stop="openCustomEditor(event)"
            >
              <Pencil :size="12" />编辑
            </button>
          </div>

          <div
            v-else
            class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400"
          >
            <span v-if="event.is_deadline" class="inline-flex items-center gap-1">
              <Clock :size="12" />{{ deadlineLabel }}
            </span>
            <span v-else class="inline-flex items-center gap-1">
              <Clock :size="12" />{{ timeLabel(event.start_time) }}–{{ endLabel }}
              <span v-if="durationText" class="text-slate-400">· {{ durationText }}</span>
            </span>
            <span v-if="noteLocation" class="inline-flex items-center gap-1">
              <MapPin :size="12" />{{ noteLocation }}
            </span>
            <span v-if="countdownInfo" class="chip border-transparent" :class="countdownClasses">
              <AlertTriangle v-if="countdownInfo.tone === 'danger'" :size="11" />
              {{ countdownInfo.text }}
            </span>
            <button
              v-if="event.source !== 'tju_schedule'"
              class="inline-flex items-center gap-1 text-slate-400 hover:text-brand-600 dark:hover:text-brand-400"
              :aria-label="`编辑：${event.title}`"
              data-testid="edit-custom-event"
              @click.stop="openCustomEditor(event)"
            >
              <Pencil :size="12" />编辑
            </button>
          </div>

          <!-- 点开才给的详情 -->
          <dl
            v-if="collapsible && expanded"
            class="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-slate-100 pt-2.5 text-xs text-slate-500 dark:border-slate-700/60 dark:text-slate-400"
            data-testid="event-detail"
          >
            <div v-if="periodLabel(event.periods)" class="flex gap-1.5">
              <dt class="shrink-0 text-slate-400">节次</dt>
              <dd>{{ periodLabel(event.periods) }}</dd>
            </div>
            <div v-if="durationPlain" class="flex gap-1.5">
              <dt class="shrink-0 text-slate-400">时长</dt>
              <dd>{{ durationPlain }}</dd>
            </div>
            <div v-if="event.teacher" class="flex gap-1.5">
              <dt class="shrink-0 text-slate-400">教师</dt>
              <dd class="min-w-0 truncate">{{ event.teacher }}</dd>
            </div>
            <div v-if="event.week" class="flex gap-1.5">
              <dt class="shrink-0 text-slate-400">周次</dt>
              <dd>第 {{ event.week }} 周</dd>
            </div>
            <div v-if="noteText && !event.teacher" class="col-span-2 flex gap-1.5">
              <dt class="shrink-0 text-slate-400">备注</dt>
              <dd class="min-w-0">{{ noteText }}</dd>
            </div>
          </dl>
        </div>
      </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Circle,
  Clock,
  GraduationCap,
  MapPin,
  Pencil,
  Trash2,
} from 'lucide-vue-next'
import { countdown, durationLabel, periodLabel, periodsShort, timeLabel } from '../utils/datetime'
import { splitNoteLocation } from '../utils/note'
import { openCustomEditor } from '../store'

const props = defineProps({ event: { type: Object, required: true } })
const emit = defineEmits(['toggle', 'remove'])

/* ----------------------------------------------- 折叠 / 展开（课表卡片） */

// 课表课程默认只露「时间区间 + 地点」，点一下才给教师、周次、节次这些。
// 待办那类卡片本来就是要做的事，信息一行就够，不折腾。
const collapsible = computed(() => props.event.source === 'tju_schedule' && !props.event.is_deadline)
const expanded = ref(false)

function toggleExpanded() {
  if (!collapsible.value) return
  expanded.value = !expanded.value
}

/* ------------------------------------------------------- 左右滑动删除 */

// 拖过这个距离就吸附到「已露出」，否则弹回原位
const THRESHOLD = 52
// 露出后的位移；再往同方向拖会有阻尼
const REVEAL = 96
const MAX = 128

const offset = ref(0)
const dragging = ref(false)
const busy = ref(false)
const cardEl = ref(null)

let pointerId = null
let startX = 0
let startY = 0
let baseOffset = 0
let axis = null
let movedDuringDrag = false
// 拖过之后那一次 click 不该落到卡片里的按钮上
let swallowClick = false

const cardStyle = computed(() => ({
  transform: `translateX(${offset.value}px)`,
  transition: dragging.value ? 'none' : 'transform 180ms ease',
  // 横向手势归我们，纵向留给页面滚动
  touchAction: 'pan-y',
}))

/* 只有落在输入控件上才不接管手势：手指从「划掉」「编辑」上开始滑也应该能滑开，
   那一次点击会被 swallowClick 吃掉（拖过之后不该再触发按钮）。 */
const GESTURE_BLOCKERS = 'input, textarea, select'

function onPointerDown(event) {
  if (busy.value) return
  if (event.pointerType === 'mouse' && event.button !== 0) return
  if (event.target?.closest?.(GESTURE_BLOCKERS)) return
  pointerId = event.pointerId
  startX = event.clientX
  startY = event.clientY
  baseOffset = offset.value
  axis = null
  movedDuringDrag = false
}

function onPointerMove(event) {
  if (pointerId === null || event.pointerId !== pointerId) return
  const dx = event.clientX - startX
  const dy = event.clientY - startY
  if (axis === null) {
    if (Math.hypot(dx, dy) < 8) return
    if (Math.abs(dx) <= Math.abs(dy)) {
      // 判定为纵向：交还给页面滚动，本次拖动作废
      pointerId = null
      return
    }
    axis = 'x'
    dragging.value = true
    try {
      cardEl.value?.setPointerCapture?.(pointerId)
    } catch {
      /* 老浏览器不支持指针捕获，不影响功能 */
    }
  }
  movedDuringDrag = true
  let next = baseOffset + dx
  if (next > MAX) next = MAX + (next - MAX) * 0.25
  if (next < -MAX) next = -MAX + (next + MAX) * 0.25
  offset.value = Math.round(next)
}

function onPointerUp(event) {
  if (pointerId === null || (event && event.pointerId !== pointerId)) return
  if (dragging.value) {
    const settled = Math.abs(offset.value) >= THRESHOLD ? Math.sign(offset.value) * REVEAL : 0
    offset.value = settled
    dragging.value = false
    if (movedDuringDrag) swallowClick = true
    if (settled !== 0) claimSwipe(close)
  }
  if (offset.value === 0) releaseSwipe(close)
  axis = null
  pointerId = null
}

function close() {
  offset.value = 0
  releaseSwipe(close)
}

function revealForFocus(event) {
  // 键盘 Tab 到「删除」上也要能看见它
  if (event.target?.dataset?.testid === 'swipe-delete' && offset.value === 0) {
    claimSwipe(close)
    offset.value = -REVEAL
  }
}

function onClickCapture(event) {
  if (swallowClick) {
    swallowClick = false
    event.stopPropagation()
    event.preventDefault()
    return
  }
  if (offset.value !== 0) {
    // 已露出时点卡片正文 = 收回
    event.stopPropagation()
    event.preventDefault()
    close()
  }
}

function remove() {
  busy.value = true
  close()
  emit('remove', props.event)
  busy.value = false
}

onBeforeUnmount(() => {
  releaseSwipe(close)
  if (revealed.value) offset.value = 0
})

const revealed = computed(() => offset.value !== 0)

/* ------------------------------------------------------------ 展示用 */

const SOURCE_LABELS = {
  microsoft_todo: 'Microsoft To Do',
  tju_schedule: '天津大学课表',
  custom: '自定义',
}

const sourceLabel = computed(() => SOURCE_LABELS[props.event.source] || props.event.source)

/* 待办任务没有地点字段，地点是并进备注的（`📍 45楼B203`）：摘出来当地点用，
   备注里只留用户自己写的那部分 —— 界面上不会重复出现那行文本。 */
const noteParts = computed(() => splitNoteLocation(props.event.description))
const noteLocation = computed(() => props.event.location || noteParts.value.location)
const noteText = computed(() => noteParts.value.note)
const sourceIcon = computed(() => (props.event.source === 'tju_schedule' ? GraduationCap : props.event.source === 'custom' ? Pencil : CalendarDays))
const accentBar = computed(() =>
  props.event.is_deadline
    ? 'border-l-4 border-l-rose-400 dark:border-l-rose-500'
    : 'border-l-4 border-l-brand-400 dark:border-l-brand-500',
)

const timeLabelSafe = timeLabel
const endLabel = computed(() => timeLabel(props.event.end_time) || '—')
const durationText = computed(() => durationLabel(props.event.start_time, props.event.end_time, props.event.periods))
// 展开区把「节次」单独列一行，时长就别再重复一遍节数
const durationPlain = computed(() => durationLabel(props.event.start_time, props.event.end_time, null))
const durationShort = computed(() => periodsShort(props.event.start_time, props.event.end_time, props.event.periods))

/* 能划掉的：待办 + 自定义 + 微软待办任务。课表课程不给划 —— 它不是"完成/未完成"语义。 */
const tickable = computed(
  () =>
    props.event.is_deadline ||
    props.event.source === 'custom' ||
    props.event.source === 'microsoft_todo',
)

const deadlineLabel = computed(() => {
  const date = new Date(props.event.start_time)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
})

const priority = computed(() => {
  const value = props.event.priority ?? 5
  if (value <= 2) return { label: '高', classes: 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300' }
  if (value <= 5) return { label: '中', classes: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300' }
  return { label: '低', classes: 'bg-slate-100 text-slate-600 dark:bg-slate-700/50 dark:text-slate-300' }
})

const countdownInfo = computed(() =>
  props.event.is_deadline && props.event.status !== 'completed' ? countdown(props.event.start_time) : null,
)
const countdownClasses = computed(() => {
  const tone = countdownInfo.value?.tone
  if (tone === 'danger') return 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300'
  if (tone === 'warn') return 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300'
  return 'bg-slate-100 text-slate-600 dark:bg-slate-700/50 dark:text-slate-300'
})
</script>
