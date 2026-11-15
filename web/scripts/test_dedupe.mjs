import { dedupeEvents, duplicateKey } from '../src/utils/dedupe.js'

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

const slot = (over = {}) => ({
  id: 'a',
  source: 'tju_schedule',
  title: '电子技术实验',
  start_time: '2026-11-16T08:00:00+08:00',
  end_time: '2026-11-16T09:35:00+08:00',
  location: '46楼A202',
  status: 'pending',
  is_deadline: false,
  ...over,
})

check('同一节课两个 id 只留一条', () => {
  const out = dedupeEvents([
    slot({ id: 'hash-week', local_override: false }),
    slot({ id: 'hash-direct', local_override: false }),
  ])
  assert(out.length === 1, `expected 1, got ${out.length}`)
})

check('保留信息更全的那条（带 override 的）', () => {
  const out = dedupeEvents([
    slot({ id: 'imported' }),
    slot({ id: 'synced', local_override: true, title: '电子技术实验' }),
  ])
  assert(out[0].id === 'synced', `expected synced, got ${out[0].id}`)
})

check('一条被划掉，合并后仍是完成态', () => {
  const out = dedupeEvents([
    slot({ id: 'x', status: 'pending' }),
    slot({ id: 'y', status: 'completed', completed_at: '2026-11-16T09:40:00+08:00', local_override: true }),
  ])
  assert(out.length === 1, 'should merge')
  assert(out[0].status === 'completed', 'status lost')
})

check('不同时段不误合', () => {
  const out = dedupeEvents([
    slot({ id: 'a' }),
    slot({ id: 'b', start_time: '2026-11-16T10:00:00+08:00' }),
  ])
  assert(out.length === 2, `expected 2, got ${out.length}`)
})

check('不同课程的同一时段不误合', () => {
  const out = dedupeEvents([slot({ id: 'a' }), slot({ id: 'b', title: '概率论' })])
  assert(out.length === 2, `expected 2, got ${out.length}`)
})

check('DDL 同标题同截止视为同一条（地点不参与判定）', () => {
  const out = dedupeEvents([
    slot({ id: 'a', is_deadline: true, location: '', title: '交实验报告' }),
    slot({ id: 'b', is_deadline: true, location: '图书馆', title: '交实验报告' }),
  ])
  assert(out.length === 1, `expected 1, got ${out.length}`)
})

check('缺标题的条目一律保留', () => {
  const out = dedupeEvents([slot({ id: 'a', title: '' }), slot({ id: 'b', title: '' })])
  assert(out.length === 2, `expected 2, got ${out.length}`)
})

check('输入数组不被修改', () => {
  const input = [slot({ id: 'a' }), slot({ id: 'b' })]
  dedupeEvents(input)
  assert(input.length === 2, 'input mutated')
})

check('空/非数组输入安全', () => {
  assert(dedupeEvents().length === 0, 'undefined')
  assert(dedupeEvents(null).length === 0, 'null')
})

check('duplicateKey 忽略秒级时间差', () => {
  assert(
    duplicateKey(slot({ start_time: '2026-11-16T08:00:59+08:00' })) ===
      duplicateKey(slot({ start_time: '2026-11-16T08:00:00+08:00' })),
    'seconds should not matter',
  )
})

if (fails.length) {
  console.error(`FAIL ${fails.length}`)
  fails.forEach((f) => console.error(' - ' + f))
  process.exit(1)
}
console.log(`dedupe tests: ${passed}/${passed} passed`)
