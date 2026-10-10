import { createApp } from 'vue'
import App from './App.vue'
import { ingestUrlToken } from './store'
import './style.css'

// A `?token=…` link must be applied before the first API call goes out.
ingestUrlToken()

const app = createApp(App)
app.mount('#app')

// Service worker: production only (dev would cache the HMR bundle). The scope
// follows the deployment base so the same bundle works at `/` and `/schedule/`.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    const base = import.meta.env.BASE_URL || '/'
    navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).catch((error) => {
      console.warn('[campushub] service worker registration failed', error)
    })
  })
}
