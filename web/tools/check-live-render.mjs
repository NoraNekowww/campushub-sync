/**
 * 线上页面体检：用系统 Edge 打开 https://nzlab.online/schedule/，分别在
 * 「无凭据」和「带令牌」两种状态下截图 + 统计渲染出来的条目数，并抓控制台错误。
 *
 * 用法（令牌不落盘、不打印）：
 *   CH_TOKEN=$(ssh root@nzlab.online 'awk -F= "/^ADMIN_TOKEN=/{print \$2}" /var/www/schedule/.env') \
 *     node tools/check-live-render.mjs
 *
 * 排查目的是回答「用户说页面全空」到底是前端渲染坏了，还是只是这台浏览器没凭据。
 */
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import puppeteer from 'puppeteer-core'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const SHOTS = join(ROOT, 'tools', 'shots')
mkdirSync(SHOTS, { recursive: true })

const EDGE = process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const TARGET = process.env.LIVE_URL || 'https://nzlab.online/schedule/'
const TOKEN = process.env.CH_TOKEN || ''

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
})
const page = await browser.newPage()
await page.setViewport({ width: 430, height: 900 })

const problems = []
page.on('console', (message) => {
  if (message.type() === 'error') problems.push(`console: ${message.text()}`)
})
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('requestfailed', (request) => problems.push(`requestfailed: ${request.url()} ${request.failure()?.errorText}`))

const stats = () =>
  page.evaluate(() => ({
    text: document.body.innerText.replace(/\s+/g, ' ').slice(0, 260),
    blocks: document.querySelectorAll('[data-testid="class-block"]').length,
    lines: document.querySelectorAll('[data-testid="line-event"]').length,
    cards: document.querySelectorAll('[data-testid="event-card"]').length,
    anyTestid: document.querySelectorAll('[data-testid]').length,
  }))

await page.goto(TARGET, { waitUntil: 'networkidle2', timeout: 60000 })
await sleep(2500)
const anon = await stats()
await page.screenshot({ path: join(SHOTS, 'live-anon.png') })
console.log('=== 无凭据 ===')
console.log('  课块:', anon.blocks, ' 线事件:', anon.lines, ' 卡片:', anon.cards, ' testid总数:', anon.anyTestid)
console.log('  可见文字:', JSON.stringify(anon.text))

if (TOKEN) {
  await page.evaluate((value) => localStorage.setItem('campushub.adminToken', value), TOKEN)
  await page.reload({ waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(3500)
  const authed = await stats()
  await page.screenshot({ path: join(SHOTS, 'live-authed.png') })
  console.log('=== 带令牌 ===')
  console.log('  课块:', authed.blocks, ' 线事件:', authed.lines, ' 卡片:', authed.cards, ' testid总数:', authed.anyTestid)
  console.log('  可见文字:', JSON.stringify(authed.text))

  // 放大镜取代了黑白模式按钮；点开之后整条顶部栏（标题 + 筛选条）都让位给搜索框。
  const headingBefore = await page.$('header h1')
  await page.click('[data-testid="search-open"]')
  await page.waitForSelector('[data-testid="search-input"]', { timeout: 10000 })
  const headingAfter = await page.$('header h1')
  await page.screenshot({ path: join(SHOTS, 'live-search.png') })
  console.log('=== 放大镜搜索 ===')
  console.log('  点开前有标题:', Boolean(headingBefore), '| 点开后标题让位:', headingAfter === null)
  await page.click('[data-testid="search-close"]')
  await sleep(600)

  // 课表视图：当前时间线 & 呼吸闪烁 & 无极横向滚动 & 地点详情
  await page.click('[data-tab="week"]')
  await page.waitForSelector('[data-testid="week-scroller"]', { timeout: 10000 })
  await sleep(1500)
  const hasLine = (await page.$('[data-testid="current-time-line"]')) !== null
  const isPulsing = hasLine
    ? await page.$eval('[data-testid="current-time-line"]', (el) => el.classList.contains('animate-pulse'))
    : false
  const lineTop = hasLine
    ? await page.$eval('[data-testid="current-time-line"]', (el) => el.style.top)
    : null
  const gutterTime = (await page.$('[data-testid="current-time-gutter"]'))
    ? await page.$eval('[data-testid="current-time-gutter"]', (el) => el.textContent.trim())
    : null

  const scrollData = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="week-scroller"]')
    return { scrollWidth: el?.scrollWidth, clientWidth: el?.clientWidth }
  })
  const hasBlockLoc = (await page.$('[data-testid="class-block-location"]')) !== null
  const hasLocSection = (await page.$('[data-testid="location-details-section"]')) !== null
  const locItems = await page.$$eval('[data-testid="location-item"]', (nodes) => nodes.length)

  await page.screenshot({ path: join(SHOTS, 'live-week-timeline.png') })
  console.log('=== 课表与地点详情实测 ===')
  console.log('  时间线存在:', hasLine, '| 闪烁:', isPulsing, '| 轴位置:', lineTop, '| 时间:', gutterTime)
  console.log('  无极连续滑动轨道:', scrollData.scrollWidth > scrollData.clientWidth, `(${scrollData.scrollWidth}px > ${scrollData.clientWidth}px)`)
  console.log('  卡片内精简地点:', hasBlockLoc, '| 页面地点详情面板:', hasLocSection, `(有地点课程数: ${locItems})`)
} else {
  console.log('（没给 CH_TOKEN，跳过带令牌那一轮）')
}

console.log('=== 控制台/网络问题 ===')
console.log(problems.length ? problems.slice(0, 10).join('\n') : '  无')
await browser.close()
