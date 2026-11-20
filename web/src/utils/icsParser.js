import { formatShanghaiIso } from './datetime.js'

function unfoldIcs(text) {
  return String(text || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\n[ \t]/g, '')
    .split('\n')
}

function unescapeIcs(val) {
  return String(val || '')
    .replace(/\\n/gi, '\n')
    .replace(/\\,/g, ',')
    .replace(/\\;/g, ';')
    .replace(/\\\\/g, '\\')
    .trim()
}

function parseIcsDate(raw) {
  if (!raw) return null
  const text = String(raw).trim()
  // YYYYMMDD
  const dOnly = /^(\d{4})(\d{2})(\d{2})$/.exec(text)
  if (dOnly) {
    return `${dOnly[1]}-${dOnly[2]}-${dOnly[3]}T08:00:00+08:00`
  }
  // YYYYMMDDTHHMMSS(Z?)
  const dtMatch = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z)?$/i.exec(text)
  if (!dtMatch) return null
  const [, y, m, d, hh, mm, ss = '00', isUtc] = dtMatch
  if (isUtc) {
    const dt = new Date(Date.UTC(+y, +m - 1, +d, +hh, +mm, +ss))
    return formatShanghaiIso(dt)
  }
  return `${y}-${m}-${d}T${hh}:${mm}:${ss}+08:00`
}

/**
 * Parse an `.ics` calendar string locally into app event items (zero network needed).
 */
export function parseIcsText(icsText) {
  const lines = unfoldIcs(icsText)
  const events = []
  let cur = null

  for (const line of lines) {
    if (line === 'BEGIN:VEVENT') {
      cur = {}
      continue
    }
    if (line === 'END:VEVENT') {
      if (cur && cur.title && cur.start_time) {
        const uid = cur.uid || `${cur.start_time}_${cur.title}`
        events.push({
          id: `ics_${btoa(unescape(encodeURIComponent(uid))).replace(/[^a-zA-Z0-9]/g, '').slice(0, 20)}`,
          source: 'tju_schedule',
          source_id: uid,
          title: cur.title,
          description: cur.description || '',
          location: cur.location || '',
          start_time: cur.start_time,
          end_time: cur.end_time || null,
          is_deadline: false,
          is_undated: false,
          status: 'pending',
          priority: 5,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
      }
      cur = null
      continue
    }
    if (!cur) continue
    const sep = line.indexOf(':')
    if (sep <= 0) continue
    const keyPart = line.slice(0, sep).split(';')[0].toUpperCase()
    const val = line.slice(sep + 1)

    if (keyPart === 'UID') cur.uid = unescapeIcs(val)
    else if (keyPart === 'SUMMARY') cur.title = unescapeIcs(val)
    else if (keyPart === 'LOCATION') cur.location = unescapeIcs(val)
    else if (keyPart === 'DESCRIPTION') cur.description = unescapeIcs(val)
    else if (keyPart === 'DTSTART') cur.start_time = parseIcsDate(val)
    else if (keyPart === 'DTEND') cur.end_time = parseIcsDate(val)
  }

  return events
}
