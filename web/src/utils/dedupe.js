/**
 * 课程/日程去重（ID 优先 + 外部课表源内容去重）。
 *
 * 原则：
 * 1. 同一主键 `event.id` 永远只保留最后修改时间最新（LWW）的那一份，绝不并存新旧两份；
 * 2. 外部课表源（`tju_schedule`）因历史两套 hash 可能产生不同 id，按 `start|title|location` 内容去重；
 * 3. 用户自建日程（`source === 'custom'`）若都拥有正式服务器主键（非 `local_` 临时主键）且 `id` 不同，
 *    视为两条独立日程，绝不按标题误合并吞没；仅当其中一条是旧版遗留 `local_` 临时项时才合并至正式主键。
 */

import { parseEventModifiedMs } from './lww.js'

/** 判断一条事件在「同一时刻、同一标题」下是否算同一条。 */
export function duplicateKey(event) {
  if (!event) return ''
  const start = String(event.start_time || '').slice(0, 16)
  const title = String(event.title || '').trim().toLowerCase()
  if (!start || !title) return ''
  const place = event.is_deadline ? '' : String(event.location || '').trim().toLowerCase()
  return `${start}|${title}|${place}`
}

function rank(event) {
  if (!event) return -1
  let score = 0
  if (event.source === 'tju_schedule') score += 4
  if (event.id && !String(event.id).startsWith('local_')) score += 3
  if (event.local_override) score += 2
  if (event.status === 'completed') score += 1
  return score
}

function mergeTwoEvents(a, b) {
  const modA = parseEventModifiedMs(a)
  const modB = parseEventModifiedMs(b)
  // 同一 ID 时严格以最后修改时间（LWW）更新者为准
  if (a.id && b.id && a.id === b.id) {
    return modB >= modA ? { ...a, ...b } : { ...b, ...a }
  }
  const winner = rank(b) > rank(a) || (rank(b) === rank(a) && modB > modA) ? b : a
  const loser = winner === b ? a : b
  const merged = { ...loser, ...winner }
  // 若两者中修改时间严格更新的一方改过完成态，或同分时有一方已划掉，保留最新完成状态
  if (modA !== modB) {
    const newer = modB > modA ? b : a
    if (newer.status) {
      merged.status = newer.status
      merged.completed_at = newer.status === 'completed' ? newer.completed_at || merged.completed_at : null
    }
  } else if (loser.status === 'completed' && winner.status !== 'completed') {
    merged.status = 'completed'
    merged.completed_at = loser.completed_at || merged.completed_at
  }
  if (loser.attachments && loser.attachments.length && !(winner.attachments || []).length) {
    merged.attachments = loser.attachments
  }
  return merged
}

function shouldContentDedupe(prev, curr) {
  if (!prev || !curr) return false
  if (prev.id && curr.id && prev.id === curr.id) return true
  const prevTemp = String(prev.id || '').startsWith('local_')
  const currTemp = String(curr.id || '').startsWith('local_')
  if (prevTemp || currTemp) return true
  // 两条都有正式不同 ID 的个人自定义日程绝不互相吞并
  if (prev.source === 'custom' && curr.source === 'custom') return false
  return true
}

export function dedupeEvents(events = []) {
  const list = Array.isArray(events) ? events : []
  // 第一趟：按主键 id 严格归一（保证每个 id 全局唯一且处于最新修改状态）
  const byId = new Map()
  const noId = []
  for (const ev of list) {
    if (!ev || ev.hidden) continue
    if (!ev.id) {
      noId.push(ev)
      continue
    }
    const prev = byId.get(ev.id)
    byId.set(ev.id, prev ? mergeTwoEvents(prev, ev) : ev)
  }

  // 第二趟：针对外部课表源及遗留 local_ 临时项做内容去重
  const slots = new Map()
  let uniqSeq = 0
  for (const event of [...byId.values(), ...noId]) {
    const key = duplicateKey(event)
    if (!key) {
      slots.set(`__raw__${uniqSeq++}`, event)
      continue
    }
    const prev = slots.get(key)
    if (!prev) {
      slots.set(key, event)
      continue
    }
    if (shouldContentDedupe(prev, event)) {
      slots.set(key, mergeTwoEvents(prev, event))
    } else {
      slots.set(`${key}#${event.id || uniqSeq++}`, event)
    }
  }
  return [...slots.values()]
}
