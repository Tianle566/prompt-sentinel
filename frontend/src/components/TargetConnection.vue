<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, duration, errorText } from '../api'
import Icon from './Icon.vue'

const props = defineProps({ target: { type: Object, required: true } })
const emit = defineEmits(['saved', 'dirty-change'])
const form = reactive({ ...props.target })
const snapshot = ref(''),
  apiKey = ref(''),
  clearKey = ref(false),
  credential = ref({ configured: false, source: 'none', saved: false }),
  models = ref([]),
  fileInput = ref(null),
  working = ref(''),
  error = ref(''),
  testResult = ref(null)
const busy = computed(() => Boolean(working.value))
const dirty = computed(
  () =>
    Boolean(snapshot.value) &&
    (JSON.stringify(form) !== snapshot.value || Boolean(apiKey.value) || clearKey.value)
)
function address(value) {
  try {
    const url = new URL((value || '').trim())
    const path =
      url.pathname.replace(/\/+$/, '').replace(/\/(?:chat\/completions|models)$/, '') || '/v1'
    return `${url.protocol}//${url.host}${path}${url.search}${url.hash}`
  } catch {
    return ''
  }
}
const hasSavedKey = computed(
  () =>
    credential.value.saved && address(form.base_url) === address(credential.value.saved_base_url)
)
const keyLabel = computed(() =>
  clearKey.value
    ? '待清除'
    : apiKey.value
      ? '待保存'
      : hasSavedKey.value
        ? '已保存'
        : credential.value.source === 'environment'
          ? '环境变量'
          : '未设置'
)
watch(dirty, (value) => emit('dirty-change', value), { immediate: true })
watch([() => JSON.stringify(form), apiKey, clearKey], () => (testResult.value = null))

function apply(data) {
  Object.assign(form, data.target)
  credential.value = data.credential
  apiKey.value = ''
  clearKey.value = false
  snapshot.value = JSON.stringify(form)
}
async function load() {
  working.value = 'load'
  error.value = ''
  try {
    apply((await api.get('/admin/target')).data)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    working.value = ''
  }
}
function payload() {
  const result = {}
  for (const field of [
    'provider',
    'base_url',
    'model',
    'small_model',
    'max_tokens',
    'timeout_seconds',
    'temperature',
    'context_length',
    'system_prompt',
  ]) {
    if (form[field] !== undefined && form[field] !== null) result[field] = form[field]
  }
  if (form.provider === 'openai') {
    if (apiKey.value.trim()) result.api_key = apiKey.value.trim()
    result.clear_api_key = clearKey.value
  }
  return result
}
function changeProvider(value) {
  apiKey.value = ''
  clearKey.value = false
  models.value = []
  error.value = ''
  const initial = JSON.parse(snapshot.value || '{}')
  if (value === initial.provider) {
    form.base_url = initial.base_url
    form.model = initial.model
  } else if (value === 'openai') {
    form.base_url = 'https://api.openai.com/v1'
    form.model = ''
  } else {
    form.base_url = 'http://127.0.0.1:11434'
    form.model = form.small_model || 'qwen3:0.6b'
  }
}
function reset() {
  Object.assign(form, JSON.parse(snapshot.value))
  apiKey.value = ''
  clearKey.value = false
  models.value = []
  error.value = ''
}
function toggleClearKey() {
  clearKey.value = !clearKey.value
  apiKey.value = ''
}
async function fetchModels() {
  working.value = 'models'
  error.value = ''
  try {
    models.value = (await api.post('/admin/target/models', payload())).data.models
    if (!form.model && models.value.length === 1) form.model = models.value[0]
    ElMessage.success(`获取到 ${models.value.length} 个模型`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    working.value = ''
  }
}
async function test() {
  if (!form.model?.trim()) {
    error.value = '请先填写模型名称或获取模型列表'
    return
  }
  working.value = 'test'
  error.value = ''
  testResult.value = null
  try {
    testResult.value = (await api.post('/admin/target/test', payload())).data
  } catch (e) {
    error.value = errorText(e)
  } finally {
    working.value = ''
  }
}
async function save() {
  if (!form.model?.trim()) {
    error.value = '请填写模型名称'
    return
  }
  working.value = 'save'
  error.value = ''
  try {
    const { data } = await api.put('/admin/target', payload())
    apply(data)
    emit('saved', data.target)
    ElMessage.success('模型连接已保存')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    working.value = ''
  }
}
async function importFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  error.value = ''
  working.value = 'import'
  try {
    if (file.size > 65536) throw new Error('size')
    const parsed = JSON.parse(await file.text())
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('format')
    const data = parsed.target && typeof parsed.target === 'object' ? parsed.target : parsed
    const values = {
      base_url: data.base_url ?? data.baseURL ?? data.OPENAI_BASE_URL,
      model: data.model ?? data.OPENAI_MODEL,
      api_key: data.api_key ?? data.apiKey ?? data.OPENAI_API_KEY,
    }
    if (Object.values(values).every((value) => value === undefined)) throw new Error('fields')
    if (Object.values(values).some((value) => value !== undefined && typeof value !== 'string'))
      throw new Error('types')
    form.provider = 'openai'
    form.base_url =
      values.base_url ||
      (props.target.provider === 'openai' ? props.target.base_url : 'https://api.openai.com/v1')
    form.model = values.model || (props.target.provider === 'openai' ? props.target.model : '')
    apiKey.value = values.api_key || ''
    clearKey.value = false
    models.value = []
    ElMessage.success('配置已导入，保存后生效')
  } catch {
    error.value =
      '请使用 64 KB 以内的 JSON 文件，包含 base_url、api_key、model 字段，字段值须为文字'
  } finally {
    working.value = ''
  }
}
onMounted(load)
</script>

