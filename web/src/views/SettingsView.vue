<template>
  <div class="space-y-4 px-4">
    <!-- ------------------------------------------------------------ account -->
    <section v-if="accountsEnabled" class="card space-y-3 p-4" data-testid="account-section">
      <header class="flex items-center gap-2">
        <UserRound :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">账号</h2>
        <span
          class="chip border-transparent"
          :class="
            account
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
              : 'bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300'
          "
        >
          {{ account ? '已登录' : '未登录' }}
        </span>
        <span
          v-if="account?.is_admin"
          class="chip border-transparent bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300"
        >
          管理员
        </span>
      </header>

      <template v-if="account">
        <dl class="grid grid-cols-3 gap-x-3 gap-y-1 text-xs">
          <dt class="text-slate-500 dark:text-slate-400">用户名</dt>
          <dd class="col-span-2 font-medium" data-testid="account-username">{{ account.username }}</dd>
          <dt class="text-slate-500 dark:text-slate-400">注册时间</dt>
          <dd class="col-span-2">{{ account.created_at_label || '—' }}</dd>
          <dt class="text-slate-500 dark:text-slate-400">上次登录</dt>
          <dd class="col-span-2">{{ account.last_login_label || '—' }}</dd>
        </dl>

        <div class="flex flex-wrap gap-2">
          <button
            class="btn-ghost !py-1.5 text-xs"
            data-testid="account-logout"
            :disabled="state.authBusy"
            @click="signOut"
          >
            退出登录
          </button>
          <button class="btn-ghost !py-1.5 text-xs" @click="showPasswordForm = !showPasswordForm">
            {{ showPasswordForm ? '收起' : '修改密码' }}
          </button>
        </div>

        <form v-if="showPasswordForm" class="space-y-2" @submit.prevent="submitPassword()">
          <input
            v-model="passwordForm.current"
            class="input text-xs"
            type="password"
            autocomplete="current-password"
            placeholder="当前密码"
          />
          <input
            v-model="passwordForm.next"
            class="input text-xs"
            type="password"
            autocomplete="new-password"
            :placeholder="`新密码（至少 ${minPasswordLength} 位）`"
          />
          <input
            v-model="passwordForm.confirm"
            class="input text-xs"
            type="password"
            autocomplete="new-password"
            placeholder="确认新密码"
          />
          <button class="btn-primary !py-1.5 text-xs" type="submit" :disabled="state.authBusy">
            保存新密码
          </button>
        </form>

        <div v-if="isAdminUser" class="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-700">
          <header class="flex items-center gap-2">
            <Users :size="14" class="text-slate-500" />
            <h3 class="text-xs font-semibold">成员（{{ members.length }}）</h3>
            <button class="btn-ghost !py-1 text-[11px]" :disabled="membersBusy" @click="loadMembers">
              <RefreshCw :size="12" /> 刷新
            </button>
          </header>
          <ul class="space-y-1 text-xs">
            <li
              v-for="row in members"
              :key="row.id"
              class="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-2 py-1.5 dark:bg-slate-800/60"
            >
              <span class="truncate">
                {{ row.username }}
                <span v-if="row.is_admin" class="text-brand-600 dark:text-brand-400">· 管理员</span>
                <span v-if="!row.is_active" class="text-rose-500">· 已停用</span>
              </span>
              <button
                v-if="row.id !== account.id"
                class="btn-ghost !py-1 text-[11px]"
                @click="toggleMember(row)"
              >
                {{ row.is_active ? '停用' : '启用' }}
              </button>
            </li>
          </ul>
        </div>
      </template>

      <template v-else>
        <p class="text-xs text-slate-500 dark:text-slate-400">
          这个日程表需要账号才能读取。登录后本机自动保持登录状态，日历订阅链接不受影响。
        </p>
        <button class="btn-primary !py-1.5 text-xs" @click="openAuthGate()">
          <LogIn :size="13" /> 登录 / 注册
        </button>
      </template>
    </section>

    <!-- ------------------------------------------------------ 接入向导 -->
    <section class="card space-y-3 p-4" data-testid="onboarding-section">
      <header class="flex items-center gap-2">
        <UserRound :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">三步接入你自己的账号</h2>
      </header>
      <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
        每个账号的数据互相看不见：课表、待办、自定义日程都只属于你自己。把这一页发给同学，让他注册后走完三步即可。
      </p>
      <ol class="space-y-2.5 text-xs">
        <li v-for="step in onboarding" :key="step.key" class="flex items-start gap-2">
          <span
            class="mt-1 h-2 w-2 shrink-0 rounded-full"
            :class="step.done ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-600'"
          />
          <div class="min-w-0 flex-1">
            <p class="font-medium">{{ step.title }}</p>
            <p class="text-[11px] text-slate-500 dark:text-slate-400">{{ step.hint }}</p>
          </div>
          <button v-if="step.target" class="btn-ghost shrink-0 !py-1 text-[11px]" @click="jumpTo(step.target)">
            {{ step.done ? '看看' : '去连接' }}
          </button>
        </li>
      </ol>
    </section>

    <!-- ------------------------------------------------------ registration -->
    <section v-if="isAdminUser" class="card space-y-3 p-4" data-testid="registration-section">
      <header class="flex flex-wrap items-center gap-2">
        <ShieldCheck :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">注册与验证</h2>
        <span
          class="chip"
          :class="
            registration.registration_open
              ? 'border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
              : 'border-transparent bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
          "
        >
          {{ registration.registration_open ? '开放注册' : '已关闭' }}
        </span>
      </header>
      <p class="text-[11px] text-slate-500 dark:text-slate-400">
        别人注册时走哪道门。图形验证码由本站自己出题（服务端渲染 SVG + 签名令牌，5 分钟有效、绑 IP、一次一换），
        不依赖 Google reCAPTCHA / hCaptcha，国内可直接访问，也不需要任何第三方账号。
      </p>

      <div class="space-y-2 rounded-xl bg-slate-50 p-2.5 text-xs dark:bg-slate-800/60">
        <div class="flex items-center gap-2">
          <span class="shrink-0 text-slate-500 dark:text-slate-400">当前邀请码</span>
          <code class="min-w-0 flex-1 truncate font-mono text-[13px]">{{
            registration.invite_code || '（未设置）'
          }}</code>
          <button class="btn-ghost shrink-0 !py-1 text-[11px]" @click="copyInvite">
            <Copy :size="12" /> 复制
          </button>
          <button
            class="btn-ghost shrink-0 !py-1 text-[11px]"
            :disabled="registrationBusy"
            @click="rotateInvite"
          >
            <RefreshCw :size="12" /> 换一个
          </button>
        </div>

        <label class="flex items-center gap-2">
          <input
            type="checkbox"
            :checked="registration.invite_required"
            :disabled="registrationBusy"
            @change="saveRegistration({ invite_required: $event.target.checked })"
          />
          <span>注册必须填邀请码（关掉即只靠验证码）</span>
        </label>

        <label class="flex items-center gap-2">
          <input
            type="checkbox"
            :checked="registration.captcha_enabled"
            :disabled="registrationBusy"
            @change="saveRegistration({ captcha_enabled: $event.target.checked })"
          />
          <span>注册必须过图形验证码</span>
        </label>

        <div class="flex items-center gap-2 pt-0.5">
          <input
            v-model="inviteDraft"
            class="input min-w-0 flex-1 text-xs"
            placeholder="自定义邀请码（留空不改动）"
            @keyup.enter="inviteDraft.trim() && saveRegistration({ invite_code: inviteDraft })"
          />
          <button
            class="btn-primary shrink-0 !py-1.5 text-xs"
            :disabled="registrationBusy || !inviteDraft.trim()"
            @click="saveRegistration({ invite_code: inviteDraft })"
          >
            保存
          </button>
        </div>
      </div>

      <p class="text-[11px] text-slate-500 dark:text-slate-400">
        把
        <code class="rounded bg-slate-100 px-1 font-mono dark:bg-slate-800">{{ registerLink }}</code>
        发给同学，让他们点「注册」用自己的账号登录（各自的课表和待办互不可见）。
      </p>
    </section>

    <!-- ------------------------------------------------------------ access -->
    <section class="card space-y-3 p-4">
      <header class="flex items-center gap-2">
        <KeyRound :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">访问令牌</h2>
        <span
          v-if="state.statusLocked"
          class="chip border-transparent bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300"
        >
          未授权
        </span>
        <span
          v-else-if="tokenPresent"
          class="chip border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300"
        >
          已连接
        </span>
      </header>
      <p class="text-xs text-slate-500 dark:text-slate-400">
        时间线是公开只读的；同步、勾选完成、上传课表等操作需要后端 <code>ADMIN_TOKEN</code>。
      </p>
      <div class="flex gap-2">
        <input
          v-model="tokenInput"
          class="input font-mono text-xs"
          type="password"
          placeholder="ADMIN_TOKEN"
          autocomplete="off"
          @keyup.enter="applyToken"
        />
        <button class="btn-primary shrink-0" @click="applyToken">{{ tokenPresent ? '更新' : '保存' }}</button>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn-ghost !py-1.5 text-xs" @click="applyToken('')">清除</button>
        <button class="btn-ghost !py-1.5 text-xs" @click="reloadAll">重新加载</button>
      </div>
    </section>

    <!-- ---------------------------------------------------------- calendar -->
    <section class="card space-y-3 p-4">
      <header class="flex items-center gap-2">
        <CalendarPlus :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">日历订阅 (.ics)</h2>
      </header>
      <p class="text-xs text-slate-500 dark:text-slate-400">
        在 iOS 日历 / Android 的「通过 URL 添加日历」里粘贴下面的地址，截止时间与课程会自动同步（含 15 分钟提醒）。
      </p>
      <div v-if="subscribeUrl" class="space-y-2">
        <textarea
          class="input h-20 resize-none break-all font-mono text-[11px]"
          readonly
          :value="subscribeUrl"
        />
        <div class="flex flex-wrap gap-2">
          <button class="btn-primary !py-1.5 text-xs" @click="copy(subscribeUrl, '订阅地址已复制')">
            <Copy :size="13" /> 复制地址
          </button>
          <a class="btn-ghost !py-1.5 text-xs" :href="webcalUrl">
            <CalendarPlus :size="13" /> 直接订阅
          </a>
          <button class="btn-ghost !py-1.5 text-xs" @click="copy(prettyUrl, 'HTTPS 地址已复制')">
            复制 https 版本
          </button>
        </div>
        <p v-if="!subscribeConfigured" class="text-[11px] text-amber-600 dark:text-amber-400">
          后端未配置 <code>SUBSCRIBE_TOKEN</code>，部署到公网前请务必设置。
        </p>
      </div>
      <p v-else class="text-xs text-slate-400">需要访问令牌才能读取订阅地址。</p>
    </section>

    <!-- -------------------------------------------------------------- sync -->
    <section class="card space-y-3 p-4">
      <header class="flex items-center gap-2">
        <RefreshCw :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">同步状态</h2>
        <button class="btn-ghost ml-auto !px-2 !py-1 text-xs" :disabled="state.syncing" @click="runSync()">
          <RefreshCw :size="12" :class="state.syncing ? 'animate-spin' : ''" /> 立即同步
        </button>
      </header>

      <DetailList
        v-if="lastSync"
        :data="lastSync"
        :keys="['trigger', 'started_at', 'finished_at', 'fetched', 'created', 'updated', 'pruned', 'message']"
        :labels="{
          trigger: '触发方式',
          started_at: '开始',
          finished_at: '结束',
          fetched: '抓取',
          created: '新增',
          updated: '更新',
          pruned: '清理',
          message: '信息',
        }"
      />
      <p v-else class="text-xs text-slate-400">还没有同步记录。</p>

      <DetailList
        v-if="scheduler"
        :data="scheduler"
        :keys="['running', 'next_run_time', 'interval_minutes', 'jobs']"
        :labels="{ running: '调度器', next_run_time: '下次运行', interval_minutes: '间隔(分)', jobs: '任务数' }"
      />

      <div v-if="connectors.length" class="space-y-2 pt-1">
        <div v-for="connector in connectors" :key="connector.name" class="rounded-xl bg-slate-50 p-2.5 dark:bg-slate-800/50">
          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold">{{ connector.name }}</span>
            <span
              class="chip border-transparent"
              :class="connector.ok
                ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                : 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300'"
            >
              {{ connector.ok ? '正常' : '异常' }}
            </span>
            <span v-if="connector.fetched != null" class="text-[11px] text-slate-400">{{ connector.fetched }} 条</span>
          </div>
          <p v-if="connector.error" class="mt-1 break-all text-[11px] text-rose-500">{{ connector.error }}</p>
        </div>
      </div>
    </section>

    <!-- --------------------------------------------------------- microsoft -->
    <section id="ms-section" class="card space-y-3 p-4">
      <header class="flex items-center gap-2">
        <CalendarDays :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">Microsoft To Do</h2>
        <span
          class="chip ml-auto border-transparent"
          :class="ms.authorized
            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
            : 'bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300'"
        >
          {{ ms.authorized ? '已授权' : '未授权' }}
        </span>
      </header>

      <DetailList :data="ms" :labels="{ account: '账号', expires_in: 'access 有效期(秒)', scopes: '权限', authority: '租户', enabled: '启用' }" />

      <div v-if="deviceFlow" class="space-y-2 rounded-xl bg-brand-50 p-3 text-xs dark:bg-brand-500/10">
        <p class="font-semibold">在浏览器中打开并输入代码：</p>
        <p class="font-mono text-lg tracking-widest">{{ deviceFlow.user_code }}</p>
        <a class="block break-all text-brand-700 underline dark:text-brand-300" :href="deviceFlow.verification_uri" target="_blank" rel="noreferrer">
          {{ deviceFlow.verification_uri_complete || deviceFlow.verification_uri }}
        </a>
        <p class="text-slate-500 dark:text-slate-400">{{ pollHint }}</p>
      </div>

      <div class="flex flex-wrap gap-2">
        <button class="btn-primary !py-1.5 text-xs" :disabled="deviceBusy" @click="startDeviceFlow">
          <LogIn :size="13" /> 设备代码登录
        </button>
        <button class="btn-ghost !py-1.5 text-xs" :disabled="!deviceFlow || deviceBusy" @click="pollDeviceFlow(true)">
          <CheckCheck :size="13" /> 我已授权
        </button>
        <button class="btn-ghost !py-1.5 text-xs" @click="forgetTokens">
          <Trash2 :size="13" /> 撤销令牌
        </button>
      </div>
    </section>

    <!-- --------------------------------------------------------------- tju -->
    <section class="card space-y-3 p-4">
      <header class="flex items-center gap-2">
        <GraduationCap :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">天津大学课表</h2>
        <span class="chip ml-auto border-transparent bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300">
          {{ tju.mode || '—' }}
        </span>
      </header>

      <DetailList
        :data="semester"
        :labels="{ name: '学期', start_date: '第一周周一', total_weeks: '周数', week: '当前周', holidays: '假期' }"
      />

      <TjuConnect id="tju-section" :tju="tju" :semester="semester" />

      <div class="space-y-2">
        <p class="label">上传 ICS 课表（微北洋接口失效时的兜底）</p>
        <input ref="fileInput" class="input !py-1.5 text-xs" type="file" accept=".ics,text/calendar" @change="uploadIcs" />
        <div class="flex flex-wrap gap-2">
          <button class="btn-ghost !py-1.5 text-xs" :disabled="busy" @click="previewIcs">
            <Eye :size="13" /> 预览解析结果
          </button>
          <button class="btn-ghost !py-1.5 text-xs" :disabled="busy" @click="clearIcs">
            <Trash2 :size="13" /> 删除已上传课表
          </button>
        </div>
        <p v-if="preview" class="rounded-xl bg-slate-50 p-2 text-[11px] dark:bg-slate-800/50">
          解析到 {{ preview.raw_events }} 条原始事件；示例：{{ sampleTitles }}
        </p>
      </div>

      <div class="space-y-2 border-t border-slate-100 pt-3 dark:border-slate-800">
        <p class="label">学期设置</p>
        <div class="grid grid-cols-2 gap-2">
          <input v-model="semesterForm.name" class="input text-xs" placeholder="学期名称" />
          <input v-model="semesterForm.start_date" class="input text-xs" type="date" />
          <input v-model.number="semesterForm.total_weeks" class="input text-xs" type="number" min="1" max="30" placeholder="总周数" />
          <button class="btn-primary text-xs" :disabled="busy" @click="saveSemester">保存学期</button>
        </div>
      </div>
    </section>

    <!-- ----------------------------------------------------------- about -->
    <section class="card space-y-3 p-4">
      <header class="flex items-center gap-2">
        <Info :size="15" class="text-brand-600 dark:text-brand-400" />
        <h2 class="text-sm font-semibold">外观与离线</h2>
      </header>
      <div class="flex gap-2">
        <button
          v-for="mode in themes"
          :key="mode.value"
          class="chip"
          :class="state.theme === mode.value ? 'chip-active' : 'chip-idle'"
          @click="setTheme(mode.value)"
        >
          <component :is="mode.icon" :size="12" />
          {{ mode.label }}
        </button>
      </div>
      <p class="text-xs text-slate-500 dark:text-slate-400">
        已缓存时间线可离线查看；在浏览器菜单选择「添加到主屏幕」即可作为 PWA 安装。
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <button class="btn-ghost !py-1.5 text-xs" @click="clearCache">
          <Trash2 :size="13" /> 清空离线缓存
        </button>
        <span class="text-[11px] text-slate-400">
          {{ cfg.app || 'CampusHub Sync' }} v{{ cfg.version || '—' }}
          <span v-if="cfg.demo_mode"> · demo</span>
          <span v-if="lastUpdatedLabel"> · 数据更新于 {{ lastUpdatedLabel }}</span>
        </span>
      </div>
    </section>

    <!-- 底部：反馈入口（仓库已公开，Issues 可匿名浏览） -->
    <footer class="pb-1 pt-1 text-center text-[11px] leading-relaxed text-slate-400">
      <a
        href="https://github.com/NoraNekowww/campushub-sync/issues/new"
        target="_blank"
        rel="noopener noreferrer"
        class="inline-flex items-center gap-1 underline decoration-dotted underline-offset-2 transition hover:text-slate-200"
        data-testid="issue-link"
      >
        <CircleAlert :size="12" />
        遇到问题 / 想提建议？去 GitHub 提 Issue
      </a>
      <div class="mt-1 text-[10px] opacity-70">
        本页源码：
        <a
          href="https://github.com/NoraNekowww/campushub-sync"
          target="_blank"
          rel="noopener noreferrer"
          class="underline decoration-dotted underline-offset-2 hover:text-slate-200"
          data-testid="repo-link"
        >NoraNekowww/campushub-sync</a>
        <span class="mx-1 opacity-60">·</span>
        <a
          href="https://github.com/NoraNekowww/campushub-sync/issues"
          target="_blank"
          rel="noopener noreferrer"
          class="underline decoration-dotted underline-offset-2 hover:text-slate-200"
          data-testid="issues-list-link"
        >全部反馈</a>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  CalendarDays,
  CalendarPlus,
  CheckCheck,
  CircleAlert,
  Copy,
  Eye,
  GraduationCap,
  Info,
  KeyRound,
  LogIn,
  Monitor,
  Moon,
  RefreshCw,
  ShieldCheck,
  Sun,
  Trash2,
  UserRound,
  Users,
} from 'lucide-vue-next'
import { api } from '../api'
import DetailList from '../components/DetailList.vue'
import TjuConnect from '../components/TjuConnect.vue'
import {
  changePassword,
  getTokenSafe,
  listUsers,
  loadRegistrationSettings,
  loadStatus,
  loadConfig,
  logout,
  notify,
  openAuthGate,
  refresh,
  runSync,
  saveToken,
  saveRegistrationSettings,
  setTheme,
  setUserActive,
  state,
} from '../store'

