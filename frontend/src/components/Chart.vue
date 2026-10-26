<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([
  LineChart,
  BarChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CanvasRenderer,
])
const props = defineProps({
  option: Object,
  label: { type: String, default: '统计图表' },
  height: { type: String, default: '280px' },
})
const el = ref(null)
let chart, observer
onMounted(() => {
  chart = echarts.init(el.value)
  chart.setOption(props.option || {})
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(el.value)
})
watch(
  () => props.option,
  async (value) => {
    await nextTick()
    chart?.setOption(value || {}, true)
  },
  { deep: true }
)
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>
<template><div ref="el" :style="{ height }" role="img" :aria-label="label"></div></template>
