/**
 * Decisive probe: can a REAL browser reach open.twt.edu.cn (WePeiYang class table)?
 *
 * Runs headless Edge/Chrome locally and:
 *   1. navigates straight to the signed class-table URL  -> status, redirect chain, body
 *   2. navigates to the unsigned URL                     -> status, redirect chain, body
 *   3. issues a same-page fetch() from https://nzlab.online/ (CORS read test)
 *   4. issues a fetch() with an Authorization header (preflight test)
 *
 * Interpretation:
 *   JSON body            -> the gate is client-fingerprint based, server-side is fixable
 *   redirect to network-notice.tju.edu.cn / 403 page -> the gate is IP (campus) based
 *
 * Usage: node twt-browser-probe.mjs
 */
import { existsSync } from 'node:fs'
import crypto from 'node:crypto'
import puppeteer from 'puppeteer-core'

const APP_KEY = '9GTdynvrCm1EKKFfVmTC'
const APP_SECRET = '1aVhfAYBFUfqrdlcT621d9d6OzahMI'
const BASE = 'https://open.twt.edu.cn/api/'
const UA_NOTE = 'WePeiYang/3.0.0 (Xiaomi MI 8; Android 29)'

const BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
]

function signed(params) {
  const t = String(Date.now())
  const p = { ...params, t }
  const raw = APP_KEY + Object.keys(p).sort().map((k) => k + p[k]).join('') + APP_SECRET
  p.sign = crypto.createHash('sha1').update(raw).digest('hex').toUpperCase()
  p.app_key = APP_KEY
  return p
}

const qs = (params) => new URLSearchParams(signed(params)).toString()
const signedUrl = (path, params = {}) => BASE + path + '?' + qs(params)

const targets = [
  ['A) signed /v1/classtable', signedUrl('v1/classtable')],
  ['B) unsigned /v1/classtable', BASE + 'v1/classtable'],
  ['C) signed /v1/auth/token/get (dummy creds)', signedUrl('v1/auth/token/get', { twtuname: '0', twtpasswd: '0' })],
]

const browser = await puppeteer.launch({
  executablePath: BROWSERS.find((p) => existsSync(p)),
  headless: 'new',
  args: ['--no-sandbox', '--disable-http2'],
})

const page = await browser.newPage()
await page.setUserAgent(UA_NOTE)

for (const [label, url] of targets) {
  console.log('\n=== ' + label + ' ===')
  console.log('url: ' + url.slice(0, 140))
  const seen = []
  const onRes = (r) => seen.push(`${r.status()} ${r.url().slice(0, 90)}`)
  page.on('response', onRes)
  try {
    const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 })
    let body = ''
    try { body = (await resp.text()).slice(0, 300).replace(/\s+/g, ' ') } catch (e) { body = '<unreadable: ' + e.message + '>' }
    console.log('final url : ' + page.url().slice(0, 140))
    console.log('status    : ' + (resp ? resp.status() : '?'))
    const h = resp ? resp.headers() : {}
    console.log('x-headers : ' + JSON.stringify(Object.fromEntries(Object.entries(h).filter(([k]) => /access-control|server|location|content-type/i.test(k)))))
    console.log('chain     : ' + seen.join('  ->  '))
    console.log('body      : ' + body)
  } catch (e) {
    console.log('ERR: ' + e.message)
    console.log('chain: ' + seen.join('  ->  '))
  }
  page.off('response', onRes)
}

// 3) CORS test from a real origin (our own site)
console.log('\n=== D) fetch() from https://nzlab.online/ (CORS) ===')
const ctl = await browser.newPage()
await ctl.goto('https://nzlab.online/', { waitUntil: 'domcontentloaded', timeout: 30000 })
for (const [label, url, opts] of [
  ['simple GET', signedUrl('v1/classtable'), {}],
  ['GET + Authorization (preflight)', signedUrl('v1/classtable'), { headers: { Authorization: 'Bearer{dummy}' } }],
]) {
  const out = await ctl.evaluate(async (u, o) => {
    try {
      const r = await fetch(u, o)
      const txt = await r.text()
      return { ok: true, status: r.status, acao: r.headers.get('access-control-allow-origin'), body: txt.slice(0, 160) }
    } catch (e) {
      return { ok: false, err: String(e) }
    }
  }, url, opts)
  console.log(label + ' -> ' + JSON.stringify(out))
}

await browser.close()