<template>
  <section class="panel target-config connection-panel" v-loading="working === 'load'">
    <div class="section-title">
      <h2>目标模型</h2>
      <el-button text size="small" :disabled="busy" @click="fileInput?.click()">
        <Icon name="upload" :size="14" />导入 JSON
      </el-button>
      <input
        ref="fileInput"
        type="file"
        accept=".json,application/json"
        class="sr-only"
        tabindex="-1"
        aria-label="导入 OpenAI 配置文件"
        @change="importFile"
      />
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      role="alert"
      class="mb20"
    />
    <el-form label-position="top">
      <el-form-item label="接口类型" for="target-provider">
        <el-select
          id="target-provider"
          v-model="form.provider"
          :disabled="busy"
          class="full-width"
          @change="changeProvider"
        >
          <el-option label="Ollama · 本地模型" value="ollama" />
          <el-option label="OpenAI 兼容接口" value="openai" />
        </el-select>
      </el-form-item>
      <el-form-item label="服务地址" for="target-base-url">
        <el-input
          id="target-base-url"
          v-model="form.base_url"
          :disabled="busy"
          :placeholder="
            form.provider === 'openai' ? 'https://api.openai.com/v1' : 'http://127.0.0.1:11434'
          "
        />
      </el-form-item>
      <template v-if="form.provider === 'openai'">
        <p class="connection-address-note">API Key 仅发送到此地址。</p>
        <el-form-item label="API Key" for="target-api-key">
          <el-input
            id="target-api-key"
            v-model="apiKey"
            type="password"
            show-password
            autocomplete="off"
            :maxlength="4096"
            :disabled="busy || clearKey"
            :placeholder="
              hasSavedKey ? '已保存，留空保留现有密钥' : '粘贴 API Key（无需密钥可留空）'
            "
          />
        </el-form-item>
        <div class="connection-key-state">
          <el-tag :type="hasSavedKey && !clearKey && !apiKey ? 'success' : 'info'" size="small">{{
            keyLabel
          }}</el-tag>
          <el-button
            v-if="credential.saved"
            text
            size="small"
            :disabled="busy"
            @click="toggleClearKey"
            >{{ clearKey ? '取消清除' : '清除已保存密钥' }}</el-button
          >
        </div>
      </template>
      <el-form-item label="模型名称" for="target-model">
        <div class="connection-model-row">
          <el-select
            id="target-model"
            v-model="form.model"
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            :disabled="busy"
            placeholder="输入或选择模型名称"
            class="full-width"
          >
            <el-option v-for="model in models" :key="model" :label="model" :value="model" />
          </el-select>
          <el-button
            :loading="working === 'models'"
            :disabled="busy && working !== 'models'"
            @click="fetchModels"
            >获取模型</el-button
          >
        </div>
      </el-form-item>
      <el-form-item
        v-if="form.provider === 'ollama'"
        label="低内存备用模型"
        for="target-small-model"
      >
        <el-input id="target-small-model" v-model="form.small_model" :disabled="busy" />
      </el-form-item>
      <details class="connection-advanced">
        <summary>生成参数</summary>
        <div class="two-fields">
          <el-form-item label="最大生成 token"
            ><el-input-number
              v-model="form.max_tokens"
              :min="1"
              :max="8192"
              :disabled="busy"
              controls-position="right"
          /></el-form-item>
          <el-form-item label="超时（秒）"
            ><el-input-number
              v-model="form.timeout_seconds"
              :min="1"
              :max="600"
              :disabled="busy"
              controls-position="right"
          /></el-form-item>
          <el-form-item label="Temperature"
            ><el-input-number
              v-model="form.temperature"
              :min="0"
              :max="2"
              :step="0.1"
              :disabled="busy"
              controls-position="right"
          /></el-form-item>
          <el-form-item label="上下文长度"
            ><el-input-number
              v-model="form.context_length"
              :min="512"
              :max="131072"
              :step="512"
              :disabled="busy"
              controls-position="right"
          /></el-form-item>
        </div>
        <el-form-item label="系统任务提示词"
          ><el-input v-model="form.system_prompt" type="textarea" :rows="4" :disabled="busy"
        /></el-form-item>
      </details>
    </el-form>
    <div v-if="testResult" class="connection-test-success" role="status">
      <Icon name="check" :size="16" />连接成功 · {{ duration(testResult.latency_ms) }}
    </div>
    <div class="connection-actions">
      <el-button :loading="working === 'test'" :disabled="busy && working !== 'test'" @click="test"
        >测试连接</el-button
      >
      <el-button v-if="dirty" :disabled="busy" @click="reset">撤销</el-button>
      <el-button
        type="primary"
        :loading="working === 'save'"
        :disabled="!dirty || (busy && working !== 'save')"
        @click="save"
        >保存连接</el-button
      >
    </div>
  </section>
</template>
