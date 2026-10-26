<script setup>
import { ref, reactive, onMounted } from 'vue'
import { api, errorText, attackTypes, attackName, duration, dateTime } from '../api'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import PipelineResult from '../components/PipelineResult.vue'
import LayerResults from '../components/LayerResults.vue'
const availableTypes = ref(Object.keys(attackTypes))
const filters = reactive({ attack_type: '', layer: '', dates: null }),
  rows = ref([]),
  total = ref(0),
  page = ref(1),
  pageSize = ref(10),
  loading = ref(false),
  error = ref(''),
  drawer = ref(false),
  detail = ref(null),
  detailLoading = ref(false),
  detailError = ref('')
async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filters.attack_type) params.attack_type = filters.attack_type
    if (filters.layer) params.layer = filters.layer
    if (filters.dates?.length === 2) {
      params.start = new Date(filters.dates[0]).toISOString()
      params.end = new Date(filters.dates[1]).toISOString()
    }
    const { data } = await api.get('/logs', { params })
    rows.value = data.items
    total.value = data.total
    availableTypes.value = [
      ...new Set([
        ...Object.keys(attackTypes),
        ...(data.attack_types || data.items.map((row) => row.attack_type)),
      ]),
    ]
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
function clear() {
  filters.attack_type = ''
  filters.layer = ''
  filters.dates = null
  load(true)
}
async function openDetail(row) {
  drawer.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    detail.value = (await api.get(`/logs/${row.id}`)).data
  } catch (e) {
    detailError.value = errorText(e)
  } finally {
    detailLoading.value = false
  }
}
onMounted(() => load())
</script>
<template>
  <section class="panel logs-panel">
    <div class="section-title">
      <div>
        <h2>
          全部请求记录 <span class="count-pill">{{ total }}</span>
        </h2>
        <p>按账号权限展示记录，点击详情查看完整检测依据</p>
      </div>
      <el-button :loading="loading" @click="load()"
        ><Icon name="refresh" :size="15" />刷新</el-button
      >
    </div>
    <div class="log-filters">
      <el-date-picker
        v-model="filters.dates"
        type="datetimerange"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        range-separator="至"
        :default-time="[new Date(2000, 1, 1, 0, 0, 0), new Date(2000, 1, 1, 23, 59, 59)]"
        aria-label="日志时间范围"
      /><el-select
        v-model="filters.attack_type"
        placeholder="全部攻击类型"
        clearable
        aria-label="筛选攻击类型"
        ><el-option
          v-for="value in availableTypes"
          :key="value"
          :value="value"
          :label="attackName(value)" /></el-select
      ><el-select v-model="filters.layer" placeholder="全部命中层" clearable aria-label="筛选命中层"
        ><el-option
          v-for="layer in ['L1', 'L2', 'L3', 'L4', 'L5']"
          :key="layer"
          :value="layer"
          :label="layer" /></el-select
      ><el-button type="primary" @click="load(true)" :loading="loading">筛选</el-button
      ><el-button @click="clear">重置</el-button>
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="mb20"
      role="alert"
    /><el-table
      :data="rows"
      v-loading="loading"
      class="log-table"
      :row-key="(row) => row.id"
      @row-click="openDetail"
      ><template #empty
        ><EmptyState
          title="没有符合条件的记录"
          text="尝试调整筛选条件，或前往对话演示产生一条请求。"
          icon="logs" /></template
      ><el-table-column label="时间" width="175"
        ><template #default="{ row }"
          ><span class="table-date">{{ dateTime(row.created_at) }}</span
          ><small class="table-subtitle"
            >#{{ row.id }} ·
            {{
              {
                chat: '对话',
                compare: '对照实验',
                attack: '攻击测试',
                document: '文档摘要',
                detect: '检测',
              }[row.kind] || row.kind
            }}</small
          ></template
        ></el-table-column
      ><el-table-column label="输入内容" min-width="225"
        ><template #default="{ row }"
          ><p class="log-text">{{ row.text }}</p>
          <small class="table-subtitle">{{
            row.protected ? '已启用防护' : '无防护通道'
          }}</small></template
        ></el-table-column
      ><el-table-column label="攻击类型" width="140"
        ><template #default="{ row }">{{ attackName(row.attack_type) }}</template></el-table-column
      ><el-table-column label="决策" width="95"
        ><template #default="{ row }"
          ><el-tag :type="row.blocked ? 'danger' : 'success'" size="small">{{
            row.blocked ? '已拦截' : '已放行'
          }}</el-tag></template
        ></el-table-column
      ><el-table-column label="命中层" width="125"
        ><template #default="{ row }"
          ><div class="hit-tags">
            <span v-for="layer in row.hit_layers" :key="layer">{{ layer }}</span
            ><span v-if="!row.hit_layers?.length" class="muted">—</span>
          </div></template
        ></el-table-column
      ><el-table-column label="总延迟" width="100"
        ><template #default="{ row }">{{ duration(row.latency_ms) }}</template></el-table-column
      ><el-table-column label="操作" width="75" fixed="right"
        ><template #default="{ row }"
          ><el-button text type="primary" @click.stop="openDetail(row)">详情</el-button></template
        ></el-table-column
      ></el-table
    >
    <div class="pagination-wrap">
      <span>共 {{ total }} 条记录</span
      ><el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="sizes, prev, pager, next"
        @current-change="load()"
        @size-change="load(true)"
      />
    </div>
    <el-drawer v-model="drawer" title="请求检测详情" size="min(680px, 100%)"
      ><div v-loading="detailLoading" class="detail-body">
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" /><template
          v-if="detail"
          ><div class="detail-meta">
            <span>#{{ detail.id }} · {{ dateTime(detail.created_at) }}</span
            ><el-tag :type="detail.protected ? 'success' : 'info'" size="small">{{
              detail.protected ? '有防护' : '无防护'
            }}</el-tag>
          </div>
          <div class="detail-label">原始输入</div>
          <div class="input-preview">{{ detail.text }}</div>
          <div class="detail-label">决策与模型输出</div>
          <PipelineResult :result="detail.result" />
          <div v-if="detail.result.document" class="mt20">
            <h3>文档逐段检测记录</h3>
            <el-collapse
              ><el-collapse-item
                v-for="paragraph in detail.result.document.paragraphs"
                :key="paragraph.index"
                :title="`段落 ${paragraph.index + 1} · ${!paragraph.detection.reliable ? '检测异常' : paragraph.is_attack ? '疑似注入' : '未检出风险'}`"
                ><p class="input-preview">{{ paragraph.text }}</p>
                <LayerResults :detection="paragraph.detection" /></el-collapse-item
            ></el-collapse></div
        ></template></div
    ></el-drawer>
  </section>
</template>
