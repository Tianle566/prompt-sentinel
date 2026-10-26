<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorText } from '../api'
import { auth } from '../auth'
import Icon from './Icon.vue'
const route = useRoute(),
  router = useRouter(),
  health = ref(null),
  healthError = ref(''),
  mobileOpen = ref(false),
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
    group: '分析与管理',
    items: [
      { path: '/logs', label: '请求与拦截日志', icon: 'logs' },
      { path: '/evaluation', label: '评测中心', icon: 'chart' },
      { path: '/policy', label: '防护策略', icon: 'settings', admin: true },
    ],
  },
]
async function loadHealth() {
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
  loadHealth()
  timer = setInterval(loadHealth, 60000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>
<template>
  <div class="app-shell">
    <button
      v-if="mobileOpen"
      class="sidebar-backdrop"
      aria-label="关闭导航"
      @click="mobileOpen = false"
    ></button>
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <router-link
        to="/dashboard"
        class="brand"
        aria-label="Prompt Sentinel 首页"
        @click="mobileOpen = false"
        ><span class="brand-mark"><Icon name="shield" :size="28" /></span
        ><span><strong>Prompt Sentinel</strong><small>提示词安全研究平台</small></span></router-link
      >
      <div class="workspace-badge">
        <span class="live-dot"></span> LOCAL RESEARCH <span class="workspace-version">v1.0</span>
      </div>
      <nav aria-label="主导航">
        <div v-for="section in nav" :key="section.group" class="nav-section">
          <div class="nav-label">{{ section.group }}</div>
          <template v-for="item in section.items" :key="item.path"
            ><router-link
              v-if="!item.admin || auth.isAdmin.value"
              :to="item.path"
              class="nav-link"
              @click="mobileOpen = false"
              ><Icon :name="item.icon" /><span>{{ item.label }}</span
              ><Icon class="nav-chevron" name="chevron" :size="14" /></router-link
          ></template>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <div class="local-note">
          <Icon name="lock" :size="17" />
          <div>
            <strong>本地运行，边界清晰</strong>
            <p>模型推理与攻击测试均在本机进行</p>
          </div>
        </div>
        <div class="account">
          <span class="avatar">{{ auth.state.user?.username?.slice(0, 1).toUpperCase() }}</span>
          <div>
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
    <div class="main-shell">
      <header class="topbar">
        <div class="breadcrumb">
          <button
            class="icon-button mobile-menu"
            @click="mobileOpen = !mobileOpen"
            aria-label="打开导航"
            :aria-expanded="mobileOpen"
          >
            <Icon name="menu" /></button
          ><span>{{ route.meta.group }}</span
          ><Icon name="chevron" :size="13" /><strong>{{ route.meta.title }}</strong>
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
                        ? '所有模型已就绪'
                        : '部分模型未就绪'
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
      <main id="main-content" class="main-content">
        <div class="page-heading">
          <div>
            <div class="eyebrow">PROMPT INJECTION DEFENSE</div>
            <h1>{{ route.meta.title }}</h1>
            <p>{{ route.meta.subtitle }}</p>
          </div>
          <div class="page-heading-emblem" aria-hidden="true">
            <Icon name="shield" :size="38" />
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
