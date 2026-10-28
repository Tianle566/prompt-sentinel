<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText, number, percentage, dateTime, artifact, attackName } from '../api'
import { auth } from '../auth'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
const datasets = ref([]),
  jobs = ref([]),
  active = ref(null),
  loading = ref(true),
  creating = ref(false),
  error = ref(''),
  tab = ref('detection'),
  images = ref({}),
  imageLoading = ref(false),
  detailLoading = ref(false),
  custom = ref(false),
  config = ref(null),
  pollError = ref('')
const form = reactive({ dataset: 'detect', experiment: 'detection', limit: 100, asr_limit: 20 })
const archived = ref(false),
  page = ref(1),
  pageSize = ref(20),
  total = ref(0),
  managing = ref(false),
  compareIds = ref([]),
  comparison = ref(null)
async function manageJob(action) {
  try {
    if (action === 'cancel')
      await ElMessageBox.confirm('取消后保留已经完成的结果；当前样本处理结束后停止。', '取消评测', {
        confirmButtonText: '确认取消评测',
        cancelButtonText: '返回',
        type: 'warning',
      })
    managing.value = true
    const id = active.value.id
    await api.post(
      `/eval/jobs/${id}/${action}`,
      action === 'archive' ? { archived: !active.value.archived } : {}
    )
    if (action === 'archive') {
      clearSelection()
      compareIds.value = []
      comparison.value = null
    }
    await refresh()
  } catch (e) {
    if (!['cancel', 'close'].includes(e)) error.value = errorText(e)
  } finally {
    managing.value = false
  }
}
async function compare() {
  managing.value = true
  try {
    comparison.value = (
      await api.get('/eval/compare', { params: { job_ids: compareIds.value.join(',') } })
    ).data
  } catch (e) {
    error.value = errorText(e)
  } finally {
    managing.value = false
  }
}
async function toggleArchive() {
  page.value = 1
  clearSelection()
  comparison.value = null
  compareIds.value = []
  await refresh()
}
const experiments = {
  all: '全部四组实验',
  detection: '实验 1 · 检测性能',
  defense: '实验 2 · 防御效果',
  ablation: '实验 3 · 消融实验',
  overhead: '实验 4 · 运行开销',
}
const statusLabels = {
  queued: '排队中',
  running: '运行中',
  cancelling: '正在取消',
  cancelled: '已取消',
  completed: '已完成',
  failed: '失败',
}
const tables = computed(() => active.value?.result?.tables || {})
const artifacts = computed(() =>
  (active.value?.result?.artifacts || [])
    .map((v) => (typeof v === 'string' ? v.split(/[\\/]/).pop() : v.filename || v.name))
    .filter(Boolean)
)
const metricCols = [
  { key: 'configuration', title: '配置' },
  { key: 'lang', title: '语言' },
  { key: 'f1', title: 'F1', rate: true },
  { key: 'precision', title: 'Precision', rate: true },
  { key: 'recall', title: 'Recall', rate: true },
  { key: 'fpr', title: '误报率', rate: true },
  { key: 'evaluated', title: '有效样本' },
  { key: 'unknown', title: '未判定' },
  { key: 'mean_latency_ms', title: '平均延迟 ms' },
]
const tableSpecs = [
  { id: 'detection', title: '检测性能', cols: metricCols },
  {
    id: 'defense',
    title: '防御效果',
    cols: [
      { key: 'configuration', title: '防护配置' },
      { key: 'attack_type', title: '攻击类型' },
      { key: 'asr', title: 'ASR', rate: true },
      { key: 'successes', title: '成功次数' },
      { key: 'requested', title: '请求样本' },
      { key: 'evaluated', title: '有效判定' },
      { key: 'unknown', title: '未判定' },
      { key: 'blocked', title: '拦截数' },
      { key: 'mean_latency_ms', title: '平均延迟 ms' },
    ],
  },
  {
    id: 'ablation',
    title: '消融实验',
    cols: [
      { key: 'configuration', title: '配置' },
      { key: 'f1', title: 'F1', rate: true },
      { key: 'asr', title: 'ASR', rate: true },
      { key: 'delta_f1', title: 'Δ F1', rate: true },
      { key: 'delta_asr', title: 'Δ ASR', rate: true },
      ...metricCols.filter((v) => ['precision', 'recall', 'evaluated', 'unknown'].includes(v.key)),
    ],
  },
  {
    id: 'overhead',
    title: '运行开销',
    cols: [
      { key: 'layer', title: '层 / 阶段' },
      { key: 'n', title: '样本量' },
      { key: 'mean_ms', title: '平均 ms' },
      { key: 'median_ms', title: '中位数 ms' },
      { key: 'p95_ms', title: 'P95 ms' },
      { key: 'source', title: '数据来源' },
    ],
  },
]
let timer,
  alive = true,
  listSequence = 0,
  detailSequence = 0,
  listPending = false,
  detailStamp = ''
