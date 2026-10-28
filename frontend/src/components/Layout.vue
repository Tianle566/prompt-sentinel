<script setup>
import { computed, nextTick, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorText } from '../api'
import { auth } from '../auth'
import Icon from './Icon.vue'
const route = useRoute(),
  router = useRouter(),
  health = ref(null),
  healthError = ref(''),
  mobileOpen = ref(false),
  collapsed = ref(false),
  isMobile = ref(false),
  sidebar = ref(null),
  menuButton = ref(null),
  refreshing = ref(false)
const nav = [
  { group: '工作空间', items: [{ path: '/dashboard', label: '安全概览', icon: 'dashboard' }] },
  {
    group: '安全实验室',
    items: [
      { path: '/chat', label: '对话演示', icon: 'chat' },
      { path: '/attack', label: '攻击测试台', icon: 'attack' },
      { path: '/documents', label: '文档摘要', icon: 'document' },
    ],
  },
  {
    group: '分析与评测',
    items: [
      { path: '/logs', label: '请求与拦截日志', icon: 'logs' },
      { path: '/evaluation', label: '评测中心', icon: 'chart' },
    ],
  },
  {
    group: '系统管理',
    items: [
      { path: '/policy', label: '防护策略', icon: 'settings', admin: true },
      { path: '/accounts', label: '账号管理', icon: 'user' },
      { path: '/rules', label: '规则与策略历史', icon: 'shield', admin: true },
      { path: '/samples', label: '攻击样本管理', icon: 'attack', admin: true },
      { path: '/audits', label: '管理操作审计', icon: 'logs', admin: true },
      { path: '/runtime', label: '运行维护', icon: 'settings', admin: true },
    ],
  },
]
const navigation = computed(() =>
  nav
    .map((section) => ({
      ...section,
      group: section.group === '系统管理' && !auth.isAdmin.value ? '个人设置' : section.group,
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
    document.title = `${title || '安全研究台'} · Prompt Sentinel`
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
  timer = setInterval(loadHealth, 60000)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  media?.removeEventListener('change', screenChanged)
  if (mobileOpen.value) document.body.style.overflow = bodyOverflow
})
</script>
<template>
  <div class="app-shell" :class="{ 'nav-collapsed': collapsed }">
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
          ><strong>Prompt Sentinel</strong><small>提示词安全研究平台</small></span
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
      <div class="workspace-badge">
        <Icon name="lock" :size="13" /><span>本地研究工作空间</span
        ><span class="workspace-version">v1.0</span>
      </div>
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
        <div class="local-note">
          <Icon name="lock" :size="17" />
          <div>
            <strong>本地运行，边界清晰</strong>
            <p>检测过程可记录，实验结果可追溯</p>
          </div>
        </div>
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
                        ? '模型文件与服务可用'
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
                <p class="helper">
                  设备策略：{{ health?.device || '—' }} · 详情见后端启动日志
                </p></template
              >
            </div></el-popover
          ><span class="topbar-divider"></span
          ><span class="topbar-role">{{ auth.isAdmin.value ? '管理员' : '研究用户' }}</span>
        </div>
      </header>
      <main id="main-content" class="main-content" tabindex="-1">
        <div class="page-heading">
          <div>
            <div class="eyebrow">{{ currentGroup }} <span>/ PROMPT SENTINEL</span></div>
            <h1>{{ pageTitle }}</h1>
            <p>{{ pageSubtitle }}</p>
          </div>
          <div class="page-context">
            <Icon name="shield" :size="17" /><span>安全研究工作台</span>
          </div>
        </div>
        <router-view />
      </main>
      <footer class="main-footer">
        <span
          >Prompt Sentinel
          <span class="footer-dot">·</span> 面向大语言模型应用的提示词注入检测与多层防护</span
        ><span>本地研究环境</span>
      </footer>
    </div>
  </div>
</template>
