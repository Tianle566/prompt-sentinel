export const requestKinds = {
  chat: '安全对话',
  compare: '对照测试',
  attack: '安全测试',
  document: '文档处理',
  detect: '输入检测',
}
export const statusLabels = { allowed: '已放行', blocked: '已拦截', error: '执行异常' }
export const statusTones = { allowed: 'success', blocked: 'danger', error: 'warning' }
export function requestStatus(row) {
  const result = row.result || {}
  const failed =
    result.error ||
    result.detection?.reliable === false ||
    result.output_check?.status === 'error' ||
    result.hardening?.status === 'error'
  return row.status || (failed ? 'error' : row.blocked ? 'blocked' : 'allowed')
}
export function periodParams(range) {
  if (range === 'all') return {}
  const now = new Date()
  const days = { day: 1, week: 7, month: 30 }[range] || 7
  return { start: new Date(now.getTime() - days * 86400000).toISOString(), end: now.toISOString() }
}
