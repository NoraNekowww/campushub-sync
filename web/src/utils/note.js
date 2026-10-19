/**
 * 待办备注里的「我们自己加的元信息行」。
 *
 * 微软待办的任务**没有**地点字段、也没有时长的概念，所以这两样都是并进备注的
 * （后端 `backend/app/connectors/ms_todo.py` 的 `note_with_meta`）：
 *
 *     📍 45楼B203
 *     ⏱ 1.5h
 *     带教材
 *
 * 展示层统一把这两行摘出来：地点在卡片上单独显示，时长换算成结束时间，
 * 备注里就不用再重复一遍（用户要求「网页端隐藏这个格式」）。
 *
 * 后端读回来时已经摘过一次（`split_note_location` / `split_note_meta`），
 * 这里再兜一层 —— 老数据、别处写入的备注、或者以后新增的写入路径漏了，
 * 都不会把 `📍 …` / `⏱ …` 漏到界面上。
 */
const LOCATION_LINE = /^[ \t]*📍[ \t]*(.*)$/
const DURATION_LINE = /^[ \t]*(?:⏱|⌛|⏳)[ \t]*([0-9]+(?:\.[0-9]+)?)[ \t]*h(?:ours?)?[ \t]*$/i

/** 把 `1.5h` / `2小时` 这种时长文本读成小时数；读不出返回 null。 */
export function parseDurationHours(value) {
  const text = value === null || value === undefined ? '' : String(value).trim()
  if (!text) return null
  const match = /^([0-9]+(?:\.[0-9]+)?)[ \t]*(?:h|hours?|小时|时)?$/i.exec(text)
  if (!match) return null
  const hours = Number(match[1])
  return Number.isFinite(hours) ? hours : null
}

/** 小时数 -> `1h` / `1.5h`（我们写进备注的那种写法）。 */
export function formatDurationHours(hours) {
  const value = Number(hours)
  if (!Number.isFinite(value) || value <= 0) return ''
  return `${Number.isInteger(value) ? value : value.toFixed(1)}h`
}

/**
 * 拆成 `{ location, durationHours, note }`：`note` 是用户自己写的那部分，
 * `durationHours` 是备注里 `⏱ …` 那行读出来的小时数（没有则为 null）。
 */
export function splitNoteMeta(note) {
  const text = note === null || note === undefined ? '' : String(note)
  if (!text) return { location: '', durationHours: null, note: '' }
  let location = ''
  let durationHours = null
  const rest = []
  for (const line of text.split(/\r?\n/)) {
    const where = LOCATION_LINE.exec(line)
    if (where && !location) {
      location = where[1].trim()
      continue
    }
    const howLong = DURATION_LINE.exec(line)
    if (howLong && durationHours === null) {
      const hours = Number(howLong[1])
      if (Number.isFinite(hours)) {
        durationHours = hours
        continue
      }
    }
    rest.push(line)
  }
  return { location, durationHours, note: rest.join('\n').trim() }
}

/** 兼容旧名字：只关心地点的那部分调用。 */
export function splitNoteLocation(note) {
  const { location, note: rest } = splitNoteMeta(note)
  return { location, note: rest }
}

/** 只留用户自己写的备注（去掉地点行和时长行）。 */
export function stripNoteLocation(note) {
  return splitNoteMeta(note).note
}

/** 同上，名字更贴切。 */
export function stripNoteMeta(note) {
  return splitNoteMeta(note).note
}
