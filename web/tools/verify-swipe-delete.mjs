// verify-swipe-delete.mjs — 用真浏览器证明「左右滑动卡片能删除日程」这条路真的通。
//
// 验证链（每一步都断言效果，不看「元素存在」）：
//   1. 登录临时账号 → 建一条自己的 DDL
//   2. 真鼠标拖开卡片 → 断言卡片 translateX(-96px)、且删除按钮的命中测试落在它自己身上
//   3. 点删除 → 断言卡片消失、服务端 /api/events 里没有了、提示条带「撤销」
//   4. 点「撤销」→ 断言卡片回来、服务端又有了
//
// 用法（账号用 tools/t_e2e_user.py 临时建，跑完删）：
//   USERNAME_E2E=... PASSWORD_E2E=... node tools/verify-swipe-delete.mjs
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import puppeteer from 'puppeteer-core'

const URL = process.env.URL || 'https://nzlab.online/schedule/'
const EXE = process.env.EDGE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const USER = process.env.USERNAME_E2E || ''
const PASS = process.env.PASSWORD_E2E || ''
const OUT_DIR = process.env.OUT_DIR || tmpdir()
const TITLE = `滑动删除自检 ${Date.now()}`

const errors = []
const browser = await puppeteer.launch({
  executablePath: EXE,
  headless: 'new',
  userDataDir: mkdtempSync(join(tmpdir(), 'edge-verify-')),
  args: ['--no-first-run', '--no-default-browser-check', '--disable-gpu'],
})
const page = await browser.newPage()
await page.setViewport({ width: 430, height: 932, deviceScaleFactor: 2 })
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()}`))

const api = async (path, init = {}) =>
  page.evaluate(
    async (p, i) => {
      const res = await fetch(p, {
        credentials: 'include',
        ...i,
        headers: { 'Content-Type': 'application/json', ...(i.headers || {}) },
      })
      let body = null
      try {
        body = await res.json()
      } catch {
        body = null
      }
      return { status: res.status, body }
    },
    path,
    init,
  )

await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 })

// 门只认账号会话（HttpOnly cookie）→ 用真账号登录
if (await page.$('[data-testid="auth-gate"]')) {
  await page.type('[data-testid="auth-username"]', USER)
  await page.type('[data-testid="auth-password"]', PASS)
  await Promise.all([
    page.waitForFunction(() => !document.querySelector('[data-testid="auth-gate"]'), { timeout: 30000 }),
    page.click('[data-testid="auth-submit"]'),
  ]).catch((e) => errors.push(`login: ${e.message}`))
}
errors.length = 0 // 匿名首屏的 401 是预期噪声
await page.waitForFunction(() => !document.querySelector('[data-testid="auth-gate"]'), { timeout: 30000 }).catch(() => {})

// 老 Service Worker 会缓存列表接口 → 先清它的数据缓存，再建事件
await page.evaluate(() => navigator.serviceWorker?.controller?.postMessage('clear-data-cache'))

const start = new Date(Date.now() + 3 * 24 * 3600 * 1000)
const created = await api('/schedule/api/events', {
  method: 'POST',
  body: JSON.stringify({
    title: TITLE,
    start_time: start.toISOString().slice(0, 19),
    is_deadline: true,
    reminder_minutes: 30,
  }),
})
const eventId = created.body?.id || null

await page.reload({ waitUntil: 'networkidle2', timeout: 60000 })
await page.waitForFunction(
  (t) => [...document.querySelectorAll('[data-testid="event-card"]')].some((c) => c.innerText.includes(t)),
  { timeout: 20000 },
  TITLE,
)

const cardRect = await page.evaluate((t) => {
  const card = [...document.querySelectorAll('[data-testid="event-card"]')].find((c) => c.innerText.includes(t))
  if (!card) return null
  const r = card.getBoundingClientRect()
  return { x: r.x, y: r.y, w: r.width, h: r.height }
}, TITLE)

// 拖开：从卡片标题那一带开始（避开左上角原生 checkbox 的 label）
const grabX = cardRect.x + cardRect.w * 0.7
const grabY = cardRect.y + cardRect.h * 0.3
const grabTarget = await page.evaluate(
  (x, y) => {
    const el = document.elementFromPoint(x, y)
    return el ? `${el.tagName.toLowerCase()}${el.dataset?.testid ? `[${el.dataset.testid}]` : ''}` : null
  },
  grabX,
  grabY,
)
await page.mouse.move(grabX, grabY)
await page.mouse.down()
for (let i = 1; i <= 10; i += 1) await page.mouse.move(grabX - i * 12, grabY)
await page.mouse.up()
await new Promise((r) => setTimeout(r, 500))

const revealed = await page.evaluate((t) => {
  const card = [...document.querySelectorAll('[data-testid="event-card"]')].find((c) => c.innerText.includes(t))
  const row = card.closest('[data-testid="event-card-row"]')
  const pane = row.querySelector('[data-testid="event-swipe-pane"]')
  const del = row.querySelector('[data-testid="swipe-delete"]')
  const r = del.getBoundingClientRect()
  const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
  return {
    transform: getComputedStyle(pane).transform,
    deleteHit: hit?.closest('[data-testid="swipe-delete"]') ? 'swipe-delete' : hit?.tagName || null,
    deleteRect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
  }
}, TITLE)
const shot1 = join(OUT_DIR, 'swipe-1-revealed.png')
await page.screenshot({ path: shot1 })

// 点「删除」
await page.mouse.click(revealed.deleteRect.x + revealed.deleteRect.w / 2, revealed.deleteRect.y + revealed.deleteRect.h / 2)
const gone = await page
  .waitForFunction(
    (t) => ![...document.querySelectorAll('[data-testid="event-card"]')].some((c) => c.innerText.includes(t)),
    { timeout: 10000 },
    TITLE,
  )
  .then(() => true)
  .catch(() => false)
await new Promise((r) => setTimeout(r, 600))

const toast = await page.evaluate(() => {
  const btn = document.querySelector('[data-testid="toast-action"]')
  if (!btn) return null
  const r = btn.getBoundingClientRect()
  const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
  return {
    label: btn.innerText.trim(),
    text: btn.parentElement?.innerText?.replace(/\s+/g, ' ').trim() || null,
    hit: hit?.closest('[data-testid="toast-action"]') ? 'toast-action' : hit?.tagName || null,
  }
})
const afterDelete = await api(`/schedule/api/events?limit=500&_=${Date.now()}`)
const stillListed = (afterDelete.body?.items || []).some((i) => i.title === TITLE)
const single = eventId ? await api(`/schedule/api/events/${eventId}`) : null
const shot2 = join(OUT_DIR, 'swipe-2-deleted-toast.png')
await page.screenshot({ path: shot2 })

// 点「撤销」
if (toast) {
  const r = await page.evaluate(() => {
    const b = document.querySelector('[data-testid="toast-action"]').getBoundingClientRect()
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
  })
  await page.mouse.click(r.x, r.y)
}
const back = await page
  .waitForFunction(
    (t) => [...document.querySelectorAll('[data-testid="event-card"]')].some((c) => c.innerText.includes(t)),
    { timeout: 10000 },
    TITLE,
  )
  .then(() => true)
  .catch(() => false)
const afterUndo = await api(`/schedule/api/events?limit=500&_=${Date.now()}`)
const listedAgain = (afterUndo.body?.items || []).some((i) => i.title === TITLE)

// 回归：手势不能把卡片里按钮的「点击」吃掉 —— 点「划掉」还得管用
const tickPoint = await page.evaluate((t) => {
  const card = [...document.querySelectorAll('[data-testid="event-card"]')].find((c) => c.innerText.includes(t))
  const b = card.querySelector('[data-testid="tick-event"]').getBoundingClientRect()
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
}, TITLE)
await page.mouse.click(tickPoint.x, tickPoint.y)
await new Promise((r) => setTimeout(r, 900))
const tickedStatus = await page.evaluate((t) => {
  const card = [...document.querySelectorAll('[data-testid="event-card"]')].find((c) => c.innerText.includes(t))
  return card?.getAttribute('data-status') || null
}, TITLE)
// 再点回来，别给临时账号留状态
await page.mouse.click(tickPoint.x, tickPoint.y)
await new Promise((r) => setTimeout(r, 900))

await browser.close()

const pass =
  created.status === 201 &&
  !!cardRect &&
  revealed.transform.includes('-96') &&
  revealed.deleteHit === 'swipe-delete' &&
  gone === true &&
  stillListed === false &&
  single?.body?.hidden === true &&
  toast?.label === '撤销' &&
  toast?.hit === 'toast-action' &&
  back === true &&
  listedAgain === true &&
  tickedStatus === 'completed' &&
  errors.length === 0

console.log(
  JSON.stringify(
    {
      title: TITLE,
      eventId,
      createStatus: created.status,
      cardRect,
      grabTarget,
      revealed,
      gone,
      toast,
      stillListed,
      hiddenOnServer: single?.body?.hidden ?? null,
      back,
      listedAgain,
      tickedStatus,
      errors,
      screenshots: [shot1, shot2],
      pass,
    },
    null,
    2,
  ),
)
process.exit(pass ? 0 : 1)
