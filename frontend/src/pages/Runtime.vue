<script setup>
import { onMounted, reactive, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUnsavedChanges } from '../composables/useUnsavedChanges'
import { api, downloadFile, errorText, number } from '../api'
const state = ref(null),
  backups = ref([]),
  error = ref(''),
  loading = ref(false),
  saving = ref(false),
  backingUp = ref(false),
  reading = ref(false),
  logName = ref('backend'),
  log = ref(null)
const form = reactive({}),
  snapshot = ref('')
const dirty = computed(() => !!snapshot.value && JSON.stringify(form) !== snapshot.value)
useUnsavedChanges(dirty)
async function reload() {
  if (dirty.value) {
    try {
      await ElMessageBox.confirm('重新载入将丢弃尚未保存的设置。', '重新载入？', {
        confirmButtonText: '重新载入',
        cancelButtonText: '继续编辑',
      })
    } catch {
      return
    }
  }
  await load()
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [runtime, files] = await Promise.all([
      api.get('/admin/runtime'),
      api.get('/admin/backups'),
    ])
    state.value = runtime.data
    Object.assign(form, runtime.data.settings)
    snapshot.value = JSON.stringify(form)
    backups.value = files.data.items
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
async function save() {
  saving.value = true
  error.value = ''
  try {
    Object.assign(form, (await api.put('/admin/runtime/settings', form)).data)
    snapshot.value = JSON.stringify(form)
    ElMessage.success('运行设置已保存，新请求和新评测生效。')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}
async function backup() {
  backingUp.value = true
  try {
    await api.post('/admin/backups')
    ElMessage.success('数据库备份完成，并通过完整性检查。')
    backups.value = (await api.get('/admin/backups')).data.items
  } catch (e) {
    error.value = errorText(e)
  } finally {
    backingUp.value = false
  }
}
async function download(filename) {
  try {
    await downloadFile(`/admin/backups/${encodeURIComponent(filename)}`, filename)
  } catch (e) {
    error.value = errorText(e)
  }
}
async function readLog() {
  reading.value = true
  try {
    log.value = (await api.get(`/admin/runtime/errors/${logName.value}`)).data
  } catch (e) {
    error.value = errorText(e)
  } finally {
    reading.value = false
  }
}
const gib = (value) => `${number(value / 1024 ** 3)} GB`
onMounted(load)
</script>
<template>
  <div v-loading="loading">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb20"
      role="alert"
    />
    <template v-if="state">
      <div class="metrics-grid runtime-metrics">
        <div class="metric-card">
          <span>可用内存</span><strong>{{ gib(state.memory.available) }}</strong
          ><small>总计 {{ gib(state.memory.total) }}</small>
        </div>
        <div class="metric-card">
          <span>磁盘可用空间</span><strong>{{ gib(state.disk.free) }}</strong
          ><small>可用于模型与数据</small>
        </div>
        <div class="metric-card">
          <span>正在运行 / 排队</span><strong>{{ state.active_jobs }}</strong
          ><small>设备策略 {{ state.device }}</small>
        </div>
      </div>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>模型与评测运行设置</h2>
            <span v-if="dirty" class="unsaved-dot">未保存</span>
          </div>
          <el-button @click="reload" :disabled="saving">刷新状态</el-button>
        </div>
        <el-alert
          v-if="state.model_error"
          :title="state.model_error"
          type="warning"
          :closable="false"
          class="mb20"
        />
        <el-form label-position="top" :disabled="saving" @submit.prevent="save">
          <div class="admin-form-grid">
            <el-form-item label="目标模型"
              ><el-select v-model="form.model" filterable allow-create aria-label="目标模型"
                ><el-option
                  v-for="model in [...new Set([form.model, ...state.models.map((v) => v.name)])]"
                  :key="model"
                  :label="model"
                  :value="model" /></el-select
            ></el-form-item>
            <el-form-item label="最大生成 token"
              ><el-input-number
                v-model="form.max_tokens"
                :min="1"
                :max="8192"
                aria-label="最大生成 token"
            /></el-form-item>
            <el-form-item label="上下文长度"
              ><el-input-number
                v-model="form.context_length"
                :min="512"
                :max="131072"
                aria-label="上下文长度"
            /></el-form-item>
            <el-form-item label="生成温度"
              ><el-input-number
                v-model="form.temperature"
                :min="0"
                :max="2"
                :step="0.1"
                aria-label="生成温度"
            /></el-form-item>
            <el-form-item label="单次生成超时（秒）"
              ><el-input-number
                v-model="form.timeout_seconds"
                :min="1"
                :max="600"
                aria-label="单次生成超时"
            /></el-form-item>
            <el-form-item label="单次评测检测样本上限"
              ><el-input-number
                v-model="form.max_detection_samples"
                :min="1"
                :max="100000"
                aria-label="检测样本上限"
            /></el-form-item>
            <el-form-item label="单次评测攻击样本上限"
              ><el-input-number
                v-model="form.max_asr_samples"
                :min="1"
                :max="1000"
                aria-label="攻击样本上限"
            /></el-form-item>
            <el-form-item label="运行与排队任务总上限"
              ><el-input-number
                v-model="form.max_queued_jobs"
                :min="1"
                :max="4"
                aria-label="任务数量上限"
            /></el-form-item>
            <el-form-item label="单次评测时间预算（秒）"
              ><el-input-number
                v-model="form.time_budget_seconds"
                :min="30"
                :max="7200"
                aria-label="实验时间预算"
            /></el-form-item>
          </div>
          <el-button native-type="submit" type="primary" :loading="saving">保存运行设置</el-button>
        </el-form>
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>数据库备份</h2>
            <p>包含账号、日志与任务信息，仅管理员可下载。</p>
          </div>
          <el-button
            type="primary"
            :loading="backingUp"
            :disabled="!state.sqlite_backup_supported"
            @click="backup"
            >建立数据库备份</el-button
          >
        </div>
        <TableScroll
          ><el-table :data="backups" empty-text="暂无数据库备份"
            ><el-table-column
              prop="filename"
              label="备份文件"
              min-width="270"
              show-overflow-tooltip
            /><el-table-column label="大小" width="120"
              ><template #default="{ row }"
                >{{ number(row.bytes / 1024) }} KB</template
              ></el-table-column
            ><el-table-column label="操作" width="100"
              ><template #default="{ row }"
                ><el-button size="small" @click="download(row.filename)"
                  >下载备份</el-button
                ></template
              ></el-table-column
            ></el-table
          ></TableScroll
        >
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>运行日志与错误</h2>
            <p>查看最近 64 KB 日志；已知密码、密钥和登录凭据会隐藏。</p>
          </div>
        </div>
        <div class="admin-toolbar">
          <el-select v-model="logName" aria-label="日志服务"
            ><el-option label="后端服务" value="backend" /><el-option
              label="前端服务"
              value="frontend" /><el-option label="模型服务" value="ollama" /></el-select
          ><el-button @click="readLog" :loading="reading">读取运行日志</el-button>
        </div>
        <template v-if="log"
          ><p v-if="log.truncated" class="helper">仅显示最近一段，完整日志保存在本机。</p>
          <pre class="admin-pre">{{ log.text }}</pre>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
.runtime-metrics {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.runtime-metrics .metric-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  min-height: 130px;
}
.runtime-metrics span,
.runtime-metrics small {
  font-size: 12px;
  color: #6d8066;
}
.runtime-metrics strong {
  font-size: 28px;
  line-height: 1.3;
  color: #36523b;
}
@media (max-width: 620px) {
  .runtime-metrics {
    grid-template-columns: minmax(0, 1fr);
  }
  .runtime-metrics .metric-card {
    min-height: 115px;
  }
}
</style>