const cfg = computed(() => state.config || {})
const ms = computed(() => cfg.value.microsoft_todo || {})
const tju = computed(() => cfg.value.tju_schedule || {})
const semester = computed(() => tju.value.semester || {})
const subscribeUrl = computed(() => cfg.value.subscribe?.url || '')
const webcalUrl = computed(() => cfg.value.subscribe?.webcal || subscribeUrl.value)
const prettyUrl = computed(() => subscribeUrl.value.replace(/^webcal:/, 'https:'))
const subscribeConfigured = computed(() => Boolean(cfg.value.subscribe?.configured))
const lastSync = computed(() => state.status?.last_sync || null)
const scheduler = computed(() => state.status?.scheduler || null)
const connectors = computed(() => state.status?.connectors || [])
const lastUpdatedLabel = computed(() =>
  state.lastUpdated
    ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(state.lastUpdated)
    : '',
)

const themes = [
  { value: 'auto', label: '跟随系统', icon: Monitor },
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
]

const tokenInput = ref('')
const tokenPresent = ref(false)
const busy = ref(false)
const preview = ref(null)
const fileInput = ref(null)
const deviceFlow = ref(null)
const deviceBusy = ref(false)
const pollHint = ref('等待授权…')
let pollTimer = null

/* ------------------------------------------------------------ 接入向导 */
const tjuConnected = computed(
  () =>
    Boolean(state.status?.connectors?.find((item) => item.name === 'tju_schedule')?.ok) ||
    Boolean(tju.value?.mode),
)
const msConnectedUi = computed(() => Boolean(ms.value?.authorized))

