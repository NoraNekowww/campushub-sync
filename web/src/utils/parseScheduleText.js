/**
 * 日程文本智能识别（纯前端、离线可用、零依赖）。
 *
 * 目标场景：用户从聊天软件 / 通知栏 / 群公告里复制一整段话（例如
 * 「周一 14:00-15:35 在 45楼B203 上高数课，记得带教材」），
 * 粘贴进标题栏后一键解析出 标题 / 日期 / 时间 / 时长 / 地点 / 备注。
 *
 * 识别策略（按置信度从高到低）：
 *  1. 绝对日期：2026-11-07 / 2026年11月7日 / 11月7日 / 11/7 / 11.7
 *  2. 相对日期：今天 / 明天 / 后天 / 大后天 / 今晚 / 明早 / 下周三 / 本周五 / 周五 / 星期三
 *  3. 时段：14:00-15:35 / 14:00~15:35 / 14点30分 / 下午2点到4点 / 14:00
 *  4. 地点：在 XXX / 地点：XXX / @ XXX / 教室 XXX楼XXX / 拿快递点
 *  5. 标题：剔除日期时间地点后的核心短语，找不到就用首个短句
 */

const WEEK_CN = ['日', '一', '二', '三', '四', '五', '六']

const pad = (n) => String(n).padStart(2, '0')

/** 本地日期格式化：YYYY-MM-DD */
export function fmtDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** "HH:MM" 串 */
const fmtTime = (h, m) => `${pad(Math.min(23, Math.max(0, h)))}:${pad(Math.min(59, Math.max(0, m)))}`

/** 解析出的字面日期，返回 { date: Date } 或 null */
function parseAbsoluteDate(text, now) {
  let m = text.match(/(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?/)
  if (m) {
    const [, y, mo, d] = m
    const date = new Date(Number(y), Number(mo) - 1, Number(d))
    if (!Number.isNaN(date.getTime())) return { date, matched: m[0] }
  }
  // 11月7日 / 11月7号
  m = text.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?/)
  if (m) {
    const mo = Number(m[1])
    const d = Number(m[2])
    if (mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
      let year = now.getFullYear()
      const date = new Date(year, mo - 1, d)
      // 已经过去超过 45 天，说明说的是明年
      if (date.getTime() < now.getTime() - 45 * 86400000) date.setFullYear(++year)
      return { date, matched: m[0] }
    }
  }
  // 11/7 或 11.7（避免误吃 14:00 这类时间）
  m = text.match(/(?<![\d:])(\d{1,2})\s*[/.]\s*(\d{1,2})(?![\d:])/)
  if (m) {
    const mo = Number(m[1])
    const d = Number(m[2])
    if (mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
      let year = now.getFullYear()
      const date = new Date(year, mo - 1, d)
      if (date.getTime() < now.getTime() - 45 * 86400000) date.setFullYear(++year)
      return { date, matched: m[0] }
    }
  }
  return null
}

/** 解析「今天/明天/下周三/周五」等相对日，返回 { date, matched } */
function parseRelativeDate(text, now) {
  const REL = [
    ['大后天', 3],
    ['后天', 2],
    ['明天', 1],
    ['明日', 1],
    ['明早', 1],
    ['明晚', 1],
    ['今天', 0],
    ['今日', 0],
    ['今晚', 0],
    ['今早', 0],
    ['今天下午', 0],
  ]
  for (const [word, offset] of REL) {
    if (text.includes(word)) {
      const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset)
      return { date, matched: word }
    }
  }
  // 下周三 / 本周五 / 这周日 / 周五 / 星期三
  const m = text.match(/(下下|下|本|这|这个)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天])/)
  if (m) {
    const target = WEEK_CN.indexOf(m[2] === '天' ? '日' : m[2])
    if (target >= 0) {
      const todayIdx = now.getDay()
      let delta
      if (m[1] === '下' || m[1] === '下下') {
        const weeksAhead = m[1] === '下下' ? 2 : 1
        delta = (7 - todayIdx + target) % 7 + 7 * (weeksAhead - 1)
        if (delta === 0) delta = 7 * weeksAhead
      } else {
        // 本周 / 这周 / 省略前缀：取最近的一个该星期几（今天算 0）
        delta = (target - todayIdx + 7) % 7
      }
      const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + delta)
      return { date, matched: m[0] }
    }
  }
  return null
}

