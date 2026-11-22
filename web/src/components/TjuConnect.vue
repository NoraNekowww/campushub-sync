<template>
  <div class="space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800" data-testid="tju-connect">
    <header class="flex flex-wrap items-center gap-2">
      <GraduationCap :size="14" class="text-brand-600 dark:text-brand-400" />
      <h3 class="text-xs font-semibold">课表导入（教务系统）</h3>
      <span
        class="chip border-transparent"
        :class="
          imported
            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
            : 'bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300'
        "
      >
        {{ imported ? `已导入 ${meta.courses ?? 0} 门课` : '未导入' }}
      </span>
      <span
        v-if="jw.credentials_saved"
        class="chip border-transparent bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300"
        title="服务器上保存了教务凭据，用来免密刷新课表；可在下方管理里删除"
      >
        教务凭据已存服务器
      </span>
    </header>

    <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
      <template v-if="offline">
        <b>离线模式也能导入课表。</b>服务器只替你登录一次教务系统、把课表换算成事件，结果直接写进本机；
        <b>不建账号、不落库、不保存密码</b>（密码只在这一页的内存里活到导入结束）。
      </template>
      <template v-else>
        <b>填「学号 + 教务系统密码」点一次就行。</b>这条链路在服务器上直连教务系统
        （<code>sso.tju.edu.cn</code> 统一身份认证 → <code>classes.tju.edu.cn/eams</code>，公网可达，
        <b>不需要待在校园网里</b>）：验证码服务器先替你识别，认不出来时才让你手填一张图。
        密码会保存在服务器上用于以后自动刷新课表，随时可以在「高级」里删掉。
      </template>
    </p>

    <div class="grid grid-cols-2 gap-2">
      <input
        v-model="form.username"
        class="input text-xs"
        data-testid="jw-account"
        placeholder="学号"
        autocomplete="username"
      />
      <input
        v-model="form.password"
        class="input text-xs"
        type="password"
        data-testid="jw-password"
        placeholder="教务系统密码"
        autocomplete="current-password"
      />
    </div>

    <button
      class="btn-primary w-full !py-2 text-sm"
      data-testid="tju-oneclick"
      :disabled="busy"
      @click="oneClick"
    >
      <RefreshCw :size="14" />
      {{ busy ? '正在导入…' : imported ? '更新课表（一键）' : '一键导入课表' }}
    </button>

    <!-- 服务器 OCR 没认出验证码时，才让用户手填一次 -->
    <div
      v-if="captcha.image"
      class="space-y-2 rounded-xl bg-amber-50 p-2.5 dark:bg-amber-500/10"
      data-testid="jw-captcha"
    >
      <p class="text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">
        教务系统这次要求人工验证码（服务器自动识别没通过）。照着下图填，再点「提交并导入」：
      </p>
      <div class="flex items-center gap-2">
        <img
          :src="captcha.image"
          alt="教务系统验证码"
          class="h-[52px] rounded border border-amber-200 bg-white"
          data-testid="jw-captcha-img"
        />
        <input
          v-model="captcha.code"
          class="input w-24 text-center font-mono text-sm"
          maxlength="6"
          placeholder="4 位字符"
          data-testid="jw-captcha-code"
        />
        <button class="btn-primary !py-1.5 text-xs" :disabled="busy" @click="submitCaptcha">
          提交并导入
        </button>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-2 pt-0.5">
      <label class="btn-ghost cursor-pointer !py-1.5 text-xs">
        <Upload :size="13" /> 从本地 .ics 导入课表
        <input
          ref="icsInput"
          type="file"
          accept=".ics,text/calendar"
          class="hidden"
          data-testid="tju-ics-input"
          @change="onIcsFileSelected"
        />
      </label>
      <span class="text-[11px] text-slate-400 dark:text-slate-500">
        {{ offline ? '离线模式支持直选本地 .ics 导入' : '也可上传 .ics 日历文件' }}
      </span>
    </div>

    <!-- ------------------------------------------------ advanced / escape hatches -->
    <details class="rounded-xl bg-slate-50 p-2.5 dark:bg-slate-800/50">
      <summary class="cursor-pointer text-[11px] font-semibold">
        教务凭据管理与清除
      </summary>

      <div class="mt-2 space-y-2 rounded-xl bg-white p-2.5 dark:bg-slate-900/40">
        <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
          <template v-if="offline">
            离线模式的课表只存在本机：换设备、清缓存都会丢，重新导入一次即可；服务器上没有你的教务凭据可删。
          </template>
          <template v-else>
            教务账号与密码在首次导入后安全储存在服务器用于定时拉取最新课表。如需更换账号或清除课表，可在下方操作：
          </template>
        </p>
        <div class="flex flex-wrap gap-2 pt-1">
          <button
            v-if="jw.credentials_saved"
            class="btn-ghost !py-1.5 text-xs text-rose-500 hover:text-rose-600"
            data-testid="jw-forget"
            :disabled="busy"
            @click="forgetJwCredentials"
          >
            <Trash2 :size="13" /> 删除教务凭据（服务器）
          </button>
          <button
            class="btn-ghost !py-1.5 text-xs text-rose-500 hover:text-rose-600"
            :disabled="busy || !imported"
            @click="clearImport"
          >
            <Trash2 :size="13" /> 清除已导入课表
          </button>
        </div>
      </div>
    </details>

    <p
      v-if="status"
      class="rounded-xl p-2 text-[11px] leading-relaxed"
      :class="statusKind === 'ok'
        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
        : statusKind === 'warn'
          ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'
          : 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'"
      data-testid="tju-status-msg"
    >
      {{ status }}
    </p>

    <p v-if="meta.updated_at" class="text-[11px] text-slate-400">
      接口数据时间：{{ meta.updated_at }} · 学期码 {{ meta.term || '—' }} · 第一周周一 {{ meta.term_start || '—' }}
    </p>
    <p v-if="jw.last_import?.at" class="text-[11px] text-slate-400" data-testid="jw-last-import">
      教务最近一次导入：{{ jw.last_import.at }} · {{ jw.last_import.courses ?? 0 }} 门课 /
      {{ jw.last_import.slots ?? 0 }} 个时段<template v-if="jw.credentials_saved"> · 凭据已存服务器</template>
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { GraduationCap, RefreshCw, Trash2, Upload } from 'lucide-vue-next'
import { api, isOfflineMode } from '../api'
import {
  clearLocalTimetable,
  forgetJw,
  importLocalEventsBatch,
  jwImport,
  jwImportLocal,
  loadConfig,
  loadJwStatus,
  notify,
  refresh,
  runSync,
} from '../store'
import { parseIcsText } from '../utils/icsParser'
import {
  hasNativeTjuBridge,
  nativeFetchCaptcha,
  nativeFetchEamsHtml,
} from '../utils/tjuNativeClient'

