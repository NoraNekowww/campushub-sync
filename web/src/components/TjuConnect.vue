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
        title="服务器上保存了教务凭据，用来免密刷新课表；可在「高级」里删除"
      >
        教务凭据已存服务器
      </span>
      <span
        v-if="hasLocalToken"
        class="chip border-transparent bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300"
        title="本机还留着微北洋令牌，可用「高级」里的「忘记本机登录」清除"
      >
        本机有微北洋令牌
      </span>
    </header>

    <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
      <b>填「学号 + 教务系统密码」点一次就行。</b>这条链路在服务器上直连教务系统
      （<code>sso.tju.edu.cn</code> 统一身份认证 → <code>classes.tju.edu.cn/eams</code>，公网可达，
      <b>不需要待在校园网里</b>）：验证码服务器先替你识别，认不出来时才让你手填一张图。
      密码会保存在服务器上用于以后自动刷新课表，随时可以在「高级」里删掉。
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

    <!-- ------------------------------------------------ advanced / escape hatches -->
    <details class="rounded-xl bg-slate-50 p-2.5 dark:bg-slate-800/50">
      <summary class="cursor-pointer text-[11px] font-semibold">
        高级：微北洋直连 / 教务凭据 / 粘贴导入 / 清除
      </summary>

      <!-- -------------------------------------- 兜底 ①：校园网里浏览器直连微北洋 -->
      <div class="mt-2 space-y-2 rounded-xl bg-white p-2.5 dark:bg-slate-900/40">
        <p class="label">兜底 ①：校园网里用本机浏览器直连微北洋</p>
        <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
          微北洋接口只对校园网开放，而且这是跨站请求（浏览器 CORS 会拦），官方
          <code>get_classes</code> 现在还会对所有账号回「学期解析失败」——所以只当兜底。
          密码只留在本机页面内存里，不上传服务器。
        </p>
        <button
          class="btn-ghost !py-1.5 text-xs"
          data-testid="tju-mw-oneclick"
          :disabled="busy"
          @click="mwOneClick"
        >
          <Globe :size="13" /> 浏览器直连微北洋（一键）
        </button>
        <p v-if="hasLocalToken" class="text-[11px] text-slate-400">
          本机已记住微北洋令牌，点上面这个按钮连密码都不用填。
        </p>
      </div>

      <div class="mt-2 space-y-2">
        <!-- ------------------------------------------------------- credentials -->
        <div class="space-y-2 rounded-xl bg-white p-2.5 dark:bg-slate-900/40">
          <p class="label">兜底 ②：把微北洋凭据存在服务器上（可选，让服务器替你试一次）</p>
          <div class="grid grid-cols-2 gap-2">
            <input v-model="form.username" class="input text-xs" data-testid="tju-account" placeholder="学号（如 30212xxxxx）" autocomplete="username" />
            <input v-model="form.password" class="input text-xs" type="password" placeholder="微北洋密码（注意：教务密码是上面那个框）" autocomplete="current-password" />
          </div>
          <div class="flex flex-wrap gap-2">
            <button class="btn-ghost !py-1.5 text-xs" data-testid="tju-save-credentials" :disabled="busy" @click="savePassword">
              <LogIn :size="13" /> 保存到服务器
            </button>
            <button class="btn-ghost !py-1.5 text-xs" :disabled="busy" @click="showToken = !showToken">
              {{ showToken ? '收起令牌输入' : '改用令牌' }}
            </button>
            <button v-if="hasLocalToken" class="btn-ghost !py-1.5 text-xs" :disabled="busy" @click="forgetLocalToken">
              <Trash2 :size="13" /> 忘记本机登录
            </button>
            <button v-if="jw.credentials_saved" class="btn-ghost !py-1.5 text-xs" data-testid="jw-forget" :disabled="busy" @click="forgetJwCredentials">
              <Trash2 :size="13" /> 删除教务凭据（服务器）
            </button>
            <button v-if="credentials.has_token" class="btn-ghost !py-1.5 text-xs" :disabled="busy" @click="forgetCredentials">
              <Trash2 :size="13" /> 删除微北洋凭据
            </button>
          </div>
          <div v-if="showToken" class="flex gap-2">
            <input v-model="form.token" class="input font-mono text-xs" placeholder="粘贴微北洋 token" autocomplete="off" />
            <button class="btn-ghost shrink-0 !py-1.5 text-xs" :disabled="busy" @click="saveToken">保存到本机</button>
          </div>
        </div>

        <!-- ------------------------------------------------------------ fetches -->
        <div class="flex flex-wrap gap-2">
          <button class="btn-ghost !py-1.5 text-xs" data-testid="tju-browser-fetch" :disabled="busy" @click="browserFetch">
            <Globe :size="13" /> 浏览器抓取（旧入口）
          </button>
          <button class="btn-ghost !py-1.5 text-xs" data-testid="tju-server-sync" :disabled="busy" @click="serverSync">
            <Server :size="13" /> 让服务器试着抓
          </button>
          <button class="btn-ghost !py-1.5 text-xs" :disabled="busy || !imported" @click="clearImport">
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

    <!-- ------------------------------------------------------------- manual -->
    <details class="rounded-xl bg-slate-50 p-2.5 text-[11px] dark:bg-slate-800/50">
      <summary class="cursor-pointer font-semibold">手动兜底（微北洋：浏览器拦截 / CORS 时用）</summary>
      <ol class="mt-2 list-decimal space-y-1.5 pl-4 text-slate-600 dark:text-slate-300">
        <li>
          复制登录链接并在校园网内打开，页面会返回 JSON；把其中的 <code>token</code>
          <button class="btn-ghost !px-1 !py-0.5 text-[11px]" @click="copy(loginUrlPreview, '登录链接已复制')">复制登录链接</button>
          粘到上面的「改用令牌」里保存。
        </li>
        <li>
          然后在 DevTools 控制台执行下面这段（已自动带上令牌），它会打印并复制课表 JSON：
          <button class="btn-ghost !px-1 !py-0.5 text-[11px]" @click="copy(snippet, '控制台命令已复制')">复制控制台命令</button>
        </li>
        <li>把拿到的 JSON 粘贴到下面，点「导入粘贴的课表」。</li>
      </ol>
      <p class="mt-2 break-all font-mono text-[10px] text-slate-400">{{ loginUrlPreview }}</p>
      <textarea
        v-model="pasted"
        class="input mt-2 h-24 resize-none font-mono text-[10px]"
        data-testid="tju-paste"
        placeholder="粘贴 v1/classtable 返回的 JSON（或微北洋 App 本地缓存里的课表 JSON）"
      />
      <div class="mt-2 flex flex-wrap gap-2">
        <button class="btn-primary !py-1.5 text-xs" data-testid="tju-import-paste" :disabled="busy || !pasted.trim()" @click="importPasted">
          <Upload :size="13" /> 导入粘贴的课表
        </button>
        <span class="text-slate-400">也支持 App 缓存：<code>schedule2_tju_classtable</code></span>
      </div>
    </details>

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
import { Globe, GraduationCap, LogIn, RefreshCw, Server, Trash2, Upload } from 'lucide-vue-next'
import { api } from '../api'
import {
  forgetJw,
  jwImport,
  loadConfig,
  loadJwStatus,
  notify,
  readTjuToken,
  rememberTjuToken,
  runSync,
  tjuBrowserImport,
} from '../store'
import {
  browserClasstable,
  browserLogin,
  consoleSnippet,
  signedUrl,
  TwtError,
} from '../twt-sign'

