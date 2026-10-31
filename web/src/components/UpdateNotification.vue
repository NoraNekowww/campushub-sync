<template>
  <div>
    <!-- 顶部横幅提示 -->
    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="-translate-y-4 opacity-0"
      leave-active-class="transition duration-200 ease-in"
      leave-to-class="-translate-y-2 opacity-0"
    >
      <aside
        v-if="showUpdateBanner"
        class="border-b border-indigo-200 bg-indigo-50/95 px-4 py-2.5 backdrop-blur dark:border-indigo-800/60 dark:bg-indigo-950/90"
        data-testid="app-update-banner"
        role="region"
        aria-label="版本更新通知"
      >
        <div class="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2.5 text-xs text-indigo-900 dark:text-indigo-200">
          <div class="flex min-w-0 items-center gap-2">
            <Sparkles :size="15" class="shrink-0 text-brand-600 dark:text-brand-400" />
            <p class="truncate font-medium">
              发现新版本 <strong>v{{ latestRelease.version }}</strong>
              <span v-if="latestRelease.title" class="hidden opacity-80 sm:inline">（{{ latestRelease.title }}）</span>
            </p>
          </div>

          <div class="flex items-center gap-2 text-[11px]">
            <button
              type="button"
              class="btn-primary !py-1 !px-2.5 inline-flex items-center gap-1 shadow-sm"
              data-testid="update-view-modal-btn"
              @click="openModal"
            >
              <Download :size="12" />
              立即查看
            </button>

            <button
              type="button"
              class="btn-ghost !border-indigo-200 !bg-transparent !py-1 !px-2 text-indigo-700 hover:!bg-indigo-100/60 dark:!border-indigo-800 dark:text-indigo-300 dark:hover:!bg-indigo-900/40"
              title="暂时忽略此版本的顶部横幅"
              @click="dismissBannerOnly"
            >
              <X :size="12" />
            </button>
          </div>
        </div>
      </aside>
    </Transition>

    <!-- 网络检测到新版本时的醒目弹窗推送 (Modal) -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 scale-95"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="showModal"
        class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm"
        data-testid="update-modal-dialog"
        role="dialog"
        aria-modal="true"
      >
        <div class="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl ring-1 ring-slate-900/10 dark:bg-slate-900 dark:ring-slate-100/10 animate-fade-up">
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-2.5">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950/50 dark:text-brand-400">
                <Rocket :size="20" />
              </div>
              <div>
                <h3 class="text-base font-semibold text-slate-800 dark:text-slate-100">发现新版本更新</h3>
                <p class="text-xs text-slate-400 dark:text-slate-500">
                  当前 v{{ CURRENT_VERSION }} → 最新 v{{ latestRelease?.version }}
                </p>
              </div>
            </div>
            <button
              type="button"
              class="btn-ghost !p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
              @click="closeModal"
            >
              <X :size="16" />
            </button>
          </div>

          <div class="my-4 rounded-xl bg-slate-50 p-3.5 text-xs text-slate-600 dark:bg-slate-800/50 dark:text-slate-300 space-y-2">
            <div class="font-medium text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
              <Sparkles :size="14" class="text-amber-500" />
              <span>{{ latestRelease?.title || '体验与性能全面升级' }}</span>
            </div>
            <ul class="list-disc pl-4 space-y-1 text-slate-500 dark:text-slate-400 text-[11px] leading-relaxed">
              <li>底栏右侧全新增设「历史日程完成归档」一栏，随时回溯历史。</li>
              <li>设置挪至右上角轻量 icon，释放屏幕空间。</li>
              <li>底层代码与响应式调度深度优化，低性能设备更加丝滑省电。</li>
              <li>支持原生网络新版弹窗直达推送与一键下载。</li>
            </ul>
          </div>

          <div class="flex items-center justify-between gap-2.5 pt-1">
            <button
              type="button"
              class="btn-ghost !px-3 !py-2 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              @click="dismissForever"
            >
              <BellOff :size="13" class="mr-1" />
              不再提示此版本
            </button>
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="btn-ghost !px-3 !py-2 text-xs"
                @click="closeModal"
              >
                稍后再说
              </button>
              <a
                :href="downloadUrl"
                target="_blank"
                class="btn-primary !px-4 !py-2 text-xs flex items-center gap-1.5 shadow-md shadow-brand-500/20"
                @click="closeModal"
              >
                <Download :size="14" />
                <span>立即下载更新</span>
              </a>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { BellOff, Download, Rocket, Sparkles, X } from 'lucide-vue-next'

const CURRENT_VERSION = '2.3.0'
const DISMISSED_KEY = 'campushub.dismissed_update'
const POPUP_SEEN_KEY = 'campushub.popup_seen_version'

const latestRelease = ref(null)
const bannerDismissed = ref(false)
const showModal = ref(false)

