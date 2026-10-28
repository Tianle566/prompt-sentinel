<script setup>
import { nextTick, onBeforeUnmount, onMounted, onUpdated, ref } from 'vue'
import Icon from './Icon.vue'

const container = ref(null),
  overflowing = ref(false)
let observer, observedTable

function measure() {
  const table = container.value?.querySelector('.el-table__body')
  const viewport = container.value?.querySelector('.el-table__body-wrapper .el-scrollbar__wrap')
  if (!table || !viewport) return
  if (table !== observedTable) {
    if (observedTable) observer?.unobserve(observedTable)
    observedTable = table
    observer?.observe(table)
  }
  overflowing.value = table.getBoundingClientRect().width > viewport.clientWidth + 1
  viewport.tabIndex = overflowing.value ? 0 : -1
  if (overflowing.value) {
    viewport.setAttribute('role', 'region')
    viewport.setAttribute('aria-label', '可左右滚动的数据表格')
  } else {
    viewport.removeAttribute('role')
    viewport.removeAttribute('aria-label')
  }
}
onMounted(async () => {
  observer = new ResizeObserver(measure)
  observer.observe(container.value)
  await nextTick()
  measure()
})
onUpdated(measure)
onBeforeUnmount(() => observer?.disconnect())
</script>
<template>
  <div ref="container" class="table-scroll">
    <p v-if="overflowing" class="table-scroll-hint">
      <Icon name="arrows" :size="15" /><span>左右滑动表格，查看完整字段</span>
    </p>
    <slot />
  </div>
</template>
