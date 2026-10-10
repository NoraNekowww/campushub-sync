// verify-panel.mjs — 用真浏览器证明「设置页」确实渲染出来了（不是空白）。
// 用法（令牌走命令替换，永不落到命令行/日志里）：
//   TOKEN=$(ssh ... 'grep -m1 "^ADMIN_TOKEN=" /var/www/schedule/.env | cut -d= -f2-' | tr -d '"') node tools/verify-panel.mjs
import puppeteer from 'puppeteer-core'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const URL = process.env.URL || 'https://nzlab.online/schedule/'
const TOKEN = process.env.TOKEN || ''
const OUT = process.env.OUT || 'C:/Users/NorazA/AppData/Local/Temp/settings-page.png'
const EXE = process.env.EDGE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'

const errors = []
const browser = await puppeteer.launch({
  executablePath: EXE,
  headless: 'new',
  userDataDir: mkdtempSync(join(tmpdir(), 'edge-verify-')),
  args: ['--no-first-run', '--no-default-browser-check', '--disable-gpu'],
})
const page = await browser.newPage()
await page.setViewport({ width: 430, height: 932, deviceScaleFactor: 2 })
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()}`))

await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 })
const gateFirst = (await page.$('[data-testid="auth-gate"]')) !== null

if (TOKEN) {
  await page.evaluate((t) => localStorage.setItem('campushub.adminToken', t), TOKEN)
  await page.reload({ waitUntil: 'networkidle2', timeout: 60000 })
}

// 门只认账号会话（HttpOnly cookie），localStorage 令牌进不去 → 用真账号登录
const USER = process.env.USERNAME_E2E || ''
const PASS = process.env.PASSWORD_E2E || ''
if (USER && (await page.$('[data-testid="auth-gate"]'))) {
  await page.type('[data-testid="auth-username"]', USER)
  await page.type('[data-testid="auth-password"]', PASS)
  await Promise.all([
    page.waitForFunction(() => !document.querySelector('[data-testid="auth-gate"]'), { timeout: 30000 }),
    page.click('[data-testid="auth-submit"]'),
  ]).catch((e) => errors.push(`login: ${e.message}`))
}
errors.length = 0 // 匿名首屏的 401 是预期噪声，登录后再重新计数

await page.waitForFunction(() => !document.querySelector('[data-testid="auth-gate"]'), { timeout: 30000 }).catch(() => {})

const navItems = await page.evaluate(() =>
  [...document.querySelectorAll('nav button, nav a, [role="tab"], footer button')].map((n) => n.innerText.trim()),
)
const clicked = await page.evaluate(() => {
  const el = [...document.querySelectorAll('button, a, [role="tab"]')].find((n) => n.innerText.trim() === '设置')
  if (!el) return false
  el.click()
  return true
})

let settingsRendered = false
try {
  await page.waitForSelector('[data-testid="onboarding-section"]', { timeout: 15000 })
  settingsRendered = true
} catch {
  /* 下面把现场一起报出来 */
}

await page.evaluate(() =>
  document.querySelector('[data-testid="onboarding-section"]')?.scrollIntoView({ block: 'start' }),
)
await new Promise((r) => setTimeout(r, 800))
await page.screenshot({ path: OUT })

const report = await page.evaluate(() => {
  const txt = (s) => document.querySelector(s)?.innerText?.replace(/\s+/g, ' ').trim() || null
  return {
    gateVisible: !!document.querySelector('[data-testid="auth-gate"]'),
    onboardingCard: txt('[data-testid="onboarding-section"]'),
    registrationCard: txt('[data-testid="registration-section"]'),
    cardCount: document.querySelectorAll('section.card').length,
    bodyChars: document.body.innerText.length,
    bodyHead: document.body.innerText.replace(/\s+/g, ' ').slice(0, 200),
  }
})
await browser.close()

console.log(JSON.stringify({ gateFirst, navItems, clickedSettingsTab: clicked, settingsRendered, errors, report, screenshot: OUT }, null, 2))
process.exit(errors.length || !settingsRendered ? 1 : 0)
