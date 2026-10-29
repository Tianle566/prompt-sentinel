<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorText } from '../api'
import Icon from './Icon.vue'
const props = defineProps({ navigation: { type: Array, required: true } })
const router = useRouter()
const visible = ref(false),
  query = ref(''),
  records = ref([]),
  loading = ref(false)
const error = ref(''),
  selected = ref(0),
  input = ref(null)
const pages = computed(() =>
  props.navigation
    .flatMap((group) => group.items)
    .filter((item) => item.label.includes(query.value.trim()))
)
const choices = computed(() => [
  ...pages.value.map((item) => ({ ...item, target: item.path })),
  ...records.value.map((item) => ({
    ...item,
    label: item.text,
    target: { path: '/logs', query: { request: item.id } },
  })),
])
let timer,
  sequence = 0
function open() {
  visible.value = true
}
defineExpose({ open })
watch(visible, async (value) => {
  sequence++
  clearTimeout(timer)
  query.value = ''
  records.value = []
  error.value = ''
  selected.value = 0
  if (value) {
    await nextTick()
    input.value?.focus()
  }
})
watch(query, () => {
  const current = ++sequence
  clearTimeout(timer)
  selected.value = 0
  records.value = []
  error.value = ''
  loading.value = false
  if (!query.value.trim() || !visible.value) return
  loading.value = true
  timer = setTimeout(async () => {
    try {
      const { data } = await api.get('/logs', { params: { q: query.value.trim(), page_size: 5 } })
      if (current === sequence && visible.value) records.value = data.items
    } catch (e) {
      if (current === sequence && visible.value) error.value = errorText(e)
    } finally {
      if (current === sequence) loading.value = false
    }
  }, 200)
})
function move(amount) {
  if (!choices.value.length) return
  selected.value = (selected.value + amount + choices.value.length) % choices.value.length
}
function go(item = choices.value[selected.value]) {
  if (!item) return
  visible.value = false
  router.push(item.target)
}
onBeforeUnmount(() => {
  clearTimeout(timer)
  sequence++
})
</script>
<template>
  <el-dialog
    v-model="visible"
    title="搜索"
    width="min(620px, calc(100% - 24px))"
    class="command-dialog"
  >
    <el-input
      ref="input"
      v-model="query"
      placeholder="搜索页面、请求内容或 #ID"
      maxlength="300"
      aria-label="搜索页面和请求"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="go()"
    />
    <div class="command-results" role="listbox" aria-label="搜索结果">
      <div v-if="pages.length" class="command-group">页面</div>
      <button
        v-for="(item, index) in pages"
        :key="item.path"
        class="command-item"
        :class="{ selected: selected === index }"
        role="option"
        :aria-selected="selected === index"
        @click="go(choices[index])"
      >
        <Icon :name="item.icon" :size="17" /><span>{{ item.label }}</span
        ><Icon name="arrow" :size="14" />
      </button>
      <div v-if="records.length" class="command-group">请求记录</div>
      <button
        v-for="(item, index) in records"
        :key="item.id"
        class="command-item"
        :class="{ selected: selected === pages.length + index }"
        role="option"
        :aria-selected="selected === pages.length + index"
        @click="go(choices[pages.length + index])"
      >
        <span class="mono">#{{ item.id }}</span
        ><span class="truncate">{{ item.text }}</span
        ><Icon name="arrow" :size="14" />
      </button>
      <p v-if="loading" class="command-empty" role="status">正在搜索…</p>
      <p v-else-if="error" class="inline-error" role="alert">{{ error }}</p>
      <p v-else-if="!choices.length" class="command-empty">没有搜索结果</p>
    </div>
    <div class="command-footer">
      <span>↑ ↓ 选择</span><span>Enter 打开</span><span>Esc 关闭</span>
    </div>
  </el-dialog>
</template>
