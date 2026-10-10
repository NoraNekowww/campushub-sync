/**
 * Client-side WePeiyang (微北洋) signature.
 *
 * The timetable API (`open.twt.edu.cn/api`) is **campus-network only**, so the
 * request has to come from the student's own browser rather than from the
 * server. These constants are public — they ship inside the official
 * open-source client (twtstudio/WePeiYang-Android, `commons/.../ServiceFactory`),
 * and the same SHA-1 scheme is applied there:
 *
 *   sign = SHA1(APP_KEY + name+value for every param sorted by name + APP_SECRET)
 *
 * Read-only use, on your own account, with the same client identity the app
 * itself uses.
 */
export const TWT_APP_KEY = '9GTdynvrCm1EKKFfVmTC'
export const TWT_APP_SECRET = '1aVhfAYBFUfqrdlcT621d9d6OzahMI'
export const TWT_OPEN_BASE = 'https://open.twt.edu.cn/api'
export const TWT_NOTICE_HOST = 'network-notice.tju.edu.cn'

const HEX = '0123456789abcdef'

/** SHA-1 fallback for non-secure origins, where `crypto.subtle` is absent. */
function sha1Fallback(bytes) {
  const bitLength = bytes.length * 8
  const withOne = bytes.slice()
  withOne.push(0x80)
  while (withOne.length % 64 !== 56) withOne.push(0)
  const lengthBytes = []
  for (let i = 7; i >= 0; i -= 1) lengthBytes.push(Math.floor(bitLength / 2 ** (i * 8)) & 0xff)
  const message = withOne.concat(lengthBytes)

  let h0 = 0x67452301
  let h1 = 0xefcdab89
  let h2 = 0x98badcfe
  let h3 = 0x10325476
  let h4 = 0xc3d2e1f0
  const words = new Array(80)
  const rotl = (value, bits) => ((value << bits) | (value >>> (32 - bits))) >>> 0

  for (let chunk = 0; chunk < message.length; chunk += 64) {
    for (let i = 0; i < 16; i += 1) {
      words[i] =
        (message[chunk + i * 4] << 24) |
        (message[chunk + i * 4 + 1] << 16) |
        (message[chunk + i * 4 + 2] << 8) |
        message[chunk + i * 4 + 3]
    }
    for (let i = 16; i < 80; i += 1) {
      words[i] = rotl(words[i - 3] ^ words[i - 8] ^ words[i - 14] ^ words[i - 16], 1)
    }
    let [a, b, c, d, e] = [h0, h1, h2, h3, h4]
    for (let i = 0; i < 80; i += 1) {
      let f
      let k
      if (i < 20) {
        f = (b & c) | (~b & d)
        k = 0x5a827999
      } else if (i < 40) {
        f = b ^ c ^ d
        k = 0x6ed9eba1
      } else if (i < 60) {
        f = (b & c) | (b & d) | (c & d)
        k = 0x8f1bbcdc
      } else {
        f = b ^ c ^ d
        k = 0xca62c1d6
      }
      const temp = (rotl(a, 5) + f + e + k + words[i]) >>> 0
      e = d
      d = c
      c = rotl(b, 30)
      b = a
      a = temp
    }
    h0 = (h0 + a) >>> 0
    h1 = (h1 + b) >>> 0
    h2 = (h2 + c) >>> 0
    h3 = (h3 + d) >>> 0
    h4 = (h4 + e) >>> 0
  }
  return [h0, h1, h2, h3, h4].map((word) => word.toString(16).padStart(8, '0')).join('')
}

async function sha1HexUpper(text) {
  const bytes = new TextEncoder().encode(text)
  if (globalThis.crypto?.subtle) {
    const digest = await crypto.subtle.digest('SHA-1', bytes)
    return Array.from(new Uint8Array(digest))
      .map((byte) => HEX[(byte >> 4) & 0xf] + HEX[byte & 0xf])
      .join('')
      .toUpperCase()
  }
  return sha1Fallback(Array.from(bytes)).toUpperCase()
}