const downloadUrl = computed(() => {
  if (latestRelease.value?.apkUrl) return latestRelease.value.apkUrl
  return 'https://github.com/NoraNekowww/campushub-sync/releases/latest/download/CampusHub.apk'
})

const isNew = computed(() => {
  if (!latestRelease.value?.version) return false
  return isNewer(latestRelease.value.version, CURRENT_VERSION)
})

/**
 * 判断是否属于移动端环境（包括 Android 原生 App、PWA、移动设备客户端）
 * 网页端（桌面端浏览器）彻底禁用更新提示；移动端正常接收更新提醒与弹窗。
 */
function isMobileClient() {
  if (typeof window === 'undefined') return false
  const ua = navigator.userAgent || ''
  return Boolean(
    window.NativeAuthBridge ||
    window.__CAMPUSHUB_CLIENT__ ||
    /CampusHubAndroid/i.test(ua) ||
    /Android|iPhone|iPad|iPod|Mobile/i.test(ua) ||
    window.matchMedia?.('(display-mode: standalone)')?.matches
  )
}

const showUpdateBanner = computed(() => {
  // 网页桌面端无需推送更新；仅在移动端展示
  if (!isMobileClient()) return false
  if (bannerDismissed.value) return false
  return isNew.value
})

/**
 * 严格语义化版本号比较：严格只有最新版本大于当前版本 (latest > current) 才返回 true。
 * 当新版本与当前版本相同 (latest === current) 或小于当前版本时，坚决返回 false，不提示更新。
 */
function isNewer(latest, current) {
  if (!latest || !current) return false
  const cleanL = String(latest).trim().replace(/^v/i, '')
  const cleanC = String(current).trim().replace(/^v/i, '')
  if (cleanL === cleanC) return false

  const parse = (v) => v.split('.').map((n) => parseInt(n, 10) || 0)
  const l = parse(cleanL)
  const c = parse(cleanC)
  const maxLen = Math.max(l.length, c.length)
  for (let i = 0; i < maxLen; i++) {
    const lv = l[i] ?? 0
    const cv = c[i] ?? 0
    if (lv > cv) return true
    if (lv < cv) return false
  }
  return false
}

function openModal() {
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

function dismissBannerOnly() {
  bannerDismissed.value = true
}

function dismissForever() {
  bannerDismissed.value = true
  showModal.value = false
  if (latestRelease.value?.version) {
    try {
      localStorage.setItem(DISMISSED_KEY, latestRelease.value.version)
    } catch {
      /* ignore */
    }
  }
}

async function checkLatestVersion() {
  try {
    const savedDismissed = localStorage.getItem(DISMISSED_KEY)
    const popupSeen = localStorage.getItem(POPUP_SEEN_KEY)
    let version = ''
    let title = ''
    let apkUrl = ''

    // 通道 1：优先请求本站 /api/version，国内环境免翻墙直连秒开
    try {
      const vResp = await fetch('./api/version')
      if (vResp.ok) {
        const vData = await vResp.json()
        version = String(vData.version || '').replace(/^v/i, '')
        title = vData.title || ''
        apkUrl = vData.download_url || vData.github_download_url || ''
      }
    } catch {
      // 忽略，fallback 到通道 2
    }

    // 通道 2：GitHub API 兜底
    if (!version) {
      const resp = await fetch('https://api.github.com/repos/NoraNekowww/campushub-sync/releases/latest', {
        headers: { Accept: 'application/vnd.github.v3+json' },
      })
      if (resp.ok) {
        const data = await resp.json()
        const tagName = data.tag_name || ''
        version = tagName.replace(/^v/i, '')
        title = data.name || ''
        const apkAsset = data.assets?.find((a) => a.name === 'CampusHub.apk')
        apkUrl = apkAsset?.browser_download_url || ''
      }
    }

    if (!version) return
    if (savedDismissed === version) {
      bannerDismissed.value = true
      return
    }

    latestRelease.value = {
      version,
      title,
      apkUrl: apkUrl || 'https://github.com/NoraNekowww/campushub-sync/releases/latest/download/CampusHub.apk',
    }

    // 网络检测到有新版本时，自动弹出居中弹窗推送（仅在移动端环境弹出，桌面网页端不弹；每个版本只主动弹一次，避免反复打扰）
    if (isMobileClient() && isNewer(version, CURRENT_VERSION) && popupSeen !== version) {
      setTimeout(() => {
        showModal.value = true
        try {
          localStorage.setItem(POPUP_SEEN_KEY, version)
        } catch {}
      }, 800)
    }
  } catch {
    /* 离线或网络异常时不阻塞主界面 */
  }
}

onMounted(() => {
  // 延迟检查，保证首屏秒开渲染完成
  setTimeout(checkLatestVersion, 1200)
})
</script>
