<template>
  <div class="space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800" data-testid="tju-connect">
    <header class="flex flex-wrap items-center gap-2">
      <GraduationCap :size="14" class="text-brand-600 dark:text-brand-400" />
      <h3 class="text-xs font-semibold">微北洋直连（学号登录 / 令牌）</h3>
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
      <span v-if="credentials.has_token" class="chip border-transparent bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300">
        凭据 {{ credentials.token_hint || '已保存' }}
      </span>
    </header>

    <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
      登录可以由服务器完成；但课表接口 <code>open.twt.edu.cn</code> <b>只对校园网开放</b>，
      所以课表要由你面前的浏览器（连着校园网时）去取。两条路都给你：
    </p>

    <!-- ------------------------------------------------------- credentials -->
    <div class="space-y-2 rounded-xl bg-slate-50 p-2.5 dark:bg-slate-800/50">
      <p class="label">1 · 账号 / 令牌</p>
      <div class="grid grid-cols-2 gap-2">
        <input v-model="form.username" class="input text-xs" data-testid="tju-account" placeholder="学号（如 30212xxxxx）" autocomplete="username" />
        <input v-model="form.password" class="input text-xs" type="password" placeholder="微北洋密码" autocomplete="current-password" />
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="btn-primary !py-1.5 text-xs" data-testid="tju-save-credentials" :disabled="busy" @click="savePassword">
          <LogIn :size="13" /> 保存凭据（服务器登录）
        </button>
        <button class="btn-ghost !py-1.5 text-xs" :disabled="busy" @click="showToken = !showToken">
          {{ showToken ? '收起令牌输入' : '改用令牌' }}
        </button>
        <button v-if="credentials.has_token" class="btn-ghost !py-1.5 text-xs" :disabled="busy" @click="forgetCredentials">
          <Trash2 :size="13" /> 删除凭据
        </button>
      </div>
      <div v-if="showToken" class="flex gap-2">
        <input v-model="form.token" class="input font-mono text-xs" placeholder="粘贴微北洋 token" autocomplete="off" />
        <button class="btn-ghost shrink-0 !py-1.5 text-xs" :disabled="busy" @click="saveToken">保存令牌</button>
      </div>
    </div>

    <!-- ------------------------------------------------------------ fetches -->
    <div class="flex flex-wrap gap-2">
      <button class="btn-ghost !py-1.5 text-xs" data-testid="tju-browser-fetch" :disabled="busy" @click="browserFetch">
        <Globe :size="13" /> 在我的浏览器里抓取（校园网）
      </button>
      <button class="btn-ghost !py-1.5 text-xs" data-testid="tju-server-sync" :disabled="busy" @click="serverSync">
        <Server :size="13" /> 让服务器试着抓
      </button>
      <button class="btn-ghost !py-1.5 text-xs" :disabled="busy || !imported" @click="clearImport">
        <Trash2 :size="13" /> 清除已导入课表
      </button>
    </div>

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
      <summary class="cursor-pointer font-semibold">手动兜底（浏览器拦截 / CORS 时用）</summary>
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Globe, GraduationCap, LogIn, Server, Trash2, Upload } from 'lucide-vue-next'
import { api } from '../api'
import { loadConfig, notify, runSync } from '../store'
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

const form = reactive({ username: '', password: '', token: '' })

const credentials = computed(() => props.tju?.credentials || {})
const meta = computed(() => props.tju?.import_meta || {})
const imported = computed(() => Boolean(meta.value?.courses))

onMounted(async () => {
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
