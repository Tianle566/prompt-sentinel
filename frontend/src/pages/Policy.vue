<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorText } from '../api'
import Icon from '../components/Icon.vue'
import { useUnsavedChanges } from '../composables/useUnsavedChanges'
const config = ref(null),
  snapshot = ref(''),
  loading = ref(true),
  saving = ref(false),
  error = ref('')
const dirty = computed(() => !!config.value && JSON.stringify(config.value) !== snapshot.value)
useUnsavedChanges(dirty)
const descriptions = {
  l1: { title: '规则过滤', subtitle: '中英文规则与编码异常检测', icon: 'logs' },
  l2: { title: 'DeBERTa 分类', subtitle: '英文注入概率与滑动窗口分析', icon: 'chart' },
  l3: { title: 'Qwen3Guard 输入审核', subtitle: '多语言安全等级与 Jailbreak 识别', icon: 'eye' },
  l4: { title: '提示加固', subtitle: '系统指令、随机分隔符与三明治防御', icon: 'lock' },
  l5: { title: '输出检测', subtitle: '金丝雀泄露、系统提示相似度与回复审核', icon: 'shield' },
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    config.value = (await api.get('/config')).data
    snapshot.value = JSON.stringify(config.value)
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
    config.value = (
      await api.put('/config', {
        layers: config.value.layers,
        fusion: config.value.fusion,
        target: config.value.target,
      })
    ).data
    snapshot.value = JSON.stringify(config.value)
    ElMessage.success('防护策略已保存，后续请求立即生效。')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}
