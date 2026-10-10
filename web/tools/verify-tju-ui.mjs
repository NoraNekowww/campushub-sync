/**
 * 课表导入（教务系统主路径 + 微北洋兜底）UI 的真浏览器回归：系统 Edge + 公网线上站点。
 *
 * 用临时账号登录后打开设置页，断言：
 *   1. 主路径是「教务系统」——学号 + 教务密码两个输入框 + 可见的「一键导入课表」按钮；
 *   2. 两个框空着就点按钮 → 只给提示，不发任何导入请求（不能让人莫名其妙地失败）；
 *   3. 服务器上的教务验证码接口真能取到一张真图（data:image/jpeg;base64…，且浏览器能解码）；
 *   4. 微北洋那条兜底还在「高级」里（校园网内可用）；
 *   5. 控制台没有真实错误（匿名 401 噪声已排除）。
 *
 * 用法：
 *   USERNAME_E2E=e2echeck PASSWORD_E2E='...' node tools/verify-tju-ui.mjs
 */
import { mkdtempSync, writeFileSync } from 'node:fs'
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
  const tjuRequests = []
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    if (/401 \(Unauthorized\)/.test(text)) return
    errors.push(`console: ${text}`)
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))
  page.on('request', (req) => {
    const url = req.url()
    if (url.includes('/api/tju/')) tjuRequests.push(`${req.method()} ${url.split('/api/')[1]}`)
  })

  const report = {}
  try {
    await page.goto(URL, { waitUntil: 'networkidle2' })
    await page.waitForSelector('input', { timeout: 20000 })
    await clickText(page, '登录')
    await sleep(400)
    await setInput(page, 0, USERNAME)
    await setInput(page, 1, PASSWORD)
    await sleep(200)
    report.loginClicked = await clickText(page, '登录')
    await page.waitForFunction(
      () => !document.body.innerText.includes('确认密码'),
      { timeout: 20000 },
    )
    await sleep(1200)

    report.wentSettings = await clickText(page, '设置')
    await sleep(1500)

    report.tjuCardTitle = await page
      .$eval('[data-testid="tju-connect"] h3', (el) => el.innerText.trim())
      .catch(() => null)
    report.jwFields = await page.evaluate(() =>
      ['jw-account', 'jw-password'].map((id) => {
        const el = document.querySelector(`[data-testid="${id}"]`)
        return {
          id,
          present: Boolean(el),
          visible: Boolean(el && el.offsetParent),
          placeholder: el?.placeholder || '',
        }
      }),
    )
    report.oneClick = await page
      .$eval('[data-testid="tju-oneclick"]', (el) => ({
        text: el.innerText.trim(),
        visible: el.offsetParent !== null,
        width: Math.round(el.getBoundingClientRect().width),
      }))
      .catch(() => null)

    // 有凭据时才会有这行；没有也算正常（只是少一条证据）
    report.lastImportLine = await page
      .$eval('[data-testid="jw-last-import"]', (el) => el.innerText.trim())
      .catch(() => null)

    // --- 空着点按钮：应当只提示、不发导入请求 ---
    tjuRequests.length = 0
    await page.click('[data-testid="tju-oneclick"]').catch(() => {})
    await sleep(900)
    report.emptyClick = {
      requests: [...tjuRequests],
      hintShown: await page
        .$eval('[data-testid="tju-connect"]', (el) => /先填/.test(el.innerText))
        .catch(() => null),
      captchaBlockVisible: await page
        .$eval('[data-testid="jw-captcha"]', (el) => el.offsetParent !== null)
        .catch(() => false),
    }

    // --- 服务器上的教务验证码：真能取到一张能解码的图 ---
    report.captcha = await page.evaluate(async () => {
      const res = await fetch('./api/tju/jw/captcha', { method: 'POST', credentials: 'include' })
      if (!res.ok) return { status: res.status }
      const body = await res.json()
      const image = body?.detail?.image || ''
      const hasImage = image.startsWith('data:image/jpeg;base64,')
      const decoded = hasImage
        ? await new Promise((resolve) => {
            const img = new Image()
            img.onload = () => resolve(img.naturalWidth > 0)
            img.onerror = () => resolve(false)
            img.src = image
          })
        : false
      return {
        status: res.status,
        hasImage,
        base64Chars: image.length,
        decoded,
        captchaId: Boolean(body?.detail?.captcha_id),
      }
    })
    if (report.captcha?.hasImage) {
      const raw = await page.evaluate(async () => {
        const res = await fetch('./api/tju/jw/captcha', { method: 'POST', credentials: 'include' })
        return (await res.json())?.detail?.image || ''
      })
      if (raw.includes(',')) {
        const file = join(tmpdir(), 'jw-captcha.jpg')
        writeFileSync(file, Buffer.from(raw.split(',')[1], 'base64'))
        report.captchaFile = file
      }
    }

    // --- 微北洋兜底还在高级里 ---
    report.mwFallback = await page
      .$eval('[data-testid="tju-mw-oneclick"]', (el) => ({
        text: el.innerText.trim(),
        insideDetails: Boolean(el.closest('details')),
      }))
      .catch(() => null)
    report.advancedSummary = await page
      .$eval('[data-testid="tju-connect"] details summary', (el) => el.innerText.trim())
      .catch(() => null)

    report.cardText = await page
      .$eval('[data-testid="tju-connect"]', (el) => el.innerText)
      .catch(() => null)
    await page.screenshot({ path: join(tmpdir(), 'tju-ui.png'), fullPage: true })
    report.screenshot = join(tmpdir(), 'tju-ui.png')
  } catch (error) {
    report.fatal = error.message
  } finally {
    await browser.close()
  }

  report.realErrors = errors
  report.pass = Boolean(
    report.jwFields?.every((f) => f.present && f.visible) &&
      report.oneClick?.visible &&
      report.oneClick?.text?.includes('导入课表') &&
      report.emptyClick?.requests?.length === 0 &&
      report.emptyClick?.hintShown === true &&
      report.captcha?.decoded === true &&
      report.mwFallback?.insideDetails &&
      !report.fatal &&
      errors.length === 0,
  )
  console.log(JSON.stringify(report, null, 2))
  process.exit(report.pass ? 0 : 1)
}

main().catch((error) => {
  console.error(error)
  process.exit(2)
})
