<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorText } from '../api'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import PipelineResult from '../components/PipelineResult.vue'
import LayerResults from '../components/LayerResults.vue'
const route = useRoute()
const file = ref(null),
  fileInput = ref(null),
  result = ref(null),
  error = ref(''),
  loading = ref(false),
  protectedMode = ref(true),
  drag = ref(false),
  activeParagraph = ref(null)
const malicious = computed(
  () => result.value?.paragraphs.filter((v) => v.is_attack && v.detection.reliable).length || 0
)
const incomplete = computed(
  () => result.value?.paragraphs.filter((v) => !v.detection.reliable).length || 0
)
function select(value) {
  if (!value) return
  error.value = ''
  if (!value.name.toLowerCase().endsWith('.txt')) {
    error.value = '请选择 UTF-8 编码的 .txt 文本文件。'
    return
  }
  if (value.size > 262144) {
    error.value = '文档不能超过 256 KB。'
    return
  }
  file.value = value
  result.value = null
  activeParagraph.value = null
}
function dropped(event) {
  drag.value = false
  if (!loading.value) select(event.dataTransfer.files[0])
}
function removeFile() {
  file.value = null
  fileInput.value.value = ''
  result.value = null
  error.value = ''
  activeParagraph.value = null
}
watch(
  () => route.query.from,
  async (id) => {
    if (!id) return
    try {
      const { data } = await api.get(`/logs/${encodeURIComponent(id)}`)
      select(
        new File([data.text], data.result?.document?.filename || `request-${data.id}.txt`, {
          type: 'text/plain',
        })
      )
    } catch (e) {
      error.value = errorText(e)
    }
  },
  { immediate: true }
)
async function summarize() {
  if (!file.value || loading.value) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('protected', String(protectedMode.value))
    result.value = (await api.post('/document/summarize', form)).data
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
</script>
<template>
  <div>
    <section class="panel upload-panel">
      <div class="section-title">
        <div>
          <h2>上传本地文档</h2>
          <p>UTF-8 纯文本 · 最大 256 KB · 最多 30,000 字符</p>
        </div>
        <div class="inline-control">
          <span>启用防护</span
          ><el-switch v-model="protectedMode" aria-label="文档摘要启用防护" :disabled="loading" />
        </div>
      </div>
      <div
        class="upload-zone"
        :class="{ dragging: drag, 'has-file': file }"
        @dragover.prevent="drag = true"
        @dragleave.prevent="drag = false"
        @drop.prevent="dropped"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".txt,text/plain"
          class="sr-only"
          :disabled="loading"
          aria-label="选择文本文件"
          @change="select($event.target.files?.[0])"
        /><span class="upload-symbol"
          ><Icon :name="file ? 'document' : 'upload'" :size="28"
        /></span>
        <div>
          <h3>{{ file ? file.name : '拖入文档，或选择文件' }}</h3>
          <p v-if="file">
            {{ `${(file.size / 1024).toFixed(1)} KB` }}
          </p>
        </div>
        <div class="upload-file-actions">
          <el-button :disabled="loading" @click="fileInput.click()">{{
            file ? '更换文件' : '选择 .txt 文件'
          }}</el-button
          ><el-button v-if="file" :disabled="loading" aria-label="移除已选文件" @click="removeFile"
            ><Icon name="close" :size="16" />移除</el-button
          >
        </div>
      </div>
      <div class="upload-action">
        <el-button type="primary" :disabled="!file" :loading="loading" @click="summarize"
          ><Icon v-if="!loading" name="shield" :size="17" />{{
            loading ? '逐段检测与生成中…' : '检测并生成摘要'
          }}</el-button
        >
      </div>
    </section>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="mb20"
      role="alert"
    />
    <div class="document-grid">
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>文档段落检查</h2>
            <p>
              {{
                result
                  ? `${result.paragraphs.length} 个段落 · ${malicious} 个段落命中风险${incomplete ? ` · ${incomplete} 个检测未完成` : ''}`
                  : ''
              }}
            </p>
          </div>
          <el-tag v-if="malicious" type="danger" size="small">{{ malicious }} 处风险</el-tag>
        </div>
        <div v-if="loading" class="processing-state">
          <span class="loading-orbit"></span>
          <h3>正在逐段扫描文档</h3>
        </div>
        <EmptyState v-else-if="!result" title="暂无文档" text="" icon="document" />
        <div v-else class="paragraph-list">
          <div
            v-for="paragraph in result.paragraphs"
            :key="paragraph.index"
            class="paragraph"
            :class="{
              malicious: paragraph.is_attack && paragraph.detection.reliable,
              unreliable: !paragraph.detection.reliable,
            }"
          >
            <button
              class="paragraph-heading"
              @click="
                activeParagraph = activeParagraph === paragraph.index ? null : paragraph.index
              "
              :aria-expanded="activeParagraph === paragraph.index"
            >
              <span>段落 {{ paragraph.index + 1 }}</span
              ><span
                >{{
                  !paragraph.detection.reliable
                    ? '检测不完整'
                    : paragraph.is_attack
                      ? '疑似注入指令'
                      : '未检出风险'
                }}<Icon name="chevrondown" :size="14"
              /></span>
            </button>
            <p>{{ paragraph.text }}</p>
            <LayerResults
              v-if="activeParagraph === paragraph.index"
              :detection="paragraph.detection"
            />
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>处理结果</h2>
          </div>
          <Icon name="shield" class="text-teal" />
        </div>
        <PipelineResult v-if="result" :result="result.result" />
        <router-link
          v-if="result?.result.id"
          :to="{ path: '/logs', query: { request: result.result.id } }"
          class="text-action result-log-link"
          >查看请求 #{{ result.result.id }} <Icon name="arrow" :size="13"
        /></router-link>
        <div v-else-if="loading" class="processing-state">
          <span class="loading-orbit"></span>
          <h3>等待防护决策</h3>
        </div>
        <EmptyState v-else title="暂无处理结果" text="" icon="shield" />
      </section>
    </div>
  </div>
</template>
