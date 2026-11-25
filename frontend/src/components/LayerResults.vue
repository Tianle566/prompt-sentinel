<script setup>
import { computed } from 'vue'
import { duration } from '../api'
const props = defineProps({ detection: Object, hardening: Object, outputCheck: Object })
const names = {
  L1: '规则过滤',
  L2: 'DeBERTa 分类',
  L3: 'Qwen3Guard 审核',
  L4: '提示加固',
  L5: '输出检测',
}
const results = computed(() => [
  ...(props.detection?.layer_results || []),
  ...(props.hardening ? [props.hardening] : []),
  ...(props.outputCheck ? [props.outputCheck] : []),
])
const isHorizon = (layer) => layer.details?.repo === 'Horizon-Labs/prompt-injection-guard-small'
const name = (layer) => (isHorizon(layer) ? 'Horizon 注入分类' : names[layer.layer] || layer.layer)
const state = (layer) =>
  !layer.enabled || layer.status === 'disabled'
    ? '已关闭'
    : layer.status === 'error'
      ? '检测异常'
      : layer.is_attack
        ? '命中风险'
        : '通过'
</script>
<template>
  <div v-if="results.length" class="layer-results">
    <div
      v-for="(layer, index) in results"
      :key="`${layer.layer}-${index}`"
      class="layer-row"
      :class="{ hit: layer.is_attack, failed: layer.status === 'error', off: !layer.enabled }"
    >
      <span class="layer-id">{{ layer.layer }}</span>
      <div class="layer-body">
        <div class="layer-title">
          <strong>{{ name(layer) }}</strong
          ><span
            class="status-text"
            :class="
              layer.status === 'error' ? 'text-warning' : layer.is_attack ? 'text-danger' : ''
            "
            >{{ state(layer) }}</span
          >
        </div>
        <div class="layer-meta">
          <span v-if="layer.score !== null && layer.score !== undefined"
            >{{
              layer.details?.document_review === 'allowed'
                ? '原始分类分数'
                : layer.layer === 'L2'
                  ? '分类分数'
                  : layer.layer === 'L3'
                    ? '策略判定值'
                    : '检测信号'
            }}
            {{ layer.score.toFixed(3) }}</span
          ><span v-if="layer.details?.safety">安全等级 {{ layer.details.safety }}</span
          ><span v-if="layer.details?.document_review === 'allowed'">文档复核通过</span
          ><span v-if="layer.details?.moderation?.safety"
            >回复等级 {{ layer.details.moderation.safety }}</span
          ><span v-if="layer.details?.window_count > 1"
            >{{ layer.details.window_count }} 个滑动窗口</span
          ><span v-if="layer.details?.canary_leaked">金丝雀泄露已检出（展示已脱敏）</span
          ><span v-if="layer.categories?.length">{{ layer.categories.join(' · ') }}</span
          ><span v-if="layer.rule_ids?.length">{{ layer.rule_ids.join(', ') }}</span
          ><span>{{ duration(layer.latency_ms) }}</span>
        </div>
        <div v-if="layer.error" class="layer-error">{{ layer.error }}</div>
      </div>
    </div>
    <div v-if="detection" class="fusion-note">
      <span v-if="!detection.layer_results?.some(isHorizon)"
        >融合策略 <strong>{{ detection.strategy }}</strong></span
      ><span v-if="!detection.reliable" class="text-warning">检测结果不完整</span
      ><span v-else>输入检测 {{ duration(detection.latency_ms) }}</span>
    </div>
  </div>
</template>