const props = defineProps({
  tju: { type: Object, default: () => ({}) },
  semester: { type: Object, default: () => ({}) },
})

const busy = ref(false)
const status = ref('')
const statusKind = ref('warn')
const form = reactive({ username: '', password: '' })
/* 服务器上的教务凭据状态（credentials_saved / username / last_import），来自 /tju/jw/status。 */
const jw = ref({})
/* 教务系统的图形验证码：服务器 OCR 认不出来时才用得上。 */
const captcha = reactive({ image: '', code: '', id: '', isNative: false })
const icsInput = ref(null)

const credentials = computed(() => props.tju?.credentials || {})
const meta = computed(() => props.tju?.import_meta || {})
const imported = computed(() => Boolean(meta.value?.courses))

onMounted(async () => {
  await loadJwMeta()
})

function say(message, kind = 'warn') {
  status.value = message
  statusKind.value = kind
}

function fail(error, fallback) {
  say(error?.message || fallback, 'danger')
}

async function refreshConfig() {
  await loadConfig()
}

/* --------------------------------------- 一键导入（主路径：教务系统 CAS）*/

/** 读一次「服务器上有没有教务凭据 / 上次导入结果」（响应里永远没有密码）。 */
async function loadJwMeta() {
  if (isOfflineMode()) {
    jw.value = {}
    return jw.value
  }
  const info = await loadJwStatus()
  jw.value = info?.detail || {}
  return jw.value
}

