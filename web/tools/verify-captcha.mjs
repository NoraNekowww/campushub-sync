// verify-captcha.mjs — 真浏览器验证「注册表单里的图形验证码确实画出来了、且可见高度>0」。
// 用法: node tools/verify-captcha.mjs   （Edge 路径可用 EDGE= 覆盖）
import puppeteer from 'puppeteer-core'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const URL = process.env.URL || 'https://nzlab.online/schedule/'
const OUT = process.env.OUT || 'C:/Users/NorazA/AppData/Local/Temp/captcha-check.png'
const EXE = process.env.EDGE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'

const errors = []
const netCaptcha = []
const browser = await puppeteer.launch({
  executablePath: EXE,
  headless: 'new',
  userDataDir: mkdtempSync(join(tmpdir(), 'edge-captcha-')),
  args: ['--no-first-run', '--no-default-browser-check', '--disable-gpu'],
})
const page = await browser.newPage()
await page.setViewport({ width: 430, height: 932, deviceScaleFactor: 2 })
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('response', (r) => {
  if (r.url().includes('/auth/captcha')) netCaptcha.push({ status: r.status(), url: r.url() })
})

await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 })
await page.waitForSelector('[data-testid="auth-gate"]', { timeout: 30000 }).catch(() => {})

// 切到「注册」页签
const tabClicked = await page.evaluate(() => {
  const btn = document.querySelector('[data-testid="auth-tab-register"]')
    || [...document.querySelectorAll('[data-testid^="auth-tab-"], button')].find((b) => /注册/.test(b.innerText))
  if (!btn) return false
  btn.click()
  return true
})

// 等验证码 SVG（前端在 captcha_required 为真时才渲染这个块）
let svgBox = null
try {
  await page.waitForSelector('svg.campushub-captcha-svg', { timeout: 15000 })
  svgBox = await page.$eval('svg.campushub-captcha-svg', (el) => {
    const r = el.getBoundingClientRect()
    return { w: Math.round(r.width), h: Math.round(r.height), paths: el.querySelectorAll('path, line, rect, text').length }
  })
} catch {
  /* 下面把现场报出来 */
}

const report = await page.evaluate(() => {
  const required = !!document.querySelector('[data-testid="auth-captcha"]')
  const holder = document.querySelector('span.block.h-\\[52px\\]') || document.querySelector('svg.campushub-captcha-svg')?.parentElement
  return {
    captchaBlockRendered: required,
    holderHasSvg: !!holder?.querySelector('svg'),
    hint: document.querySelector('[data-testid="auth-captcha-refresh"]')?.title
      || [...document.querySelectorAll('div,span')].map((n) => n.innerText).find((t) => t && /点图换一张|加载中/.test(t)) || null,
    inviteFieldPresent: !!document.querySelector('[data-testid="auth-invite"]'),
    bodyHead: document.body.innerText.replace(/\s+/g, ' ').slice(0, 220),
  }
})
await new Promise((r) => setTimeout(r, 500))
await page.screenshot({ path: OUT })
await browser.close()

// 匿名访客首屏必然有几个 401（拉 events/status 未登录），是预期噪声
const realErrors = errors.filter((e) => !/401 \(Unauthorized\)/.test(e))

const ok =
  tabClicked &&
  !!svgBox &&
  svgBox.w > 0 &&
  svgBox.h > 0 &&
  report.captchaBlockRendered &&
  realErrors.length === 0
console.log(
  JSON.stringify(
    { tabClicked, svgBox, netCaptcha, errors, realErrors, report, screenshot: OUT, pass: ok },
    null,
    2,
  ),
)
process.exit(ok ? 0 : 1)