const props = defineProps({
  tju: { type: Object, default: () => ({}) },
  semester: { type: Object, default: () => ({}) },
})

const busy = ref(false)
const showToken = ref(false)
const status = ref('')
const statusKind = ref('warn')
const pasted = ref('')
const loginUrlPreview = ref('生成中…')
const snippet = ref('')
/* 本机记住的微北洋令牌（localStorage）—— 有它才能「一键」和「打开 App 自动续」。 */
const localToken = ref(readTjuToken())

const form = reactive({ username: '', password: '', token: '' })
/* 服务器上的教务凭据状态（credentials_saved / username / last_import），来自 /tju/jw/status。 */
const jw = ref({})
/* 教务系统的图形验证码：服务器 OCR 认不出来时才用得上。 */
const captcha = reactive({ image: '', code: '', id: '' })

const credentials = computed(() => props.tju?.credentials || {})
const meta = computed(() => props.tju?.import_meta || {})
const imported = computed(() => Boolean(meta.value?.courses))
const hasLocalToken = computed(() => Boolean(localToken.value))

onMounted(async () => {
  localToken.value = readTjuToken()
  await loadJwMeta()
  try {
    loginUrlPreview.value = await signedUrl('/v1/auth/token/get', { twtuname: '<学号>', twtpasswd: '<密码>' })
  } catch (error) {
    loginUrlPreview.value = '（无法生成链接：需要 https 页面）'
  }
  snippet.value = consoleSnippet(credentials.value.has_token ? '<在下面粘贴token>' : '<你的token>')
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
  const info = await loadJwStatus()
  jw.value = info?.detail || {}
  return jw.value
}

/** 服务器 OCR 没认出验证码时，取一张真图让用户手填。 */
async function loadCaptchaImage() {
  try {
    const info = await api.jwCaptcha()
    captcha.image = info?.detail?.image || ''
    captcha.id = info?.detail?.captcha_id || ''
    captcha.code = ''
  } catch (error) {
    say(`验证码拉不下来：${error?.message || '未知错误'}`, 'danger')
  }
}

/** 把教务链路的报错翻成人话，并区分「要验证码」和「账号密码错」。 */
async function reportJwError(error) {
  const detail = error?.detail || {}
  const kind = detail.kind || ''
  if (kind === 'captcha') {
    say('教务系统要求验证码：服务器自动识别没通过，下面这张图填一下就能继续。', 'warn')
    await loadCaptchaImage()
    return
  }
  if (kind === 'auth_required') {
    say('学号或密码不对 —— 这里要的是「教务系统 / 统一身份认证」的密码，不是微北洋的。', 'danger')
    return
  }
  say(detail.message || error?.message || '导入失败', 'danger')
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
    const result = await jwImport({
      username,
      password: form.password,
      save: true,
      run_sync: true,
      via: 'cas',
      week: props.semester?.current_week || null,
    })
    const info = result?.detail?.import || {}
    say(result?.message || `已导入 ${info.courses || 0} 门课`, 'ok')
    notify(result?.message || '课表已导入', 'ok')
    if (result?.detail?.warning) say(`${result.message}｜${result.detail.warning}`, 'warn')
    form.password = ''
    await loadJwMeta()
    localToken.value = readTjuToken()
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
    const result = await jwImport({
      username,
      password: form.password,
      save: true,
      run_sync: true,
      via: 'cas',
      week: props.semester?.current_week || null,
      captcha: captcha.code.trim(),
      captcha_id: captcha.id,
    })
    const info = result?.detail?.import || {}
    say(result?.message || `已导入 ${info.courses || 0} 门课`, 'ok')
    notify(result?.message || '课表已导入', 'ok')
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

/* -------------------------------------------- 兜底：本机浏览器直连微北洋 */
/**
 * 一次点击走完：本机令牌 → （需要时）学号密码换令牌 → 抓课表 → 导入 → 同步。
 * 密码只留在页面内存里（不写 localStorage、不发服务器），关掉页面即消失。
 * 抓到令牌后就地记住，所以之后每次都是「一键」，不需要再输密码。
 */
async function mwOneClick() {
  if (!readTjuToken() && (!form.username || !form.password)) {
    say('先填「学号 + 微北洋密码」，再点这个按钮（登录只在你本机完成，密码不上传）', 'warn')
    return
  }
  const needsLogin = !readTjuToken()
  busy.value = true
  status.value = ''
  try {
    if (needsLogin) say('① 正在你本机登录微北洋…', 'warn')
    const { courses } = await tjuBrowserImport({
      username: needsLogin ? form.username.trim() : '',
      password: needsLogin ? form.password : '',
    })
    localToken.value = readTjuToken()
    say(`已导入 ${courses} 门课，正在同步到日历…`, 'ok')
    await runSync()
    await loadConfig()
  } catch (error) {
    if (error instanceof TwtError && (error.kind === 'cors' || error.kind === 'campus')) {
      say(
        '微北洋这条路没成：它的接口只对校园网开放，而且还是跨站请求（浏览器 CORS 会拦）。' +
          '如果人已经在校园网里还这样，那就是 CORS 拦的，不是网络问题 —— ' +
          '请直接用上面的「一键导入课表」（走教务系统，服务器直连，不需要校园网），' +
          '或者在本块里粘贴课表 JSON。',
        'warn',
      )
    } else if (error instanceof TwtError && error.kind === 'credentials') {
      localToken.value = ''
      say('本机记住的登录已失效，请重新填一次密码再点按钮。', 'warn')
    } else {
      fail(error, '导入失败')
    }
  } finally {
    busy.value = false
  }
}

/** 换账号 / 换设备前清掉本机令牌；下次会重新用学号密码登录。 */
function forgetLocalToken() {
  rememberTjuToken('')
  localToken.value = ''
  say('已忘记本机登录：下次会重新用学号 / 密码登录。', 'ok')
}

/* ------------------------------------------------------------ credentials */
async function savePassword() {
  if (!form.username || !form.password) {
    say('请填写学号和密码', 'warn')
    return
  }
  busy.value = true
  say('正在用服务器登录微北洋…', 'warn')
  try {
    const result = await api.tjuSaveCredentials({
      mode: 'password',
      username: form.username.trim(),
      password: form.password,
    })
    say(result.message || '凭据已保存', 'ok')
    form.password = ''
    await refreshConfig()
  } catch (error) {
    fail(error, '登录失败')
  } finally {
    busy.value = false
  }
}

async function saveToken() {
  if (!form.token.trim()) {
    say('请粘贴 token', 'warn')
    return
  }
  busy.value = true
  try {
    const result = await api.tjuSaveCredentials({ mode: 'token', token: form.token.trim() })
    say(result.message || '令牌已保存', 'ok')
    await refreshConfig()
  } catch (error) {
    fail(error, '令牌无效')
  } finally {
    busy.value = false
  }
}

async function forgetCredentials() {
  busy.value = true
  try {
    const result = await api.tjuClearCredentials()
    say(result.message || '凭据已删除', 'ok')
    await refreshConfig()
  } catch (error) {
    fail(error, '删除失败')
  } finally {
    busy.value = false
  }
}

/* --------------------------------------------------------------- fetching */
async function serverSync() {
  busy.value = true
  say('服务器正在尝试抓取课表…', 'warn')
  try {
    const result = await api.tjuServerSync()
    if (result.ok) {
      say(result.message || '课表已导入', 'ok')
      notify(result.message || '课表已导入', 'ok')
      await refreshConfig()
      await runSync()
    } else {
      say(
        `${result.message || '抓取失败'}${result.detail?.kind === 'campus_network' ? ' — 这是预期结果，请用上面的「在我的浏览器里抓取」。' : ''}`,
        'warn',
      )
    }
  } catch (error) {
    fail(error, '抓取失败')
  } finally {
    busy.value = false
  }
}

async function browserFetch() {
  busy.value = true
  try {
    if (!form.username || !form.password) {
      say('浏览器抓取需要学号+密码（登录在你本机完成，密码不经过服务器）', 'warn')
      return
    }
    say('① 在你本机登录微北洋…', 'warn')
    const token = await browserLogin(form.username.trim(), form.password)
    say('② 登录成功，正在拉取课表…', 'warn')
    const payload = await browserClasstable(token)
    const courses = payload?.data?.data?.length ?? 0
    say(`③ 拿到 ${courses} 门课，正在导入…`, 'warn')
    const result = await api.tjuImport({ payload, source: 'browser' })
    const info = result.detail?.import || {}
    say(
      `${result.message || '导入成功'}（清理演示数据 ${result.detail?.demo_rows_removed ?? 0} 条）`,
      'ok',
    )
    form.password = ''
    await refreshConfig()
    await runSync()
    if (!info.courses) say('导入完成，但没有解析到课程 — 请检查返回的 JSON', 'warn')
  } catch (error) {
    if (error instanceof TwtError && error.kind === 'cors') {
      say(
        '浏览器直连被拦（CORS/网络）。请用下面的「手动兜底」：先复制登录链接拿 token，再复制控制台命令拿 JSON。',
        'danger',
      )
    } else {
      fail(error, '浏览器抓取失败')
    }
  } finally {
    busy.value = false
  }
}

async function importPasted() {
  busy.value = true
  try {
    const text = pasted.value.trim()
    const result = await api.tjuImport({ text, source: 'paste' })
    say(result.message || '导入成功', 'ok')
    pasted.value = ''
    await refreshConfig()
    await runSync()
  } catch (error) {
    fail(error, '导入失败')
  } finally {
    busy.value = false
  }
}

async function clearImport() {
  busy.value = true
  try {
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

async function copy(text, message) {
  try {
    await navigator.clipboard.writeText(text)
    notify(message, 'ok')
  } catch (error) {
    notify('复制失败，请手动选择文本', 'warn')
  }
}
</script>
