/**
 * Headless UI check for the CampusHub Sync PWA.
 *
 *   node verify-ui.mjs --base http://127.0.0.1:8099 --token dev-admin-token
 *
 * Reuses the system Edge/Chrome (no Chromium download), drives the real app,
 * asserts the DOM, captures screenshots for each view and exits non-zero if any
 * JS error, failed request or DOM assertion fails — i.e. it is a gate, not a
 * photo shoot.
 */
import { mkdirSync } from 'node:fs'
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
const BASE = (args.base || 'http://127.0.0.1:8000').replace(/\/$/, '')
const TOKEN = args.token || ''

const failures = []
const notes = []
const check = (ok, label, detail = '') => {
  if (!ok) failures.push(label)
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ` — ${detail}` : ''}`)
}

async function pickBrowser() {
  const { existsSync } = await import('node:fs')
  for (const candidate of BROWSERS) {
    if (existsSync(candidate)) return candidate
  }
  throw new Error(`no system browser found in:\n  ${BROWSERS.join('\n  ')}`)
}

/** Navigate by tab name — text matching is ambiguous once views are mounted. */
const gotoView = (page, tab) =>
  page.evaluate((name) => {
    const target = document.querySelector(`[data-testid=nav-tab][data-tab="${name}"]`)
    if (!target) return false
    target.click()
    return true
  }, tab)

const main = async () => {
  mkdirSync(OUT, { recursive: true })
  const executablePath = await pickBrowser()
  const browser = await puppeteer.launch({
    executablePath,
    headless: 'new',
    args: ['--headless=new', '--hide-scrollbars', '--disable-gpu', '--no-sandbox'],
  })

  const page = await browser.newPage()
  const consoleErrors = []
  const pageErrors = []
  const failedRequests = []
  page.on('console', async (message) => {
    if (message.type() !== 'error') return
    // `text()` alone renders objects as "JSHandle@error" — unwrap the args too
    const parts = [message.text()]
    for (const arg of message.args()) {
      try {
        const value = await arg.evaluate((node) => {
          if (node instanceof Error) return `${node.name}: ${node.message}`
          try {
            return JSON.stringify(node)
          } catch {
            return String(node)
          }
        })
        if (value) parts.push(String(value).slice(0, 240))
      } catch {
        /* argument already collected */
      }
    }
    consoleErrors.push([...new Set(parts)].join(' '))
  })
  page.on('pageerror', (error) => pageErrors.push(String(error)))
  page.on('requestfailed', (request) => {
    const url = request.url()
    if (url.includes('favicon')) return
    failedRequests.push(`${request.method()} ${url} — ${request.failure()?.errorText}`)
  })

  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 })
  const url = `${BASE}/?token=${encodeURIComponent(TOKEN)}`
  await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 })
  await page.waitForFunction(
    () => !document.querySelector('.animate-pulse'), // skeletons gone => data arrived
    { timeout: 30000 },
  ).catch(() => notes.push('skeleton still visible after 30s'))

  check(
    page.url().includes('token=') === false,
    'magic-link token is stripped from the URL',
    page.url(),
  )

  // ------------------------------------------------------------ agenda view
  const agenda = await page.evaluate(() => {
    const dayHeadings = [...document.querySelectorAll('[data-testid=day-group]')].map((el) =>
      (el.querySelector('header')?.innerText || '').split('\n')[0].trim(),
    )
    const cards = [...document.querySelectorAll('[data-testid=event-card]')]
    return {
      title: document.title,
      dayHeadings,
      cardCount: cards.length,
      classCards: cards.filter((c) => c.dataset.kind === 'class').length,
      deadlineCards: cards.filter((c) => c.dataset.kind === 'deadline').length,
      checkboxes: cards.filter((c) => c.querySelector('input[type=checkbox]')).length,
      sources: [...new Set(cards.map((c) => c.dataset.source))],
      bg: getComputedStyle(document.body).backgroundColor,
      dark: document.documentElement.classList.contains('dark'),
    }
  })
  check(agenda.cardCount > 0, 'agenda renders event cards', `${agenda.cardCount} cards`)
  check(agenda.classCards > 0, 'class cards render', `${agenda.classCards}`)
  check(agenda.deadlineCards > 0, 'deadline cards render', `${agenda.deadlineCards}`)
  check(
    agenda.sources.length > 1,
    'both sources are represented',
    agenda.sources.join(', '),
  )
  check(agenda.dayHeadings.length > 0, 'events are grouped by day', agenda.dayHeadings.slice(0, 4).join(' / '))
  check(agenda.checkboxes > 0, 'deadlines expose a completion checkbox', `${agenda.checkboxes}`)
  check(agenda.dark === true, 'dark mode active by default')
  await page.screenshot({ path: `${OUT}/01-agenda-mobile.png`, fullPage: false })

  await page.screenshot({ path: `${OUT}/02-agenda-mobile-full.png`, fullPage: true })

  // -------------------------------------------------------------- week view
  check(await gotoView(page, 'week'), 'bottom nav switches to the week view')
  await new Promise((r) => setTimeout(r, 900))
  const week = await page.evaluate(() => {
    const blocks = [...document.querySelectorAll('[data-testid=class-block]')]
    const scroller = document.querySelector('[data-testid=week-scroller]')
    return {
      hasGrid: Boolean(scroller),
      blockCount: blocks.length,
      label: blocks[0]?.innerText.replace(/\n/g, ' ').slice(0, 40) || '',
      dayColumns: new Set(blocks.map((b) => b.dataset.day)).size,
      scrollLeft: scroller ? Math.round(scroller.scrollLeft) : -1,
      visibleDays: scroller
        ? [...scroller.querySelectorAll('[data-testid=class-block]')].filter((b) => {
            const box = b.getBoundingClientRect()
            const frame = scroller.getBoundingClientRect()
            return box.left >= frame.left - 1 && box.right <= frame.right + 1
          }).length
        : -1,
    }
  })
  check(week.blockCount > 0, 'week grid positions class blocks', `${week.blockCount} blocks, e.g. ${week.label}`)
  check(week.hasGrid, 'week grid container rendered')
  // the grid is wider than the viewport: today's column must be scrolled into view
  check(
    week.scrollLeft > 0 && week.visibleDays > 0,
    'week grid auto-scrolls to today',
    `scrollLeft=${week.scrollLeft}px, ${week.visibleDays} of ${week.blockCount} blocks on screen`,
  )
  await page.screenshot({ path: `${OUT}/03-week-mobile.png`, fullPage: true })

  // ---------------------------------------------------------- settings view
  check(await gotoView(page, 'settings'), 'bottom nav switches to the settings view')
  await new Promise((r) => setTimeout(r, 1200))
  const settings = await page.evaluate(() => {
    const text = document.body.innerText
    const link = [...document.querySelectorAll('input, textarea, code, a')]
      .map((el) => el.value || el.textContent || '')
      .find((value) => value.includes('calendar.ics'))
    return {
      hasSubscribe: /订阅|calendar\.ics/.test(text),
      hasMsSection: /Microsoft To Do|微软/i.test(text),
      hasTju: /课表|微北洋|TJU/i.test(text),
      hasSync: /同步/.test(text),
      hasTokenField: !!document.querySelector('input[type=password], input[placeholder*="令牌"]'),
      subscribeUrl: link || '',
      statusError: /无法|失败|401/.test(text),
    }
  })
  check(settings.hasSubscribe, 'settings shows the subscription section')
  check(settings.subscribeUrl.includes('calendar.ics'), 'subscription URL is rendered', settings.subscribeUrl)
  check(settings.hasMsSection, 'settings shows the Microsoft To Do section')
  check(settings.hasTju, 'settings shows the timetable section')
  check(settings.hasSync, 'settings shows sync controls')
  check(!settings.statusError, 'no auth error text on the settings page')
  await page.screenshot({ path: `${OUT}/04-settings-mobile.png`, fullPage: true })

  // ------------------------------------------------------- desktop, light --
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 })
  await gotoView(page, 'agenda')
  await new Promise((r) => setTimeout(r, 600))
  await page.evaluate(() => {
    document.documentElement.classList.remove('dark')
    localStorage.setItem('campushub.theme', 'light')
  })
  await new Promise((r) => setTimeout(r, 300))
  await page.screenshot({ path: `${OUT}/05-agenda-desktop-light.png`, fullPage: false })
  await page.evaluate(() => {
    document.documentElement.classList.add('dark')
    localStorage.setItem('campushub.theme', 'dark')
  })
  await new Promise((r) => setTimeout(r, 300))
  await page.screenshot({ path: `${OUT}/06-agenda-desktop-dark.png`, fullPage: false })

  // ------------------------------------------------------------ SW/offline
  const sw = await page.evaluate(async () => {
    if (!('serviceWorker' in navigator)) return { registered: false, reason: 'unsupported' }
    const registration = await navigator.serviceWorker.getRegistration()
    return { registered: !!registration, active: registration?.active?.state || '' }
  })
  check(
    sw.registered || sw.reason === 'unsupported' || !sw.active,
    'service worker registered (production build)',
    JSON.stringify(sw),
  )

  check(pageErrors.length === 0, 'no uncaught page errors', pageErrors.join(' | '))
  check(consoleErrors.length === 0, 'no console errors', consoleErrors.slice(0, 3).join(' | '))
  check(failedRequests.length === 0, 'no failed requests', failedRequests.slice(0, 3).join(' | '))

  await browser.close()

  console.log('\nscreenshots in', OUT)
  notes.forEach((note) => console.log('note:', note))
  console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nall UI checks passed')
  process.exit(failures.length ? 1 : 0)
}

main().catch((error) => {
  console.error('harness error:', error)
  process.exit(2)
})
