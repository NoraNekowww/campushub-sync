/**
 * 用 puppeteer-core + 本机 Edge 做一次真实 UI 冒烟：
 * 打开日程弹窗 → 往标题栏粘贴长文本 → 断言「自动识别」按钮出现 →
 * 点击后断言各字段被回填。
 * 用法：node scripts/smoke_detect.mjs [url]
 */
import puppeteer from 'puppeteer-core'

const URL = process.argv[2] || 'http://127.0.0.1:5199/'
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const SAMPLE = '11月20日 09:00-11:00 在 46楼A202 上电子技术实验，记得带实验报告'

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=430,900'],
  defaultViewport: { width: 430, height: 900 },
})
const page = await browser.newPage()
const logs = []
page.on('console', (m) => logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`))

const fail = (msg) => {
  console.log('FAIL:', msg)
  console.log(logs.join('\n'))
  browser.close()
  process.exit(1)
}

await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 })

// 1. 打开新建日程弹窗（右下角悬浮按钮）
const fab = await page.$('[data-testid="fab-new-event"]')
if (!fab) {
  await page.screenshot({ path: 'scripts/debug_page.png' })
  fail('找不到「新建日程」悬浮按钮')
}
await fab.click()
await new Promise((r) => setTimeout(r, 600))

const hasEditor = await page.$('[data-testid="custom-event-editor"]')
if (!hasEditor) {
  console.log(logs.join('\n'))
  fail('日程弹窗未打开')
}

// 2. 断言 placeholder 里带了自动识别提示
const placeholder = await page.$eval('[data-testid="custom-title"]', (el) => el.placeholder)
if (!/粘贴/.test(placeholder)) fail(`placeholder 缺少提示文案：${placeholder}`)

// 3. 在标题框里模拟一次真实 paste 事件（绕过剪贴板权限）
await page.$eval(
  '[data-testid="custom-title"]',
  (el, text) => {
    el.focus()
    const dt = new DataTransfer()
    dt.setData('text/plain', text)
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
  },
  SAMPLE,
)

await new Promise((r) => setTimeout(r, 300))
const bar = await page.$('[data-testid="auto-detect-bar"]')
if (!bar) fail('粘贴长文本后没有出现自动识别按钮')

const btnText = await page.$eval('[data-testid="auto-detect-apply"]', (el) => el.textContent.trim())
if (btnText !== '自动识别') fail(`按钮文案不对：${btnText}`)

// 4. 点击识别并校验回填
await page.click('[data-testid="auto-detect-apply"]')
await new Promise((r) => setTimeout(r, 500))

const values = await page.evaluate(() => ({
  title: document.querySelector('[data-testid="custom-title"]').value,
  date: document.querySelector('[data-testid="custom-date"]').value,
  duration: document.querySelector('[data-testid="custom-duration"]')?.value ?? null,
  hint: document.querySelector('[data-testid="auto-detect-hint"]')?.textContent.trim() ?? null,
  locationInputs: [...document.querySelectorAll('input.input')].map((i) => i.value),
}))

if (values.title !== '电子技术实验 带实验报告') fail(`标题回填错误：${values.title}`)
if (values.date !== '2026-11-20') fail(`日期回填错误：${values.date}`)
if (!values.hint || !/已识别/.test(values.hint)) fail('缺少识别结果提示')
if (!values.locationInputs.includes('46楼A202')) fail(`地点未回填：${JSON.stringify(values.locationInputs)}`)

// 5. 截图取证
await page.screenshot({ path: 'scripts/detect_result.png' })
console.log('UI SMOKE OK')
console.log(JSON.stringify(values, null, 1))
await browser.close()
