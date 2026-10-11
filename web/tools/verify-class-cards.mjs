/**
 * 课表卡片「折叠只看时间+地点，点开才有详情」的真浏览器回归（系统 Edge）。
 *
 * 用系统 Edge 打开本地构建产物，把 /api/* 全部用 fixture 应答 —— 这样测的是
 * 前端真实渲染，不碰服务器、不写任何数据。断言：
 *   1. 日程里的课表卡片折叠态只有「时间区间 + 地点」：没有来源标签、没有教师、没有备注；
 *   2. 点一下卡片 → 详情出现（节次/时长/教师/周次/来源），再点一下 → 收起；
 *   3. 课表这一周的格子里，点一节课 → 下方出现详情卡，点「收起」→ 消失；
 *   4. 控制台没有真实错误。
 *
 * 用法：node tools/verify-class-cards.mjs
 */
import { createServer } from 'node:http'
import { mkdtempSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIST = join(ROOT, 'dist')
const EDGE = process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const PORT = Number(process.env.PORT || 4179)

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webmanifest': 'application/manifest+json',
}

/** 用带 +08:00 的 ISO 串造「今天」的课，和线上数据同格式。 */
function dayWithOffset(offsetDays = 0) {
  const shanghai = new Date(Date.now() + 8 * 3600 * 1000 + offsetDays * 86400000)
  return shanghai.toISOString().slice(0, 10)
}
const TODAY = dayWithOffset()

const CLASS_EVENTS = [
  {
    id: 'tju-1',
    source: 'tju_schedule',
    source_id: 'week:1',
    title: '工程科学导论A',
    start_time: `${TODAY}T10:20:00+08:00`,
    end_time: `${TODAY}T12:00:00+08:00`,
    location: '43楼A308',
    periods: [4, 5],
    teacher: '李某某',
    week: 7,
    is_deadline: false,
    status: 'pending',
    priority: 5,
    description: '教师：李某某 地点：43楼A308 学期：2026 秋季学期',
  },
  {
    id: 'tju-2',
    source: 'tju_schedule',
    source_id: 'week:2',
    title: '英语听说',
    start_time: `${TODAY}T13:30:00+08:00`,
    end_time: `${TODAY}T15:05:00+08:00`,
    location: '33楼B201',
    periods: [6, 7],
    teacher: '王某某',
    week: 7,
    is_deadline: false,
    status: 'pending',
    priority: 5,
    description: '教师：王某某 地点：33楼B201 学期：2026 秋季学期',
  },
  {
    id: 'ddl-1',
    source: 'microsoft_todo',
    source_id: 'task:1',
    title: '交物理实验报告',
    start_time: `${TODAY}T23:00:00+08:00`,
    end_time: `${TODAY}T23:00:00+08:00`,
    location: '',
    periods: null,
    is_deadline: true,
    status: 'pending',
    priority: 3,
    description: '写在实验课后第二天',
  },
]

const failures = []
function check(name, condition, extra = '') {
  if (condition) {
    console.log(`  ✓ ${name}`)
  } else {
    failures.push(name)
    console.log(`  ✗ ${name} ${extra}`)
  }
}

async function startStaticServer() {
  const server = createServer((req, res) => {
    const path = decodeURIComponent(req.url.split('?')[0]).replace(/^\/schedule/, '') || '/'
    const file = join(DIST, path === '/' ? 'index.html' : path)
    if (!existsSync(file) || !readFileSync(file, { flag: 'r' })) {
      res.writeHead(404).end('nope')
      return
    }
    res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' })
    res.end(readFileSync(file))
  })
  await new Promise((resolve) => server.listen(PORT, '127.0.0.1', resolve))
  return server
}