/** 中文数字转阿拉伯（仅覆盖 0-59，够用于小时分钟） */
function cnNum(str) {
  const map = { 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 }
  if (!str) return NaN
  if (/^\d+$/.test(str)) return Number(str)
  if (str === '十') return 10
  if (str.includes('十')) {
    const [a, b] = str.split('十')
    const tens = a ? map[a] : 1
    const ones = b ? map[b] : 0
    if (tens === undefined || ones === undefined) return NaN
    return tens * 10 + ones
  }
  return map[str] ?? NaN
}

/** 给 12 小时制补上下午：下午/晚上 +12（同时把时段词一起吃掉，避免污染标题） */
/* 午别词：「晚上 8 点半」也会被写成「晚8点半」「今晚八点半」，单字「晚/早」必须一起认。
   放在最后按长度倒序匹配，避免「晚上」被「晚」抢先吃掉。 */
const MERIDIEM_TAIL_RE = /(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|夜间|今早|明早|今晚|明晚|晚|早)$/

/** 从 idx 往前找最近的午别词（窗口放宽到 6 字，覆盖「明天晚上」这种复合写法） */
function meridiemBefore(text, idx) {
  const before = text.slice(Math.max(0, idx - 6), idx)
  const m = before.match(MERIDIEM_TAIL_RE)
  return m ? m[0] : ''
}

function applyMeridiem(hour, text, matchedStart) {
  const word = meridiemBefore(text, matchedStart)
  // 明早/今早 属于上午，不 +12
  if (word && /^(上午|早上|早晨|早)$/.test(word)) {
    if (hour === 12) return 0
    return hour
  }
  if (word && /^(下午|傍晚|晚上|夜里|夜间|今晚|明晚|晚)$/.test(word)) {
    if (hour < 12) return hour + 12
    return hour
  }
  if (word === '中午' && hour < 11) return hour + 12
  if (word === '凌晨' && hour === 12) return 0
  return hour
}

/** 把紧贴在时间前面的「下午/晚上/今晚」并入匹配范围 */
function expandWithMeridiem(text, matched) {
  const idx = text.indexOf(matched)
  if (idx <= 0) return matched
  const word = meridiemBefore(text, idx)
  return word ? word + matched : matched
}

/** 解析时间范围 / 单点时间，返回 { start, end, matched } 或 null */
function parseTime(text) {
  const hit = parseTimeRaw(text)
  if (!hit) return null
  return { ...hit, matched: expandWithMeridiem(text, hit.matched) }
}

