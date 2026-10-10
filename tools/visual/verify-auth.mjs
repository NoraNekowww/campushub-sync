/**
 * Headless account-flow check for the CampusHub Sync PWA.
 *
 *   node verify-auth.mjs --base http://127.0.0.1:8099 \
 *        --invite let-me-in --user e2e-user --password e2e-password-1
 *
 * Drives a real browser with a throwaway profile (so the cookie jar starts
 * empty) and walks the whole wall: gate -> bad invite -> register -> timeline
 * -> reload persistence -> settings -> logout -> gate again. Exits non-zero on
 * any failed assertion, JS error or failed request.
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
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, arg, index, all) => {
    if (arg.startsWith('--')) pairs.push([arg.slice(2), all[index + 1]])
    return pairs
  }, []),
)
const BASE = (args.base || 'http://127.0.0.1:8099').replace(/\/$/, '')
const INVITE = args.invite || ''
const USER = args.user || 'e2e-user'
const PASSWORD = args.password || 'e2e-password-1'

const failures = []
const check = (ok, label, detail = '') => {
  if (!ok) failures.push(label)
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ` — ${detail}` : ''}`)
}

async function pickBrowser() {
  const { existsSync } = await import('node:fs')
  for (const candidate of BROWSERS) if (existsSync(candidate)) return candidate
  throw new Error(`no system browser found in:\n  ${BROWSERS.join('\n  ')}`)
}

const has = (page, selector) =>
  page.evaluate((sel) => Boolean(document.querySelector(sel)), selector)

const textOf = (page, selector) =>
  page.evaluate((sel) => document.querySelector(sel)?.textContent?.trim() || '', selector)

const fill = async (page, selector, value) => {
  await page.click(selector, { clickCount: 3 })
  await page.type(selector, value, { delay: 12 })
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** Wait for a selector to show up (polls instead of relying on timing). */
async function waitFor(page, selector, timeout = 15000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await has(page, selector)) return true
    await sleep(150)
  }
  return false
}

async function waitUntilGone(page, selector, timeout = 15000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (!(await has(page, selector))) return true
    await sleep(150)
  }
  return false
}

const main = async () => {
  mkdirSync(OUT, { recursive: true })
  const profile = mkdtempSync(resolve(tmpdir(), 'campushub-e2e-'))
  const browser = await puppeteer.launch({
    executablePath: await pickBrowser(),
    headless: 'new',
    userDataDir: profile,
    args: ['--headless=new', '--hide-scrollbars', '--disable-gpu', '--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 430, height: 932, deviceScaleFactor: 2 })

  const consoleErrors = []
  const failedRequests = []
  /* The app probes these endpoints while signed out; a 401 there is the
     designed answer that puts the login wall up, not a failure. */
  const AUTH_PROBES = [/\/api\/events/, /\/api\/config/, /\/api\/status/, /\/api\/auth\/me/]
  /* This script deliberately submits a wrong invite code first, so a refused
     register/login is an expected answer rather than a broken app. */
  const REFUSED_ON_PURPOSE = [/\/api\/auth\/(register|login)/, ...AUTH_PROBES]
  const expected401 = (status, url) =>
    (status === 401 || status === 403) && REFUSED_ON_PURPOSE.some((re) => re.test(url))

  page.on('pageerror', (error) => consoleErrors.push(String(error)))
  page.on('console', (message) => {
    const text = message.text()
    if (message.type() === 'error' && !/Failed to load resource[^\n]*(401|403)/.test(text)) {
      consoleErrors.push(text)
    }
  })
  page.on('response', (response) => {
    const url = response.url()
    if (response.status() >= 400 && !url.includes('favicon') && !expected401(response.status(), url)) {
      failedRequests.push(`${response.status()} ${url}`)
    }
  })

  // ---------------------------------------------------------------- the wall
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
  check(await waitFor(page, '[data-testid=auth-gate]'), 'anonymous visitor sees the login gate')
  check(
    !(await has(page, '[data-testid=event-card]')),
    'no timeline content is rendered before signing in',
  )
  await page.screenshot({ path: resolve(OUT, '10-auth-gate.png') })

  // ------------------------------------------------------ register: bad code
  await page.click('[data-testid=auth-tab-register]')
  await sleep(200)
  await fill(page, '[data-testid=auth-username]', USER)
  await fill(page, '[data-testid=auth-password]', PASSWORD)
  await fill(page, '[data-testid=auth-confirm]', PASSWORD)
  if (INVITE) await fill(page, '[data-testid=auth-invite]', 'definitely-wrong')
  await page.click('[data-testid=auth-submit]')
  check(
    await waitFor(page, '[data-testid=auth-error]', 10000),
    'wrong invite code is refused with a message',
    await textOf(page, '[data-testid=auth-error]'),
  )

  // ------------------------------------------------------------ real signup
  if (INVITE) await fill(page, '[data-testid=auth-invite]', INVITE)
  await page.click('[data-testid=auth-submit]')
  const signedIn = await waitUntilGone(page, '[data-testid=auth-gate]', 20000)
  check(
    signedIn,
    'correct invite code creates the account and enters the app',
    signedIn ? '' : `still blocked: ${await textOf(page, '[data-testid=auth-error]')}`,
  )
  check(
    await waitFor(page, '[data-testid=event-card], [data-testid=day-group]', 20000),
    'timeline renders for the signed-in account',
  )
  await page.screenshot({ path: resolve(OUT, '11-auth-signed-in.png') })

  // ------------------------------------------------------- cookie survives…
  await page.reload({ waitUntil: 'networkidle2' })
  await sleep(600)
  check(!(await has(page, '[data-testid=auth-gate]')), 'session survives a reload (cookie, not JS)')
  check(await has(page, '[data-testid=event-card]'), 'timeline still rendered after reload')

  // ------------------------------------------------------------- settings
  await page.evaluate(() => {
    document.querySelector('[data-testid=nav-tab][data-tab="settings"]')?.click()
  })
  check(await waitFor(page, '[data-testid=account-section]'), 'settings shows the account section')
  const shownUser = await textOf(page, '[data-testid=account-username]')
  check(shownUser === USER, 'account section names the signed-in user', shownUser)
  await page.screenshot({ path: resolve(OUT, '12-account-settings.png') })

  // --------------------------------------------------------------- logout
  if (await has(page, '[data-testid=account-logout]')) {
    await page.click('[data-testid=account-logout]')
    check(await waitFor(page, '[data-testid=auth-gate]', 15000), 'signing out brings the gate back')
    check(
      !(await has(page, '[data-testid=event-card]')),
      'timeline disappears after signing out',
    )
  } else {
    check(false, 'signing out brings the gate back', 'logout button missing')
  }

  // ------------------------------------------------------------ hygiene
  check(consoleErrors.length === 0, 'no JS errors', consoleErrors.slice(0, 3).join(' | '))
  check(failedRequests.length === 0, 'no failed requests', failedRequests.slice(0, 3).join(' | '))

  await browser.close()
  console.log(`\n${failures.length ? `${failures.length} FAILED` : 'all account checks passed'}`)
  process.exit(failures.length ? 1 : 0)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