const onboarding = computed(() => [
  {
    key: 'account',
    title: '① 用自己的账号登录',
    hint: state.user ? `已登录：${state.user.username}` : '还没登录 —— 上面「账号」卡片里注册 / 登录',
    done: Boolean(state.user),
    target: '',
  },
  {
    key: 'tju',
    title: '② 连我的教务（教务系统）',
    hint: tjuConnected.value
      ? '已连上，课表会自己同步进来'
      : '填一次学号 + 教务系统密码（统一身份认证那套），课表就进来了',
    done: tjuConnected.value,
    target: 'tju-section',
  },
  {
    key: 'ms',
    title: '③ 连我的微软待办',
    hint: msConnectedUi.value ? '已授权，新建日程可以同步到待办' : '设备码授权一次，待办双向同步',
    done: msConnectedUi.value,
    target: 'ms-section',
  },
])

function jumpTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ------------------------------------------------------- registration gate */

const registration = ref({
  invite_code: '',
  invite_required: false,
  captcha_enabled: true,
  registration_open: true,
})
const registrationBusy = ref(false)
const inviteDraft = ref('')
const registerLink = computed(() => `${location.origin}${location.pathname}`)

async function loadRegistration() {
  try {
    const payload = await loadRegistrationSettings()
    if (payload) registration.value = payload
  } catch (error) {
    // Admin-only endpoint: a non-admin just never sees this card.
  }
}