const running = (job) => ['queued', 'running', 'cancelling'].includes(job.status)
const listParams = () => ({
  archived: archived.value,
  page: page.value,
  page_size: pageSize.value,
  summary: true,
})
function clearSelection() {
  detailSequence++
  active.value = null
  detailStamp = ''
  detailLoading.value = false
  clearImages()
}
async function changePage() {
  clearSelection()
  compareIds.value = []
  comparison.value = null
  await refresh()
}
async function initialize() {
  loading.value = true
  try {
    const [ds, js, cfg] = await Promise.all([
      api.get('/eval/datasets'),
      api.get('/eval/jobs', { params: listParams() }),
      api.get('/config'),
    ])
    if (!alive) return
    datasets.value = ds.data.items
    jobs.value = js.data.items
    total.value = js.data.total
    config.value = cfg.data
    if (jobs.value.length) await selectJob(jobs.value[0])
  } catch (e) {
    if (alive) error.value = errorText(e)
  } finally {
    if (alive) loading.value = false
  }
}
function syncTab() {
  const keys = Object.keys(active.value?.result?.tables || {})
  tab.value = keys.find((key) => active.value?.result?.tables[key]?.length) || 'detection'
}
async function refresh(silent = false) {
  if (silent && listPending) return
  const sequence = ++listSequence
  const params = listParams()
  listPending = true
  if (!silent) {
    loading.value = true
    error.value = ''
  }
  try {
    const { data } = await api.get('/eval/jobs', { params })
    if (!alive || sequence !== listSequence) return
    total.value = data.total
    const lastPage = Math.max(1, Math.ceil(data.total / pageSize.value))
    if (page.value > lastPage) {
      page.value = lastPage
      return await refresh()
    }
    jobs.value = data.items
    const next = data.items.find((v) => v.id === active.value?.id) || data.items[0]
    if (next) {
      const completed =
        active.value?.id === next.id && running(active.value) && next.status === 'completed'
      await selectJob(next)
      if (alive && sequence === listSequence && completed) {
        ElMessage.success('评测任务已结束，可查看实际完成的指标与图表。')
      }
    } else clearSelection()
    if (!alive || sequence !== listSequence) return
    pollError.value = ''
  } catch (e) {
    if (alive && sequence === listSequence) {
      if (silent) pollError.value = errorText(e)
      else error.value = errorText(e)
    }
  } finally {
    if (sequence === listSequence) {
      listPending = false
      if (alive) loading.value = false
    }
  }
}
async function create() {
  creating.value = true
  error.value = ''
  try {
    const body = {
      experiment: form.experiment,
      limit: form.limit,
      asr_limit: form.asr_limit,
    }
    if (custom.value && config.value)
      body.config = { layers: config.value.layers, fusion: config.value.fusion }
    const { data } = await api.post('/eval/jobs', body)
    archived.value = false
    page.value = 1
    clearSelection()
    active.value = data
    await refresh()
    ElMessage.success('评测已加入后台队列，可以离开当前页面。')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    creating.value = false
  }
}
function setDataset() {
  if (form.dataset) form.experiment = form.dataset === 'asr' ? 'defense' : 'detection'
}
function setExperiment() {
  form.dataset = ['all', 'ablation'].includes(form.experiment)
    ? null
    : form.experiment === 'defense'
      ? 'asr'
      : 'detect'
}
async function selectJob(job) {
  const same = active.value?.id === job.id
  const stamp = `${job.id}:${job.updated_at}`
  active.value = { ...job, result: same ? active.value.result : null }
  if (!same) {
    clearImages()
    syncTab()
  }
  if (same && detailStamp === stamp) return
  const sequence = ++detailSequence
  detailLoading.value = true
  try {
    const { data } = await api.get(`/eval/jobs/${job.id}`)
    if (!alive || sequence !== detailSequence) return
    active.value = data
    detailStamp = `${data.id}:${data.updated_at}`
    syncTab()
  } catch (e) {
    if (alive && sequence === detailSequence) error.value = errorText(e)
  } finally {
    if (alive && sequence === detailSequence) detailLoading.value = false
  }
}
function clearImages() {
  Object.values(images.value).forEach(URL.revokeObjectURL)
  images.value = {}
}
async function loadImages() {
  if (!active.value || imageLoading.value) return
  imageLoading.value = true
  const id = active.value.id
  try {
    for (const filename of artifacts.value.filter((v) => v.endsWith('.png'))) {
      if (!alive || active.value?.id !== id) break
      if (images.value[filename]) continue
      const url = await artifact(id, filename)
      if (alive && active.value?.id === id) images.value[filename] = url
      else URL.revokeObjectURL(url)
    }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    if (alive) imageLoading.value = false
  }
}
async function download(filename) {
  try {
    await artifact(active.value.id, filename, true)
  } catch (e) {
    error.value = errorText(e)
  }
}
function value(row, col) {
  const value = row[col.key]
  if (value === null || value === undefined) return '—'
  if (col.key === 'attack_type') return attackName(value)
  if (col.rate) return percentage(value)
  return typeof value === 'number' ? number(value) : value
}
function visibleRefresh() {
  if (!document.hidden && jobs.value.some(running)) refresh(true)
}
async function poll() {
  if (!alive) return
  if (!document.hidden && jobs.value.some(running)) await refresh(true)
  if (alive) timer = setTimeout(poll, 4000)
}
onMounted(async () => {
  await initialize()
  if (alive) {
    document.addEventListener('visibilitychange', visibleRefresh)
    timer = setTimeout(poll, 4000)
  }
})
onBeforeUnmount(() => {
  alive = false
  listSequence++
  detailSequence++
  clearTimeout(timer)
  document.removeEventListener('visibilitychange', visibleRefresh)
  clearImages()
})
</script>
<template>
  <div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="mb20"
      role="alert"
    /><el-alert
      v-if="pollError"
      :title="`进度更新暂时失败，将自动重试：${pollError}`"
      type="warning"
      :closable="false"
      class="mb20"
    />
    <div class="evaluation-layout">
      <section class="panel evaluation-setup">
        <div class="section-title">
          <div>
            <h2>创建评测任务</h2>
            <p>固定随机种子，保留配置快照</p>
          </div>
          <Icon name="chart" class="text-teal" />
        </div>
        <el-alert
          v-if="!auth.isAdmin.value"
          title="普通用户可以查看自己的评测记录；创建评测需要管理员权限。"
          type="info"
          :closable="false"
          class="mb20"
        /><el-form label-position="top" :disabled="!auth.isAdmin.value || creating"
          ><el-form-item label="数据集"
            ><el-input
              v-if="['all', 'ablation'].includes(form.experiment)"
              model-value="检测集 + 攻击成功率集"
              readonly /><el-select
              v-else
              v-model="form.dataset"
              class="full-width"
              @change="setDataset"
              ><el-option
                v-for="dataset in datasets"
                :key="dataset.id"
                :value="dataset.id"
                :label="`${dataset.name}（${dataset.count} 条）`" /></el-select></el-form-item
          ><el-form-item label="实验类型"
            ><el-select v-model="form.experiment" class="full-width" @change="setExperiment"
              ><el-option
                v-for="(name, key) in experiments"
                :key="key"
                :value="key"
                :label="name" /></el-select
          ></el-form-item>
          <p class="helper experiment-dataset-note">
            {{
              ['all', 'ablation'].includes(form.experiment)
                ? '此实验使用检测集与攻击成功率集。'
                : form.experiment === 'defense'
                  ? '此实验使用攻击成功率集。'
                  : '此实验使用检测集。'
            }}
          </p>
          <el-form-item label="检测样本上限"
            ><el-input-number
              v-model="form.limit"
              :min="1"
              :max="100000"
              controls-position="right"
              class="full-width" /></el-form-item
          ><el-form-item
            v-if="['all', 'defense', 'ablation'].includes(form.experiment)"
            label="攻击生成样本上限"
            ><el-input-number
              v-model="form.asr_limit"
              :min="1"
              :max="1000"
              controls-position="right"
              class="full-width"
          /></el-form-item>
          <div class="setting-row">
            <div>
              <strong>本次任务独立策略</strong>
              <p>仅影响本次评测，不修改全局策略</p>
            </div>
            <el-switch v-model="custom" aria-label="启用本次评测独立策略" />
          </div>
          <div v-if="custom && config" class="eval-custom">
            <label class="field-label">融合策略</label
            ><el-select v-model="config.fusion.strategy" class="full-width"
              ><el-option label="Any · 任意命中" value="any" /><el-option
                label="Vote · 多数投票"
                value="vote" /><el-option label="Weighted · 加权" value="weighted"
            /></el-select>
            <div class="setting-label">
              <span>L2 分类阈值</span><strong>{{ config.layers.l2.threshold.toFixed(2) }}</strong>
            </div>
            <el-slider
              v-model="config.layers.l2.threshold"
              :min="0"
              :max="1"
              :step="0.01"
              aria-label="本次评测 L2 阈值"
            />
            <div class="setting-row">
              <div>
                <strong>拦截 Controversial</strong>
                <p>本次评测 L3 审核策略</p>
              </div>
              <el-switch
                v-model="config.layers.l3.block_controversial"
                aria-label="本次评测拦截争议输入"
              />
            </div>
          </div>
          <el-button
            type="primary"
            size="large"
            class="full-width"
            :loading="creating"
            @click="create"
            :disabled="!auth.isAdmin.value || !datasets.length || creating"
            ><Icon v-if="!creating" name="bolt" :size="17" />启动后台评测</el-button
          ></el-form
        >
        <p class="helper mt16">
          各实验按固定协议启用对应防护层；全防护配置启用
          L1—L5，消融逐层移除。独立策略只调整融合方式、阈值与争议输入处理。CPU
          运行可能耗时较长，结果保留真实错误与未判定样本。
        </p>
      </section>
      <section class="panel evaluation-jobs" v-loading="loading">
        <div class="section-title">
          <div>
            <h2>后台任务</h2>
            <p>每页 20 个任务，运行进度每 4 秒自动更新</p>
            <el-switch
              v-model="archived"
              active-text="查看已归档"
              aria-label="查看已归档评测"
              @change="toggleArchive"
            />
          </div>
          <el-button :loading="loading" @click="refresh()"
            ><Icon name="refresh" :size="15" />刷新</el-button
          >
        </div>
        <EmptyState
          v-if="!jobs.length"
          title="还没有评测任务"
          text="选择数据集与实验设置，启动第一轮可复现实验。"
          icon="chart"
        />
        <div v-else class="job-list">
          <button
            v-for="job in jobs"
            :key="job.id"
            class="job-item"
            :class="{ active: active?.id === job.id }"
            @click="selectJob(job)"
          >
            <div class="job-title">
              <strong>{{ experiments[job.experiment] || '评测任务' }}</strong
              ><el-tag
                :type="
                  job.status === 'completed'
                    ? 'success'
                    : job.status === 'failed'
                      ? 'danger'
                      : 'warning'
                "
                size="small"
                >{{ statusLabels[job.status] }}</el-tag
              >
            </div>
            <p class="job-meta">
              {{ dateTime(job.created_at) }} <span>#{{ job.id.slice(0, 8) }}</span>
            </p>
            <el-progress
              :percentage="Math.round(job.progress || 0)"
              :stroke-width="5"
              :status="
                job.status === 'failed'
                  ? 'exception'
                  : job.status === 'completed'
                    ? 'success'
                    : undefined
              "
            />
            <p class="job-message">{{ job.error || job.message }}</p>
          </button>
        </div>
        <el-pagination
          v-if="total > pageSize"
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          class="mt16"
          @current-change="changePage"
        />
      </section>
    </div>
    <section v-if="jobs.filter((job) => job.has_result).length >= 2" class="panel">
      <div class="section-title">
        <div>
          <h2>实验结果对比</h2>
          <p>选择当前列表中 2–4 个已结束且有结果的任务。</p>
        </div>
      </div>
      <div class="admin-toolbar">
        <el-select
          v-model="compareIds"
          multiple
          :multiple-limit="4"
          placeholder="选择对比任务"
          aria-label="选择对比任务"
          ><el-option
            v-for="job in jobs.filter((item) => item.has_result && !running(item))"
            :key="job.id"
            :value="job.id"
            :label="`${experiments[job.experiment]} · ${job.id.slice(0, 8)}`" /></el-select
        ><el-button :disabled="compareIds.length < 2" :loading="managing" @click="compare"
          >对比所选实验</el-button
        >
      </div>
      <template v-if="comparison"
        ><el-alert
          :title="comparison.same_protocol ? '任务协议与配置一致' : '任务协议或配置存在差异'"
          :description="comparison.note"
          type="info"
          :closable="false"
          class="mb20"
        /><TableScroll
          ><el-table :data="comparison.items"
            ><el-table-column
              prop="id"
              label="任务 ID"
              min-width="160"
              show-overflow-tooltip
            /><el-table-column label="状态" width="100"
              ><template #default="{ row }">{{
                statusLabels[row.status]
              }}</template></el-table-column
            ><el-table-column label="检测 F1（any / 全语言）" min-width="170"
              ><template #default="{ row }"
                >{{ percentage(row.f1)
                }}<small class="table-subtitle"
                  >有效样本 {{ number(row.detection_evaluated) }}</small
                ></template
              ></el-table-column
            ><el-table-column label="ASR（full / 全类别）" min-width="170"
              ><template #default="{ row }"
                >{{ percentage(row.asr)
                }}<small class="table-subtitle"
                  >有效判定 {{ number(row.asr_evaluated) }}</small
                ></template
              ></el-table-column
            ><el-table-column label="流程平均耗时 ms" min-width="150"
              ><template #default="{ row }">{{ number(row.latency_ms) }}</template></el-table-column
            ></el-table
          ></TableScroll
        ></template
      >
    </section>
    <section v-if="active" v-loading="detailLoading" class="panel eval-output-panel">
      <div v-if="auth.isAdmin.value" class="admin-toolbar">
        <el-button
          v-if="['queued', 'running'].includes(active.status)"
          type="danger"
          :loading="managing"
          @click="manageJob('cancel')"
          >取消此评测</el-button
        ><el-button
          v-if="!['queued', 'running', 'cancelling'].includes(active.status)"
          :loading="managing"
          @click="manageJob('archive')"
          >{{ active.archived ? '取消归档' : '归档此评测' }}</el-button
        ><span v-if="active.status === 'cancelling'" class="helper"
          >正在取消，当前样本完成后停止。</span
        >
      </div>
      <div class="section-title">
        <div>
          <h2>
            实验结果 <span class="count-pill">#{{ active.id.slice(0, 8) }}</span>
          </h2>
          <p>{{ experiments[active.experiment] }} · {{ statusLabels[active.status] }}</p>
        </div>
        <el-button
          v-if="artifacts.some((v) => v.endsWith('.png'))"
          :loading="imageLoading"
          @click="loadImages"
          ><Icon name="eye" :size="16" />载入实验图表</el-button
        >
      </div>
      <el-alert
        v-if="active.status === 'cancelled'"
        title="任务已取消，已完成的数据与文件继续保留，结果仅代表实际完成范围。"
        type="warning"
        :closable="false"
        class="mb20"
      />
      <el-alert
        v-if="active.status === 'failed'"
        :title="active.error || '任务失败，请检查模型、数据集和后端日志。'"
        type="error"
        :closable="false"
        show-icon
      />
      <div
        v-if="!active.result && ['queued', 'running', 'cancelling'].includes(active.status)"
        class="evaluation-wait"
      >
        <el-progress :percentage="Math.round(active.progress || 0)" :stroke-width="8" />
        <p>{{ active.message }}</p>
        <p class="helper">任务完成后将展示实际计算的指标、图表和可下载产物。</p>
      </div>
      <template v-if="active.result"
        ><el-alert
          v-if="active.result.ai_review"
          :title="`${active.result.ai_review.count} 条独立 AI 复核已完成 · 非人工复核`"
          :description="`与自动判据的一致率 ${percentage(active.result.ai_review.agreement_rate)}，差异 ${active.result.ai_review.disagreements} 条；涉及 ${active.result.ai_review.unique_sample_ids} 个不同输入。逐条理由和差异见 ai_review.csv。一致率不代表真实准确率。`"
          type="info"
          :closable="false"
          show-icon
          class="mb20"
        /><el-alert
          v-if="active.result.status === 'incomplete' || active.result.timed_out"
          title="本次评测未完整完成。请结合错误、有效样本数与未判定数量解读指标，不能作为全量实验结论。"
          type="warning"
          :closable="false"
          show-icon
          class="mb20"
        />
        <details v-if="active.result.errors?.length" class="evaluation-errors">
          <summary>查看评测错误（{{ active.result.errors.length }}）</summary>
          <pre>{{ JSON.stringify(active.result.errors, null, 2) }}</pre>
        </details>
        <el-tabs v-model="tab"
          ><el-tab-pane
            v-for="spec in tableSpecs"
            :key="spec.id"
            :name="spec.id"
            :label="spec.title"
            ><TableScroll v-if="tables[spec.id]?.length"
              ><el-table :data="tables[spec.id]" max-height="500"
                ><el-table-column
                  v-for="col in spec.cols"
                  :key="col.key"
                  :label="col.title"
                  :min-width="col.key === 'configuration' || col.key === 'source' ? 150 : 105"
                  ><template #default="{ row }">{{ value(row, col) }}</template></el-table-column
                ></el-table
              ></TableScroll
            ><EmptyState
              v-else
              title="本次任务没有该组实验结果"
              text="可以创建对应实验，或检查评测是否完整完成。"
              icon="chart" /></el-tab-pane
        ></el-tabs>
        <div v-if="Object.keys(images).length" class="eval-images">
          <figure v-for="(url, filename) in images" :key="filename">
            <img :src="url" :alt="`实际评测图表：${filename}`" />
            <figcaption>
              {{ filename
              }}<el-button text type="primary" @click="download(filename)"
                ><Icon name="download" :size="15" />下载</el-button
              >
            </figcaption>
          </figure>
        </div>
        <div v-if="artifacts.length" class="artifact-list">
          <div class="detail-label">结果文件</div>
          <button
            v-for="filename in artifacts"
            :key="filename"
            class="artifact-file"
            @click="download(filename)"
          >
            <Icon :name="filename.endsWith('.png') ? 'chart' : 'document'" :size="17" /><span>{{
              filename
            }}</span
            ><Icon name="download" :size="15" />
          </button>
        </div>
        <details class="evaluation-errors">
          <summary>查看实验元数据与数据范围</summary>
          <pre>{{
            JSON.stringify(
              {
                status: active.result.status,
                counts: active.result.counts,
                data_scope: active.result.data_scope,
                timed_out: active.result.timed_out,
              },
              null,
              2
            )
          }}</pre>
        </details></template
      >
    </section>
  </div>
</template>
