<template>
  <div
    data-testid="auth-gate"
    class="flex min-h-screen flex-col items-center justify-center gap-4 px-5 py-10"
  >
    <div class="text-center">
      <div class="text-2xl font-semibold tracking-tight">{{ appName }}</div>
      <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
        课表与截止日期聚合 · 需要账号访问
      </p>
    </div>

    <form
      class="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      @submit.prevent="submit"
    >
      <div class="mb-4 grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 text-sm dark:bg-slate-800">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          type="button"
          class="rounded-lg px-3 py-1.5 font-medium transition"
          :class="
            mode === tab.value
              ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-950 dark:text-slate-100'
              : 'text-slate-500 dark:text-slate-400'
          "
          :data-testid="`auth-tab-${tab.value}`"
          :disabled="tab.value === 'register' && !registrationOpen"
          @click="setMode(tab.value)"
        >
          {{ tab.label }}
        </button>
      </div>

      <label class="block text-sm">
        <span class="text-slate-600 dark:text-slate-300">用户名</span>
        <input
          v-model="username"
          data-testid="auth-username"
          name="username"
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-sky-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          placeholder="3-32 位字母/数字/._-"
        />
      </label>

      <label class="mt-3 block text-sm">
        <span class="text-slate-600 dark:text-slate-300">密码</span>
        <input
          v-model="password"
          data-testid="auth-password"
          name="password"
          type="password"
          autocomplete="current-password"
          class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-sky-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          :placeholder="`至少 ${minLength} 位`"
        />
      </label>

      <template v-if="mode === 'register'">
        <label class="mt-3 block text-sm">
          <span class="text-slate-600 dark:text-slate-300">确认密码</span>
          <input
            v-model="confirm"
            data-testid="auth-confirm"
            type="password"
            autocomplete="new-password"
            class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-sky-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
        </label>

        <label class="mt-3 block text-sm">
          <span class="text-slate-600 dark:text-slate-300">昵称（可选）</span>
          <input
            v-model="displayName"
            data-testid="auth-display-name"
            class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-sky-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            placeholder="显示在设置里"
          />
        </label>

        <label v-if="inviteRequired" class="mt-3 block text-sm">
          <span class="text-slate-600 dark:text-slate-300">邀请码</span>
          <input
            v-model="inviteCode"
            data-testid="auth-invite"
            class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-sky-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            placeholder="向站主索取"
          />
        </label>

        <div v-if="captchaRequired" class="mt-3">
          <span class="text-sm text-slate-600 dark:text-slate-300">图形验证码</span>
          <div class="mt-1 flex items-stretch gap-2">
            <input
              v-model="captchaAnswer"
              data-testid="auth-captcha"
              name="captcha"
              autocapitalize="characters"
              spellcheck="false"
              maxlength="8"
              class="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 tracking-[0.3em] text-slate-900 outline-none focus:border-sky-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              placeholder="输入图中字符"
            />
            <button
              type="button"
              data-testid="auth-captcha-refresh"
              class="shrink-0 overflow-hidden rounded-xl border border-slate-300 bg-slate-100 dark:border-slate-700"
              :title="captchaHint"
              @click="refreshCaptcha()"
            >
              <!-- The challenge is an SVG string we render ourselves, so there is
                   no third-party script (and no reCAPTCHA-style DNS that fails
                   behind the GFW). -->
              <span
                v-if="captchaSvg"
                class="block h-[52px] w-[148px] bg-[#eef2f7] [&>svg]:block [&>svg]:h-full [&>svg]:w-full"
                v-html="captchaSvg"
              />
              <span
                v-else
                class="flex h-[52px] w-[148px] items-center justify-center text-xs text-slate-500"
              >
                {{ captchaLoading ? '加载中…' : '点此刷新' }}
              </span>
            </button>
          </div>
          <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {{ captchaHint }}
          </p>
        </div>
      </template>

      <p
        v-if="errorText"
        data-testid="auth-error"
        class="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/50 dark:text-rose-300"
      >
        {{ errorText }}
      </p>

      <button
        type="submit"
        data-testid="auth-submit"
        class="mt-4 w-full rounded-xl bg-sky-600 px-4 py-2.5 font-medium text-white transition hover:bg-sky-500 disabled:opacity-60"
        :disabled="state.authBusy"
      >
        {{ state.authBusy ? '处理中…' : mode === 'login' ? '登录' : '注册并进入' }}
      </button>

      <p v-if="mode === 'login'" class="mt-3 text-center text-xs text-slate-500 dark:text-slate-400">
        <template v-if="registrationOpen">
          还没有账号？
          <button type="button" class="text-sky-600 underline dark:text-sky-400" @click="setMode('register')">
            注册
          </button>
        </template>
        <template v-else>注册已关闭，请联系站主开通</template>
      </p>
    </form>

    <!-- 离线模式：不登录、不联网，数据只保存在本机 -->
    <div
      class="w-full max-w-sm rounded-2xl border border-dashed border-slate-300 px-4 py-3 text-center dark:border-slate-700"
    >
      <button
        type="button"
        data-testid="auth-offline"
        class="text-sm font-medium text-slate-700 underline-offset-4 hover:underline dark:text-slate-200"
        @click="startOffline"
      >
        离线使用（不使用云同步）
      </button>
      <p class="mt-1 text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
        课表、日程、待办只保存在这台设备上，不上传服务器；账号栏显示为「本地账号」。
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { enableOfflineMode, login, loadCaptcha, register, saveToken, state } from '../store'

