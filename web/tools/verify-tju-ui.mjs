/**
 * 「一键导入」UI 的真浏览器回归（系统 Edge + 公网线上站点）。
 *
 * 用临时账号 e2echeck 登录后打开设置页，断言：
 *   1. 课表导入卡片的「一键导入课表」按钮存在且可见；
 *   2. 高级折叠块里保留了令牌 / 服务器抓取 / 粘贴导入等兜底；
 *   3. 控制台没有真实错误（匿名 401 噪声已排除）。
 *
 * 用法：
 *   USERNAME_E2E=e2echeck PASSWORD_E2E='...' node tools/verify-tju-ui.mjs
 */
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import puppeteer from 'puppeteer-core'

const URL = process.env.APP_URL || 'https://nzlab.online/schedule/'
const USERNAME = process.env.USERNAME_E2E || 'e2echeck'
const PASSWORD = process.env.PASSWORD_E2E || ''
const EDGE =
  process.env.EDGE_PATH ||
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function setInput(page, idx, value) {
  await page.evaluate(
    (i, v) => {
      const el = [...document.querySelectorAll('input')].filter((n) => n.offsetParent)
      if (!el[i]) return
      el[i].value = v
      el[i].dispatchEvent(new Event('input', { bubbles: true }))
    },
    idx,
    value,
  )
}

async function clickText(page, text) {
  return await page.evaluate((t) => {
    const nodes = [...document.querySelectorAll('button, a, [role="tab"], [role="button"]')]
    const hit = nodes.reverse().find((n) => n.textContent.trim() === t && n.offsetParent !== null)
    if (!hit) return false
    hit.click()
    return true
  }, text)
}

async function main() {
  const profile = mkdtempSync(join(tmpdir(), 'chk-tju-'))
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: 'new',
    userDataDir: profile,
    args: ['--no-first-run', '--no-default-browser-check', '--disable-dev-shm-usage'],
    defaultViewport: { width: 430, height: 932, isMobile: true, hasTouch: true },
  })
  const page = await browser.newPage()
  const errors = []
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    if (/401 \(Unauthorized\)/.test(text)) return
    errors.push(`console: ${text}`)
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))

  const report = {}
  try {
    await page.goto(URL, { waitUntil: 'networkidle2' })
    await page.waitForSelector('input', { timeout: 20000 })
    await clickText(page, '登录')
    await sleep(400)
    await setInput(page, 0, USERNAME)
    await setInput(page, 1, PASSWORD)
    await sleep(200)
    const loginClicked = await clickText(page, '登录')
    report.loginClicked = loginClicked
    await page.waitForFunction(
      () => !document.body.innerText.includes('确认密码'),
      { timeout: 20000 },
    )
    await sleep(1200)

    // 进设置页
    const wentSettings = await clickText(page, '设置')
    report.wentSettings = wentSettings
    await sleep(1200)

    report.tjuCard = await page.$eval('[data-testid="tju-connect"]', (el) => el.innerText)
      .catch(() => null)
    report.oneClick = await page
      .$eval('[data-testid="tju-oneclick"]', (el) => ({
        text: el.innerText.trim(),
        visible: el.offsetParent !== null,
        width: Math.round(el.getBoundingClientRect().width),
      }))
      .catch(() => null)
    report.hiddenByDefault = await page.$eval(
      '[data-testid="tju-paste"]',
      (el) => el.offsetParent === null || !el.closest('details')?.open,
    ).catch(() => null)
    report.advancedSummary = await page
      .$eval('[data-testid="tju-connect"] details summary', (el) => el.innerText.trim())
      .catch(() => null)
    report.hasTokenChip = await page
      .$$eval('[data-testid="tju-connect"] .chip', (els) => els.map((e) => e.innerText.trim()))
      .catch(() => [])

    await page.screenshot({ path: join(tmpdir(), 'tju-ui.png'), fullPage: true })
    report.screenshot = join(tmpdir(), 'tju-ui.png')
  } catch (error) {
    report.fatal = error.message
  } finally {
    await browser.close()
  }
  report.realErrors = errors
  report.pass = Boolean(
    report.oneClick?.visible &&
      report.oneClick?.text?.includes('导入课表') &&
      report.advancedSummary &&
      errors.length === 0,
  )
  console.log(JSON.stringify(report, null, 2))
  process.exit(report.pass ? 0 : 1)
}

main().catch((error) => {
  console.error(error)
  process.exit(2)
})
