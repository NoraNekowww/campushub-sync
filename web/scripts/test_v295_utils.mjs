import { strEnc } from '../src/utils/tjuDes.js'
import { parseIcsText } from '../src/utils/icsParser.js'
import { WALLPAPER_CATEGORIES, getRandomWallpaper } from '../src/utils/wallpapers.js'

let passed = 0
const fails = []

function check(name, fn) {
  try {
    fn()
    passed += 1
  } catch (err) {
    fails.push(`${name}: ${err.message}`)
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed')
}

check('tjuDes strEnc produces deterministic hex blocks', () => {
  const out1 = strEnc('test123456', '1', '2', '3')
  const out2 = strEnc('test123456', '1', '2', '3')
  assert(/^[0-9A-F]{16,}$/.test(out1), `unexpected hex: ${out1}`)
  assert(out1 === out2, 'must be deterministic')
  assert(strEnc('') === '', 'empty string returns empty')
})

check('icsParser extracts VEVENT courses with Asia/Shanghai timestamps', () => {
  const ics = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'BEGIN:VEVENT',
    'UID:course-1@tju',
    'SUMMARY:高等数学(上)',
    'LOCATION:45楼B201',
    'DTSTART:20261120T083000',
    'DTEND:20261120T100500',
    'DESCRIPTION:王老师',
    'END:VEVENT',
    'END:VCALENDAR',
  ].join('\r\n')
  const items = parseIcsText(ics)
  assert(items.length === 1, `expected 1, got ${items.length}`)
  assert(items[0].title === '高等数学(上)', 'title mismatch')
  assert(items[0].location === '45楼B201', 'location mismatch')
  assert(items[0].start_time === '2026-11-20T08:30:00+08:00', `bad start: ${items[0].start_time}`)
  assert(items[0].end_time === '2026-11-20T10:05:00+08:00', `bad end: ${items[0].end_time}`)
})

check('wallpapers catalog has valid paired URLs and getRandomWallpaper works', () => {
  assert(WALLPAPER_CATEGORIES.length === 4, 'expected 4 categories')
  for (const cat of WALLPAPER_CATEGORIES) {
    assert(cat.items.length >= 2, `category ${cat.key} too small`)
    for (const item of cat.items) {
      assert(item.title && item.light.startsWith('https://') && item.dark.startsWith('https://'), 'invalid wallpaper item')
    }
    const picked = getRandomWallpaper(cat.key, cat.items[0].light)
    assert(picked && picked.light !== cat.items[0].light, 'random should rotate away from current')
  }
})

if (fails.length) {
  console.error(`FAIL ${fails.length}`)
  fails.forEach((f) => console.error(' - ' + f))
  process.exit(1)
}
console.log(`v295 utils tests: ${passed}/${passed} passed`)
