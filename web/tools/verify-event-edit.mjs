/**
 * 「网页端改自己的日程」的真浏览器回归（系统 Edge，本地构建产物 + API fixture，不碰线上）：
 *
 *   1. 每一张卡片都有编辑入口 —— 课表 / 待办 / 自定义都能改，不再只有自定义日程能编辑；
 *   2. 课表事件：弹窗认得出自己改的是「这节课」（不摆「全天」开关、不摆「同步到微软待办」，
 *      因为这两样对教务同步来的事件没有意义）；
 *   3. 点保存发出去的 PATCH 体：时间 / 地点 / 备注都对，且**不夹带 is_deadline**
 *      （外部来源不该被网页端改掉事件类型）；
 *   4. 待办事件：同样能改，PATCH 体同样不带 is_deadline。
 *
 * 用法：node tools/verify-event-edit.mjs
 */
import { createServer } from 'node:http'
import { mkdtempSync, readFileSync, existsSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIST = join(ROOT, 'dist')
const EDGE = process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const PORT = Number(process.env.PORT || 4183)

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
const TODAY = dayWithOffset(1)

const EVENTS = [
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
  {
    id: 'todo-1',
    source: 'microsoft_todo',
    source_id: 'task:1',
    title: '交大作业',
    start_time: `${TODAY}T23:00:00+08:00`,
    end_time: null,
    location: '任务',
    periods: null,
    is_deadline: true,
    status: 'pending',
    priority: 3,
    description: '带教材',
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
    if (!existsSync(file)) {
      res.writeHead(404).end('nope')
      return
    }
    res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' })
    res.end(readFileSync(file))
  })
  await new Promise((resolve) => server.listen(PORT, '127.0.0.1', resolve))
  return server
}

/** 在弹窗里按 label 文本填字段（Vue 的 v-model 只认原生 input 事件）。 */
async function fillForm(page, values) {
  await page.evaluate((values) => {
    const setValue = (el, value) => {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }
    const byLabel = (text) => {
      const label = [...document.querySelectorAll('form label')].find((l) =>
        l.innerText.includes(text),
      )
      return label ? label.querySelector('input, textarea') : null
    }
    const title = document.querySelector('[data-testid="custom-title"]')
    if (values.title != null) setValue(title, values.title)
    const date = document.querySelector('[data-testid="custom-date"]')
    if (values.date != null && date) setValue(date, values.date)
    const start = byLabel('开始') || byLabel('截止时间')
    if (values.start != null && start) setValue(start, values.start)
    const end = byLabel('结束')
    if (values.end != null && end) setValue(end, values.end)
    const location = byLabel('地点')
    if (values.location != null && location) setValue(location, values.location)
    const note = byLabel('备注')
    if (values.description != null && note) setValue(note, values.description)
  }, values)
}

const dialogShape = (page) =>
  page.evaluate(() => {
    const form = document.querySelector('form')
    if (!form) return null
    // 页面里还有别的 h2（分组标题），编辑弹窗那个一定是「编辑…」
    const heading = [...document.querySelectorAll('h2')]
      .map((node) => node.innerText.trim())
      .find((text) => text.startsWith('编辑')) || ''
    return {
      heading,
      text: form.innerText.replace(/\s+/g, ' ').trim(),
      hasAllDay: [...form.querySelectorAll('label')].some((l) =>
        l.innerText.includes('全天'),
      ),
      hasMsSync: Boolean(form.querySelector('[data-testid="custom-to-ms"]')),
      saveLabel: (form.querySelector('[data-testid="custom-save"]') || {}).innerText || '',
    }
  })

