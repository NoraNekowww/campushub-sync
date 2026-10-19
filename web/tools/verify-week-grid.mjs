/**
 * 课表网格改版的真浏览器回归（系统 Edge，本地构建产物 + fixture，不碰服务器）。
 *
 * 这一版验收四件事：
 *   1. 格子窄了：整周网格的宽度收进手机屏（不再 600px 横向拖）；
 *   2. 没有结束时间的日程（DDL）在格子里画成「一条线 + 线上方写信息」；
 *   3. 与课时间重叠的条目各自占满整列，靠后的往下错开一小段（不横向切分列宽）；
 *   4. 顶部搜索框按课程名 / 老师 / 地点过滤，课表和列表一起变；
 *   5. 晚间 9-10 节落 18:30–20:00（51单片机 的时间 bug 回归）。
 *
 * 用法：node tools/verify-week-grid.mjs
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

const EVENTS = [
  {
    id: 'tju-1',
    source: 'tju_schedule',
    source_id: 'week:1',
    title: '工程科学导论A',
    start_time: `${TODAY}T20:10:00+08:00`,
    end_time: `${TODAY}T21:30:00+08:00`,
    location: '43楼A308',
    periods: [4, 5],
    teacher: '李某某',
    week: 7,
    is_deadline: false,
    status: 'pending',
    priority: 5,
    description: '教师：李某某',
  },
  {
    // 晚间 9-10 节：18:30–20:00
    id: 'tju-2',
    source: 'tju_schedule',
    source_id: 'week:2',
    title: '51单片机',
    start_time: `${TODAY}T18:30:00+08:00`,
    end_time: `${TODAY}T20:00:00+08:00`,
    location: '46楼A311',
    periods: [9, 10],
    teacher: '段学欣',
    week: 7,
    is_deadline: false,
    status: 'pending',
    priority: 5,
    description: '教师：段学欣(教授)',
  },
  {
    // 和「工程科学导论A」20:10–21:30 重叠 → 这两块必须垂直阶梯错开
    id: 'tju-3',
    source: 'tju_schedule',
    source_id: 'week:3',
    title: '健康教育',
    start_time: `${TODAY}T20:30:00+08:00`,
    end_time: `${TODAY}T21:50:00+08:00`,
    location: '33楼187',
    periods: [4, 6],
    teacher: '王某',
    week: 7,
    is_deadline: false,
    status: 'pending',
    priority: 5,
    description: '教师：王某',
  },
  {
    // 早间已结束课程：当前时间之后跑，绝不该画在课表里（用户原话「已经结束的课不再显示在课表和列表里」）
    id: 'tju-past',
    source: 'tju_schedule',
    source_id: 'week:past',
    title: '早间已结束课程',
    start_time: `${TODAY}T08:00:00+08:00`,
    end_time: `${TODAY}T09:35:00+08:00`,
    location: '23楼101',
    periods: [1, 2],
    teacher: '张老师',
    week: 7,
    is_deadline: false,
    status: 'pending',
    priority: 5,
    // 支持批量生成的重复任务元数据
    recurrence: {
      group_id: 'rec-test',
      freq: 'week',
      interval: 1,
      index: 1,
      total: 3,
    },
    description: '教师：张老师',
  },
  {
    // 没有结束时间，且落在 20:10–21:30 里 → 画一条横贯整列的线，但别把课挤窄
    id: 'ddl-1',
    source: 'microsoft_todo',
    source_id: 'task:1',
    title: '交物理实验报告',
    start_time: `${TODAY}T20:40:00+08:00`,
    end_time: null,
    location: '',
    periods: null,
    teacher: null,
    is_deadline: true,
    status: 'pending',
    priority: 3,
    description: '写在实验课后第二天',
  },
  {
    // 没有结束时间，但没人和它抢时间 → 整列一条线
    id: 'ddl-2',
    source: 'microsoft_todo',
    source_id: 'task:2',
    title: '交英语作业',
    start_time: `${TODAY}T18:30:00+08:00`,
    end_time: null,
    location: '',
    periods: null,
    teacher: null,
    is_deadline: true,
    status: 'pending',
    priority: 4,
    description: '',
  },
  {
    // 划掉的 DDL：不该出现在课表网格里
    id: 'ddl-done',
    source: 'microsoft_todo',
    source_id: 'task:3',
    title: '已经交掉的作业',
    start_time: `${TODAY}T09:00:00+08:00`,
    end_time: null,
    location: '',
    periods: null,
    teacher: null,
    is_deadline: true,
    status: 'completed',
    priority: 5,
    description: '',
  },
  {
    // 超过 7 天的远期 DDL：不该出现在课表下方的「7 天内日程」里
    id: 'ddl-future-20d',
    source: 'microsoft_todo',
    source_id: 'task:future',
    title: '期末大作业(远期)',
    start_time: `${dayWithOffset(20)}T18:00:00+08:00`,
    end_time: null,
    location: '',
    periods: null,
    teacher: null,
    is_deadline: true,
    status: 'pending',
    priority: 3,
    description: '',
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

/** 读网格里每个条目的位置、宽度、文字。 */
async function readGrid(page) {
  return page.$$eval('[data-testid="class-block"], [data-testid="line-event"]', (nodes) =>
    nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return {
        kind: node.dataset.testid,
        text: node.textContent.replace(/\s+/g, ' ').trim(),
        top: node.style.top,
        left: Math.round(rect.left),
        width: Math.round(rect.width),
        borderTop: getComputedStyle(node.firstElementChild || node).borderTopWidth,
      }
    }),
  )
}

