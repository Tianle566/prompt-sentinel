import axios from 'axios'
export const api = axios.create({ baseURL: '/api', timeout: 20000 })
api.interceptors.request.use((config) => {
  if (/^\/(?:detect|chat(?:\/compare)?|attack\/run|document\/summarize)$/.test(config.url || ''))
    config.timeout = 900000
  if (config.url === '/admin/target/test') config.timeout = 45000
  const token = sessionStorage.getItem('sentinel_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      sessionStorage.removeItem('sentinel_token')
      window.dispatchEvent(new Event('sentinel:expired'))
    }
    return Promise.reject(error)
  }
)
export function errorText(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail))
    return detail.map((v) => `${v.loc?.slice(1).join('.') || '请求'}：${v.msg}`).join('；')
  if (error?.code === 'ECONNABORTED')
    return /^\/(?:detect|chat|attack\/run|document\/summarize)/.test(error.config?.url || '')
      ? '请求等待超时。模型可能仍在处理，请到拦截日志查看结果。'
      : '服务响应超时，请稍后重试或查看启动窗口。'
  if (!error?.response) return '无法连接后端服务，请确认项目已启动，并查看启动窗口。'
  return `请求失败（${error.response.status}），请稍后重试。`
}
export const attackTypes = {
  goal_hijacking: '目标劫持',
  prompt_leaking: '提示泄露',
  prompt_leakage: '提示泄露',
  role_play: '角色扮演 / 越狱',
  roleplay: '角色扮演 / 越狱',
  jailbreak: '角色扮演 / 越狱',
  encoded_obfuscation: '编码混淆',
  encoding: '编码混淆',
  encoded: '编码混淆',
  encoding_obfuscation: '编码混淆',
  indirect_injection: '间接注入',
  indirect: '间接注入',
  unsafe_instruction: '不安全指令',
  manual: '手动测试',
  benign: '正常输入',
  unknown: '未分类',
  prompt_injection: '提示词注入',
  canary_leakage: '金丝雀泄露',
  unsafe_response: '不安全回复',
  Violent: '暴力内容',
  'Non-violent Illegal Acts': '非暴力违法行为',
  'Sexual Content or Sexual Acts': '色情内容',
  PII: '个人隐私信息',
  'Suicide & Self-Harm': '自伤内容',
  'Unethical Acts': '不道德行为',
  'Politically Sensitive Topics': '政治敏感内容',
  'Copyright Violation': '版权侵权',
  Jailbreak: '越狱指令',
}
export const attackName = (value) => attackTypes[value] || value || '未分类'
export const number = (value) =>
  typeof value === 'number'
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value)
    : '—'
export const duration = (value) =>
  typeof value === 'number'
    ? value >= 1000
      ? `${number(value / 1000)} s`
      : `${number(value)} ms`
    : '—'
export const percentage = (value) =>
  typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—'
export const dateTime = (value) =>
  value
    ? new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`).toLocaleString('zh-CN', {
        hour12: false,
      })
    : '—'
export async function downloadFile(url, filename, params) {
  const { data } = await api.get(url, { params, responseType: 'blob' })
  const objectUrl = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}
export async function artifact(jobId, filename, download = false) {
  const { data } = await api.get(
    `/eval/artifacts/${encodeURIComponent(jobId)}/${encodeURIComponent(filename)}`,
    { responseType: 'blob' }
  )
  const url = URL.createObjectURL(data)
  if (download) {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return url
}