/** 离线模式下没有服务器凭据可查，导入只是「借服务器算一次」。 */
const offline = computed(() => isOfflineMode())

/** 服务器 OCR 没认出验证码时，取一张真图让用户手填。 */
async function loadCaptchaImage() {
  try {
    if (hasNativeTjuBridge()) {
      const nat = await nativeFetchCaptcha()
      captcha.image = nat.image || ''
      captcha.id = nat.captcha_id || ''
      captcha.code = ''
      captcha.isNative = true
      return
    }
    const info = isOfflineMode() ? await api.jwLocalCaptcha() : await api.jwCaptcha()
    captcha.image = info?.detail?.image || ''
    captcha.id = info?.detail?.captcha_id || ''
    captcha.code = ''
    captcha.isNative = false
  } catch (error) {
    say(`验证码拉不下来：${error?.message || '未知错误'}`, 'danger')
  }
}

async function runNativeImport({ username, password, captchaCode = '', captchaId = '' }) {
  say('① 正在由手机直连天大统一身份认证与教务系统…', 'warn')
  const rawHtml = await nativeFetchEamsHtml({
    username,
    password,
    captcha: captchaCode,
    captchaId,
  })
  say('② 课表已取回，正在换算课程时段…', 'warn')
  const parsedRes = await api.jwLocalParse({
    courses_html: rawHtml.courses_html,
    calendar_raw: rawHtml.calendar_raw,
    term: rawHtml.term,
    week: props.semester?.current_week || null,
  })
  const detail = parsedRes?.detail || {}
  if (isOfflineMode()) {
    importLocalEventsBatch(detail.events || [], {
      courses: detail.courses || 0,
      source: 'local',
      semester: detail.semester || {},
      termStart: detail.term_start || '',
    })
    return parsedRes
  }
  say('③ 课表解析完成，正在同步到云端账号…', 'warn')
  const importedRes = await api.tjuImport({
    payload: detail.raw_payload,
    source: 'jw-native',
    total_weeks: detail.total_weeks,
    run_sync: true,
  })
  await Promise.all([loadConfig(), refresh({ silent: true })])
  return importedRes
}

/** 把教务链路的报错翻成人话，并区分「要验证码」和「账号密码错」。 */
async function reportJwError(error) {
  const detail = error?.detail || {}
  const kind = detail.kind || ''
  if (kind === 'captcha') {
    say('教务系统要求验证码：自动识别没通过，下面这张图填一下就能继续。', 'warn')
    await loadCaptchaImage()
    return
  }
  if (kind === 'auth_required') {
    say('学号或密码不对 —— 这里要的是「教务系统 / 统一身份认证」的密码，不是微北洋的。', 'danger')
    return
  }
  if (kind === 'network') {
    say(detail.message || error?.message || '服务器暂无法直连天大教务，可使用 Android 客户端直连导入或下方本地 .ics 导入', 'danger')
    return
  }
  say(detail.message || error?.message || '导入失败', 'danger')
}

/** 真·导入：Android 客户端无论离线或在线一律优先走手机直连教务；网页端按离线/在线走服务端接口。 */
async function runImport(payload) {
  if (hasNativeTjuBridge()) {
    return runNativeImport({
      username: payload.username,
      password: payload.password,
      captchaCode: payload.captcha || '',
      captchaId: payload.captcha_id || '',
    })
  }
  return isOfflineMode() ? jwImportLocal(payload) : jwImport(payload)
}

