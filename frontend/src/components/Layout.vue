<script setup>
import { computed, nextTick, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorText } from '../api'
import { auth } from '../auth'
import Icon from './Icon.vue'
import CommandMenu from './CommandMenu.vue'
const route = useRoute(),
  router = useRouter(),
  health = ref(null),
  healthError = ref(''),
  mobileOpen = ref(false),
  collapsed = ref(false),
  isMobile = ref(false),
  sidebar = ref(null),
  menuButton = ref(null),
  commandMenu = ref(null),
  refreshing = ref(false)
const nav = [
  {
    group: '监控',
    items: [
      { path: '/dashboard', label: '概览', icon: 'dashboard' },
      { path: '/logs', label: '请求日志', icon: 'logs' },
      { path: '/evaluation', label: '评测任务', icon: 'chart' },
    ],
  },
  {
    group: '工作台',
    items: [
      { path: '/chat', label: '安全对话', icon: 'chat' },
      { path: '/documents', label: '文档处理', icon: 'document' },
      { path: '/attack', label: '安全测试', icon: 'attack' },
    ],
  },
  {
    group: '管理',
    items: [
      { path: '/policy', label: '防护策略', icon: 'settings', admin: true },
      { path: '/rules', label: '检测规则', icon: 'shield', admin: true },
      { path: '/samples', label: '测试样本', icon: 'attack', admin: true },
      { path: '/accounts', label: '成员与权限', icon: 'user' },
      { path: '/audits', label: '操作审计', icon: 'logs', admin: true },
      { path: '/runtime', label: '系统设置', icon: 'settings', admin: true },
    ],
  },
]
const navigation = computed(() =>
  nav
    .map((section) => ({
      ...section,
      group: section.group === '管理' && !auth.isAdmin.value ? '个人设置' : section.group,
      items: section.items
        .filter((item) => !item.admin || auth.isAdmin.value)
        .map((item) => ({
          ...item,
          label: item.path === '/accounts' && !auth.isAdmin.value ? '个人账号' : item.label,
        })),
    }))
    .filter((section) => section.items.length)
)
const currentGroup = computed(
  () =>
    navigation.value.find((section) => section.items.some((item) => item.path === route.path))
      ?.group
)
const pageTitle = computed(() =>
  route.path === '/accounts' && !auth.isAdmin.value ? '个人账号' : route.meta.title
)
const pageSubtitle = computed(() =>
  route.path === '/accounts' && !auth.isAdmin.value
    ? '查看个人账号，更新登录密码。'
    : route.meta.subtitle
)
watch(
  pageTitle,
  (title) => {
    document.title = `${title || '控制台'} · Prompt Sentinel`
  },
  { immediate: true }
)
function toggleNavigation() {
  if (isMobile.value) mobileOpen.value = !mobileOpen.value
  else collapsed.value = !collapsed.value
}
function navigationKeydown(event) {
  if (!mobileOpen.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    mobileOpen.value = false
  }
  if (event.key !== 'Tab') return
  const targets = [...sidebar.value.querySelectorAll('a[href], button:not(:disabled)')].filter(
    (element) => element.getClientRects().length
  )
  const first = targets[0],
    last = targets.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}
let bodyOverflow = '',
  media