async function saveRegistration(patch) {
  registrationBusy.value = true
  try {
    const next = await saveRegistrationSettings(patch)
    if (next) registration.value = next
    inviteDraft.value = ''
  } catch (error) {
    notify(error.message || '保存失败', 'danger')
  } finally {
    registrationBusy.value = false
  }
}

function rotateInvite() {
  return saveRegistration({ rotate: true })
}

async function copyInvite() {
  try {
    await navigator.clipboard.writeText(registration.value.invite_code || '')
    notify('邀请码已复制', 'ok')
  } catch (error) {
    notify('复制失败，请手动选中', 'warn')
  }
}

// `state.accounts` arrives after mount, so wait for the admin flag instead of
// fetching on mount alone.
// NOTE: this computed MUST stay above the watch below — the watcher is
// `immediate`, so it evaluates its source during setup, and a `const` declared
// further down would be in the temporal dead zone (ReferenceError → blank page).
const isAdminUser = computed(() => Boolean(state.user?.is_admin) || Boolean(state.viewerAdmin))
watch(
  isAdminUser,
  (on) => {
    if (on) loadRegistration()
  },
  { immediate: true },
)

const semesterForm = reactive({ name: '', start_date: '', total_weeks: 16 })

onMounted(async () => {
  tokenInput.value = getTokenSafe()
  tokenPresent.value = Boolean(tokenInput.value)
  syncSemesterForm()
  if (isAdminUser.value) loadMembers()
})