async function onIcsFileSelected(e) {
  const file = e.target?.files?.[0]
  if (!file) return
  busy.value = true
  try {
    if (isOfflineMode()) {
      const text = await file.text()
      const events = parseIcsText(text)
      if (!events.length) {
        say('这个 .ics 文件里没有解析到有效课程事件', 'warn')
        return
      }
      const uniqueTitles = new Set(events.map((ev) => ev.title))
      importLocalEventsBatch(events, { courses: uniqueTitles.size, source: 'ics' })
      say(`已从本地 .ics 导入 ${uniqueTitles.size} 门课 / ${events.length} 个时段`, 'ok')
      notify(`本地课表已导入：${events.length} 个时段`, 'ok')
    } else {
      const res = await api.uploadIcs(file)
      say(res?.message || '已从 .ics 导入课表', 'ok')
      notify(res?.message || '已从 .ics 导入课表', 'ok')
      await Promise.all([refreshConfig(), runSync()])
    }
  } catch (error) {
    fail(error, '导入 .ics 失败')
  } finally {
    busy.value = false
    if (icsInput.value) icsInput.value.value = ''
  }
}

function importedCount(result) {
  return result?.detail?.import?.courses ?? result?.detail?.courses ?? 0
}

/**
 * 一次点击走完：服务器登录教务系统（CAS）→ 抓课表 → 导入 → 同步。
 * 不依赖校园网、不需要本机令牌。要人工验证码时把图显示出来，填完点「提交并导入」。
 */
async function oneClick() {
  const username = form.username.trim()
  if (!username || !form.password) {
    say('先填「学号 + 教务系统密码」（教务系统 = 统一身份认证那套，不是微北洋密码），再点这个按钮。', 'warn')
    return
  }
  busy.value = true
  status.value = ''
  captcha.image = ''
  captcha.code = ''
  try {
    say('① 正在服务器上登录教务系统…', 'warn')
    const result = await runImport({
      username,
      password: form.password,
      save: !isOfflineMode(),
      run_sync: !isOfflineMode(),
      via: 'cas',
      week: props.semester?.current_week || null,
    })
    const info = result?.detail?.import || {}
    say(result?.message || `已导入 ${importedCount(result)} 门课`, 'ok')
    notify(result?.message || (isOfflineMode() ? '课表已存入本机' : '课表已导入'), 'ok')
    if (result?.detail?.warning) say(`${result.message}｜${result.detail.warning}`, 'warn')
    form.password = ''
    await loadJwMeta()
  } catch (error) {
    await reportJwError(error)
  } finally {
    busy.value = false
  }
}

/** 手填验证码后继续（沿用页面内存里的密码，不写 localStorage）。 */
async function submitCaptcha() {
  const username = form.username.trim()
  if (!captcha.code.trim()) {
    say('先把图里的字符填上。', 'warn')
    return
  }
  if (!username || !form.password) {
    say('密码框空了：再填一次学号 + 教务密码，然后点「一键导入课表」。', 'warn')
    return
  }
  busy.value = true
  try {
    const result = await runImport({
      username,
      password: form.password,
      save: !isOfflineMode(),
      run_sync: !isOfflineMode(),
      via: 'cas',
      week: props.semester?.current_week || null,
      captcha: captcha.code.trim(),
      captcha_id: captcha.id,
    })
    say(result?.message || `已导入 ${importedCount(result)} 门课`, 'ok')
    notify(result?.message || (isOfflineMode() ? '课表已存入本机' : '课表已导入'), 'ok')
    captcha.image = ''
    captcha.code = ''
    form.password = ''
    await loadJwMeta()
  } catch (error) {
    await reportJwError(error)
  } finally {
    busy.value = false
  }
}

/** 删掉服务器上保存的教务凭据（已导入的课表保留）。 */
async function forgetJwCredentials() {
  busy.value = true
  try {
    const result = await forgetJw()
    say(result?.message || '已删除服务器上的教务凭据', 'ok')
    await loadJwMeta()
  } catch (error) {
    fail(error, '删除失败')
  } finally {
    busy.value = false
  }
}

async function clearImport() {
  busy.value = true
  try {
    if (isOfflineMode()) {
      const { removed } = clearLocalTimetable()
      say(`已清除本机课表（${removed} 条）`, 'ok')
      return
    }
    const result = await api.tjuClearImport()
    say(result.message || '已清除导入的课表', 'ok')
    await refreshConfig()
    await runSync()
  } catch (error) {
    fail(error, '清除失败')
  } finally {
    busy.value = false
  }
}
</script>
