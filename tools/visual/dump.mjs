/** Throwaway diagnostic: dump the rendered text of one view. */
import puppeteer from 'puppeteer-core'

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, arg, index, all) => {
    if (arg.startsWith('--')) pairs.push([arg.slice(2), all[index + 1]])
    return pairs
  }, []),
)

const browser = await puppeteer.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: 'new',
  args: ['--no-sandbox'],
})
const page = await browser.newPage()
await page.setViewport({ width: 420, height: 900 })
await page.goto(`${args.base}/?token=${encodeURIComponent(args.token)}`, { waitUntil: 'networkidle0' })
await new Promise((r) => setTimeout(r, 800))
if (args.click) {
  await page.evaluate((needle) => {
    const target = [...document.querySelectorAll('button')].find((b) =>
      (b.textContent || '').includes(needle),
    )
    target?.click()
  }, args.click)
  await new Promise((r) => setTimeout(r, 1500))
}
const info = await page.evaluate(() => {
  const views = [...document.querySelectorAll('main > *')].map((el) => ({
    tag: el.tagName,
    testid: el.dataset.testid || '',
    shown: getComputedStyle(el).display !== 'none',
    text: (el.innerText || '').slice(0, 2500),
  }))
  return {
    localStorage: { ...localStorage },
    view: window.__campushub_view || '',
    views,
    bodyText: document.body.innerText.slice(0, 1200),
  }
})
console.log(JSON.stringify(info, null, 2))
await browser.close()
