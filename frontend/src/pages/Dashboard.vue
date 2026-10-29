<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorText, attackName, number, duration, percentage, dateTime } from '../api'
import { requestKinds, statusLabels, requestStatus, periodParams } from '../console'
import Icon from '../components/Icon.vue'
import Chart from '../components/Chart.vue'
import EmptyState from '../components/EmptyState.vue'
const router = useRouter()
const stats = ref(null),
  loading = ref(true),
  error = ref(''),
  range = ref('week'),
  period = ref({}),
  updated = ref('')
async function load() {
  loading.value = true
  error.value = ''
  const params = periodParams(range.value)
  try {
    const { data } = await api.get('/stats', { params })
    stats.value = data
    period.value = params
    updated.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
function logs(status) {
  router.push({
    path: '/logs',
    query: {
      ...period.value,
      ...(status === 'blocked' ? { blocked: 'true' } : status ? { status } : {}),
    },
  })
}
onMounted(load)
const daily = computed(() => {
  const recorded = stats.value?.daily || []
  if (!recorded.length || !period.value.start || !period.value.end) return recorded
  const from = new Date(period.value.start.slice(0, 10)).getTime()
  const until = new Date(period.value.end.slice(0, 10)).getTime()
  const byDate = new Map(recorded.map((row) => [row.date, row]))
  const rows = []
  // Empty days within the queried interval have no recorded requests.
  for (let time = from; time <= until && rows.length < 32; time += 86400000) {
    const date = new Date(time).toISOString().slice(0, 10)
    rows.push(byDate.get(date) || { date, total: 0, blocked: 0 })
  }
  return rows
})
const base = {
  color: ['#b77e5b', '#b86d60', '#8d9276', '#d3bea4', '#9b9385'],
  textStyle: {
    fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif',
    fontSize: 12,
    color: '#736e62',
  },
  tooltip: {
    backgroundColor: '#fff',
    borderColor: '#edebe7',
    textStyle: { color: '#736e62', fontSize: 12 },
  },
}
const trendOption = computed(() => ({
  ...base,
  tooltip: { ...base.tooltip, trigger: 'axis' },
  legend: {
    top: 0,
    right: 0,
    icon: 'circle',
    itemWidth: 7,
    textStyle: { color: '#736e62', fontSize: 12 },
  },
  grid: { left: 36, top: 43, right: 18, bottom: 26 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: daily.value.map((v) => v.date.slice(5)),
    axisLine: { lineStyle: { color: '#efeeeb' } },
    axisTick: { show: false },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: '#f4f3f0', type: 'dashed' } },
  },
  series: [
    {
      name: '全部请求',
      type: 'line',
      smooth: false,
      symbolSize: 6,
      lineStyle: { width: 2 },
      areaStyle: { color: '#b363470c' },
      data: daily.value.map((v) => v.total),
    },
    {
      name: '已拦截',
      type: 'line',
      smooth: false,
      symbolSize: 6,
      lineStyle: { width: 2 },
      data: daily.value.map((v) => v.blocked),
    },
  ],
}))
const attackOption = computed(() => ({
  ...base,
  tooltip: { ...base.tooltip, formatter: '{b}<br/>{c} 次 · {d}%' },
  legend: {
    orient: 'vertical',
    right: 8,
    top: 'middle',
    icon: 'circle',
    itemWidth: 7,
    textStyle: { color: '#736e62', fontSize: 12 },
  },
  series: [
    {
      type: 'pie',
      radius: ['58%', '77%'],
      center: ['32%', '50%'],
      label: { show: false },
      itemStyle: { borderWidth: 3, borderColor: '#fff', borderRadius: 2 },
      data: (stats.value?.attack_types || []).map((v) => ({ ...v, name: attackName(v.name) })),
    },
  ],
}))
const layersOption = computed(() => ({
  ...base,
  grid: { left: 28, right: 14, top: 20, bottom: 26 },
  xAxis: {
    type: 'category',
    data: stats.value?.layers.map((v) => v.name),
    axisLine: { lineStyle: { color: '#efeeeb' } },
    axisTick: { show: false },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: '#f4f3f0', type: 'dashed' } },
  },
  series: [
    {
      type: 'bar',
      barMaxWidth: 25,
      itemStyle: { color: '#bd9a89', borderRadius: [3, 3, 0, 0] },
      data: stats.value?.layers.map((v) => v.value),
    },
  ],
}))
</script>
<template>
  <div class="dashboard operational-dashboard">
    <div class="workspace-toolbar">
      <div class="toolbar-status">
        <span class="live-dot"></span><span>请求监控</span
        ><small v-if="updated">更新于 {{ updated }}</small>
      </div>
      <div class="toolbar-actions">
        <el-select
          v-model="range"
          aria-label="统计时间范围"
          class="period-select"
          :disabled="loading"
          @change="load"
        >
          <el-option label="最近 24 小时" value="day" /><el-option label="最近 7 天" value="week" />
          <el-option label="最近 30 天" value="month" /><el-option label="全部时间" value="all" />
        </el-select>
        <el-button :loading="loading" @click="load" aria-label="刷新概览"
          ><Icon name="refresh" :size="15"
        /></el-button>
        <el-button type="primary" @click="router.push('/chat')"
          ><Icon name="chat" :size="15" />新建对话</el-button
        >
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="mb20" />
    <div v-loading="loading" class="operational-metrics">
      <button class="operational-metric" @click="logs()">
        <span>请求总数<Icon name="arrow" :size="14" /></span
        ><strong>{{ number(stats?.total_requests) }}</strong
        ><small>当前时间范围</small>
      </button>
      <button class="operational-metric" @click="logs('blocked')">
        <span>已拦截<Icon name="arrow" :size="14" /></span
        ><strong>{{ number(stats?.blocked_requests) }}</strong
        ><small
          ><b class="metric-red">{{ percentage(stats?.block_rate) }}</b> 请求拦截率</small
        >
      </button>
      <div class="operational-metric">
        <span>平均响应时间<Icon name="clock" :size="15" /></span
        ><strong class="metric-time">{{ duration(stats?.average_latency_ms) }}</strong
        ><small>检测与模型生成</small>
      </div>
      <button class="operational-metric" @click="logs('error')">
        <span>执行异常<Icon name="arrow" :size="14" /></span
        ><strong :class="{ 'metric-amber': stats?.error_requests }">{{
          number(stats?.error_requests)
        }}</strong
        ><small>{{ stats?.error_requests ? '查看异常记录' : '无异常记录' }}</small>
      </button>
    </div>
    <div class="operational-chart-grid">
      <section class="panel traffic-chart">
        <div class="section-title">
          <h2>请求趋势</h2>
          <span class="subtle-label">UTC · 按日</span>
        </div>
        <Chart
          v-if="stats?.daily?.length"
          :option="trendOption"
          label="请求与拦截趋势"
          height="245px"
        />
        <EmptyState v-else title="暂无请求" icon="chart" text="" />
      </section>
      <section class="panel">
        <div class="section-title">
          <h2>拦截分布</h2>
          <router-link
            :to="{ path: '/logs', query: { ...period, blocked: 'true' } }"
            class="text-action"
            >查看记录<Icon name="arrow" :size="13"
          /></router-link>
        </div>
        <Chart
          v-if="stats?.attack_types?.length"
          :option="attackOption"
          label="拦截类型分布"
          height="245px"
        />
        <EmptyState v-else title="暂无拦截" icon="shield" text="" />
      </section>
    </div>
    <div class="operational-bottom-grid">
      <section class="panel recent-panel">
        <div class="section-title">
          <h2>最近请求</h2>
          <router-link :to="{ path: '/logs', query: period }" class="text-action"
            >全部记录<Icon name="arrow" :size="13"
          /></router-link>
        </div>
        <TableScroll
          ><el-table
            :data="stats?.recent_requests || []"
            class="compact-table clickable-table"
            @row-click="
              (row) => router.push({ path: '/logs', query: { ...period, request: row.id } })
            "
          >
            <template #empty><EmptyState title="暂无请求" icon="logs" text="" /></template>
            <el-table-column label="请求" min-width="220"
              ><template #default="{ row }"
                ><div class="request-cell">
                  <span class="mono muted">#{{ row.id }}</span
                  ><span class="truncate">{{ row.text }}</span>
                </div></template
              ></el-table-column
            >
            <el-table-column label="用途" width="105"
              ><template #default="{ row }">{{
                requestKinds[row.kind] || row.kind
              }}</template></el-table-column
            >
            <el-table-column label="状态" width="100"
              ><template #default="{ row }"
                ><span class="status-badge" :class="requestStatus(row)">{{
                  statusLabels[requestStatus(row)]
                }}</span></template
              ></el-table-column
            >
            <el-table-column label="响应" width="85"
              ><template #default="{ row }">{{
                duration(row.latency_ms)
              }}</template></el-table-column
            >
            <el-table-column label="时间" width="145"
              ><template #default="{ row }"
                ><span class="subtle-label">{{ dateTime(row.created_at) }}</span></template
              ></el-table-column
            >
          </el-table></TableScroll
        >
      </section>
      <section class="panel defense-summary">
        <div class="section-title">
          <h2>防护表现</h2>
          <el-popover trigger="click" :width="290"
            ><template #reference
              ><button class="icon-button" aria-label="防护指标说明">
                <Icon name="info" :size="16" /></button
            ></template>
            <p class="context-help">
              拦截成功率仅统计开启防护的有效攻击测试。执行错误及未判定结果不计入分母；它不代表全部请求的准确率。
            </p></el-popover
          >
        </div>
        <div class="interception-value">
          <span>攻击拦截成功率</span
          ><strong>{{ percentage(stats?.attack_interception?.rate) }}</strong
          ><small
            >{{ number(stats?.attack_interception?.intercepted) }} /
            {{ number(stats?.attack_interception?.evaluated) }} 有效测试</small
          >
        </div>
        <Chart
          v-if="stats?.total_requests"
          :option="layersOption"
          label="各层命中次数"
          height="140px"
        />
        <router-link to="/attack" class="text-action defense-test-link"
          >运行安全测试<Icon name="arrow" :size="14"
        /></router-link>
      </section>
    </div>
  </div>
</template>