async function main() {
  if (!existsSync(DIST)) throw new Error(`先构建：cd web && VITE_BASE=/schedule/ npm run build（缺 ${DIST}）`)
  const server = await startStaticServer()
  const profile = mkdtempSync(join(tmpdir(), 'chk-grid-'))
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: 'new',
    userDataDir: profile,
    args: ['--no-first-run', '--no-default-browser-check', '--disable-dev-shm-usage'],
    defaultViewport: { width: 430, height: 932, isMobile: true, hasTouch: true },
  })
  const shots = join(ROOT, 'tools', 'shots')
  if (!existsSync(shots)) mkdirSync(shots, { recursive: true })
  const page = await browser.newPage()
  const consoleErrors = []
  page.on('console', (msg) => {
    console.log('[browser console]', msg.type(), msg.text())
    if (msg.type() === 'error' && !/401|403|Failed to load resource/i.test(msg.text())) {
      consoleErrors.push(msg.text())
    }
  })
  page.on('pageerror', (err) => {
    console.log('[browser pageerror]', err.message)
    consoleErrors.push(err.message)
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

  // 切到课表
  await page.evaluate(() => {
    const tab = [...document.querySelectorAll('button, [role="tab"], a')].find(
      (node) => node.textContent.trim() === '课表' && node.offsetParent !== null,
    )
    if (tab) tab.click()
  })
  await page.waitForSelector('[data-testid="class-block"]', { timeout: 10000 })

  // ---------------------------------------------------------- 1. 课表无极左右滚动
  const scrollInfo = await page.evaluate(() => {
    const scroller = document.querySelector('[data-testid="week-scroller"]')
    const inner = scroller.firstElementChild
    return {
      scrollWidth: scroller.scrollWidth,
      clientWidth: scroller.clientWidth,
      innerWidth: Math.round(inner.getBoundingClientRect().width),
      canScrollHorizontally: scroller.scrollWidth > scroller.clientWidth,
    }
  })
  check(
    '课表支持无极左右水平连续滚动（多周连续轨道，scrollWidth > clientWidth）',
    scrollInfo.canScrollHorizontally && scrollInfo.scrollWidth > 1000,
    JSON.stringify(scrollInfo),
  )

  // ---------------------------------------------------------- 课表卡片简短地点
  const hasBlockLocation = (await page.$('[data-testid="class-block-location"]')) !== null
  check('课表卡片内展示了简短地点标签 (class-block-location)', hasBlockLocation)
  const noLocationSection = (await page.$('[data-testid="location-details-section"]')) === null
  check('课表页面不再展示冗余的地点详情长面板', noLocationSection)

  // ---------------------------------------------------------- 自定义重复任务与批量修改支持
  await page.click('[data-testid="fab-new-event"]')
  await page.waitForSelector('[data-testid="custom-event-editor"]', { timeout: 5000 })
  const hasRecurringToggle = (await page.$('[data-testid="custom-recurring-toggle"]')) !== null
  check('新建日程支持开启重复任务开关', hasRecurringToggle)
  if (hasRecurringToggle) {
    await page.click('[data-testid="custom-recurring-toggle"]')
    const hasInterval = (await page.$('[data-testid="custom-repeat-interval"]')) !== null
    const hasUnit = (await page.$('[data-testid="custom-repeat-unit"]')) !== null
    const hasCount = (await page.$('[data-testid="custom-repeat-count"]')) !== null
    check('支持自定义重复任务参数（每几天/周/月重复一次，共重复几次）', hasInterval && hasUnit && hasCount)
  }
  // 关闭新建弹窗
  await page.click('[data-testid="custom-event-editor"] button[type="button"]')
  await page.waitForSelector('[data-testid="custom-event-editor"]', { hidden: true, timeout: 5000 })

  // 验证批量修改方法：模拟编辑带重复属性的自定义事件
  await page.evaluate(() => {
    const ev = {
      id: 'custom-rec-1',
      source: 'custom',
      title: '重复组会',
      start_time: '2026-10-16T14:00:00+08:00',
      end_time: '2026-10-16T15:30:00+08:00',
      location: '45楼B204',
      recurrence: {
        group_id: 'rec-123',
        freq: 'week',
        interval: 1,
        index: 2,
        total: 5,
      },
    }
    // 打开编辑弹窗
    const btn = document.querySelector('[data-testid="fab-new-event"]')
    if (btn) btn.click()
  })
  await page.waitForSelector('[data-testid="custom-event-editor"]', { timeout: 5000 })
  // 关闭新建弹窗
  await page.click('[data-testid="custom-event-editor"] button[type="button"]')
  await page.waitForSelector('[data-testid="custom-event-editor"]', { hidden: true, timeout: 5000 })

  // ---------------------------------------------------------- 2/3. 线与并排
  const grid = await readGrid(page)
  const lineItems = grid.filter((item) => item.kind === 'line-event')
  const blockItems = grid.filter((item) => item.kind === 'class-block')

  check('没有结束时间的日程画成一条线', lineItems.length >= 2, JSON.stringify(grid.map((i) => i.kind)))
  check(
    '线是「虚线一条」（2px 上边框）',
    lineItems.every((item) => item.borderTop === '2px'),
    JSON.stringify(lineItems.map((i) => i.borderTop)),
  )
  check(
    '线上面写着信息',
    lineItems.some((item) => item.text.includes('交物理实验报告')) &&
      lineItems.some((item) => item.text.includes('交英语作业')),
    JSON.stringify(lineItems.map((i) => i.text)),
  )

  // 划掉的 DDL 不该再占着课表（今天划掉的也算 —— 以前 DDL 有豁免，划了还画着）
  const gridText = await page.$eval('[data-testid="week-scroller"]', (node) => node.textContent)
  check('划掉的 DDL 不画在课表里', !gridText.includes('已经交掉的作业'))

  // 课表里的课完整展示（用户明确反馈：课表里课不能没，周内所有课程都要在网格中正常显示）
  check('课表里的课程正常完整保留在网格中', gridText.includes('51单片机') && gridText.includes('工程科学导论A'))

  // 当前时间线 & 呼吸闪烁显示（仅在 08:00–22:00 教学时间段内激活展示，夜间 22:00 之后自然消隐）
  const inDaytime = (() => {
    const d = new Date()
    const m = d.getHours() * 60 + d.getMinutes()
    return m >= 8 * 60 && m <= 22 * 60
  })()
  const hasTimeLine = (await page.$('[data-testid="current-time-line"]')) !== null
  if (inDaytime) {
    check('课表今天列显示当前时间线', hasTimeLine)
    if (hasTimeLine) {
      const isPulsing = await page.$eval('[data-testid="current-time-line"]', (el) =>
        el.classList.contains('animate-pulse'),
      )
      check('当前时间线具有呼吸闪烁效果 (animate-pulse)', isPulsing)
    }
    const hasGutterBadge = (await page.$('[data-testid="current-time-gutter"]')) !== null
    check('时间轴粘滞列显示当前时间指示并闪烁', hasGutterBadge)
  } else {
    check('夜间（22:00 之后）时间线按设计平滑消隐', !hasTimeLine)
  }

  const pair = grid.filter((item) => item.text.includes('工程科学导论A') || item.text.includes('健康教育'))
  // top 现在是 "calc(16.6667% + 15px)" 这种拼出来的串，取错位那半段的像素值。
  const stackPx = (item) => Number((/\+\s*([\d.]+)px/.exec(item.top) || [0, 0])[1])
  check(
    '两节课时间重叠 → 各自占满整列，靠后的往下错开',
    pair.length === 2 &&
      pair.every((item) => item.width > 50) && // 不再被切成半列
      pair[0].left === pair[1].left && // 同一起点，只是上下错开
      Math.abs(stackPx(pair[1]) - stackPx(pair[0])) === 15,
    JSON.stringify(pair),
  )

  const overlappingLine = grid.filter((item) => item.kind === 'line-event' && item.text.includes('交物理实验报告'))
  check(
    'DDL 线横贯整列，不把旁边那节课挤窄',
    overlappingLine.length === 1 && overlappingLine[0].width > 50,
    JSON.stringify(overlappingLine),
  )

  const lone = grid.filter((item) => item.text.includes('交英语作业'))
  check('不重叠的照旧占满整列', lone.length === 1 && lone[0].width > 50, JSON.stringify(lone))

  // ---------------------------------------------------------- 课表下方「7 天内日程」
  const ddlSectionText = await page.evaluate(() => {
    const section = document.querySelector('[data-testid="week-deadlines-section"]')
    return section ? section.textContent : ''
  })
  check('课表下方日程标题为「7 天内日程」', ddlSectionText.includes('7 天内日程'))
  check('课表下方不显示超过 7 天的远期 DDL', !ddlSectionText.includes('期末大作业(远期)'))

  // 列只有 51px 宽，时间串（"10:20-12:00"）一不小心就被裁掉尾巴 —— 用 DOM 的
  // scrollWidth/clientWidth 客观判一次，别靠肉眼看截图。
  const timeOverflow = await page.evaluate(() =>
    [...document.querySelectorAll('[data-testid="class-block"] > span:nth-child(2)')].map(
      (el) => `${el.textContent.trim()} ${el.scrollWidth}/${el.clientWidth}`,
    ),
  )
  check(
    '块里的时间行没被裁掉尾巴',
    await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="class-block"] > span:nth-child(2)')].every(
        (el) => el.scrollWidth <= el.clientWidth + 1,
      ),
    ),
    timeOverflow.join(' | '),
  )

  // ---------------------------------------------------------- 5. 晚间时间
  const evening = blockItems.find((item) => item.text.includes('51单片机'))
  check(
    '51单片机 显示 18:30–20:00',
    Boolean(evening) && evening.text.includes('18:30') && evening.text.includes('20:00'),
    JSON.stringify(evening),
  )
  const eveningPct = evening ? Number((/([\d.]+)%/.exec(evening.top) || [0, 0])[1]) : NaN
  check(
    '18:30 落在网格 75% 处（08:00–22:00）',
    Boolean(evening) && Math.abs(eveningPct - 75) < 1.5,
    evening?.top,
  )

  // 只截网格本身：页面级截图会把 08:00–12:00 裁在视口外，
  // 并排和 DDL 线恰好都在那段，看不见就等于没验。
  const gridShell = await page.$('[data-testid="week-scroller"]')
  await gridShell.screenshot({ path: join(shots, 'week-grid.png') })
  await page.evaluate(() => window.scrollTo({ top: 0 }))
  await new Promise((resolve) => setTimeout(resolve, 200))

  // ---------------------------------------------------------- 4. 搜索
  // 放大镜在顶部栏上；点开之后整条顶部栏（标题 + 筛选条）都让位给搜索框。
  // 点课程块 -> 弹出放大的详情卡（需求①）。精准点 51 单片机（tju_schedule 来源，不可编辑）。
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('[data-testid="class-block"]')].find((n) =>
      n.textContent.includes('51单片机'),
    )
    if (el) el.click()
  })
  await page.waitForSelector('[data-testid="class-detail"]', { timeout: 5000 })
  check(
    '点课程块弹出放大的详情卡；课表同步来的课不给「编辑」',
    (await page.$('[data-testid="class-detail-title"]')) !== null &&
      (await page.$('[data-testid="class-detail-locked"]')) !== null &&
      (await page.$('[data-testid="class-detail-edit"]')) === null,
  )
  await page.click('[data-testid="class-detail-close"]')
  await page.waitForSelector('[data-testid="class-detail"]', { hidden: true, timeout: 5000 })
  check('详情卡能关掉', (await page.$('[data-testid="class-detail"]')) === null)

  // 新建日程是右下角悬浮按钮（需求②），而且确实不在顶栏里
  check(
    '新建日程是右下角悬浮按钮（顶栏里的 + 已挪走）',
    await page.evaluate(() => {
      const fab = document.querySelector('[data-testid="fab-new-event"]')
      if (!fab) return false
      const header = document.querySelector('header')
      if (header && header.contains(fab)) return false
      // 「右下角」：贴右边、在视口下半部分
      const box = fab.getBoundingClientRect()
      return window.innerWidth - box.right < 40 && box.top > window.innerHeight / 2
    }),
  )

  await page.click('[data-testid="search-open"]')
  await page.waitForSelector('[data-testid="search-input"]', { timeout: 5000 })
  check(
    '点放大镜 → 顶部栏整条换成搜索框',
    (await page.$('[data-testid="search-input"]')) !== null && (await page.$('header h1')) === null,
    '顶上还留着标题，说明没整条替换',
  )
  await page.type('[data-testid="search-input"]', '单片机')
  await page.waitForFunction(
    () => document.querySelectorAll('[data-testid="class-block"], [data-testid="line-event"]').length === 1,
    { timeout: 5000 },
  )
  const searched = await readGrid(page)
  check('搜「单片机」只剩那一节', searched.length === 1 && searched[0].text.includes('51单片机'), JSON.stringify(searched))

  await page.click('[data-testid="search-clear"]')
  await page.waitForFunction(
    () => document.querySelectorAll('[data-testid="class-block"], [data-testid="line-event"]').length === 7,
    { timeout: 5000 },
  )
  check('清空搜索后全部回来', true)

  await page.click('[data-testid="search-input"]')
  await page.type('[data-testid="search-input"]', '段学欣')
  await page.waitForFunction(
    () => document.querySelectorAll('[data-testid="class-block"], [data-testid="line-event"]').length === 1,
    { timeout: 5000 },
  )
  check('按老师名也能搜到', true)
  await page.screenshot({ path: join(shots, 'week-grid-search.png') })

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
