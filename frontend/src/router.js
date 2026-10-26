import { createRouter, createWebHistory } from 'vue-router'
import { auth } from './auth'
import Layout from './components/Layout.vue'
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('./pages/Login.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      component: Layout,
      children: [
        { path: '', redirect: '/dashboard' },
        {
          path: 'dashboard',
          component: () => import('./pages/Dashboard.vue'),
          meta: {
            title: '安全概览',
            subtitle: '观察流量、理解威胁，让每一层防护都有据可查。',
            group: '工作空间',
          },
        },
        {
          path: 'chat',
          component: () => import('./pages/Chat.vue'),
          meta: {
            title: '对话演示',
            subtitle: '一条输入，两条通道。直观验证多层防护的效果。',
            group: '安全实验室',
          },
        },
        {
          path: 'attack',
          component: () => import('./pages/Attack.vue'),
          meta: {
            title: '攻击测试台',
            subtitle: '从本地样本到自主构造，检验提示词注入防线。',
            group: '安全实验室',
          },
        },
        {
          path: 'documents',
          component: () => import('./pages/Documents.vue'),
          meta: {
            title: '文档摘要',
            subtitle: '逐段识别不可信指令，验证间接注入防护。',
            group: '安全实验室',
          },
        },
        {
          path: 'logs',
          component: () => import('./pages/Logs.vue'),
          meta: {
            title: '请求与拦截日志',
            subtitle: '回溯每次请求的输入、决策与各层检测依据。',
            group: '分析与管理',
          },
        },
        {
          path: 'policy',
          component: () => import('./pages/Policy.vue'),
          meta: {
            title: '防护策略',
            subtitle: '调整五层防线与融合策略，保存后立即应用。',
            group: '分析与管理',
            admin: true,
          },
        },
        {
          path: 'evaluation',
          component: () => import('./pages/Evaluation.vue'),
          meta: {
            title: '评测中心',
            subtitle: '以可复现的实验，衡量检测性能、防御效果与开销。',
            group: '分析与管理',
          },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
router.beforeEach(async (to) => {
  if (!auth.state.checked) await auth.check()
  document.title = `${to.meta.title || '安全研究台'} · Prompt Sentinel`
  if (!to.meta.public && !auth.state.user)
    return { path: '/login', query: { redirect: to.fullPath } }
  if (to.meta.public && auth.state.user) return '/dashboard'
  if (to.meta.admin && !auth.isAdmin.value) return '/dashboard'
})
window.addEventListener('sentinel:expired', () => {
  auth.logout()
  router.replace({ path: '/login', query: { expired: '1' } })
})
export default router
