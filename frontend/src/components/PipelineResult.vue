<script setup>
import { duration } from '../api'
import Icon from './Icon.vue'
import LayerResults from './LayerResults.vue'
defineProps({ result: Object, showLayers: { type: Boolean, default: true } })
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
    <div v-if="result.output" class="model-output" :class="{ 'blocked-output': result.blocked }">
      {{ result.output }}
    </div>
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