function parseTimeRaw(text) {
  // 14:00-15:35 / 14:00~15:35 / 14：00 到 15：35
  let m = text.match(
    /(\d{1,2})\s*[:：]\s*(\d{2})\s*(?:-|~|～|—|至|到)\s*(\d{1,2})\s*[:：]\s*(\d{2})/,
  )
  if (m) {
    const h1 = Number(m[1])
    let h2 = Number(m[3])
    if (h2 < h1) h2 += 12
    return {
      start: fmtTime(h1, Number(m[2])),
      end: fmtTime(h2, Number(m[4])),
      matched: m[0],
    }
  }
  // 下午2点到4点 / 14:00 到 15:00 / 2点-4点 / 八点半到十点
  m = text.match(
    /(\d{1,2}|[一二两三四五六七八九十]{1,3})\s*[点時时]\s*(半|\d{1,2}\s*分)?\s*(?:-|~|～|—|至|到)\s*(\d{1,2}|[一二两三四五六七八九十]{1,3})\s*[点時时]\s*(半|\d{1,2}\s*分)?/,
  )
  if (m) {
    let h1 = cnNum(m[1])
    let h2 = cnNum(m[3])
    const idx = text.indexOf(m[0])
    h1 = applyMeridiem(h1, text, idx)
    h2 = applyMeridiem(h2, text, idx)
    const minuteOf = (g) => {
      if (!g) return 0
      if (g === '半') return 30
      return Number(g.replace(/[^\d]/g, '')) || 0
    }
    let m1 = minuteOf(m[2])
    let m2 = minuteOf(m[4])
    // 晚上八点半到十点：结束点没写午别，跟着开始点走，别掉回早上
    if (h2 < h1 || (h2 === h1 && m2 < m1)) h2 += 12
    return { start: fmtTime(h1, m1), end: fmtTime(h2, m2), matched: m[0] }
  }
  // 14:00 / 14：00（前面带「晚/晚上/下午」时要补成 20:30）
  m = text.match(/(\d{1,2})\s*[:：]\s*(\d{2})/)
  if (m) {
    let h = Number(m[1])
    const mi = Number(m[2])
    if (h <= 23 && mi <= 59) {
      h = applyMeridiem(h, text, text.indexOf(m[0]))
      if (h > 23) h -= 12
      return { start: fmtTime(h, mi), end: '', matched: m[0] }
    }
  }
  // 下午2点 / 两点半 / 14点30分
  m = text.match(/(\d{1,2}|[一二两三四五六七八九十]{1,3})\s*[点時时]\s*(半|\d{1,2}\s*分)?/)
  if (m) {
    let h = cnNum(m[1])
    let mi = 0
    if (m[2] === '半') mi = 30
    else if (m[2]) mi = Number(m[2].replace(/[^\d]/g, '')) || 0
    const idx = text.indexOf(m[0])
    h = applyMeridiem(h, text, idx)
    if (h <= 23) return { start: fmtTime(h, mi), end: '', matched: m[0] }
  }
  return null
}

