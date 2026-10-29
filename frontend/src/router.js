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
            title: '概览',
            subtitle: '指标按当前时间范围统计，趋势按 UTC 自然日汇总。点击统计卡片可查看对应请求。',
            group: '工作空间',
          },
        },
        {
          path: 'chat',
          component: () => import('./pages/Chat.vue'),
          meta: {
            title: '安全对话',
            subtitle:
              '默认开启防护。切换对照模式可查看相同输入的两种响应；从请求日志可带入原始输入重新运行。',
            group: '安全实验室',
          },
        },
        {
          path: 'attack',
          component: () => import('./pages/Attack.vue'),
          meta: {
            title: '安全测试',
            subtitle:
              '选择样本或手动输入进行测试，最多 25 条。攻击成功按预期标记或回复审核判定；错误和未判定结果不计入有效分母。测试仅连接本机目标模型。',
            group: '安全实验室',
          },
        },
        {
          path: 'documents',
          component: () => import('./pages/Documents.vue'),
          meta: {
            title: '文档处理',
            subtitle: '逐段识别不可信指令，验证间接注入防护。',
            group: '安全实验室',
          },
        },
        {
          path: 'logs',
          component: () => import('./pages/Logs.vue'),
          meta: {
            title: '请求日志',
            subtitle:
              '按内容或 #ID 搜索请求。导出遵循当前筛选，最多包含最近 10000 条；执行异常单独标记。',
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
          path: 'accounts',
          component: () => import('./pages/Accounts.vue'),
          meta: {
            title: '成员与权限',
            subtitle:
              '管理员可创建成员、调整权限、停用账号和重置密码。权限或密码变更会使旧登录失效；系统保留最后一个有效管理员。',
            group: '分析与管理',
          },
        },
        {
          path: 'evaluation',
          component: () => import('./pages/Evaluation.vue'),
          meta: {
            title: '评测任务',
            subtitle:
              '新建评测后在后台运行，可以离开此页。每个任务保留配置快照；结果支持下载、对比和归档，取消任务会保留已经完成的结果。',
            group: '分析与管理',
          },
        },
        ...[
          [
            'rules',
            '检测规则',
            '编辑规则后需保存发布。启用状态与表达式都会记录版本，历史规则和策略可恢复。',
            () => import('./pages/Rules.vue'),
          ],
          [
            'samples',
            '测试样本',
            '内置样本只读，自定义样本可新增、编辑或停用。可从请求详情保存样本，再载入安全测试。',
            () => import('./pages/Samples.vue'),
          ],
          [
            'audits',
            '操作审计',
            '记录成员、策略、规则与评测等管理操作。导出遵循当前筛选，最多包含最近 10000 条。',
            () => import('./pages/Audits.vue'),
          ],
          [
            'runtime',
            '系统设置',
            '保存的运行参数用于后续请求和新任务。数据库备份含账号与日志等私有数据，请妥善保管。',
            () => import('./pages/Runtime.vue'),
          ],
        ].map(([path, title, subtitle, component]) => ({
          path,
          component,
          meta: { title, subtitle, group: '分析与管理', admin: true },
        })),
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
router.beforeEach(async (to) => {
  if (!auth.state.checked) await auth.check()
  document.title = `${to.meta.title || '控制台'} · Prompt Sentinel`
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
