<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, errorText, attackName, number, duration, percentage } from '../api'
import Icon from '../components/Icon.vue'
import Chart from '../components/Chart.vue'
import EmptyState from '../components/EmptyState.vue'
const stats = ref(null),
  loading = ref(true),
  error = ref('')
const defenseLayers = ['规则过滤', '语义分类', '输入审核', '提示加固', '输出检查']
async function load() {
  loading.value = true
  error.value = ''
  try {
    stats.value = (await api.get('/stats')).data
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)
const palette = ['#147d68', '#6ca990', '#c0cba0', '#bf965d', '#648897', '#c5d8d3']
const chartBase = {
  color: palette,
  textStyle: {
    fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif',
    fontSize: 12,
    color: '#61756b',
  },
  tooltip: {
    trigger: 'item',
    backgroundColor: '#fff',
    borderColor: '#e7ebe6',
    textStyle: { color: '#233936' },
  },
}
const attackOption = computed(() => ({
  ...chartBase,
  tooltip: { ...chartBase.tooltip, formatter: '{b}<br/>{c} 次 · {d}%' },
  legend: { bottom: 0, icon: 'circle', textStyle: { color: '#61756b', fontSize: 12 } },
  series: [
    {
      type: 'pie',
      radius: ['48%', '71%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 5, borderColor: '#fff', borderWidth: 3 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 15, fontWeight: 600 } },
      data: (stats.value?.attack_types || []).map((v) => ({ ...v, name: attackName(v.name) })),
    },
  ],
}))
const trendOption = computed(() => ({
  ...chartBase,
  tooltip: { trigger: 'axis' },
  legend: { top: 0, right: 0, icon: 'circle', itemWidth: 9, textStyle: { color: '#7b8785' } },
  grid: { left: 40, top: 50, right: 20, bottom: 30 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: stats.value?.daily.map((v) => v.date.slice(5)) || [],
    axisLine: { lineStyle: { color: '#e6ebe7' } },
    axisTick: { show: false },
    axisLabel: { color: '#82908a' },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLabel: { color: '#82908a' },
    splitLine: { lineStyle: { color: '#eff2ed', type: 'dashed' } },
  },
  series: [
    {
      name: '全部请求',
      type: 'line',
      smooth: true,
      symbolSize: 6,
      lineStyle: { width: 2 },
      itemStyle: { color: '#a2b5c2' },
      data: stats.value?.daily.map((v) => v.total),
    },
    {
      name: '已拦截',
      type: 'line',
      smooth: true,
      symbolSize: 7,
      lineStyle: { width: 3 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: '#187a7035' },
            { offset: 1, color: '#187a7000' },
          ],
        },
      },
      data: stats.value?.daily.map((v) => v.blocked),
    },
  ],
}))
const layersOption = computed(() => ({
  ...chartBase,
  grid: { left: 40, right: 20, top: 20, bottom: 30 },
  xAxis: {
    type: 'category',
    data: stats.value?.layers.map((v) => v.name),
    axisLine: { lineStyle: { color: '#e5ebe6' } },
    axisTick: { show: false },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: '#eff2ed', type: 'dashed' } },
  },
  series: [
    {
      type: 'bar',
      barMaxWidth: 35,
      itemStyle: { color: '#6b9e90', borderRadius: [5, 5, 0, 0] },
      data: stats.value?.layers.map((v) => v.value),
    },
  ],
}))
const latencyOption = computed(() => ({
  ...chartBase,
  tooltip: { trigger: 'axis', valueFormatter: (v) => duration(v) },
  grid: { left: 40, right: 40, top: 12, bottom: 25 },
  xAxis: {
    type: 'value',
    name: 'ms',
    axisLabel: { color: '#82908a' },
    splitLine: { lineStyle: { color: '#eff2ed', type: 'dashed' } },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: stats.value?.latencies.map((v) => v.name),
    axisTick: { show: false },
    axisLine: { show: false },
  },
  series: [
    {
      type: 'bar',
      barMaxWidth: 18,
      itemStyle: { color: '#90adbd', borderRadius: [0, 4, 4, 0] },
      data: stats.value?.latencies.map((v) => v.value),
    },
  ],
}))
</script>
<template>
  <div class="dashboard">
    <div class="overview-banner">
      <div class="banner-icon"><Icon name="shield" :size="31" /></div>
      <div>
        <div class="eyebrow">LOCAL SECURITY WORKSPACE</div>
        <h2>从注入检测，到防护结果追溯</h2>
        <p>对照模型响应，检查可疑输入，复核每一次防护决策。</p>
      </div>
      <div class="banner-actions">
        <router-link class="banner-link" to="/chat"
          >开始对照实验 <Icon name="arrow" :size="18" /></router-link
        ><router-link class="banner-secondary" to="/logs"
          >查看请求日志 <Icon name="logs" :size="15"
        /></router-link>
      </div>
      <ol class="defense-pipeline" aria-label="五层防护架构流程">
        <li v-for="(layer, index) in defenseLayers" :key="layer">
          <b>L{{ index + 1 }}</b
          ><span>{{ layer }}</span
          ><Icon v-if="index < 4" name="chevron" :size="13" />
        </li>
      </ol>
      <div class="banner-decoration" aria-hidden="true"></div>
    </div>
    <div class="section-title overview-toolbar">
      <div>
        <h2>流量与防护</h2>
        <p>{{ stats ? '累计请求统计 · 数据来自真实运行日志' : '正在读取运行数据' }}</p>
      </div>
      <el-button :loading="loading" @click="load"
        ><Icon name="refresh" :size="15" />刷新数据</el-button
      >
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="mb20" />
    <div v-loading="loading" class="metrics-grid dashboard-metrics">
      <div class="metric-card">
        <div class="metric-top">
          <span>请求总数</span
          ><span class="metric-icon tone-blue"><Icon name="chat" :size="18" /></span>
        </div>
        <div class="metric-value">{{ number(stats?.total_requests) }}<small>次</small></div>
        <div class="metric-caption">已记录的检测与模型请求</div>
      </div>
      <div class="metric-card">
        <div class="metric-top">
          <span>拦截请求</span
          ><span class="metric-icon tone-teal"><Icon name="shield" :size="18" /></span>
        </div>
        <div class="metric-value">{{ number(stats?.blocked_requests) }}<small>次</small></div>
        <div class="metric-caption">输入风险与输出泄露拦截</div>
      </div>
      <div class="metric-card">
        <div class="metric-top">
          <span>请求拦截率</span
          ><span class="metric-icon tone-amber"><Icon name="attack" :size="18" /></span>
        </div>
        <div class="metric-value">{{ percentage(stats?.block_rate) }}</div>
        <div class="metric-caption">拦截次数 / 全部请求</div>
      </div>
      <div class="metric-card featured-metric">
        <div class="metric-top">
          <span>攻击拦截成功率</span
          ><span class="metric-icon tone-teal"><Icon name="shield" :size="18" /></span>
        </div>
        <div class="metric-value">{{ percentage(stats?.attack_interception?.rate) }}</div>
        <div class="metric-caption" v-if="stats?.attack_interception?.evaluated">
          成功拦截 {{ number(stats.attack_interception.intercepted) }} /
          {{ number(stats.attack_interception.evaluated) }} 条有效攻击测试
        </div>
        <div class="metric-caption" v-else>暂无有效攻击测试</div>
      </div>
      <div class="metric-card">
        <div class="metric-top">
          <span>平均总延迟</span
          ><span class="metric-icon tone-lilac"><Icon name="clock" :size="18" /></span>
        </div>
        <div class="metric-value metric-duration">{{ duration(stats?.average_latency_ms) }}</div>
        <div class="metric-caption">含模型生成与各层检测</div>
      </div>
    </div>
    <div class="interception-note">
      <Icon name="info" :size="16" />
      <p>
        攻击拦截成功率 = 成功拦截 / 有效攻击测试，仅统计攻击测试台中已开启防护的记录。 错误
        {{ number(stats?.attack_interception?.errors) }} 条、未判定
        {{ number(stats?.attack_interception?.unknown) }} 条不计入分母；该指标不等同于检测准确率。
      </p>
      <router-link to="/attack">前往攻击测试台 <Icon name="arrow" :size="14" /></router-link>
    </div>
    <div class="chart-grid">
      <section class="panel trend-panel">
        <div class="section-title">
          <div>
            <h2>每日请求与拦截趋势</h2>
            <p>观察每日防护流量变化</p>
          </div>
          <span class="subtle-tag">按日聚合</span>
        </div>
        <Chart
          v-if="stats?.daily?.length"
          :option="trendOption"
          label="每日总请求与拦截次数折线图"
        /><EmptyState
          v-else
          title="流量曲线等待第一条请求"
          text="完成一次对话或攻击测试后，趋势将在此显示。"
          icon="chart"
        />
      </section>
      <section class="panel distribution-panel">
        <div class="section-title">
          <div>
            <h2>拦截类型分布</h2>
            <p>已拦截请求中的攻击类别</p>
          </div>
          <span class="chart-dot"></span>
        </div>
        <Chart
          v-if="stats?.attack_types?.length"
          :option="attackOption"
          label="已拦截请求的攻击类型分布环形图"
        /><EmptyState
          v-else
          title="暂无拦截记录"
          text="真实检测到的攻击类型将在此汇总。"
          icon="shield"
        />
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>各层命中次数</h2>
            <p>单次请求可同时命中多层</p>
          </div>
          <span class="subtle-tag">L1—L5</span>
        </div>
        <Chart
          v-if="stats?.total_requests"
          :option="layersOption"
          label="各检测层风险命中次数柱状图"
          height="240px"
        /><EmptyState v-else title="暂无检测数据" text="层级命中来自实际防护决策。" />
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>各层平均检测延迟</h2>
            <p>仅统计正常执行的检测层</p>
          </div>
          <span class="subtle-tag">毫秒</span>
        </div>
        <Chart
          v-if="stats?.latencies?.length"
          :option="latencyOption"
          label="各检测层平均延迟横向柱状图"
          height="240px"
        /><EmptyState
          v-else
          title="暂无延迟数据"
          text="完成检测后可比较各层运行开销。"
          icon="clock"
        />
      </section>
    </div>
    <div class="dashboard-bottom">
      <Icon name="info" :size="17" />
      <p>统计覆盖当前账号可访问的请求。模型状态与策略变更可在对应页面查看。</p>
      <router-link to="/logs">查看完整日志 <Icon name="arrow" :size="15" /></router-link>
    </div>
  </div>
</template>
