/**
 * Live check of the nzlab portal account widget + the /schedule/ login wall.
 *
 *   node verify-portal.mjs --base https://nzlab.online \
 *        --invite <邀请码> --user nz-e2e-web --password <password>
 *
 * Creates a real account on the real host, checks the redirect into the PWA,
 * the signed-in state on the portal, the logout, and that no JS errors or
 * unexpected HTTP failures happen along the way. Run it on a throwaway account;
 * delete the row afterwards if you want the invitee to become the first admin.
 */
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(HERE, 'shots')

const BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
]

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, arg, index, all) => {
    if (arg.startsWith('--')) pairs.push([arg.slice(2), all[index + 1]])
    return pairs
  }, []),
)
const BASE = (args.base || 'https://nzlab.online').replace(/\/$/, '')
const INVITE = args.invite || ''
const USER = args.user || `nz-e2e-${Date.now().toString(36)}`
const PASSWORD = args.password || 'e2e-password-1'

const failures = []
const check = (ok, label, detail = '') => {
  if (!ok) failures.push(label)
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ` — ${detail}` : ''}`)
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const has = (page, selector) => page.evaluate((s) => Boolean(document.querySelector(s)), selector)
const textOf = (page, selector) =>
  page.evaluate((s) => document.querySelector(s)?.textContent?.trim() || '', selector)

async function waitFor(page, selector, timeout = 20000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await has(page, selector)) return true
    await sleep(200)
  }
  return false
}

/** Existence is not enough: the account widget only becomes visible once the
    session fetch resolves, so clicks must wait for a real layout box. */
async function waitVisible(page, selector, timeout = 20000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const visible = await page.evaluate((s) => {
      const el = document.querySelector(s)
      if (!el) return false
      const box = el.getBoundingClientRect()
      return box.width > 0 && box.height > 0
    }, selector)
    if (visible) return true
    await sleep(150)
  }
  return false
}

async function waitEnabled(page, selector, timeout = 20000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const enabled = await page.evaluate((s) => !document.querySelector(s)?.disabled, selector)
    if (enabled) return true
    await sleep(150)
  }
  return false
}

async function pickBrowser() {
  const { existsSync } = await import('node:fs')
  for (const candidate of BROWSERS) if (existsSync(candidate)) return candidate
  throw new Error('no system browser found')
}

const main = async () => {
  mkdirSync(OUT, { recursive: true })
  const browser = await puppeteer.launch({
    executablePath: await pickBrowser(),
    headless: 'new',
    userDataDir: mkdtempSync(resolve(tmpdir(), 'nzlab-portal-')),
    args: ['--headless=new', '--hide-scrollbars', '--no-sandbox', '--ignore-certificate-errors'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 })

  const pageErrors = []
  const failed = []
  const PROBES = [/\/schedule\/api\/(events|config|status|auth\/me)/, /\/schedule\/api\/auth\/(register|login)/]
  page.on('pageerror', (error) => pageErrors.push(String(error)))
  page.on('response', (response) => {
    const url = response.url()
    const expected = (response.status() === 401 || response.status() === 403) && PROBES.some((re) => re.test(url))
    if (response.status() >= 400 && !url.includes('favicon') && !expected) {
      failed.push(`${response.status()} ${url}`)
    }
  })

  // ------------------------------------------------------------- the portal
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
  check(await waitVisible(page, '#account-open'), 'portal shows the account button in the top-right')
  check(await has(page, '#card-schedule'), 'portal lists the schedule project')
  check(
    (await textOf(page, '#card-schedule-badge')).includes('需登录'),
    'schedule card is badged as locked before signing in',
    await textOf(page, '#card-schedule-badge'),
  )
  await page.screenshot({ path: resolve(OUT, '20-portal-signed-out.png') })

  // ----------------------------------------------------- register from portal
  await page.click('#account-open')
  check(await waitFor(page, '#auth-overlay:not(.hidden)'), 'the account modal opens')
  check(
    await waitEnabled(page, '#tab-register'),
    'the register tab is available (invite registration is open)',
  )
  await page.click('#tab-register')
  await sleep(150)
  const fill = async (selector, value) => {
    await page.click(selector, { clickCount: 3 })
    await page.type(selector, value, { delay: 15 })
  }
  await fill('#auth-username', USER)
  await fill('#auth-password', PASSWORD)
  await fill('#auth-confirm', PASSWORD)
  if (INVITE) await fill('#auth-invite', INVITE)
  await page.screenshot({ path: resolve(OUT, '21-portal-register-modal.png') })
  await page.click('#auth-submit')

  // -------------------------------------------------- redirected into the PWA
  await sleep(2500)
  const landed = page.url().includes('/schedule/')
  check(landed, 'registering redirects into /schedule/', page.url())
  check(
    await waitFor(page, '[data-testid=event-card], [data-testid=day-group]', 20000),
    'the timeline renders right after signing up',
  )
  check(!(await has(page, '[data-testid=auth-gate]')), 'no login wall for the fresh session')
  await page.screenshot({ path: resolve(OUT, '22-schedule-signed-in.png') })

  // ---------------------------------------------- direct hit on the PWA alone
  const deep = await browser.newPage()
  await deep.setViewport({ width: 430, height: 932, deviceScaleFactor: 2 })
  await deep.goto(`${BASE}/schedule/`, { waitUntil: 'domcontentloaded' })
  check(!(await waitFor(deep, '[data-testid=auth-gate]', 6000)), 'cookie from the portal also admits /schedule/')
  await deep.close()

  // ------------------------------------------------------- portal signed-in
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
  check(await waitFor(page, '#account-who:not(.hidden)'), 'portal shows the signed-in account')
  check(
    (await textOf(page, '#account-name')) === USER,
    'portal names the account',
    await textOf(page, '#account-name'),
  )
  check(
    (await textOf(page, '#card-schedule-badge')).includes('已登录'),
    'schedule card unlocks for the signed-in account',
    await textOf(page, '#card-schedule-badge'),
  )
  await page.screenshot({ path: resolve(OUT, '23-portal-signed-in.png') })

  // -------------------------------------------------------------- and out
  await page.click('#account-logout')
  check(await waitFor(page, '#account-open:not(.hidden)', 10000), 'logout returns the portal to signed-out')
  await page.goto(`${BASE}/schedule/`, { waitUntil: 'domcontentloaded' })
  check(await waitFor(page, '[data-testid=auth-gate]', 15000), 'after logout /schedule/ asks for a login again')

  check(pageErrors.length === 0, 'no JS errors on the portal or the PWA', pageErrors.slice(0, 2).join(' | '))
  check(failed.length === 0, 'no unexpected HTTP failures', failed.slice(0, 3).join(' | '))

  await browser.close()
  console.log(`\naccount used: ${USER}`)
  console.log(failures.length ? `${failures.length} FAILED` : 'all portal checks passed')
  process.exit(failures.length ? 1 : 0)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
