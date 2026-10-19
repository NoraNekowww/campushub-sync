/**
 * 日程卡片两件事的真浏览器回归（系统 Edge，本地构建产物 + API fixture，不碰线上）：
 *
 *   1. 长标题要**看全**（换行铺开），不是被截成一行省略号；
 *   2. 待办备注里的 `📍 地点` 行在界面上**屏蔽掉**，地点改为卡片上单独显示。
 *
 * 用最坏的数据来测：fixture 的备注里带着 `📍 45楼B203`（假设后端没摘干净），
 * 前端也得把它挡住并拿出来当地点。
 *
 * 用法：node tools/verify-event-card-note.mjs
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
const PORT = Number(process.env.PORT || 4181)

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webmanifest': 'application/manifest+json',
}

function dayWithOffset(offsetDays = 0) {
  const shanghai = new Date(Date.now() + 8 * 3600 * 1000 + offsetDays * 86400000)
  return shanghai.toISOString().slice(0, 10)
}
const TODAY = dayWithOffset()

const LONG_TITLE = '数据科学基础课程设计（含实验环节）第三次大作业与阶段报告提交说明会'
const NOTE_WITH_LOCATION = '📍 45楼B203\n带教材和计算器'

const EVENTS = [
  {
    id: 'todo-1',
    source: 'microsoft_todo',
    source_id: 'task:1',
    title: LONG_TITLE,
    start_time: `${TODAY}T23:00:00+08:00`,
    end_time: `${TODAY}T23:00:00+08:00`,
    // 后端已经摘过一次时会是这样：地点在 location、备注只剩用户写的
    location: '',
    periods: null,
    is_deadline: true,
    status: 'pending',
    priority: 3,
    description: NOTE_WITH_LOCATION,
  },
  {
    id: 'class-1',
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
  if (!existsSync(DIST)) throw new Error(`先构建：cd web && npm run build（缺 ${DIST}）`)
  const server = await startStaticServer()
  const profile = mkdtempSync(join(tmpdir(), 'chk-note-'))
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
    if (url.includes('/api/events')) return json({ items: EVENTS, total: EVENTS.length })
    if (url.includes('/api/status')) return json({ ok: true, sources: {}, scheduler: {} })
    if (url.includes('/api/config')) return json({ viewer: { admin: false }, accounts: { enabled: false } })
    if (url.includes('/api/auth/session')) return json({ user: null, accounts: { enabled: false } })
    return json({})
  })

  await page.goto(`http://127.0.0.1:${PORT}/schedule/`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('[data-testid="event-card"][data-kind="deadline"]', { timeout: 15000 })

  // ------------------------------------------------------ 1. 标题要看全
  const title = await page.evaluate(() => {
    const card = document.querySelector('[data-testid="event-card"][data-kind="deadline"]')
    const h3 = card.querySelector('h3')
    const style = getComputedStyle(h3)
    return {
      text: h3.innerText.trim(),
      horizontalOverflow: h3.scrollWidth - h3.clientWidth,
      lineHeight: parseFloat(style.lineHeight),
      height: h3.getBoundingClientRect().height,
      textOverflow: style.textOverflow,
      whiteSpace: style.whiteSpace,
    }
  })
  check('标题文本完整在 DOM 里', title.text.startsWith('数据科学基础课程设计'), title.text)
  check(
    '标题没有被水平裁切（换行铺开，而不是省略号）',
    title.horizontalOverflow <= 1 && title.textOverflow !== 'ellipsis' && title.whiteSpace !== 'nowrap',
    JSON.stringify(title),
  )
  check('长标题确实占了两行以上（否则这个用例没测到东西）', title.height > title.lineHeight * 1.5, JSON.stringify(title))

  // ------------------------------------------------------ 2. 地点行被屏蔽
  const cardShape = await page.evaluate(() => {
    const card = document.querySelector('[data-testid="event-card"][data-kind="deadline"]')
    return {
      text: card.innerText.replace(/\s+/g, ' ').trim(),
      pins: card.querySelectorAll('svg').length,
    }
  })
  check('卡片上不出现 📍 那行文本', !cardShape.text.includes('📍'), cardShape.text)
  check('备注里的地点拿出来单独显示了', cardShape.text.includes('45楼B203'), cardShape.text)
  check('备注只留用户自己写的部分', !cardShape.text.includes('📍') && cardShape.text.includes('45楼B203'), cardShape.text)

  // 点开详情：备注字段里也不该再有那行
  const detail = await page.evaluate(() => {
    const card = document.querySelector('[data-testid="event-card"][data-kind="deadline"]')
    return card.innerText.replace(/\s+/g, ' ').trim()
  })
  check('整张卡片都不带 📍', !detail.includes('📍'), detail)

  if (!existsSync(shots)) (await import('node:fs')).mkdirSync(shots, { recursive: true })
  await page.screenshot({ path: join(shots, 'event-card-note.png') })

  check('控制台没有真实错误', consoleErrors.length === 0, consoleErrors.join(' | '))

  await browser.close()
  server.close()

  console.log(`\n${failures.length ? `FAIL (${failures.length})` : 'PASS'} ── 截图在 web/tools/shots/event-card-note.png`)
  if (failures.length) process.exit(1)
}

main().catch((error) => {
  console.error('FAIL', error)
  process.exit(1)
})
