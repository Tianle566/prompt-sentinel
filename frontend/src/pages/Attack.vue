<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api, errorText, attackName, duration } from '../api'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import PipelineResult from '../components/PipelineResult.vue'
const marker = ref('')
const samples = ref([]),
  types = ref([]),
  type = ref(''),
  mode = ref('library'),
  selected = ref([]),
  manual = ref(''),
  protectedMode = ref(true),
  loadingSamples = ref(false),
  running = ref(false),
  error = ref(''),
  results = ref([]),
  drawer = ref(false),
  current = ref(null)
const count = computed(() =>
  mode.value === 'library'
    ? selected.value.length
    : manual.value.split(/\n\s*---\s*\n/).filter((v) => v.trim()).length
)
async function loadSamples(initial = false) {
  loadingSamples.value = true
  error.value = ''
  selected.value = []
  try {
    const { data } = await api.get('/attack/samples', {
      params: { limit: 200, ...(type.value ? { attack_type: type.value } : {}) },
    })
    samples.value = data.items
    if (initial) types.value = [...new Set(data.items.map((v) => v.attack_type))]
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loadingSamples.value = false
  }
}
watch(mode, (value) => {
  if (value === 'library') loadSamples()
})
onMounted(() => loadSamples(true))
function pickOne() {
  if (!samples.value.length) return
  selected.value = [String(samples.value[Math.floor(Math.random() * samples.value.length)].id)]
}
async function run() {
  if (!count.value || running.value) return
  if (count.value > 25) {
    error.value = '每次最多测试 25 条，请减少选择或输入。'
    return
  }
  running.value = true
  error.value = ''
  results.value = []
  try {
    const body = {
      protected: protectedMode.value,
      ...(mode.value === 'library'
        ? { sample_ids: selected.value }
        : {
            attack_type: type.value || null,
            expected_marker: ['prompt_leaking', 'role_play'].includes(type.value)
              ? null
              : marker.value.trim() || null,
            texts: manual.value
              .split(/\n\s*---\s*\n/)
              .map((v) => v.trim())
              .filter(Boolean),
          }),
    }
    results.value = (await api.post('/attack/run', body)).data.items
  } catch (e) {
    error.value = errorText(e)
  } finally {
    running.value = false
  }
}
function detail(item) {
  current.value = item
  drawer.value = true
}
</script>
<template>
  <div>
    <div class="experiment-note">
      <Icon name="lock" :size="18" />
      <p>
        所有攻击仅发送到本机目标模型。攻击成功由指定标记或输出审核判定；无法自动判定的结果显示为「未判定」。
      </p>
    </div>
    <div class="attack-grid">
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>构造测试</h2>
            <p>选择样本或输入自定义提示词</p>
          </div>
          <span class="step-number">01</span>
        </div>
        <el-segmented
          v-model="mode"
          :options="[
            { label: '本地样本库', value: 'library' },
            { label: '手动输入', value: 'manual' },
          ]"
          block
        />
        <div class="sample-filter">
          <el-select
            v-model="type"
            placeholder="全部攻击类型"
            clearable
            aria-label="攻击类型"
            @change="mode === 'library' && loadSamples()"
            ><el-option
              v-for="item in types"
              :key="item"
              :label="attackName(item)"
              :value="item" /></el-select
          ><el-button
            v-if="mode === 'library'"
            @click="pickOne"
            :disabled="!samples.length || loadingSamples"
            ><Icon name="refresh" :size="15" />随机抽样</el-button
          >
        </div>
        <template v-if="mode === 'library'"
          ><el-checkbox-group
            v-model="selected"
            v-loading="loadingSamples"
            class="sample-list"
            aria-label="攻击样本"
          >
            <EmptyState
              v-if="!samples.length && !loadingSamples"
              title="没有可用样本"
              text="请先运行数据集构建脚本，或切换到手动输入。"
            /><el-checkbox
              v-for="sample in samples"
              :key="sample.id"
              :value="String(sample.id)"
              :aria-label="`选择样本 ${sample.id}`"
              class="sample-item"
              :class="{ selected: selected.includes(String(sample.id)) }"
            >
              <div>
                <span class="sample-category"
                  >{{ attackName(sample.attack_type) }}
                  <small>{{ sample.lang?.toUpperCase() }}</small></span
                >
                <p>{{ sample.text }}</p>
                <span class="sample-id">{{ sample.id }}</span>
              </div></el-checkbox
            >
          </el-checkbox-group></template
        ><template v-else
          ><el-input
            v-if="!['prompt_leaking', 'role_play'].includes(type)"
            v-model="marker"
            placeholder="预期输出标记（可选，例如 RESULT-42）"
            aria-label="攻击成功预期标记"
            class="mb20"
          />
          <p v-if="type === 'prompt_leaking'" class="helper">
            自动检查原始回复是否泄露会话金丝雀。
          </p>
          <p v-else-if="type === 'role_play'" class="helper">
            自动使用 Qwen3Guard 审核生成回复，Unsafe 视为成功。
          </p>
          <el-input
            v-model="manual"
            type="textarea"
            :rows="12"
            class="manual-input"
            placeholder="输入一条攻击提示词。批量测试时，在两条输入之间用单独一行 --- 分隔。"
            aria-label="自定义攻击提示词"
          />
          <p class="helper">
            支持单条与批量输入，最多 25 条；批量输入用单独一行 --- 分隔。
          </p></template
        >
        <div class="attack-options">
          <span><Icon name="shield" :size="17" />启用多层防护</span
          ><el-switch v-model="protectedMode" aria-label="启用多层防护" :disabled="running" />
        </div>
        <el-button
          class="full-width"
          type="primary"
          size="large"
          :loading="running"
          :disabled="!count"
          @click="run"
          ><Icon v-if="!running" name="bolt" :size="17" />{{
            running ? '正在依次执行测试…' : `运行测试${count ? `（${count} 条）` : ''}`
          }}</el-button
        >
        <p v-if="running" class="helper">
          批量测试在后端依次运行，请保持页面打开。CPU 推理可能需要数分钟。
        </p>
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>测试结果</h2>
            <p>检查拦截决策与攻击成功情况</p>
          </div>
          <span class="step-number">02</span>
        </div>
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
          class="mb20"
          role="alert"
        />
        <div v-if="results.length" class="test-result-summary">
          <div>
            <strong>{{ results.length }}</strong
            ><span>完成测试</span>
          </div>
          <div>
            <strong class="text-teal">{{ results.filter((v) => v.blocked).length }}</strong
            ><span>已被拦截</span>
          </div>
          <div>
            <strong class="text-danger">{{
              results.filter((v) => v.success === true).length
            }}</strong
            ><span>攻击成功</span>
          </div>
        </div>
        <div v-if="running" class="processing-state">
          <span class="loading-orbit"></span>
          <h3>测试运行中</h3>
          <p>实际输出与各层检测依据将在完成后显示</p>
        </div>
        <EmptyState
          v-else-if="!results.length"
          title="等待第一轮安全测试"
          text="左侧选择样本并运行，即可检查模型响应和防护表现。"
          icon="attack"
        />
        <div v-else class="attack-results">
          <button
            v-for="(item, index) in results"
            :key="index"
            class="attack-result-item"
            @click="detail(item)"
          >
            <div class="attack-result-head">
              <span class="result-index">{{ String(index + 1).padStart(2, '0') }}</span
              ><strong>{{ attackName(item.attack_type) }}</strong
              ><el-tag
                :type="item.result.error ? 'warning' : item.blocked ? 'success' : 'info'"
                size="small"
                >{{ item.result.error ? '服务异常' : item.blocked ? '已拦截' : '已放行' }}</el-tag
              >
            </div>
            <p>{{ item.text }}</p>
            <div class="attack-result-foot">
              <span :class="{ 'text-danger': item.success === true }">{{
                item.success === null
                  ? '攻击成功：未判定'
                  : item.success
                    ? '攻击成功：是'
                    : '攻击成功：否'
              }}</span
              ><span
                >{{ duration(item.result.latency_ms) }} <Icon name="chevron" :size="13"
              /></span>
            </div>
          </button>
        </div>
      </section>
    </div>
    <el-drawer v-model="drawer" title="攻击测试详情" size="min(620px, 100%)"
      ><template v-if="current"
        ><div class="detail-label">测试输入</div>
        <div class="input-preview">{{ current.text }}</div>
        <PipelineResult :result="current.result" /></template
    ></el-drawer>
  </div>
</template>