async function main() {
  if (!existsSync(DIST)) throw new Error(`先构建：cd web && VITE_BASE=/schedule/ npm run build（缺 ${DIST}）`)
  const server = await startStaticServer()
  const profile = mkdtempSync(join(tmpdir(), 'chk-cards-'))
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: 'new',
    userDataDir: profile,
    args: ['--no-first-run', '--no-default-browser-check', '--disable-dev-shm-usage'],
    defaultViewport: { width: 430, height: 932, isMobile: true, hasTouch: true },
  })
  const shots = join(ROOT, 'tools', 'shots')
  const page = await browser.newPage()
  const consoleErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !/401|403|Failed to load resource/i.test(msg.text())) {
      consoleErrors.push(msg.text())
    }
  })

  await page.setRequestInterception(true)
  page.on('request', (request) => {
    const url = request.url()
    if (!url.includes('/api/')) return request.continue()
    const json = (body) =>
      request.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/api/events/ms/lists')) return json({ items: [] })
    if (url.includes('/api/events')) return json({ items: CLASS_EVENTS, total: CLASS_EVENTS.length })
    if (url.includes('/api/status')) return json({ ok: true, sources: {}, scheduler: {} })
    if (url.includes('/api/config')) return json({ viewer: { admin: false }, accounts: { enabled: false } })
    if (url.includes('/api/auth/session')) return json({ user: null, accounts: { enabled: false } })
    return json({})
  })

  await page.goto(`http://127.0.0.1:${PORT}/schedule/`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('[data-testid="event-card"]', { timeout: 15000 })

  // ---------------------------------------------------------- 日程：折叠态
  const basics = await page.$$eval('[data-testid="event-basics"]', (nodes) =>
    nodes.map((n) => n.textContent.replace(/\s+/g, ' ').trim()),
  )
  check('课表卡片折叠态 = 时间区间 + 地点', basics.length === 2 && basics[0].includes('10:20–12:00') && basics[0].includes('43楼A308'), JSON.stringify(basics))
  check('折叠态不显示来源标签', !basics.some((text) => text.includes('天津大学课表')))
  check('折叠态没有教师/备注', !basics.some((text) => text.includes('教师') || text.includes('李某某')))

  const visibleText = await page.evaluate(() => document.body.innerText)
  check('折叠态没把教师名渲染出来', !visibleText.includes('李某某'), visibleText.slice(0, 200))

  const detailsBefore = await page.$$('[data-testid="event-detail"]')
  check('折叠时没有详情块', detailsBefore.length === 0)

  // 点开第一张课表卡片
  await page.evaluate(() => {
    const body = document.querySelector('[data-testid="event-card"][data-kind="class"] [data-testid="event-body"]')
    body.click()
  })
  await page.waitForSelector('[data-testid="event-detail"]', { timeout: 5000 })
  const detailText = await page.$eval('[data-testid="event-detail"]', (n) => n.textContent.replace(/\s+/g, ' ').trim())
  check('点开后出现详情：节次', /第 4-5 节/.test(detailText), detailText)
  check('点开后出现详情：教师', detailText.includes('李某某'), detailText)
  check('点开后出现详情：周次', /第 7 周/.test(detailText), detailText)
  check('点开后出现详情：来源', detailText.includes('天津大学课表'), detailText)
  if (!existsSync(shots)) (await import('node:fs')).mkdirSync(shots, { recursive: true })
  await page.screenshot({ path: join(shots, 'agenda-expanded.png') })

  // 再点一下收起
  await page.evaluate(() => {
    document.querySelector('[data-testid="event-card"][data-kind="class"] [data-testid="event-body"]').click()
  })
  await page.waitForFunction(() => !document.querySelector('[data-testid="event-detail"]'), { timeout: 5000 })
  check('再点一下收起详情', true)
  await page.screenshot({ path: join(shots, 'agenda-collapsed.png') })

  const deadlineShape = await page.evaluate(() => {
    const card = document.querySelector('[data-testid="event-card"][data-kind="deadline"]')
    if (!card) return null
    return {
      basics: card.querySelectorAll('[data-testid="event-basics"]').length,
      text: card.innerText.replace(/\s+/g, ' ').trim(),
    }
  })
  check(
    '待办卡片没被折叠改动（不给它套课表那套，截止时间照旧）',
    deadlineShape !== null && deadlineShape.basics === 0 && deadlineShape.text.includes('交物理实验报告') && /\d+:\d+/.test(deadlineShape.text),
    JSON.stringify(deadlineShape),
  )

  // ---------------------------------------------------------- 课表：点格子看详情
  await page.evaluate(() => {
    const tab = [...document.querySelectorAll('button, [role="tab"], a')].find(
      (n) => n.textContent.trim() === '课表' && n.offsetParent !== null,
    )
    if (tab) tab.click()
  })
  await page.waitForSelector('[data-testid="class-block"]', { timeout: 10000 })
  const blockText = await page.$eval('[data-testid="class-block"]', (n) => n.textContent.replace(/\s+/g, ' ').trim())
  check('格子内容 = 课名 + 时间 + 地点', /10:20–12:00/.test(blockText) && blockText.includes('43楼A308'), blockText)

  check('点格子前没有详情卡', (await page.$$('[data-testid="class-detail"]')).length === 0)
  await page.evaluate(() => document.querySelector('[data-testid="class-block"]').click())
  await page.waitForSelector('[data-testid="class-detail"]', { timeout: 5000 })
  const weekDetail = await page.$eval('[data-testid="class-detail"]', (n) => n.textContent.replace(/\s+/g, ' ').trim())
  check('点格子后详情卡有教师', weekDetail.includes('李某某'), weekDetail)
  check('点格子后详情卡有周次', /第 7 周/.test(weekDetail), weekDetail)
  check('点格子后详情卡有节次', /第 4-5 节/.test(weekDetail), weekDetail)
  // 详情卡在网格下方，截图前滚到它，别让截图只剩格子
  await page.evaluate(() => {
    document.querySelector('[data-testid="class-detail"]').scrollIntoView({ block: 'center' })
  })
  await new Promise((resolve) => setTimeout(resolve, 350))
  await page.screenshot({ path: join(shots, 'week-detail.png') })

  await page.evaluate(() => document.querySelector('[data-testid="class-detail-close"]').click())
  await page.waitForFunction(() => !document.querySelector('[data-testid="class-detail"]'), { timeout: 5000 })
  check('点「收起」详情卡消失', true)

  check('控制台没有真实错误', consoleErrors.length === 0, consoleErrors.join(' | '))

  await browser.close()
  server.close()

  console.log(`\n${failures.length ? `FAIL (${failures.length})` : 'PASS'} ── 截图在 web/tools/shots/`)
  if (failures.length) process.exit(1)
}

main().catch((error) => {
  console.error('FAIL', error)
  process.exit(1)
})
