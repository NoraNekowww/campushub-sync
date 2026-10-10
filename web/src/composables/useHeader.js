/** Small derived-value helpers kept out of the components. */
const formatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
})

export const haveEvents = (state) => (state.events || []).length > 0

export function subtitleText(state, hasEvents) {
  if (state.syncing) return '正在与 Microsoft To Do / 教务同步…'
  const last = state.lastUpdated
  if (state.error) return state.error
  if (!hasEvents) return '暂无日程'
  const stamp = last
    ? new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(last)
    : ''
  const today = formatter.format(new Date())
  return stamp ? `${today} · 更新于 ${stamp} · ${state.total} 条` : `${today} · ${state.total} 条`
}