function reset() {
  config.value = JSON.parse(snapshot.value)
}
onMounted(load)
</script>
<template>
  <div v-loading="loading">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="mb20"
      role="alert"
    /><template v-if="config"
      ><div class="policy-topline">
        <div class="policy-actions">
          <span v-if="dirty" class="unsaved-dot">有未保存的更改</span
          ><el-button @click="reset" :disabled="!dirty || saving">撤销更改</el-button
          ><el-button type="primary" @click="save" :loading="saving" :disabled="!dirty"
            ><Icon v-if="!saving" name="check" :size="17" />保存策略</el-button
          >
        </div>
      </div>
      <div class="policy-layout">
        <div class="layer-config-list">
          <section
            v-for="(item, key, index) in descriptions"
            :key="key"
            class="panel policy-layer"
            :class="{ 'layer-disabled': !config.layers[key].enabled }"
          >
            <div class="policy-layer-header">
              <span class="layer-large-id">L{{ index + 1 }}</span>
              <div>
                <h2>{{ item.title }}</h2>
              </div>
              <el-switch
                v-model="config.layers[key].enabled"
                :aria-label="`启用 ${item.title}`"
                :disabled="saving"
              />
            </div>
            <div class="layer-config-body" v-if="config.layers[key].enabled">
              <div v-if="key === 'l1'" class="helper">
                <router-link to="/rules" class="text-action"
                  >管理检测规则 <Icon name="arrow" :size="13"
                /></router-link>
              </div>
              <template v-if="key === 'l2'"
                ><div class="setting-label">
                  <span>攻击概率阈值</span
                  ><strong>{{ config.layers.l2.threshold.toFixed(2) }}</strong>
                </div>
                <el-slider
                  v-model="config.layers.l2.threshold"
                  :min="0"
                  :max="1"
                  :step="0.01"
                  :disabled="saving"
                  aria-label="DeBERTa 攻击概率阈值"
                />
                <p class="helper">
                  概率大于或等于阈值时视为攻击。中文输入可能存在漏检，请结合 L3 审核。
                </p></template
              >
              <div v-if="key === 'l3'" class="setting-row">
                <div>
                  <strong>拦截 Controversial</strong>
                  <p>Unsafe 与 Jailbreak 默认判为攻击</p>
                </div>
                <el-switch
                  v-model="config.layers.l3.block_controversial"
                  :disabled="saving"
                  aria-label="拦截争议输入"
                />
              </div>
              <template v-if="key === 'l4'"
                ><div class="setting-row">
                  <div>
                    <strong>随机分隔符包装</strong>
                    <p>Spotlighting 隔离不可信输入</p>
                  </div>
                  <el-switch
                    v-model="config.layers.l4.spotlighting"
                    :disabled="saving"
                    aria-label="随机分隔符包装"
                  />
                </div>
                <div class="setting-row">
                  <div>
                    <strong>三明治防御</strong>
                    <p>在用户输入后重申原始任务</p>
                  </div>
                  <el-switch
                    v-model="config.layers.l4.sandwich"
                    :disabled="saving"
                    aria-label="三明治防御"
                  /></div></template
              ><template v-if="key === 'l5'"
                ><div class="setting-row">
                  <div>
                    <strong>金丝雀泄露检测</strong>
                    <p>识别会话随机标记泄露</p>
                  </div>
                  <el-switch
                    v-model="config.layers.l5.canary"
                    :disabled="saving"
                    aria-label="金丝雀检测"
                  />
                </div>
                <div class="setting-row">
                  <div>
                    <strong>系统提示相似度检测</strong>
                    <p>检测输出与系统提示词的最长公共子串</p>
                  </div>
                  <el-switch
                    v-model="config.layers.l5.similarity"
                    :disabled="saving"
                    aria-label="系统提示相似度检测"
                  />
                </div>
                <template v-if="config.layers.l5.similarity"
                  ><div class="setting-label">
                    <span>最长公共子串阈值（字符）</span
                    ><strong>{{ config.layers.l5.similarity_threshold }}</strong>
                  </div>
                  <el-slider
                    v-model="config.layers.l5.similarity_threshold"
                    :min="10"
                    :max="300"
                    :step="1"
                    :disabled="saving"
                    aria-label="相似子串字符阈值"
                /></template>
                <div class="setting-row">
                  <div>
                    <strong>Qwen3Guard 回复审核</strong>
                    <p>检查生成回复的安全等级与类别</p>
                  </div>
                  <el-switch
                    v-model="config.layers.l5.guard_response"
                    :disabled="saving"
                    aria-label="大模型回复审核"
                  /></div
              ></template>
            </div>
          </section>
        </div>
        <div class="policy-side">
          <section class="panel">
            <div class="section-title">
              <div>
                <h2>融合决策</h2>
                <p>合并 L1 / L2 / L3 输入判定</p>
              </div>
              <Icon name="settings" class="text-teal" />
            </div>
            <label class="field-label" for="fusion-strategy">融合策略</label
            ><el-select
              id="fusion-strategy"
              v-model="config.fusion.strategy"
              :disabled="saving"
              class="full-width"
              ><el-option label="Any · 任一层命中即拦截" value="any" /><el-option
                label="Vote · 多数投票"
                value="vote" /><el-option label="Weighted · 加权决策" value="weighted"
            /></el-select>
            <div v-if="config.fusion.strategy === 'weighted'" class="weighted-settings">
              <div v-for="layer in ['L1', 'L2', 'L3']" :key="layer" class="setting-row">
                <label :for="`weight-${layer}`">{{ layer }} 权重</label
                ><el-input-number
                  :id="`weight-${layer}`"
                  v-model="config.fusion.weights[layer]"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :precision="2"
                  :disabled="saving"
                  size="small"
                />
              </div>
              <div class="setting-label">
                <span>融合拦截阈值</span><strong>{{ config.fusion.threshold.toFixed(2) }}</strong>
              </div>
              <el-slider
                v-model="config.fusion.threshold"
                :min="0"
                :max="1"
                :step="0.01"
                :disabled="saving"
                aria-label="融合拦截阈值"
              />
            </div>
            <div class="setting-row failclosed-setting">
              <div>
                <strong>异常时保守拦截</strong>
                <p>检测层不可用时阻止放行</p>
              </div>
              <el-switch
                v-model="config.fusion.fail_closed"
                :disabled="saving"
                aria-label="检测异常时保守拦截"
              />
            </div>
          </section>
          <section class="panel target-config">
            <div class="section-title">
              <div>
                <h2>目标模型</h2>
                <p>本地 Ollama 或兼容 OpenAI 接口</p>
              </div>
              <Icon name="chat" class="text-teal" />
            </div>
            <el-form label-position="top"
              ><el-form-item label="接口类型"
                ><el-select v-model="config.target.provider" class="full-width" :disabled="saving"
                  ><el-option value="ollama" label="Ollama" /><el-option
                    value="openai"
                    label="OpenAI 兼容接口" /></el-select></el-form-item
              ><el-form-item label="服务地址"
                ><el-input
                  v-model="config.target.base_url"
                  :disabled="saving"
                  placeholder="http://127.0.0.1:11434" /></el-form-item
              ><el-form-item label="模型名称"
                ><el-input v-model="config.target.model" :disabled="saving" /></el-form-item
              ><el-form-item label="低内存备用模型"
                ><el-input v-model="config.target.small_model" :disabled="saving"
              /></el-form-item>
              <div class="two-fields">
                <el-form-item label="最大生成 token"
                  ><el-input-number
                    v-model="config.target.max_tokens"
                    :min="16"
                    :max="8192"
                    :disabled="saving"
                    controls-position="right" /></el-form-item
                ><el-form-item label="超时（秒）"
                  ><el-input-number
                    v-model="config.target.timeout_seconds"
                    :min="10"
                    :max="1800"
                    :disabled="saving"
                    controls-position="right"
                /></el-form-item>
              </div>
              <el-form-item label="系统任务提示词"
                ><el-input
                  v-model="config.target.system_prompt"
                  type="textarea"
                  :rows="4"
                  :disabled="saving" /></el-form-item
            ></el-form>
          </section>
        </div></div
    ></template>
    <div v-else-if="!loading" class="panel"><el-button @click="load">重试加载</el-button></div>
  </div>
</template>