function screenChanged(event) {
  isMobile.value = event.matches
  if (!event.matches) mobileOpen.value = false
}
watch(collapsed, (value) => {
  try {
    localStorage.setItem('sentinel:sidebar', value ? 'collapsed' : 'expanded')
  } catch {
    // Navigation remains usable when browser storage is unavailable.
  }
})
watch(mobileOpen, async (open) => {
  if (open) {
    bodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } else document.body.style.overflow = bodyOverflow
  await nextTick()
  if (open) sidebar.value?.querySelector('a')?.focus()
  else menuButton.value?.focus()
})
watch(
  () => route.path,
  () => {
    mobileOpen.value = false
  }
)
async function loadHealth() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    health.value = (await api.get('/health', { timeout: 10000 })).data
    healthError.value = ''
  } catch (e) {
    healthError.value = errorText(e)
  } finally {
    refreshing.value = false
  }
}
function logout() {
  auth.logout()
  router.push('/login')
}
function shortcut(event) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    commandMenu.value?.open()
  }
}
let timer
onMounted(() => {
  media = window.matchMedia('(max-width: 800px)')
  screenChanged(media)
  media.addEventListener('change', screenChanged)
  try {
    collapsed.value = localStorage.getItem('sentinel:sidebar') === 'collapsed'
  } catch {
    collapsed.value = false
  }
  loadHealth()
  window.addEventListener('keydown', shortcut)
  timer = setInterval(loadHealth, 60000)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  window.removeEventListener('keydown', shortcut)
  media?.removeEventListener('change', screenChanged)
  if (mobileOpen.value) document.body.style.overflow = bodyOverflow
})
</script>
<template>
  <div
    class="app-shell"
    :class="{ 'nav-collapsed': collapsed, 'chat-shell': route.path === '/chat' }"
  >
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <button
      v-if="mobileOpen"
      class="sidebar-backdrop"
      aria-label="关闭导航"
      @click="mobileOpen = false"
    ></button>
    <aside
      id="primary-navigation"
      ref="sidebar"
      class="sidebar"
      :class="{ open: mobileOpen }"
      :inert="isMobile && !mobileOpen ? true : undefined"
      @keydown="navigationKeydown"
    >
      <router-link
        to="/dashboard"
        class="brand"
        aria-label="Prompt Sentinel 首页"
        @click="mobileOpen = false"
        ><span class="brand-mark"><Icon name="shield" :size="28" /></span
        ><span class="brand-copy"
          ><strong>Prompt Sentinel</strong><small>AI 安全控制台</small></span
        ></router-link
      >
      <button
        type="button"
        class="icon-button navigation-close"
        aria-label="关闭侧栏导航"
        @click="mobileOpen = false"
      >
        <Icon name="close" :size="19" />
      </button>
      <div class="workspace-badge"><Icon name="lock" :size="13" /><span>默认工作区</span></div>
      <nav aria-label="主导航">
        <div v-for="section in navigation" :key="section.group" class="nav-section">
          <div class="nav-label">{{ section.group }}</div>
          <template v-for="item in section.items" :key="item.path"
            ><router-link
              :to="item.path"
              class="nav-link"
              :aria-label="item.label"
              :title="collapsed && !isMobile ? item.label : undefined"
              @click="mobileOpen = false"
              ><Icon :name="item.icon" /><span class="nav-text">{{ item.label }}</span
              ><Icon class="nav-chevron" name="chevron" :size="14" /></router-link
          ></template>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <div class="account">
          <span class="avatar">{{ auth.state.user?.username?.slice(0, 1).toUpperCase() }}</span>
          <div class="account-copy">
            <strong>{{ auth.state.user?.username }}</strong
            ><small>{{ auth.isAdmin.value ? '系统管理员' : '普通用户' }}</small>
          </div>
          <button
            class="icon-button logout-button"
            @click="logout"
            aria-label="退出登录"
            title="退出登录"
          >
            <Icon name="logout" :size="18" />
          </button>
        </div>
      </div>
    </aside>
    <div class="main-shell" :inert="mobileOpen ? true : undefined">
      <header class="topbar">
        <div class="breadcrumb">
          <button
            ref="menuButton"
            class="icon-button navigation-toggle"
            @click="toggleNavigation"
            :aria-label="isMobile ? '打开导航' : collapsed ? '展开导航' : '收起导航'"
            :title="isMobile ? '打开导航' : collapsed ? '展开导航' : '收起导航'"
            :aria-expanded="isMobile ? mobileOpen : !collapsed"
            aria-controls="primary-navigation"
          >
            <Icon name="menu" /></button
          ><span>{{ currentGroup }}</span
          ><Icon name="chevron" :size="13" /><strong>{{ pageTitle }}</strong>
        </div>
        <div class="topbar-right">
          <button class="command-trigger" @click="commandMenu?.open()" aria-label="搜索页面和请求">
            <Icon name="logs" :size="15" /><span>搜索</span><kbd>Ctrl K</kbd>
          </button>
          <el-popover placement="bottom-end" :width="310" trigger="click"
            ><template #reference
              ><button
                class="health-badge"
                :class="{ degraded: health?.status !== 'ok' || healthError }"
              >
                <span class="live-dot"></span
                >{{
                  healthError
                    ? '后端未连接'
                    : !health
                      ? '检查服务中'
                      : health.status === 'ok'
                        ? '服务状态'
                        : '部分服务未就绪'
                }}<Icon name="chevrondown" :size="13" /></button
            ></template>
            <div class="health-popover">
              <div class="section-title">
                <h3>运行状态</h3>
                <button
                  class="icon-button"
                  aria-label="刷新运行状态"
                  @click="loadHealth"
                  :disabled="refreshing"
                >
                  <Icon name="refresh" :size="17" />
                </button>
              </div>
              <p v-if="healthError" class="text-danger">{{ healthError }}</p>
              <template v-else
                ><div v-for="(model, key) in health?.models" :key="key" class="health-model">
                  <span>{{
                    {
                      deberta: 'DeBERTa 分类器',
                      qwen_guard: 'Qwen3Guard 审核',
                      target: '目标语言模型',
                    }[key] || key
                  }}</span
                  ><el-tag :type="model.ready ? 'success' : 'warning'" size="small">{{
                    model.ready ? '已就绪' : '未就绪'
                  }}</el-tag>
                </div>
                <p class="helper">运行设备：{{ health?.device || '—' }}</p></template
              >
            </div></el-popover
          ><span class="topbar-divider"></span
          ><span class="topbar-role">{{ auth.state.user?.username }}</span>
        </div>
      </header>
      <main id="main-content" class="main-content" tabindex="-1">
        <div v-if="route.path !== '/chat'" class="page-heading">
          <div>
            <h1>{{ pageTitle }}</h1>
          </div>
          <el-popover
            v-if="route.meta.subtitle"
            placement="bottom-end"
            :width="320"
            trigger="click"
          >
            <template #reference
              ><button class="page-help" aria-label="页面帮助">
                <Icon name="info" :size="16" /><span>帮助</span>
              </button></template
            >
            <p class="context-help">{{ pageSubtitle }}</p>
          </el-popover>
        </div>
        <router-view />
      </main>
    </div>
    <CommandMenu ref="commandMenu" :navigation="navigation" />
  </div>
</template>