const mode = ref('login')
const username = ref('')
const password = ref('')
const confirm = ref('')
const displayName = ref('')
const inviteCode = ref('')
const localError = ref('')
const showToken = ref(false)
const tokenInput = ref('')

const captchaToken = ref('')
const captchaSvg = ref('')
const captchaAnswer = ref('')
const captchaLoading = ref(false)
const captchaError = ref('')

const tabs = [
  { value: 'login', label: '登录' },
  { value: 'register', label: '注册' },
]

const appName = computed(() => state.config?.app || 'CampusHub Sync')
const registrationOpen = computed(() => state.accounts?.registration_open !== false)
const inviteRequired = computed(() => Boolean(state.accounts?.invite_required))
const captchaRequired = computed(() => Boolean(state.accounts?.captcha_required))
const minLength = computed(() => Number(state.accounts?.password_min_length) || 6)
const errorText = computed(() => localError.value || state.authError)
const captchaHint = computed(
  () => captchaError.value || '看不清就点图换一张 · 5 分钟内有效',
)

/**
 * Pull a fresh challenge; the answer lives only inside the signed token.
 *
 * 失败不能把图留空：一次网络抖动（校园网切换、服务端 5xx、切前台）就自动重试一次，
 * 仍然失败才提示，并把原因写进提示里 —— 否则用户看到的是「有输入框、没有图」。
 */
let captchaSeq = 0

async function refreshCaptcha(attempt = 0) {
  const seq = attempt === 0 ? ++captchaSeq : captchaSeq
  captchaLoading.value = true
  captchaError.value = ''
  if (attempt === 0) captchaAnswer.value = ''
  try {
    const payload = await loadCaptcha()
    if (seq !== captchaSeq) return
    if (payload?.svg) {
      captchaSvg.value = payload.svg
      captchaToken.value = payload.token || ''
      return
    }
    if (attempt < 2) {
      await new Promise((resolve) => setTimeout(resolve, 450 * (attempt + 1)))
      if (seq !== captchaSeq) return
      return await refreshCaptcha(attempt + 1)
    }
    captchaSvg.value = ''
    captchaToken.value = ''
    if (captchaRequired.value) {
      const why = state.captchaError ? `（${state.captchaError}）` : ''
      captchaError.value = `验证码加载失败${why}，点图重试 · 或换个窗口打开`
    }
  } catch (error) {
    if (seq !== captchaSeq) return
    if (attempt < 2) {
      await new Promise((resolve) => setTimeout(resolve, 450 * (attempt + 1)))
      if (seq !== captchaSeq) return
      return await refreshCaptcha(attempt + 1)
    }
    captchaSvg.value = ''
    captchaToken.value = ''
    if (captchaRequired.value) captchaError.value = '验证码加载失败，点图重试 · 或换个窗口打开'
  } finally {
    if (seq === captchaSeq) {
      captchaLoading.value = false
    }
  }
}

watch([captchaRequired, mode], ([on, m]) => {
  if (on && m === 'register' && (!captchaSvg.value || !captchaToken.value) && !captchaLoading.value) {
    refreshCaptcha()
  }
})
onMounted(() => {
  if (captchaRequired.value) refreshCaptcha()
})

function setMode(next) {
  mode.value = next
  localError.value = ''
  state.authError = ''
  if (next === 'register' && captchaRequired.value && !captchaSvg.value) refreshCaptcha()
}

async function submit() {
  localError.value = ''
  state.authError = ''
  if (!username.value.trim()) {
    localError.value = '请填写用户名'
    return
  }
  if (password.value.length < minLength.value) {
    localError.value = `密码至少 ${minLength.value} 位`
    return
  }
  if (mode.value === 'register' && password.value !== confirm.value) {
    localError.value = '两次输入的密码不一致'
    return
  }
  if (mode.value === 'register' && inviteRequired.value && !inviteCode.value.trim()) {
    localError.value = '请填写邀请码'
    return
  }
  if (mode.value === 'register' && captchaRequired.value && !captchaAnswer.value.trim()) {
    localError.value = '请填写图形验证码'
    return
  }

  const ok =
    mode.value === 'register'
      ? await register(username.value, password.value, inviteCode.value, displayName.value, {
          token: captchaToken.value,
          answer: captchaAnswer.value,
        })
      : await login(username.value, password.value)

  if (!ok && !localError.value && !state.authError) {
    localError.value = '登录请求未成功完成，请检查网络或稍后重试'
  }

  // Keep the typed values when the attempt failed — retrying after a typo'd
  // invite code should not mean re-typing the password too. The captcha is the
  // exception: it is single-use, so swap in a new one.
  if (ok) {
    password.value = ''
    confirm.value = ''
  } else if (mode.value === 'register' && captchaRequired.value) {
    await refreshCaptcha()
  }
}

function useToken() {
  if (!tokenInput.value.trim()) {
    localError.value = '请粘贴令牌'
    return
  }
  saveToken(tokenInput.value.trim())
  tokenInput.value = ''
}

/** 离线模式：不登录，所有数据只留在本机；之后可在设置里退出并恢复云同步。 */
function startOffline() {
  localError.value = ''
  state.authError = ''
  enableOfflineMode()
}
</script>
