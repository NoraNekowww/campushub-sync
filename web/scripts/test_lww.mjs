import {
  mergeServerEventWithLocal,
  mergeSyncedCreateResult,
  parseEventModifiedMs,
  shouldApplySyncedPatchResult,
} from '../src/utils/lww.js'

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

const undated = (over = {}) => ({
  id: 'custom-undated-1',
  source: 'custom',
  title: '整理报销单',
  is_undated: true,
  is_deadline: true,
  status: 'pending',
  start_time: '2026-11-20T09:00:00+08:00',
  end_time: null,
  updated_at: '2026-11-20T09:00:00+08:00',
  ...over,
})

check('可办事项划掉后，云端较旧的 pending 快照不能刷回（LWW）', () => {
  const local = undated({
    status: 'completed',
    completed_at: '2026-11-20T01:05:00.000Z',
    updated_at: '2026-11-20T01:05:00.000Z',
    client_updated_at: '2026-11-20T01:05:00.000Z',
  })
  const server = undated({
    status: 'pending',
    updated_at: '2026-11-20T09:00:00+08:00',
  })
  const merged = mergeServerEventWithLocal(server, local, {
    hasPendingSync: false,
    completedOverride: null,
  })
  assert(merged.status === 'completed', `expected completed, got ${merged.status}`)
})

check('同一秒内（< 1s）划掉可办事项同样不被云端旧快照覆盖', () => {
  const local = undated({
    status: 'completed',
    updated_at: '2026-11-20T01:00:00.350Z',
    client_updated_at: '2026-11-20T01:00:00.350Z',
  })
  const server = undated({
    status: 'pending',
    updated_at: '2026-11-20T09:00:00+08:00', // 01:00:00.000Z
  })
  const merged = mergeServerEventWithLocal(server, local)
  assert(merged.status === 'completed', `expected completed within 1s, got ${merged.status}`)
})

check('本地存在待同步队列时，即使设备时钟略慢也不被云端刷回', () => {
  const local = undated({
    status: 'completed',
    client_updated_at: '2026-11-20T00:59:55.000Z', // 5s slower clock
  })
  const server = undated({
    status: 'pending',
    updated_at: '2026-11-20T09:00:00+08:00',
  })
  const override = { status: 'completed', timestamp: Date.parse('2026-11-20T00:59:55.000Z') }
  const merged = mergeServerEventWithLocal(server, local, {
    hasPendingSync: true,
    completedOverride: override,
  })
  assert(merged.status === 'completed', `expected pending sync to keep completed, got ${merged.status}`)
})

check('无待同步改动且云端最后修改时间严格更新时，对齐采用云端最新状态', () => {
  const local = undated({
    status: 'completed',
    updated_at: '2026-11-20T09:05:00+08:00',
    client_updated_at: '2026-11-20T09:05:00+08:00',
  })
  const server = undated({
    status: 'pending',
    title: '整理报销单（另一设备恢复）',
    updated_at: '2026-11-20T09:10:00+08:00',
  })
  const merged = mergeServerEventWithLocal(server, local, {
    hasPendingSync: false,
    completedOverride: null,
  })
  assert(merged.status === 'pending', `expected remote newer pending, got ${merged.status}`)
  assert(merged.title === '整理报销单（另一设备恢复）', 'expected newer title from cloud')
  assert(merged.client_updated_at === '2026-11-20T09:10:00+08:00', 'expected aligned client_updated_at')
})

check('移动端新建 local_ 可办事项后立即划掉，队列建表回写不丢失完成态', () => {
  const localBefore = undated({
    id: 'local_123',
    status: 'completed',
    created_at: '2026-11-20T01:00:00.000Z',
    updated_at: '2026-11-20T01:00:02.000Z',
    client_updated_at: '2026-11-20T01:00:02.000Z',
  })
  const serverCreated = undated({
    id: 'custom-real-99',
    status: 'pending',
    created_at: '2026-11-20T09:00:05+08:00',
    updated_at: '2026-11-20T09:00:05+08:00',
  })
  const reconciled = mergeSyncedCreateResult(serverCreated, localBefore, {
    createClientUpdatedAt: '2026-11-20T01:00:00.000Z',
    completedOverride: { status: 'completed', timestamp: Date.parse('2026-11-20T01:00:02.000Z') },
  })
  assert(reconciled.id === 'custom-real-99', 'must keep server id')
  assert(reconciled.status === 'completed', `expected completed preserved, got ${reconciled.status}`)
})

check('在途旧 PATCH 返回不得覆盖本地更新的二次切换', () => {
  const localNewer = undated({
    status: 'pending',
    client_updated_at: '2026-11-20T01:00:05.000Z',
  })
  assert(shouldApplySyncedPatchResult(localNewer, '2026-11-20T01:00:01.000Z') === false, 'stale ack rejected')
  assert(shouldApplySyncedPatchResult(localNewer, '2026-11-20T01:00:05.000Z') === true, 'matching ack accepted')
  assert(parseEventModifiedMs(localNewer) === Date.parse('2026-11-20T01:00:05.000Z'), 'exact ms parsed')
})

if (fails.length) {
  console.error(`FAIL ${fails.length}`)
  fails.forEach((f) => console.error(' - ' + f))
  process.exit(1)
}
console.log(`lww tests: ${passed}/${passed} passed`)
