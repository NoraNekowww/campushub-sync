import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// `VITE_BASE` lets the same bundle be served from `/` (dev, standalone) or
// from a sub-path such as `/schedule/` (the nzlab.online deployment) — assets,
// the service worker and the API base all follow it. See web/src/api.js.
export default defineConfig({
  base: process.env.VITE_BASE || '/',
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
})
