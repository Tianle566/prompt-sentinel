<script setup>
import { ref, reactive, watch, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorText, attackTypes, attackName, duration, dateTime, downloadFile } from '../api'
import { auth } from '../auth'
import { requestKinds, statusLabels, requestStatus } from '../console'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import PipelineResult from '../components/PipelineResult.vue'
import LayerResults from '../components/LayerResults.vue'
const route = useRoute(),
  router = useRouter()
const filters = reactive({
  q: '',
  status: '',
  kind: '',
  attack_type: '',
  layer: '',
  dates: null,
  user_id: null,
  blocked: '',
})
const appliedParams = ref({})
const moreCount = computed(
  () =>
    ['user_id', 'attack_type', 'layer', 'blocked'].filter(
      (key) => filters[key] !== '' && filters[key] != null
    ).length
)
const availableTypes = ref(Object.keys(attackTypes)),
  users = ref([]),
  rows = ref([]),
  total = ref(0)
const page = ref(1),
  pageSize = ref(20),
  loading = ref(false),
  exporting = ref(false),
  error = ref('')
const drawer = ref(false),
  detail = ref(null),
  detailLoading = ref(false),
  detailError = ref(''),
  detailTab = ref('overview')
let loadSequence = 0,
  detailSequence = 0
const scalar = (value) => (typeof value === 'string' ? value : '')
function params() {
  const value = {}
  for (const name of ['q', 'status', 'kind', 'attack_type', 'layer', 'user_id']) {
    if (filters[name]) value[name] = filters[name]
  }
  if (filters.dates?.length === 2) {
    value.start = new Date(filters.dates[0]).toISOString()
    value.end = new Date(filters.dates[1]).toISOString()
  }
  if (filters.blocked !== '') value.blocked = filters.blocked
  return value
}
function readQuery(query) {
  for (const key of ['q', 'status', 'kind', 'attack_type', 'layer'])
    filters[key] = scalar(query[key])
  filters.user_id = /^\d+$/.test(scalar(query.user_id)) ? Number(query.user_id) : null
  filters.blocked = ['true', 'false'].includes(query.blocked) ? query.blocked : ''
  filters.dates =
    query.start &&
    query.end &&
    Number.isFinite(Date.parse(query.start)) &&
    Number.isFinite(Date.parse(query.end))
      ? [new Date(query.start), new Date(query.end)]
      : null
  page.value = Math.max(1, Math.min(100000, Number(query.page) || 1))
  pageSize.value = [10, 20, 50].includes(Number(query.page_size)) ? Number(query.page_size) : 20
}
async function load() {
  const current = ++loadSequence
  loading.value = true
  error.value = ''
  try {
    const currentParams = params()
    const { data } = await api.get('/logs', {
      params: { page: page.value, page_size: pageSize.value, ...currentParams },
    })
    if (current !== loadSequence) return
    rows.value = data.items
    total.value = data.total
    appliedParams.value = currentParams
    availableTypes.value = [
      ...new Set([...Object.keys(attackTypes), ...(data.attack_types || [])]),
    ].filter(Boolean)
  } catch (e) {
    if (current === loadSequence) error.value = errorText(e)
  } finally {
    if (current === loadSequence) loading.value = false
  }
}
function apply(reset = true) {
  if (reset) page.value = 1
  const query = { ...params(), page: String(page.value), page_size: String(pageSize.value) }
  if (JSON.stringify(route.query) === JSON.stringify(query)) load()
  else router.push({ path: '/logs', query })
}
function clear() {
  Object.assign(filters, {
    q: '',
    status: '',
    kind: '',
    attack_type: '',
    layer: '',
    dates: null,
    user_id: null,
    blocked: '',
  })
  apply()
}
async function exportLogs() {
  exporting.value = true
  try {
    await downloadFile('/logs/export.csv', 'request-logs.csv', appliedParams.value)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    exporting.value = false
  }
}
async function fetchDetail(id) {
  const current = ++detailSequence
  drawer.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  detailTab.value = 'overview'
  try {
    const { data } = await api.get(`/logs/${encodeURIComponent(id)}`)
    if (current === detailSequence) detail.value = data
  } catch (e) {
    if (current === detailSequence) detailError.value = errorText(e)
  } finally {
    if (current === detailSequence) detailLoading.value = false
  }
}
function openDetail(row) {
  router.push({ path: '/logs', query: { ...route.query, request: String(row.id) } })
}
function closeDetail(open) {
  if (open) return
  const { request, ...query } = route.query
  router.replace({ path: '/logs', query })
}
async function copyLink() {
  try {
    await navigator.clipboard.writeText(location.href)
    ElMessage.success('链接已复制')
  } catch {
    ElMessage.error('复制失败，请从地址栏复制链接')
  }
}
function replay() {
  router.push({
    path: detail.value.kind === 'document' ? '/documents' : '/chat',
    query: { from: detail.value.id },
  })
}
watch(
  () => route.query,
  (query, previous) => {
    const withoutRequest = ({ request, ...rest } = {}) => JSON.stringify(rest)
    if (!previous || withoutRequest(query) !== withoutRequest(previous)) {
      readQuery(query)
      load()
    }
    if (query.request && (!previous || query.request !== previous.request))
      fetchDetail(query.request)
    if (!query.request) {
      detailSequence++
      drawer.value = false
    }
  },
  { immediate: true }
)
onMounted(async () => {
  if (auth.isAdmin.value) {
    try {
      users.value = (await api.get('/users', { params: { page_size: 100 } })).data.items
    } catch (e) {
      error.value = errorText(e)
    }
  }
})
</script>
<template>
  <section class="panel logs-panel operational-logs">
    <div class="section-title log-topline">
      <el-segmented
        v-model="filters.status"
        :options="[
          { label: '全部请求', value: '' },
          { label: '已拦截', value: 'blocked' },
          { label: '执行异常', value: 'error' },
          { label: '已放行', value: 'allowed' },
        ]"
        aria-label="请求状态"
        @change="apply()"
      />
      <div class="toolbar-actions">
        <span class="subtle-label">{{ total }} 条</span
        ><el-button :loading="exporting" :disabled="loading || !total" @click="exportLogs"
          ><Icon name="download" :size="14" />导出</el-button
        ><el-button :loading="loading" @click="load" aria-label="刷新请求日志"
          ><Icon name="refresh" :size="15"
        /></el-button>
      </div>
    </div>
    <form class="request-filters" @submit.prevent="apply()">
      <el-input
        v-model="filters.q"
        placeholder="搜索内容或 #ID"
        maxlength="300"
        clearable
        aria-label="搜索请求"
        class="request-search"
        @clear="apply()"
      />
      <el-select
        v-model="filters.kind"
        placeholder="全部用途"
        clearable
        aria-label="筛选请求用途"
        @change="apply()"
        ><el-option v-for="(label, key) in requestKinds" :key="key" :value="key" :label="label"
      /></el-select>
      <el-date-picker
        v-model="filters.dates"
        type="datetimerange"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        range-separator="—"
        :default-time="[new Date(2000, 1, 1, 0, 0, 0), new Date(2000, 1, 1, 23, 59, 59)]"
        aria-label="日志时间范围"
        @change="apply()"
      />
      <el-popover placement="bottom-end" :width="300" trigger="click">
        <template #reference
          ><el-button
            >更多筛选<span v-if="moreCount" class="count-pill">{{ moreCount }}</span></el-button
          ></template
        >
        <el-form label-position="top" class="more-filters">
          <el-form-item v-if="auth.isAdmin.value" label="成员"
            ><el-select
              v-model="filters.user_id"
              placeholder="全部成员"
              clearable
              filterable
              aria-label="筛选日志用户"
              @change="apply()"
              ><el-option
                v-for="user in users"
                :key="user.id"
                :value="user.id"
                :label="user.username" /></el-select
          ></el-form-item>
          <el-form-item label="风险类型"
            ><el-select
              v-model="filters.attack_type"
              placeholder="全部风险类型"
              clearable
              aria-label="筛选攻击类型"
              @change="apply()"
              ><el-option
                v-for="value in availableTypes"
                :key="value"
                :value="value"
                :label="attackName(value)" /></el-select
          ></el-form-item>
          <el-form-item label="命中层"
            ><el-select
              v-model="filters.layer"
              placeholder="全部命中层"
              clearable
              aria-label="筛选命中层"
              @change="apply()"
              ><el-option
                v-for="layer in ['L1', 'L2', 'L3', 'L4', 'L5']"
                :key="layer"
                :value="layer"
                :label="layer" /></el-select
          ></el-form-item>
          <el-form-item label="实际处置"
            ><el-select
              v-model="filters.blocked"
              placeholder="全部处置"
              clearable
              aria-label="筛选实际处置"
              @change="apply()"
              ><el-option value="true" label="拦截（含保守拦截）" /><el-option
                value="false"
                label="未拦截" /></el-select
          ></el-form-item>
        </el-form>
      </el-popover>
      <el-button native-type="submit" :loading="loading">搜索</el-button
      ><el-button text @click="clear">清除</el-button>
    </form>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="mb20"
      role="alert"
    />
    <TableScroll
      ><el-table
        :data="rows"
        v-loading="loading"
        row-key="id"
        class="log-table compact-table clickable-table"
        @row-click="openDetail"
      >
        <template #empty
          ><EmptyState title="没有匹配的请求" text="" icon="logs"
            ><el-button text type="primary" @click="clear">清除筛选</el-button></EmptyState
          ></template
        >
        <el-table-column label="请求" min-width="280"
          ><template #default="{ row }"
            ><div class="request-cell">
              <span class="mono muted">#{{ row.id }}</span
              ><span class="truncate">{{ row.text }}</span>
            </div>
            <small class="table-subtitle"
              >{{ requestKinds[row.kind] || row.kind }}<span class="cell-separator">·</span
              >{{ row.protected ? '防护开启' : '防护关闭' }}</small
            ></template
          ></el-table-column
        >
        <el-table-column label="状态" width="105"
          ><template #default="{ row }"
            ><span class="status-badge" :class="requestStatus(row)">{{
              statusLabels[requestStatus(row)]
            }}</span></template
          ></el-table-column
        >
        <el-table-column label="风险类型" width="125"
          ><template #default="{ row }">{{
            attackName(row.attack_type)
          }}</template></el-table-column
        >
        <el-table-column label="命中层" width="115"
          ><template #default="{ row }"
            ><div class="hit-tags">
              <span v-for="layer in row.hit_layers" :key="layer">{{ layer }}</span
              ><span v-if="!row.hit_layers?.length" class="muted">—</span>
            </div></template
          ></el-table-column
        >
        <el-table-column
          v-if="auth.isAdmin.value"
          label="成员"
          prop="username"
          width="110"
          show-overflow-tooltip
        />
        <el-table-column label="响应时间" width="95"
          ><template #default="{ row }"
            ><span class="mono">{{ duration(row.latency_ms) }}</span></template
          ></el-table-column
        >
        <el-table-column label="时间" width="160"
          ><template #default="{ row }"
            ><span class="table-date">{{ dateTime(row.created_at) }}</span></template
          ></el-table-column
        >
        <el-table-column label="" width="64" fixed="right"
          ><template #default="{ row }"
            ><button
              class="icon-button"
              :aria-label="`查看请求 ${row.id}`"
              @click.stop="openDetail(row)"
            >
              <Icon name="chevron" :size="16" /></button></template
        ></el-table-column> </el-table
    ></TableScroll>
    <div class="pagination-wrap">
      <span>共 {{ total }} 条</span
      ><el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="sizes, prev, pager, next"
        @current-change="apply(false)"
        @size-change="apply()"
      />
    </div>
    <el-drawer
      v-model="drawer"
      :title="detail ? `请求 #${detail.id}` : '请求详情'"
      size="min(760px, 100%)"
      @update:model-value="closeDetail"
    >
      <div v-loading="detailLoading" class="detail-body">
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <template v-if="detail">
          <div class="detail-actionbar">
            <span class="status-badge" :class="requestStatus(detail)">{{
              statusLabels[requestStatus(detail)]
            }}</span
            ><span class="subtle-label">{{ dateTime(detail.created_at) }}</span>
            <div class="toolbar-actions">
              <el-button size="small" @click="copyLink">复制链接</el-button
              ><el-button type="primary" size="small" @click="replay">重新测试</el-button>
            </div>
          </div>
          <el-tabs v-model="detailTab"
            ><el-tab-pane label="概览" name="overview">
              <dl class="request-properties">
                <div>
                  <dt>用途</dt>
                  <dd>{{ requestKinds[detail.kind] || detail.kind }}</dd>
                </div>
                <div>
                  <dt>防护</dt>
                  <dd>{{ detail.protected ? '开启' : '关闭' }}</dd>
                </div>
                <div>
                  <dt>响应时间</dt>
                  <dd>{{ duration(detail.latency_ms) }}</dd>
                </div>
                <div>
                  <dt>风险类型</dt>
                  <dd>{{ attackName(detail.attack_type) }}</dd>
                </div>
              </dl>
              <div class="detail-section-title">
                <h3>输入</h3>
                <el-button
                  v-if="auth.isAdmin.value"
                  text
                  size="small"
                  @click="router.push({ path: '/samples', query: { from: detail.id } })"
                  >保存为样本</el-button
                >
              </div>
              <div class="input-preview">{{ detail.text }}</div>
              <h3 class="detail-section-title">处理结果</h3>
              <PipelineResult :result="detail.result" />
              <details v-if="detail.result.document" class="result-details">
                <summary>文档段落</summary>
                <el-collapse
                  ><el-collapse-item
                    v-for="paragraph in detail.result.document.paragraphs"
                    :key="paragraph.index"
                    :title="`段落 ${paragraph.index + 1} · ${!paragraph.detection.reliable ? '检测异常' : paragraph.is_attack ? '疑似注入' : '未检出风险'}`"
                    ><p class="input-preview">{{ paragraph.text }}</p>
                    <LayerResults :detection="paragraph.detection" /></el-collapse-item
                ></el-collapse>
              </details> </el-tab-pane
            ><el-tab-pane label="原始数据" name="raw">
              <pre class="admin-pre">{{ JSON.stringify(detail.result, null, 2) }}</pre>
            </el-tab-pane></el-tabs
          >
        </template>
      </div>
    </el-drawer>
  </section>
</template>
