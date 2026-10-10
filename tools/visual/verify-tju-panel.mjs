/**
 * Live check of the new 微北洋 panel on the deployed PWA.
 *
 * Loads https://nzlab.online/schedule/ in headless Edge with the admin token in
 * localStorage, opens 设置, exercises the panel (status + the server-side fetch
 * button, which must report the campus-network gate), and screenshots it.
 *
 *   CAMPUSHUB_ADMIN_TOKEN=... node verify-tju-panel.mjs [base-url]
 */
import { existsSync, mkdirSync } from 'node:fs'
import puppeteer from 'puppeteer-core'

const BASE = (process.argv[2] || 'https://nzlab.online').replace(/\/$/, '')
const TOKEN = process.env.CAMPUSHUB_ADMIN_TOKEN || ''
const OUT_DIR = new URL('./shots/', import.meta.url).pathname.replace(/^\//, '')

const BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
]

let failures = 0
const check = (ok, label, extra = '') => {
  if (!ok) failures += 1
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? ` — ${extra}` : ''}`)
}

const browser = await puppeteer.launch({
  executablePath: BROWSERS.find((p) => existsSync(p)),
  headless: 'new',
  args: ['--no-sandbox', '--disable-http2'],
})
const page = await browser.newPage()
await page.setViewport({ width: 430, height: 900, deviceScaleFactor: 2 })

const errors = []
page.on('pageerror', (error) => errors.push(String(error)))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text())
})

try {
  await page.goto(`${BASE}/schedule/`, { waitUntil: 'networkidle2', timeout: 60000 })
  await page.evaluate((token) => {
    localStorage.setItem('campushub.adminToken', token)
    localStorage.setItem('campushub.theme', 'light')
  }, TOKEN)
  await page.reload({ waitUntil: 'networkidle2', timeout: 60000 })
  errors.length = 0 // the first, tokenless load is expected to 401 (AuthGate)

  const switched = await page.evaluate(() => {
    const tab = document.querySelector('[data-testid=nav-tab][data-tab="settings"]')
    if (!tab) return false
    tab.click()
    return true
  })
  check(switched, 'bottom nav exposes the settings tab')

  await page.waitForSelector('[data-testid=tju-connect]', { timeout: 20000 })
  check(true, '微北洋 panel is rendered')

  const panelText = await page.$eval('[data-testid=tju-connect]', (node) => node.innerText.replace(/\s+/g, ' '))
  check(panelText.includes('微北洋直连'), 'panel carries its heading', panelText.slice(0, 60))
  check(panelText.includes('校园网'), 'panel explains the campus-network constraint')

  const account = await page.$('[data-testid=tju-account]')
  const save = await page.$('[data-testid=tju-save-credentials]')
  check(Boolean(account && save), 'credential inputs exist')

  // The server-side button must come back with the campus-network explanation.
  await page.click('[data-testid=tju-server-sync]')
  await page.waitForFunction(
    () => {
      const node = document.querySelector('[data-testid=tju-status-msg]')
      if (!node) return false
      const text = node.innerText.trim()
      // wait past the in-flight hint, for the actual result
      return text.length > 0 && !text.includes('正在尝试')
    },
    { timeout: 60000 },
  )
  const status = await page.$eval('[data-testid=tju-status-msg]', (node) => node.innerText.trim())
  check(/校园网|凭据|课表/.test(status), 'server-side fetch reports a real outcome', status.slice(0, 80))

  mkdirSync(OUT_DIR, { recursive: true })
  const shot = `${OUT_DIR}tju-panel.png`
  await page.$eval('[data-testid=tju-connect]', (node) => node.scrollIntoView({ block: 'center' }))
  await page.screenshot({ path: shot, fullPage: false })
  console.log(`\nscreenshot: ${shot}`)
  console.log(`page errors: ${errors.length ? errors.slice(0, 3).join(' | ') : 'none'}`)
  check(errors.length === 0, 'no console/page errors while rendering')
} catch (error) {
  check(false, 'panel verification crashed', String(error).slice(0, 200))
} finally {
  await browser.close()
}

console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nALL CHECKS PASSED')
process.exit(failures ? 1 : 0)
