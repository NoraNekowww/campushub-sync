<template>
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
          <a
            :href="downloadUrl"
            target="_blank"
            class="btn-primary !py-1 !px-2.5 inline-flex items-center gap-1 shadow-sm"
            data-testid="update-download-btn"
          >
            <Download :size="12" />
            一键下载
          </a>

          <button
            type="button"
            class="btn-ghost !border-indigo-200 !bg-transparent !py-1 !px-2 text-indigo-700 hover:!bg-indigo-100/60 dark:!border-indigo-800 dark:text-indigo-300 dark:hover:!bg-indigo-900/40"
            title="永久关闭此版本的更新提示"
            data-testid="update-dismiss-btn"
            @click="dismissUpdate"
          >
            <BellOff :size="12" />
            永久关闭该通知
          </button>
        </div>
      </div>
    </aside>
  </Transition>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { BellOff, Download, Sparkles } from 'lucide-vue-next'

const CURRENT_VERSION = '2.0.5'
const DISMISSED_KEY = 'campushub.dismissed_update'

const latestRelease = ref(null)
const dismissed = ref(false)

const downloadUrl = computed(() => {
  if (latestRelease.value?.apkUrl) return latestRelease.value.apkUrl
  return 'https://github.com/NoraNekowww/campushub-sync/releases/latest/download/CampusHub.apk'
})

const showUpdateBanner = computed(() => {
  if (dismissed.value) return false
  if (!latestRelease.value?.version) return false
  return isNewer(latestRelease.value.version, CURRENT_VERSION)
})

/**
 * 语义化版本号比较 (例如 '2.0.3' > '2.0.2')
 */
function isNewer(latest, current) {
  const parse = (v) => String(v).replace(/^v/i, '').split('.').map((n) => parseInt(n, 10) || 0)
  const l = parse(latest)
  const c = parse(current)
  for (let i = 0; i < Math.max(l.length, c.length); i++) {
    const lv = l[i] || 0
    const cv = c[i] || 0
    if (lv > cv) return true
    if (lv < cv) return false
  }
  return false
}

function dismissUpdate() {
  dismissed.value = true
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
      dismissed.value = true
      return
    }

    latestRelease.value = {
      version,
      title,
      apkUrl: apkUrl || 'https://github.com/NoraNekowww/campushub-sync/releases/latest/download/CampusHub.apk',
    }
  } catch {
    /* 离线或网络异常时不阻塞主界面 */
  }
}

onMounted(() => {
  // 延迟 1.5 秒检查更新，避免与首屏网络竞态
  setTimeout(checkLatestVersion, 1500)
})
</script>