async function main() {
  if (!existsSync(DIST)) throw new Error(`先构建：cd web && npm run build（缺 ${DIST}）`)
  const server = await startStaticServer()
  const profile = mkdtempSync(join(tmpdir(), 'chk-edit-'))
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

  const patches = []
  await page.setRequestInterception(true)
  page.on('request', (request) => {
    const url = request.url()
    if (!url.includes('/api/')) return request.continue()
    if (request.method() === 'PATCH' && url.includes('/api/events/')) {
      patches.push(JSON.parse(request.postData() || '{}'))
      const target = EVENTS.find((item) => url.includes(item.id)) || EVENTS[0]
      return request.respond({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...target, local_override: true }),
      })
    }
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
  await page.waitForSelector('[data-testid="event-card"]', { timeout: 15000 })

  // ------------------------------------------- 1. 每张卡片都有编辑入口
  const cards = await page.evaluate(() =>
    [...document.querySelectorAll('[data-testid="event-card"]')].map((card) => ({
      kind: card.dataset.kind,
      title: (card.querySelector('h3') || {}).innerText || '',
      hasEdit: Boolean(card.querySelector('[data-testid="edit-custom-event"]')),
    })),
  )
  check('页面上确实有课表卡和待办卡', cards.some((c) => c.kind === 'class') && cards.some((c) => c.kind === 'deadline'), JSON.stringify(cards))
  check(
    '每一张卡片都有编辑入口（课表折叠态也算）',
    cards.length > 0 && cards.every((c) => c.hasEdit),
    JSON.stringify(cards),
  )

  // ------------------------------------------- 2. 课表事件：弹窗说自己在改「这节课」
  await page.evaluate(() => {
    document
      .querySelector('[data-testid="event-card"][data-kind="class"] [data-testid="edit-custom-event"]')
      .click()
  })
  await page.waitForFunction(() => document.body.innerText.includes('编辑这节课'), { timeout: 5000 })
  const classDialog = await dialogShape(page)
  check('课表事件弹窗标题是「编辑这节课」', classDialog.heading === '编辑这节课', classDialog.heading)
  check('课表事件不摆「全天 / 当截止日期用」开关', classDialog.hasAllDay === false)
  check('课表事件不摆「同步到微软待办」区块', classDialog.hasMsSync === false)

  // ------------------------------------------- 3. 改时间 / 地点 / 备注 → PATCH 体
  await fillForm(page, {
    date: dayWithOffset(1),
    start: '13:30',
    end: '15:05',
    location: '55楼A101',
    description: '记得带笔记本',
  })
  await page.click('[data-testid="custom-save"]')
  await page.waitForFunction(() => !document.body.innerText.includes('编辑这节课'), { timeout: 8000 })

  const classPatch = patches[0] || {}
  check('保存时发出了一次 PATCH', patches.length >= 1, JSON.stringify(patches))
  check(
    'PATCH 带上了新的开始 / 结束时间',
    classPatch.start_time === `${dayWithOffset(1)}T13:30:00` && (classPatch.end_time === `${dayWithOffset(1)}T15:00:00` || classPatch.end_time === `${dayWithOffset(1)}T15:05:00`),
    JSON.stringify(classPatch),
  )
  check('PATCH 带上了地点和备注', classPatch.location === '55楼A101' && classPatch.description === '记得带笔记本', JSON.stringify(classPatch))
  check('外部来源的 PATCH 不夹带 is_deadline（不许改事件类型）', !('is_deadline' in classPatch), JSON.stringify(classPatch))

  // ------------------------------------------- 4. 待办事件：也能改，同样不改类型
  await page.evaluate(() => {
    document
      .querySelector('[data-testid="event-card"][data-kind="deadline"] [data-testid="edit-custom-event"]')
      .click()
  })
  await page.waitForFunction(() => document.body.innerText.includes('编辑这条待办'), { timeout: 5000 })
  const todoDialog = await dialogShape(page)
  check('待办事件弹窗标题是「编辑这条待办」', todoDialog.heading === '编辑这条待办', todoDialog.heading)
  check('待办事件不摆「同步到微软待办」区块（已经在那儿了）', todoDialog.hasMsSync === false)

  await fillForm(page, { title: '交大作业（改）', start: '09:00', description: '带教材和计算器' })
  await page.click('[data-testid="custom-save"]')
  await page.waitForFunction(() => !document.body.innerText.includes('编辑这条待办'), { timeout: 8000 })

  const todoPatch = patches[1] || {}
  check('待办的 PATCH 改了标题 / 时间 / 备注', todoPatch.title === '交大作业（改）' && todoPatch.start_time === `${TODAY}T09:00:00` && todoPatch.description === '带教材和计算器', JSON.stringify(todoPatch))
  check('待办的 PATCH 也不夹带 is_deadline', !('is_deadline' in todoPatch), JSON.stringify(todoPatch))

  if (!existsSync(shots)) mkdirSync(shots, { recursive: true })
  await page.evaluate(() => {
    document.querySelector('[data-testid="event-card"][data-kind="class"] [data-testid="edit-custom-event"]').click()
  })
  await page.waitForFunction(() => document.body.innerText.includes('编辑这节课'), { timeout: 5000 })
  await page.screenshot({ path: join(shots, 'event-edit.png') })

  check('控制台没有真实错误', consoleErrors.length === 0, consoleErrors.join(' | '))

  await browser.close()
  server.close()

  console.log(`\n${failures.length ? `FAIL (${failures.length})` : 'PASS'} ── 截图在 web/tools/shots/event-edit.png`)
  if (failures.length) process.exit(1)
}

main().catch((error) => {
  console.error('FAIL', error)
  process.exit(1)
})
