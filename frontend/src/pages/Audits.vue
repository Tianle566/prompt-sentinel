<script setup>
import { onMounted, ref } from 'vue'
import { api, dateTime, downloadFile, errorText } from '../api'
const items = ref([]),
  users = ref([]),
  total = ref(0),
  page = ref(1),
  action = ref(''),
  userId = ref(null)
const loading = ref(false),
  exporting = ref(false),
  error = ref(''),
  detail = ref(null)
const labels = {
  'account.create': '新增账号',
  'account.update': '调整账号权限与状态',
  'account.password_reset': '重置账号密码',
  'account.password_change': '修改自己的密码',
  'policy.update': '修改防护策略',
  'policy.restore': '恢复历史策略',
  'rules.update': '修改规则',
  'rules.restore': '恢复规则',
  'sample.create': '新增样本',
  'sample.update': '编辑样本',
  'sample.delete': '移除样本',
  'evaluation.create': '创建评测',
  'evaluation.cancel': '取消评测',
  'evaluation.archive': '归档评测',
  'evaluation.unarchive': '取消归档',
  'runtime.settings': '调整运行设置',
  'target.connection': '更新模型连接',
  'database.backup': '备份数据库',
  'database.backup_download': '下载数据库备份',
  'logs.export': '导出请求日志',
}
function params() {
  return {
    ...(action.value ? { action: action.value } : {}),
    ...(userId.value ? { user_id: userId.value } : {}),
  }
}
async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/admin/audits', { params: { ...params(), page: page.value } })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
async function exportRecords() {
  exporting.value = true
  try {
    await downloadFile('/admin/audits/export.csv', 'admin-audits.csv', params())
  } catch (e) {
    error.value = errorText(e)
  } finally {
    exporting.value = false
  }
}
onMounted(async () => {
  await load()
  try {
    users.value = (await api.get('/users', { params: { page_size: 100 } })).data.items
  } catch (e) {
    error.value = errorText(e)
  }
})
</script>
<template>
  <section class="panel">
    <div class="section-title">
      <div>
        <h2>
          操作记录 <span class="count-pill">{{ total }}</span>
        </h2>
      </div>
      <el-button @click="exportRecords" :loading="exporting">导出审计 CSV</el-button>
    </div>
    <div class="admin-toolbar">
      <el-select v-model="action" placeholder="全部操作" clearable aria-label="筛选管理操作"
        ><el-option
          v-for="(label, key) in labels"
          :key="key"
          :label="label"
          :value="key" /></el-select
      ><el-select v-model="userId" placeholder="全部操作人" clearable aria-label="筛选操作人"
        ><el-option
          v-for="user in users"
          :key="user.id"
          :value="user.id"
          :label="user.username" /></el-select
      ><el-button @click="load(true)" :loading="loading">筛选记录</el-button>
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb20"
      role="alert"
    />
    <TableScroll
      ><el-table :data="items" v-loading="loading" empty-text="暂无管理操作记录">
        <el-table-column label="时间" min-width="185"
          ><template #default="{ row }">{{ dateTime(row.created_at) }}</template></el-table-column
        >
        <el-table-column prop="username" label="操作人" min-width="130" />
        <el-table-column label="操作" min-width="180"
          ><template #default="{ row }">{{
            labels[row.action] || row.action
          }}</template></el-table-column
        >
        <el-table-column prop="target" label="对象" min-width="180" show-overflow-tooltip />
        <el-table-column label="详情" width="85"
          ><template #default="{ row }"
            ><el-button size="small" @click="detail = row">查看</el-button></template
          ></el-table-column
        >
      </el-table></TableScroll
    >
    <el-pagination
      v-if="total > 20"
      v-model:current-page="page"
      :total="total"
      :page-size="20"
      layout="prev, pager, next"
      class="admin-pagination"
      @current-change="load()"
    />
    <el-drawer
      :model-value="!!detail"
      title="操作详情"
      size="min(650px, 100%)"
      @close="detail = null"
    >
      <template v-if="detail"
        ><dl class="request-properties">
          <div>
            <dt>操作</dt>
            <dd>{{ labels[detail.action] || detail.action }}</dd>
          </div>
          <div>
            <dt>操作人</dt>
            <dd>{{ detail.username }}</dd>
          </div>
          <div>
            <dt>对象</dt>
            <dd>{{ detail.target }}</dd>
          </div>
          <div>
            <dt>时间</dt>
            <dd>{{ dateTime(detail.created_at) }}</dd>
          </div>
        </dl>
        <h3 class="detail-section-title">变更内容</h3>
        <pre class="admin-pre">{{ JSON.stringify(detail.details, null, 2) }}</pre>
      </template>
    </el-drawer>
  </section>
</template>