/** Params plus `t` / `sign` / `app_key`, exactly like the official client. */
export async function signedQuery(params = {}) {
  const payload = {}
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) payload[key] = String(value)
  })
  payload.t = String(Date.now())
  const raw =
    TWT_APP_KEY +
    Object.keys(payload)
      .sort()
      .map((name) => name + payload[name])
      .join('') +
    TWT_APP_SECRET
  return { ...payload, sign: await sha1HexUpper(raw), app_key: TWT_APP_KEY }
}

export async function signedUrl(path, params = {}) {
  const query = await signedQuery(params)
  return `${TWT_OPEN_BASE}${path}?${new URLSearchParams(query).toString()}`
}

const asJson = async (response) => {
  const text = await response.text()
  try {
    return { ok: true, data: JSON.parse(text), text }
  } catch (error) {
    return { ok: false, data: null, text }
  }
}

const describeFailure = (status, text) => {
  if (/network-notice|校内访问|违规操作/i.test(text)) {
    return '当前网络不在校园网内（接口把你送去了校内网提示页）'
  }
  if (status === 0) return '请求被浏览器拦截（很可能是 CORS 或网络不通）'
  return `接口返回 HTTP ${status}`
}

export class TwtError extends Error {
  constructor(message, kind = 'unknown') {
    super(message)
    this.name = 'TwtError'
    this.kind = kind
  }
}

/** Log in from the browser and return the token (never sent to our server). */
export async function browserLogin(username, password) {
  let response
  try {
    response = await fetch(await signedUrl('/v1/auth/token/get', { twtuname: username, twtpasswd: password }))
  } catch (error) {
    throw new TwtError(describeFailure(0, String(error)), 'cors')
  }
  const parsed = await asJson(response)
  if (!parsed.ok) {
    throw new TwtError(describeFailure(response.status, parsed.text), 'campus')
  }
  const body = parsed.data || {}
  if (String(body.error_code ?? -1) !== '-1' && String(body.error_code) !== '0') {
    const message = body.message || `error_code=${body.error_code}`
    const kind = /30001|30002|40004|密码/.test(message) ? 'credentials' : 'protocol'
    throw new TwtError(`微北洋登录失败：${message}`, kind)
  }
  const token = body?.data?.token || body?.token
  if (!token) throw new TwtError('登录成功但没有拿到 token', 'protocol')
  return token
}

/** Fetch the class table with a token — the campus-only call. */
export async function browserClasstable(token, { allowEmptyToken = false } = {}) {
  if (!token && !allowEmptyToken) throw new TwtError('需要先拿到 token', 'credentials')
  const url = await signedUrl('/v1/classtable')
  let response
  try {
    response = await fetch(url, {
      headers: { Authorization: `Bearer${token}`, Accept: 'application/json' },
    })
  } catch (error) {
    throw new TwtError(describeFailure(0, String(error)), 'cors')
  }
  const parsed = await asJson(response)
  if (!parsed.ok) throw new TwtError(describeFailure(response.status, parsed.text), 'campus')
  const body = parsed.data || {}
  const code = String(body.error_code ?? '-1')
  if (code !== '-1' && code !== '0') {
    const message = body.message || `error_code=${body.error_code}`
    throw new TwtError(`课表接口返回：${message}`, /token|登录/.test(message) ? 'credentials' : 'protocol')
  }
  return body
}

/** A copy-paste console snippet for the manual fallback. */
export function consoleSnippet(token = '<你的token>') {
  return `// 校园网内，在浏览器 DevTools 控制台执行；会打印并复制课表 JSON
(async () => {
  const K = "${TWT_APP_KEY}", S = "${TWT_APP_SECRET}";
  const TOKEN = "${token}";
  const p = { t: String(Date.now()) };
  const raw = K + Object.keys(p).sort().map((k) => k + p[k]).join("") + S;
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(raw));
  const sign = [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, "0")).join("").toUpperCase();
  const url = \`${TWT_OPEN_BASE}/v1/classtable?t=\${p.t}&sign=\${sign}&app_key=\${K}\`;
  const r = await fetch(url, { headers: { Authorization: \`Bearer\${TOKEN}\` } });
  const text = await r.text();
  console.log(text);
  try { await navigator.clipboard.writeText(text); } catch (e) {}
  return text;
})();`
}
