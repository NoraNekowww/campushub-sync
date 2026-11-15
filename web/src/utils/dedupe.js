/**
 * 课程/日程去重。
 *
 * 病根：服务器上并排存着两套 id 体系 ——
 *   · 学期同步建立的 `hash(tju_schedule + "…w9:d2:p3-4:A202")`
 *   · 教务直连导入建立的 `hash(tju_schedule + "学期:课程:…")`
 * 同一节课于是有两个不同的 event id；一次 refresh 从 `/api/events` 拉回来两条，
 * 当日同步又写回本地缓存，列表里就出现两次。谁先清缓存谁看不到它。
 * 服务器现在已经只建一种 id，但老数据还在，前端再兜一层内容去重。
 *
 * 判重键、优先级、合并方式都放在这里，事件列表与周课表共用同一套。
 */

/** 判断一条事件在「同一时刻、同一标题」下是否算同一条。 */
export function duplicateKey(event) {
  if (!event) return ''
  const start = String(event.start_time || '').slice(0, 16)
  const title = String(event.title || '').trim().toLowerCase()
  if (!start || !title) return ''
  // 课表按「同一天同标题同地点」合并；DDL 没有地点概念，按「同标题同截止」合并
  const place = event.is_deadline ? '' : String(event.location || '').trim().toLowerCase()
  return `${start}|${title}|${place}`
}

/** 合并时字段的取舍顺序：课表来源、用户改过的、服务器 id 的优先。 */
function rank(event) {
  if (!event) return -1
  let score = 0
  // 课表来源比手抄的优先展示（有周次、地点、老师）
  if (event.source === 'tju_schedule') score += 4
  // 用户改过/划过的必须留下，否则会「一刷新又变回未完成」
  if (event.local_override) score += 2
  if (event.status === 'completed') score += 1
  return score
}

/**
 * 按内容去重，保留信息最全的那一条，同时把「完成」状态带过去。
 * 传入数组本身不被修改，返回新数组且保持原有顺序。
 */
export function dedupeEvents(events = []) {
  const list = Array.isArray(events) ? events : []
  const slots = new Map()
  list.forEach((event, index) => {
    const key = duplicateKey(event)
    if (!key) {
      // 无法判定（缺标题或缺时间）的条目一律保留，宁多勿丢
      slots.set(`__raw__${index}`, event)
      return
    }
    const prev = slots.get(key)
    if (!prev) {
      slots.set(key, event)
      return
    }
    const winner = rank(event) > rank(prev) ? event : prev
    const loser = winner === event ? prev : event
    const merged = { ...loser, ...winner }
    // 被划掉的一条即便信息更少，也要把完成状态带过去
    if (loser.status === 'completed' && winner.status !== 'completed') {
      merged.status = 'completed'
      merged.completed_at = loser.completed_at || merged.completed_at
    }
    if (loser.attachments && loser.attachments.length && !(winner.attachments || []).length) {
      merged.attachments = loser.attachments
    }
    slots.set(key, merged)
  })
  return [...slots.values()]
}
