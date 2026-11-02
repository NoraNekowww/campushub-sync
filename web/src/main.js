import { createApp } from 'vue'
import App from './App.vue'
import { ingestUrlToken } from './store'
import './style.css'

// A `?token=…` link must be applied before the first API call goes out.
ingestUrlToken()

const app = createApp(App)
app.mount('#app')

// Service worker: production only, but strictly DISABLED on native Android client
// to prevent remote asset caching from overriding local APK assets and causing mixed versions.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  const isNativeApp =
    typeof window !== 'undefined' &&
    Boolean(window.NativeAuthBridge || /CampusHubAndroid/i.test(navigator.userAgent || ''))

  if (!isNativeApp) {
    window.addEventListener('load', () => {
      const base = import.meta.env.BASE_URL || '/'
      navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).catch((error) => {
        console.warn('[campushub] service worker registration failed', error)
      })
    })
  } else {
    // 原生客户端清理任何历史残留的 Service Worker 注册，确保 100% 纯净使用本地 assets
    navigator.serviceWorker
      .getRegistrations()
      .then((registrations) => {
        for (const reg of registrations) {
          reg.unregister()
        }
      })
      .catch(() => {})
  }
}
