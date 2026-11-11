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

// ─── 午别词：单字「晚/早」也必须补成 12 小时制（v2.8.7）
const n1 = parseScheduleText('晚上八点半开会', NOW)
check('n1.start', n1.start, '20:30')
check('n1.title', n1.title, '开会')

const n2 = parseScheduleText('周三晚8点半 交实验报告', NOW)
check('n2.start', n2.start, '20:30')

const n3 = parseScheduleText('11.20 晚8:30 开会', NOW)
check('n3.start', n3.start, '20:30')

const n4 = parseScheduleText('明晚8点半 开会', NOW)
check('n4.start', n4.start, '20:30')

const n5 = parseScheduleText('早8点 跑操', NOW)
check('n5.start', n5.start, '08:00')

// 范围里分钟不能丢：「八点半到十点半」
const n6 = parseScheduleText('11月20日晚上八点半到十点半 在46楼A202 上电子技术实验', NOW)
check('n6.start', n6.start, '20:30')
check('n6.end', n6.end, '22:30')
check('n6.title', n6.title, '电子技术实验')
check('n6.location', n6.location, '46楼A202')

// ─── 标题提炼失败 → 通用名称，绝不把整段话塞进标题
check('g1', parseScheduleText('晚上八点半', NOW).title, '待办事项')
check('g2', parseScheduleText('明天晚上8点半', NOW).title, '待办事项')
check('g3', parseScheduleText('11月20日 20:30', NOW).title, '待办事项')
check('g4', parseScheduleText('啊那个就是那个啥来着', NOW).title, '待办事项')
check('g5', parseScheduleText('下周三下午两点 45楼B203', NOW).title, '日程')

// 长句要截在第一个短句，不能原样搬运
check('g6', parseScheduleText('明晚8点半 和导师讨论毕设选题，记得带上开题报告和上周的实验数据', NOW).title, '导师讨论毕设选题')
check('g7', parseScheduleText('这个周末要把论文写完', NOW).title, '论文写完')
// 提炼成功时不能被通用名称顶掉
check('g8', parseScheduleText('记得11月25号之前把实验报告交了', NOW).title, '实验报告')
check('g9', parseScheduleText('今晚八点半 宿舍楼下取外卖', NOW).title, '宿舍楼下取外卖')

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
