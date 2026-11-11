import { parseScheduleText } from '../src/utils/parseScheduleText.js'

const NOW = new Date(2026, 10, 11, 10, 0, 0) // 2026-11-11 周三 10:00
let pass = 0
let fail = 0

function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (ok) { pass++ } else { fail++; console.log(`FAIL ${name}\n  got : ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`) }
}

const r1 = parseScheduleText('周一 14:00-15:35 在 45楼B203 上高数课，记得带教材', NOW)
check('r1.date', r1.date, '2026-11-16')
check('r1.start', r1.start, '14:00')
check('r1.end', r1.end, '15:35')
check('r1.location', r1.location, '45楼B203')
check('r1.kind', r1.kind, 'class')
check('r1.duration', r1.duration, 1.5)
check('r1.title', r1.title, '高数课 记得带教材')

const r2 = parseScheduleText('明天下午3点到5点在图书馆三楼开组会', NOW)
check('r2.date', r2.date, '2026-11-12')
check('r2.start', r2.start, '15:00')
check('r2.end', r2.end, '17:00')
check('r2.duration', r2.duration, 2)
check('r2.location', r2.location, '图书馆三楼')
check('r2.title', r2.title, '开组会')

const r3 = parseScheduleText('2026-11-20 09:00-11:00 46楼A202 电子技术实验，带实验报告', NOW)
check('r3.date', r3.date, '2026-11-20')
check('r3.location', r3.location, '46楼A202')
check('r3.title', r3.title, '电子技术实验 带实验报告')

const r4 = parseScheduleText('11月15日 晚上7点 在北洋园体育馆打羽毛球', NOW)
check('r4.date', r4.date, '2026-11-15')
check('r4.start', r4.start, '19:00')
check('r4.location', r4.location, '北洋园体育馆')
check('r4.title', r4.title, '打羽毛球')
check('r4.kind', r4.kind, 'class')

const r5 = parseScheduleText('周五 8点 交实验报告', NOW)
check('r5.date', r5.date, '2026-11-13')
check('r5.start', r5.start, '08:00')
check('r5.title', r5.title, '交实验报告')
check('r5.location', r5.location, '')

const r6 = parseScheduleText('记得拿快递', NOW)
check('r6.title', r6.title, '拿快递')
check('r6.date', r6.date, '2026-11-11')
check('r6.start', r6.start, '21:00')

const r7 = parseScheduleText('今晚八点半 宿舍楼下取外卖', NOW)
check('r7.start', r7.start, '20:30')
check('r7.title', r7.title, '宿舍楼下取外卖')

const r8 = parseScheduleText('11/20 13:30 地点：图书馆报告厅 讲座：人工智能前沿', NOW)
check('r8.date', r8.date, '2026-11-20')
check('r8.location', r8.location, '图书馆报告厅')
check('r8.title', r8.title, '讲座 人工智能前沿')

const r9 = parseScheduleText('下周三 10:00 一教101 集合，去参观实验室', NOW)
check('r9.date', r9.date, '2026-11-18')
check('r9.location', r9.location, '一教101')

// 原文必须完整保存进备注
check('r1.desc', r1.description, '周一 14:00-15:35 在 45楼B203 上高数课，记得带教材')

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