/** 转义正则特殊字符，用于把识别出的地点反查回原文 */
function escapeRe(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 把「在」后面抓到的长串裁成真正的地点。
 *
 * 抓到的往往是「图书馆三楼开组会」这种「地点 + 动作」粘连串。中文里地点几乎
 * 总以结构词收尾（楼/馆/室/场/厅/区/座/门/中心/教室…），所以取**最后一处**
 * 结构词之前的整体，比猜测动作词更稳。
 */
const PLACE_TAIL =
  /(楼|馆|室|场|厅|堂|区|座|幢|栋|门|层|中心|广场|礼堂|教室|实验室|会议室|图书馆|食堂|公寓|宿舍|校区|学院|机房|报告厅|体育场|体育馆)/g

function trimToPlace(raw) {
  const s = raw.trim()
  if (!s) return ''
  let lastEnd = -1
  let m
  PLACE_TAIL.lastIndex = 0
  while ((m = PLACE_TAIL.exec(s)) !== null) {
    const end = m.index + m[0].length
    // 结构词后紧跟门牌号（45楼B203 / 图书馆三楼）时，把门牌一起收进地点
    const rest = s.slice(end)
    const door = rest.match(/^(?:[A-Za-z]{0,3}\d{1,4}[A-Za-z]?|[一二三四五六七八九十]{1,2}(?:楼|层)|东|西|南|北)/)
    const full = door ? end + door[0].length : end
    const tail = s.slice(full)
    // 门牌号之后若还接动作词，说明地点到 full 为止
    if (!tail || /^(?:开|上|听|参|去|打|取|拿|领|办|进|集|签|考|吃|会|自|做|写|复|预|交|值|排|整)/.test(tail)) {
      lastEnd = full
    }
    if (PLACE_TAIL.lastIndex === m.index) PLACE_TAIL.lastIndex++
  }
  if (lastEnd >= 2) return s.slice(0, lastEnd)
  // 兜底：砍掉首个动作短语之后的部分
  const cut = s.search(/(?:开|上|听|参|去|打|取|拿|领|办|进|集|签)(?:组会|课|会|自习|实验|快递|外卖|球|餐)/)
  return cut >= 2 ? s.slice(0, cut) : s
}

/** 解析地点，返回 { location, matched } */
function parseLocation(text) {
  const clean = (s) =>
    s
      .replace(/^[\s:：,，、]+/, '')
      .replace(/[\s,，。;；!！?？]+$/, '')
      .replace(/^[的得在了于]+/, '')
      .trim()
  const patterns = [
    /(?:地点|地址|教室|会议室|场地|集合地|上课地点)\s*[:：]\s*([^\s,，。;；!！?？]{1,24})/,
    /(?:在|于)\s*([^\s,，。;；!！?？]{2,24})/,
    /@\s*([^\s,，。;；!！?？]{2,24})/,
    /([0-9]+楼[0-9A-Za-z-]*|[一二三四五六七八九十百零\d]{1,3}教[0-9A-Za-z-]*(?:室|楼)?|[A-Za-z]?\d{2,3}\s*室)/,
  ]
  for (const re of patterns) {
    const m = text.match(re)
    if (!m) continue
    const rawGroup = m[1] || m[0]
    const loc = trimToPlace(clean(rawGroup))
    if (!loc || loc.length < 2) continue
    // 切掉前导噪声后，剩余地点在原文里的真实位置
    const noise = rawGroup.indexOf(loc) > 0 ? rawGroup.slice(0, rawGroup.indexOf(loc)) : ''
    const anchor = m.index + m[0].indexOf(rawGroup) + noise.length
    // 从这里往回吃：包括 "在/于/@"、地点前缀词和地点本身，整块从原文里挖掉
    let start = anchor
    const head = text.slice(Math.max(0, anchor - 8), anchor)
    const prefix = head.match(/(?:地点|地址|教室|会议室|场地|集合地|上课地点|在|于|@)\s*[:：]?\s*$/)
    if (prefix) start = Math.max(0, anchor - prefix[0].length)
    const end = anchor + loc.length
    return { location: loc, matched: text.slice(start, end) }
  }
  return null
}

/** 从剩余文本里提炼标题：优先用顿号/逗号切出的最短有意义的片段 */
const FILLER_RE =
  /^(记得|记得要|别忘了|别忘|请|麻烦|需要|关于|内容|备注|事项|通知|另外|还有|然后|就是|那|这个|那个)+/

/** 标题里不该出现的残渣：时间切走后剩的单字、口语连词、纯语气词 */
const TITLE_JUNK_RE =
  /^(?:半|点|分|时|晚|早|号|日|月|年|点整|左右|前后|之间|开始|结束|的|了|就|要|在|于|和|跟|把|被|对|给|有|是|及|与)+$/

/**
 * 判断「这条标题其实什么都没提炼出来」：
 * 只剩时间/日期本身、只剩碎片、或干脆是整段原文照抄。
 */
function isTitleHopeless(title, original, rawNow) {
  const t = title.replace(/\s+/g, '')
  if (!t) return true
  if (TITLE_JUNK_RE.test(title)) return true
  // 标题里几乎全是数字与时间单位 → 只写了个时间点，没给事由
  const timeish = t.replace(
    /[\d年月日号点分时半至到\-~～—:：上午早上早晨中午下午傍晚晚上夜里凌晨明今早晚前后左右]/g,
    '',
  )
  if (timeish.length <= 1) return true
  // 纯语气词/口头禅（啊那个就是那个啥来着）→ 没有任何事由信息。
  // 反向判断更稳：剥掉语气词后还剩实义汉字才算提炼成功，白名单永远不够全。
  const CHATTER_WORDS = [
    '那个啥来着', '那个啥', '差不多', '唉呀', '什么', '怎么', '样子', '大概', '好像', '可能',
    '应该', '其实', '反正', '总之', '所以', '但是', '不过', '或者', '以及', '然后', '还有',
    '那个', '这个', '就是', '那啥', '来着', '嗯', '哦', '噢', '哎', '诶', '欸', '呃', '额',
    '啊', '呀', '吧', '呢', '嘛', '哈', '了', '的', '是', '在', '和', '跟', '要', '想',
    '说', '啥', '呗', '啦', '咯', '哟', '喂', '唉', '就',
  ].sort((a, b) => b.length - a.length)
  const chatterRe = new RegExp(CHATTER_WORDS.join('|'), 'g')
  const stripped = t.replace(chatterRe, '').replace(/[\s\p{P}]/gu, '')
  if (stripped.length <= 1) return true
  // 剥完只剩标点/数字 → 也算没提炼出来
  if (!/[\u4e00-\u9fa5a-zA-Z]/.test(stripped)) return true
  // 整段原文照抄：长的算失败，短得像名字（开组会）才留
  const o = String(original || '').replace(/\s+/g, '')
  if (t === o && t.length > 10) return true
  return false
}

function parseTitle(remainder, original) {
  const tidy = (s) =>
    s
      .replace(/[，,。;；!！?？:：]+/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(FILLER_RE, '')
      .trim()

  // 日期/时间被切走后常留下「前」「之前」「以前」「截止」「前提交」这类残渣，
  // 以及「记得」「在」「上」这种没有信息量的引导词。逐层剥掉，剥到没变化为止。
  const scrub = (s) => {
    let prev
    let cur = s
    do {
      prev = cur
      cur = cur
        .replace(/^[\s，,。;；:：]+/, '')
        .replace(/^(?:截止时间|截止日期|截止|最晚|之前|以前|前|后|起|止|从|至|到)\s*/, '')
        .replace(FILLER_RE, '')
        .replace(/^[的得了上下去来一边啦吧呀在于把被对给和跟向从有是及与要]+/, '')
        // 时间被切走后残留的「半」「点半」「点钟」之类单字碎片
        .replace(/^[半点钟分時时]\s*/, '')
        // 日期/时间没被主流程切干净时残留的前缀（周三下午两点 / 11月20日）
        .replace(
          /^(?:今天|明天|后天|大后天|昨天|前天|本周|这周|这周末|周末|下周末|下周|下下周|周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天])\s*/,
          '',
        )
        .replace(/^(?:上午|早上|早晨|中午|下午|傍晚|晚上|夜里|凌晨|明早|今早|明晚|今晚|早晚?)\s*/, '')
        .replace(/^\d{1,2}\s*月\s*\d{1,2}\s*[日号]\s*/, '')
        .replace(/^\d{1,2}\s*月\s*/, '')
        .replace(/^[\d一二两三四五六七八九十]{1,3}\s*[点時时]\s*(?:半|\d{1,2}\s*分)?\s*/, '')
        .replace(/\s+/g, ' ')
        .trim()
    } while (cur !== prev)
    // 结尾的「交了 / 提交了 / 办了」是口语尾巴，留着不像标题
    return cur.replace(/(?:交了|办完|搞定|弄完|交|提交|完成|做完)$/, '').trim() || cur
  }

  let text = scrub(tidy(remainder))
  if (!text || text.length < 2) text = scrub(tidy(original))
  if (!text || text.length < 2) text = scrub(original.replace(/[，,。;；!！?？:：]+/g, ' '))
  if (!text || text.length < 2) return ''

  // 优先取第一个短语；一段话里第一个短句通常是事由，后面都是补充说明
  const clauses = text
    .split(/[，,。;；!！?？·、]|\s{2,}/)
    .map((s) => s.trim())
    .filter(Boolean)
  let title = clauses.find((c) => c.length >= 2) || text
  // 还是太长（一整个长句）就按空格再切一刀
  if (title.length > 16) {
    const cut = title.split(/\s+/)[0]
    if (cut.length >= 2 && cut.length < title.length) title = cut
  }
  title = title.slice(0, 24).trim()

  // 提炼失败就返回空串，由主流程换成「日程 / 待办事项」这类通用名称，
  // 绝不把一整段话原样塞成标题。
  if (title.length < 2) return ''
  if (isTitleHopeless(title, original)) return ''
  return title
}

/** 标题是否只是地点（「45楼B203」），那就等于没提炼出什么事由 */
function titleIsJustLocation(title, location) {
  if (!title || !location) return false
  const norm = (s) => String(s).replace(/[\s，,。;；:：·、-]/g, '').toLowerCase()
  const t = norm(title)
  const l = norm(location)
  if (!t || !l) return false
  return t === l || l.includes(t) || t.includes(l)
}

/** 主入口：把一段文本解析成日程字段 */
export function parseScheduleText(raw, now = new Date()) {
  const text = String(raw || '').replace(/\r/g, ' ').replace(/\n+/g, ' ')
  let working = text
  const result = {
    title: '',
    date: '',
    kind: 'class',
    start: '',
    end: '',
    duration: 0,
    location: '',
    description: '',
  }

  // 1. 时间（先解析，避免日期正则误吃冒号）
  const time = parseTime(working)
  if (time) {
    result.start = time.start
    result.end = time.end
    working = working.replace(time.matched, ' ')
  }

  // 2. 日期
  const abs = parseAbsoluteDate(working, now)
  const rel = abs ? null : parseRelativeDate(working, now)
  const dateHit = abs || rel
  if (dateHit) {
    result.date = fmtDate(dateHit.date)
    working = working.replace(dateHit.matched, ' ')
  } else {
    result.date = fmtDate(now)
  }
  // 单独出现的「下午 / 晚上」在这之后彻底无用，清掉免得污染标题
  working = working.replace(/凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|夜间/g, ' ')

  // 3. 地点
  const loc = parseLocation(working)
  if (loc) {
    result.location = loc.location
    working = working.replace(loc.matched, ' ')
  }

  // 4. 时长 / 类型判定
  if (result.start && result.end) {
    const [h1, m1] = result.start.split(':').map(Number)
    const [h2, m2] = result.end.split(':').map(Number)
    let hours = h2 + m2 / 60 - (h1 + m1 / 60)
    if (hours <= 0) hours += 24
    const OPTIONS = [0.5, 1, 1.5, 2, 2.5, 3, 4, 6, 8]
    result.duration = OPTIONS.reduce(
      (best, opt) => (Math.abs(opt - hours) < Math.abs(best - hours) ? opt : best),
      OPTIONS[0],
    )
    result.kind = 'class'
  } else if (!result.start) {
    // 完全没提到时间 → 按待办处理，默认 21:00 截止
    result.kind = 'deadline'
    result.start = '21:00'
  } else {
    // 只给了时间点：有地点/有事件动词就是活动（用默认 1.5h），否则当截止时刻
    const activity = Boolean(result.location) || /开会|上课|组会|自习|实验|讲座|课|面试|面谈|答辩|球|报告|聚会|活动|培训|会议|考试|讨论/.test(text)
    result.kind = activity ? 'class' : 'deadline'
    if (activity) result.duration = 1.5
  }

  // 5. 标题：识别不出有意义的短语时，按类型给一个通用名称（而不是拿整段话当标题）
  const parsedTitle = parseTitle(working, text)
  const generic = result.kind === 'deadline' ? '待办事项' : '日程'
  result.title = parsedTitle && !titleIsJustLocation(parsedTitle, result.location) ? parsedTitle : generic
  result.description = text.trim()
  return result
}
