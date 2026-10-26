import { computed, reactive } from 'vue'
import { api } from './api'
const state = reactive({ user: null, checked: false })
export const auth = {
  state,
  isAdmin: computed(() => state.user?.role === 'admin'),
  async login(values) {
    const { data } = await api.post('/auth/login', values)
    sessionStorage.setItem('sentinel_token', data.access_token)
    state.user = data.user
    state.checked = true
  },
  async check() {
    if (!sessionStorage.getItem('sentinel_token')) {
      state.user = null
      state.checked = true
      return false
    }
    try {
      const { data } = await api.get('/auth/me')
      state.user = data
      state.checked = true
      return true
    } catch {
      sessionStorage.removeItem('sentinel_token')
      state.user = null
      state.checked = true
      return false
    }
  },
  logout() {
    sessionStorage.removeItem('sentinel_token')
    state.user = null
    state.checked = true
  },
}
