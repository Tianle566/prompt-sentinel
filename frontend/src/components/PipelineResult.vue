<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { duration } from '../api'
import Icon from './Icon.vue'
import LayerResults from './LayerResults.vue'
const props = defineProps({ result: Object, showLayers: { type: Boolean, default: true } })
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
    if (alive && props.result === result)
      copyError.value = '无法访问剪贴板，请手动选择回复文字复制。'
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
  <div v-if="result">
    <div
      class="result-state"
      :class="result.error ? 'state-warning' : result.blocked ? 'state-danger' : 'state-success'"
    >
      <Icon :name="result.error ? 'warning' : result.blocked ? 'shield' : 'check'" /><strong>{{
        result.error
          ? '服务异常'
          : result.blocked
            ? result.detection?.reliable === false
              ? '保守拦截'
              : '请求已拦截'
            : '请求已完成'
      }}</strong
      ><span>{{ duration(result.latency_ms) }}</span>
    </div>
    <div v-if="result.error" class="inline-error" role="alert">{{ result.error }}</div>
    <template v-if="result.output">
      <div class="model-output-heading">
        <span>{{ result.blocked ? '拦截说明' : '模型回复' }}</span
        ><button
          type="button"
          class="copy-output"
          :disabled="copying"
          :aria-label="result.blocked ? '复制拦截说明' : '复制模型回复'"
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
    <div v-else-if="!result.error" class="muted output-empty">此请求没有返回模型输出。</div>
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
    <LayerResults
      v-if="showLayers"
      :detection="result.detection"
      :hardening="result.hardening"
      :output-check="result.output_check"
    />
  </div>
</template>
