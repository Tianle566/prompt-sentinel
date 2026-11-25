<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { duration } from '../api'
import Icon from './Icon.vue'
import LayerResults from './LayerResults.vue'
const props = defineProps({
  result: Object,
  showLayers: { type: Boolean, default: true },
  documentView: Boolean,
})
const status = computed(() => {
  const { result, documentView } = props
  if (!result) return null
  const inspectionFailed =
    documentView &&
    result.blocked &&
    (result.detection?.reliable === false ||
      result.document_review?.status === 'error' ||
      result.output_check?.status === 'error')
  if (result.error || inspectionFailed) {
    const label = documentView ? (result.blocked ? '检测异常 · 已拦截' : '生成异常') : '服务异常'
    return { label, tone: 'state-warning', icon: 'warning' }
  }
  if (result.blocked) {
    const label = documentView
      ? '已拦截'
      : result.detection?.reliable === false
        ? '保守拦截'
        : '请求已拦截'
    return { label, tone: 'state-danger', icon: 'shield' }
  }
  return { label: documentView ? '摘要已完成' : '请求已完成', tone: 'state-success', icon: 'check' }
})
const outputLabel = computed(() => {
  if (props.result?.blocked) return '拦截说明'
  if (props.documentView) return props.result?.error ? '异常说明' : '文档摘要'
  return '模型回复'
})
const copied = ref(false),
  copying = ref(false),
  copyError = ref('')
let copiedTimer,
  alive = true
watch(
  () => props.result,
  () => {
    copied.value = false
    copyError.value = ''
  }
)
async function copyOutput() {
  const result = props.result
  copied.value = false
  copying.value = true
  copyError.value = ''
  try {
    await navigator.clipboard.writeText(result.output)
    if (!alive || props.result !== result) return
    copied.value = true
    clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    if (alive && props.result === result) {
      const text = props.documentView ? '上方文字' : '回复文字'
      copyError.value = `无法访问剪贴板，请手动选择${text}复制。`
    }
  } finally {
    copying.value = false
  }
}
onBeforeUnmount(() => {
  alive = false
  clearTimeout(copiedTimer)
})
</script>
<template>
  <div v-if="result" :class="{ 'document-result': documentView }">
    <div class="result-state" :class="status.tone">
      <Icon :name="status.icon" /><strong>{{ status.label }}</strong
      ><span>{{ documentView ? '总耗时 ' : '' }}{{ duration(result.latency_ms) }}</span>
    </div>
    <div v-if="result.error" class="inline-error" role="alert">{{ result.error }}</div>
    <p v-if="result.document_detector === 'horizon'" class="fusion-note detector-note">
      <span>文档检测</span><strong>Horizon 单模型（试用）</strong>
    </p>
    <p v-if="result.document_review?.status === 'allowed'" class="fusion-note">
      初始分类信号已通过文档复核，摘要继续经过提示加固与输出检查。
    </p>
    <p v-else-if="result.document_review?.status === 'retained'" class="fusion-note">
      文档复核仍有风险信号，已保留拦截。
    </p>
    <p v-else-if="result.document_review?.status === 'error'" class="fusion-note">
      文档复核未完成，已保留原拦截。
    </p>
    <template v-if="result.output">
      <div class="model-output-heading">
        <component :is="documentView ? 'h3' : 'span'">{{ outputLabel }}</component
        ><button
          type="button"
          class="copy-output"
          :disabled="copying"
          :aria-label="`复制${outputLabel}`"
          @click="copyOutput"
        >
          <Icon :name="copied ? 'check' : 'copy'" :size="14" />{{ copied ? '已复制' : '复制' }}
        </button>
      </div>
      <div class="model-output" :class="{ 'blocked-output': result.blocked }">
        {{ result.output }}
      </div>
      <p v-if="copied || copyError" class="copy-feedback" role="status">
        {{ copyError || '内容已复制到剪贴板。' }}
      </p>
    </template>
    <div v-else-if="!result.error" class="muted output-empty">
      {{ documentView ? '未返回文档摘要。' : '此请求没有返回模型输出。' }}
    </div>
    <div v-if="result.attack_evaluation" class="fusion-note">
      <span
        >自动判据
        {{
          { marker: '指定标记', canary: '金丝雀泄露', guard_unsafe: '回复安全审核' }[
            result.attack_evaluation.oracle?.type
          ] || '未指定'
        }}</span
      ><strong>{{
        result.attack_evaluation.success === null
          ? '未判定'
          : result.attack_evaluation.success
            ? '攻击成功'
            : '攻击未成功'
      }}</strong
      ><span v-if="result.attack_evaluation.evidence?.moderation?.details?.safety"
        >回复等级 {{ result.attack_evaluation.evidence.moderation.details.safety }}</span
      >
    </div>
    <details
      v-if="showLayers && (result.detection || result.hardening || result.output_check)"
      class="result-details"
    >
      <summary>
        检测详情
        <Icon v-if="documentView" class="details-chevron" name="chevrondown" :size="16" />
      </summary>
      <LayerResults
        :detection="result.detection"
        :hardening="result.hardening"
        :output-check="result.output_check"
      />
    </details>
  </div>
</template>

<style scoped>
.document-result .result-state {
  min-height: 44px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid var(--result-border);
  border-radius: 10px;
  background: var(--result-background);
  color: var(--result-ink);
}
.document-result .state-success {
  --result-border: #d8eddf;
  --result-background: #edf8f2;
  --result-ink: #28634a;
}
.document-result .state-danger {
  --result-border: #f3d8d9;
  --result-background: #fef0ef;
  --result-ink: #a83439;
}
.document-result .state-warning {
  --result-border: #f3e5c8;
  --result-background: #fff6e5;
  --result-ink: #815219;
}
.document-result .result-state strong {
  font-size: 13px;
  font-weight: 700;
}
.document-result .result-state > span {
  color: inherit;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.document-result .detector-note {
  margin-top: 12px;
  color: var(--muted);
}
.document-result .detector-note strong {
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
}
.document-result .model-output-heading {
  margin: 18px 0 10px;
}
.document-result .model-output-heading h3 {
  margin: 0;
  color: var(--ink);
  font-size: 16px;
  font-weight: 700;
}
.document-result .copy-output {
  min-height: 36px;
  padding-inline: 10px;
  border-color: var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--ink);
  font-size: 12px;
}
.document-result .copy-output:hover:not(:disabled) {
  border-color: #aebdf4;
  background: var(--accent-soft);
  color: var(--accent);
}
.document-result .model-output {
  max-height: none;
  padding: clamp(14px, 2.5vw, 20px);
  border-color: var(--line);
  border-radius: 12px;
  background: var(--canvas);
  color: var(--ink);
  font-size: 15px;
  line-height: 1.9;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.document-result .result-details {
  margin-top: 19px;
  padding-top: 0;
  border-color: var(--line);
}
.document-result .result-details > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 42px;
  padding: 6px 2px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  list-style: none;
}
.document-result .result-details > summary:hover {
  color: var(--accent);
}
.document-result .result-details > summary::-webkit-details-marker {
  display: none;
}
.document-result .result-details[open] .details-chevron {
  transform: rotate(180deg);
}
.document-result .result-details > summary:focus-visible,
.document-result .copy-output:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
