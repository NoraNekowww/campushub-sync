/**
 * backgroundBlur.js
 * 预制高斯模糊图层生成器：
 * 采用离屏 Canvas 一次性离线模糊生成轻量级 DataURL / ObjectURL，
 * 避免对每个玻璃卡片和每个渲染帧反复执行高开销的动态 CSS backdrop-filter，
 * 极大幅度节省移动端与桌面端的 GPU / CPU 算力开销。
 */

let cachedSourceUrl = ''
let cachedBlurredUrl = ''
let inFlightPromise = null

/**
 * 离屏快速多通道下采样方框模糊 / 高斯近似
 * 先将原图下采样到适合移动端视网膜屏的合适尺寸，再做一次高斯模糊处理并输出轻量 WebP/JPEG
 */
export async function generatePreblurredImage(srcUrl, blurRadius = 24) {
  if (!srcUrl) return ''
  if (srcUrl === cachedSourceUrl && cachedBlurredUrl) {
    return cachedBlurredUrl
  }
  if (inFlightPromise && inFlightPromise._src === srcUrl) {
    return inFlightPromise
  }

  const task = (async () => {
    try {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.referrerPolicy = 'no-referrer'

      await new Promise((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = (e) => reject(new Error('Background image load failed: ' + e))
        img.src = srcUrl
      })

      // 下采样降维：背景图无需 4K 分辨率，宽度限制在 640px 既能保证超高清柔化，又极大减少内存占用与 Canvas 滤镜耗时
      const targetW = Math.min(img.naturalWidth || 640, 640)
      const ratio = targetW / (img.naturalWidth || targetW)
      const targetH = Math.round((img.naturalHeight || 360) * ratio)

      const canvas = document.createElement('canvas')
      canvas.width = targetW
      canvas.height = targetH
      const ctx = canvas.getContext('2d')

      if (!ctx) return ''

      // 运用 Canvas 原生 filter 进行一次性离屏模糊
      // 在小分辨率下模糊半径相应缩放（大约 12px ~ 16px 即呈现浓郁磨砂深度）
      const scaledRadius = Math.max(8, Math.round(blurRadius * ratio * 1.5))
      ctx.filter = `blur(${scaledRadius}px)`
      // 适度向外放大绘制避免模糊边缘泛白黑边
      const overflow = scaledRadius * 2
      ctx.drawImage(img, -overflow, -overflow, targetW + overflow * 2, targetH + overflow * 2)

      // 导出高压缩比 webp / jpeg
      const blurredDataUrl = canvas.toDataURL('image/jpeg', 0.82)
      cachedSourceUrl = srcUrl
      cachedBlurredUrl = blurredDataUrl

      // 挂载到全局 CSS 变量，供卡片使用
      if (typeof document !== 'undefined') {
        document.documentElement.style.setProperty('--preblurred-bg-url', `url("${blurredDataUrl}")`)
        document.documentElement.classList.add('has-preblurred-bg')
      }

      return blurredDataUrl
    } catch (err) {
      console.warn('[backgroundBlur] Canvas 预制模糊生成降级:', err)
      // 降级兜底：直接使用原图地址，CSS 仍保持优雅渲染
      if (typeof document !== 'undefined') {
        document.documentElement.style.setProperty('--preblurred-bg-url', `url("${srcUrl}")`)
      }
      return srcUrl
    }
  })()

  task._src = srcUrl
  inFlightPromise = task
  return task
}

export function clearBlurredCache() {
  cachedSourceUrl = ''
  cachedBlurredUrl = ''
  if (typeof document !== 'undefined') {
    document.documentElement.style.removeProperty('--preblurred-bg-url')
    document.documentElement.classList.remove('has-preblurred-bg')
  }
}
