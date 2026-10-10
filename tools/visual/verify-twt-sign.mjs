/**
 * Cross-check the browser-side signature against the Python one.
 *
 * Imports the real `web/src/twt-sign.js` (the web package is `"type": "module"`)
 * and runs both code paths — `crypto.subtle` and the pure-JS fallback — against
 * a digest computed by the backend:
 *
 *   EXPECTED=$(python -c "…")   # sign for a fixed timestamp
 *   node verify-twt-sign.mjs "$EXPECTED"
 */
const expected = (process.argv[2] || '').trim().toUpperCase()

globalThis.Date.now = () => 1520000000123

const mod = await import('../../web/src/twt-sign.js')
const params = { twtuname: '3018216000', twtpasswd: 'secret' }

let failures = 0
const check = (label, actual) => {
  const ok = actual === expected
  if (!ok) failures += 1
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: ${actual}`)
}

const subtleQuery = await mod.signedQuery(params)
check('crypto.subtle path', subtleQuery.sign)
console.log('       t =', subtleQuery.t, '| app_key =', subtleQuery.app_key)
console.log('       keys sorted:', Object.keys(subtleQuery).sort().join(','))

// Same computation without WebCrypto (http:// origins) must agree.
const originalCrypto = globalThis.crypto
Object.defineProperty(globalThis, 'crypto', { value: undefined, configurable: true })
try {
  const fallbackQuery = await mod.signedQuery(params)
  check('pure-JS SHA-1 fallback', fallbackQuery.sign)
} finally {
  Object.defineProperty(globalThis, 'crypto', { value: originalCrypto, configurable: true })
}

const url = await mod.signedUrl('/v1/classtable')
console.log('       signed url:', url.slice(0, 120) + '…')
const snippet = mod.consoleSnippet('TOKEN123')
console.log('       snippet mentions classtable:', snippet.includes('/v1/classtable'))

console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nALL CHECKS PASSED')
process.exit(failures ? 1 : 0)