onBeforeUnmount(() => stopPolling())

function syncSemesterForm() {
  const summary = semester.value || {}
  semesterForm.name = summary.name || ''
  semesterForm.start_date = summary.start_date || ''
  semesterForm.total_weeks = summary.total_weeks || 16
}

function applyToken(value) {
  const next = value === '' ? '' : tokenInput.value
  saveToken(next)
  tokenInput.value = next
  tokenPresent.value = Boolean(next)
  refresh({ silent: true })
}

async function reloadAll() {
  await Promise.all([refresh(), loadStatus(), loadConfig()])
  syncSemesterForm()
  notify('已重新加载', 'ok')
}

async function copy(text, message) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    notify(message, 'ok')
  } catch (error) {
    notify('复制失败，请手动选择文本', 'warn')
  }
}

const sampleTitles = computed(() => {
  const sample = preview.value?.expanded_sample || []
  return sample.map((item) => item.title).join(' / ') || '—'
})

async function uploadIcs(event) {
  const file = event.target.files?.[0]
  if (!file) return
  busy.value = true
  try {
    const result = await api.uploadIcs(file)
    notify(result.message || '课表已保存，正在同步', 'ok')
    await runSync()
  } catch (error) {
    notify(error.message || '上传失败', 'danger')
  } finally {
    busy.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function previewIcs() {
  busy.value = true
  try {
    const result = await api.schedulePreview()
    preview.value = result.detail || {}
    notify(`解析到 ${preview.value.raw_events ?? 0} 条事件`, 'ok')
  } catch (error) {
    notify(error.message || '没有可预览的课表', 'warn')
  } finally {
    busy.value = false
  }
}

async function clearIcs() {
  busy.value = true
  try {
    await api.removeIcs()
    preview.value = null
    notify('已删除上传的课表', 'ok')
  } catch (error) {
    notify(error.message || '删除失败', 'danger')
  } finally {
    busy.value = false
  }
}

async function saveSemester() {
  if (!semesterForm.start_date) {
    notify('请填写第一周周一的日期', 'warn')
    return
  }
  busy.value = true
  try {
    const result = await api.putSemester({
      name: semesterForm.name || null,
      start_date: semesterForm.start_date,
      total_weeks: Number(semesterForm.total_weeks) || 16,
      holidays: [],
    })
    notify(result.message || '学期已保存', 'ok')
    await Promise.all([loadConfig(), runSync()])
    syncSemesterForm()
  } catch (error) {
    notify(error.message || '保存失败', 'danger')
  } finally {
    busy.value = false
  }
}

/* -------------------------------------------------------------- account */

const account = computed(() => state.user || null)
const accountsEnabled = computed(() => Boolean(state.accounts?.enabled))
const minPasswordLength = computed(() => Number(state.accounts?.password_min_length) || 8)
const showPasswordForm = ref(false)
const members = ref([])
const membersBusy = ref(false)
const passwordForm = reactive({ current: '', next: '', confirm: '' })

async function signOut() {
  await logout()
  showPasswordForm.value = false
  members.value = []
}

async function submitPassword() {
  const { current, next, confirm } = passwordForm
  if (!current || !next) {
    notify('请填写当前密码与新密码', 'warn')
    return
  }
  if (next !== confirm) {
    notify('两次输入的新密码不一致', 'warn')
    return
  }
  if (next.length < minPasswordLength.value) {
    notify(`新密码至少 ${minPasswordLength.value} 位`, 'warn')
    return
  }
  const ok = await changePassword(current, next)
  if (ok) {
    passwordForm.current = ''
    passwordForm.next = ''
    passwordForm.confirm = ''
    showPasswordForm.value = false
  } else {
    notify(state.authError || '修改失败', 'danger')
  }
}

async function loadMembers() {
  if (!isAdminUser.value) return
  membersBusy.value = true
  try {
    members.value = await listUsers()
  } catch (error) {
    notify(error.message || '无法读取成员列表', 'warn')
  } finally {
    membersBusy.value = false
  }
}

async function toggleMember(row) {
  try {
    await setUserActive(row.id, !row.is_active)
    await loadMembers()
  } catch (error) {
    notify(error.message || '操作失败', 'danger')
  }
}

/* ---------------------------------------------------------- device flow */

async function startDeviceFlow() {
  deviceBusy.value = true
  pollHint.value = '等待授权…'
  try {
    deviceFlow.value = await api.msStartDevice()
    pollHint.value = deviceFlow.value.message || '等待授权…'
    startPolling(Math.max(3, deviceFlow.value.interval || 5))
  } catch (error) {
    notify(error.message || '无法启动设备代码流程', 'danger')
  } finally {
    deviceBusy.value = false
  }
}

function startPolling(seconds) {
  stopPolling()
  pollTimer = setInterval(() => pollDeviceFlow(false), seconds * 1000)
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function pollDeviceFlow(manual) {
  if (!deviceFlow.value) return
  try {
    const result = await api.msPollDevice()
    if (result.state === 'authorized') {
      stopPolling()
      deviceFlow.value = null
      notify(`Microsoft 账号已连接${result.account ? `：${result.account}` : ''}`, 'ok')
      await Promise.all([loadConfig(), runSync()])
      return
    }
    if (result.state === 'expired' || result.state === 'error') {
      stopPolling()
      pollHint.value = result.message || '代码已过期，请重新发起'
      notify(result.message || '设备代码已过期', 'warn')
      return
    }
    pollHint.value = result.message || '仍在等待授权…'
    if (manual) notify('尚未完成授权', 'warn')
  } catch (error) {
    if (manual) notify(error.message || '轮询失败', 'danger')
  }
}

async function forgetTokens() {
  try {
    const result = await api.msSignOut()
    stopPolling()
    deviceFlow.value = null
    notify(result.message || '已撤销令牌', 'ok')
    await loadConfig()
  } catch (error) {
    notify(error.message || '撤销失败', 'danger')
  }
}

/* ---------------------------------------------------------------- cache */

async function clearCache() {
  try {
    if (typeof caches !== 'undefined') {
      const keys = await caches.keys()
      await Promise.all(keys.map((key) => caches.delete(key)))
    }
    const registrations = await navigator.serviceWorker?.getRegistrations?.()
    registrations?.forEach((registration) => registration.unregister())
    notify('离线缓存已清空，刷新后重建', 'ok')
  } catch (error) {
    notify('清空失败', 'danger')
  }
}
</script>
