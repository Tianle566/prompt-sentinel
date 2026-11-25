<script setup>
import { ref, computed, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorText } from '../api'
import { auth } from '../auth'
import Icon from '../components/Icon.vue'
import PipelineResult from '../components/PipelineResult.vue'
import LayerResults from '../components/LayerResults.vue'
const route = useRoute()
const file = ref(null),
  fileInput = ref(null),
  result = ref(null),
  error = ref(''),
  loading = ref(false),
  protectedMode = ref(true),
  detectorMode = ref('default'),
  drag = ref(false),
  filter = ref('all'),
  activeParagraph = ref(null)
const canTryHorizon = computed(() => auth.isAdmin.value && protectedMode.value)
const paragraphs = computed(() => result.value?.paragraphs ?? [])
const malicious = computed(
  () => paragraphs.value.filter((paragraph) => paragraphTone(paragraph) === 'risk').length
)
const incomplete = computed(
  () => paragraphs.value.filter((paragraph) => paragraphTone(paragraph) === 'issue').length
)
const visibleParagraphs = computed(() =>
  filter.value === 'all'
    ? paragraphs.value
    : paragraphs.value.filter((paragraph) => paragraphTone(paragraph) === filter.value)
)
const statusMessage = computed(() => {
  if (loading.value) return '正在检查文档并生成摘要…'
  const current = result.value?.result
  if (!current) return ''
  if (current.blocked) {
    return current.error || current.detection?.reliable === false
      ? '检测未完成，文档已拦截。'
      : '发现风险，文档已拦截。'
  }
  return current.error || !current.output?.trim() ? '摘要生成未完成。' : '文档摘要已完成。'
})
const fileSize = computed(() => {
  if (!file.value) return ''
  const { size } = file.value
  return size < 1024 ? `${size} B` : `${(size / 1024).toFixed(1)} KB`
})
const paragraphLabels = {
  risk: ['warning', '命中风险'],
  issue: ['warning', '检测异常'],
  reviewed: ['shield', '复核通过'],
  clear: ['check', '未检出风险'],
}
function paragraphTone(paragraph) {
  if (!paragraph.detection.reliable) return 'issue'
  if (paragraph.is_attack) return 'risk'
  return paragraph.original_detection ? 'reviewed' : 'clear'
}
function filterParagraphs(value) {
  filter.value = value
  activeParagraph.value = null
}
watch(canTryHorizon, (available) => {
  if (!available) detectorMode.value = 'default'
})
let sourceController, summaryController
function clearResult() {
  summaryController?.abort()
  loading.value = false
  result.value = null
  filterParagraphs('all')
}
function setFile(value) {
  error.value = ''
  const retained = file.value ? ' 已保留当前文件。' : ''
  if (!value.name.toLowerCase().endsWith('.txt')) {
    error.value = `请选择 UTF-8 编码的 .txt 文本文件。${retained}`
    return
  }
  if (value.size > 262144) {
    error.value = `文档不能超过 256 KB。${retained}`
    return
  }
  file.value = value
  clearResult()
}
function select(value) {
  if (!value) return
  sourceController?.abort()
  setFile(value)
}
function dropped(event) {
  drag.value = false
  if (!loading.value) select(event.dataTransfer.files[0])
}
function leaveDropzone(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) drag.value = false
}
function fileChanged(event) {
  select(event.target.files?.[0])
  event.target.value = ''
}
function removeFile() {
  sourceController?.abort()
  file.value = null
  error.value = ''
  clearResult()
}
watch(
  () => route.query.from,
  async (id, _previous, onCleanup) => {
    if (typeof id !== 'string' || !id) return
    const controller = new AbortController()
    sourceController = controller
    const { signal } = controller
    onCleanup(() => controller.abort())
    try {
      const { data } = await api.get(`/logs/${encodeURIComponent(id)}`, { signal })
      if (signal.aborted) return
      setFile(
        new File([data.text], data.result?.document?.filename || `request-${data.id}.txt`, {
          type: 'text/plain',
        })
      )
    } catch (e) {
      if (!signal.aborted) error.value = errorText(e)
    }
  },
  { immediate: true }
)
async function summarize() {
  const submittedFile = file.value
  if (!submittedFile || loading.value) return
  sourceController?.abort()
  summaryController = new AbortController()
  const { signal } = summaryController
  loading.value = true
  error.value = ''
  result.value = null
  filterParagraphs('all')
  try {
    const form = new FormData()
    form.append('file', submittedFile)
    form.append('protected', String(protectedMode.value))
    if (canTryHorizon.value && detectorMode.value === 'horizon')
      form.append('detector_mode', 'horizon')
    const { data } = await api.post('/document/summarize', form, { signal })
    if (!signal.aborted) result.value = data
  } catch (e) {
    if (!signal.aborted) error.value = errorText(e)
  } finally {
    if (!signal.aborted) loading.value = false
  }
}
onBeforeUnmount(() => summaryController?.abort())
</script>
<template>
  <div class="document-page">
    <section class="panel document-upload" aria-labelledby="document-upload-heading">
      <div class="document-input">
        <div class="document-heading">
          <h2 id="document-upload-heading">选择文档</h2>
          <p>UTF-8 TXT · 最大 256 KB · 最多 30,000 字符</p>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept=".txt,text/plain"
          class="sr-only"
          tabindex="-1"
          aria-label="选择文本文件"
          :disabled="loading"
          @change="fileChanged"
        />
        <div
          class="document-dropzone"
          :class="{ 'is-dragging': drag, 'has-file': file }"
          @dragover.prevent="drag = !loading"
          @dragleave.prevent="leaveDropzone"
          @drop.prevent="dropped"
        >
          <div v-if="file" class="document-file">
            <span class="document-file-icon"><Icon name="document" :size="22" /></span>
            <div class="document-file-meta">
              <strong :title="file.name">{{ file.name }}</strong>
              <span>{{ fileSize }}</span>
            </div>
            <div class="document-file-actions">
              <button type="button" :disabled="loading" @click="fileInput.click()">更换文件</button>
              <button
                type="button"
                :disabled="loading"
                aria-label="移除已选文件"
                @click="removeFile"
              >
                <Icon name="close" :size="17" />
              </button>
            </div>
          </div>
          <button v-else class="document-drop-button" type="button" @click="fileInput.click()">
            <span class="document-file-icon"><Icon name="upload" :size="22" /></span>
            <span class="document-drop-copy">
              <strong>拖入 TXT 文件</strong>
              <span>或<span class="document-picker-label">点击选择文件</span></span>
            </span>
          </button>
        </div>
      </div>
      <div class="document-control-rail">
        <div class="document-controls" role="group" aria-labelledby="document-control-heading">
          <h2 id="document-control-heading">检测设置</h2>
          <div class="document-protection">
            <Icon name="shield" :size="16" />
            <span>启用防护</span>
            <el-switch v-model="protectedMode" aria-label="文档摘要启用防护" :disabled="loading" />
          </div>
          <div v-if="canTryHorizon" class="document-mode">
            <span>检测方式</span>
            <el-select
              v-model="detectorMode"
              aria-label="检测方式"
              class="document-detector-select"
              :disabled="loading"
            >
              <el-option value="default" label="默认多模型防护" />
              <el-option value="horizon" label="Horizon 单模型（试用）" />
            </el-select>
          </div>
          <div class="document-action-row">
            <el-button
              class="document-action"
              type="primary"
              :disabled="!file"
              :loading="loading"
              @click="summarize"
            >
              <Icon v-if="!loading" name="shield" :size="17" />检测并生成摘要
            </el-button>
            <p :class="loading ? 'document-progress' : 'sr-only'" role="status">
              {{ statusMessage }}
            </p>
          </div>
        </div>
      </div>
    </section>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon role="alert" />
    <div v-if="result" class="document-workspace">
      <section class="panel document-result" aria-labelledby="document-result-heading">
        <div class="document-section-header">
          <h2 id="document-result-heading">处理结果</h2>
          <router-link
            v-if="result.result.id"
            :to="{ path: '/logs', query: { request: result.result.id } }"
            class="document-log-link"
          >
            请求 #{{ result.result.id }} <Icon name="arrow" :size="15" />
          </router-link>
        </div>
        <PipelineResult :result="result.result" document-view />
      </section>
      <section class="panel document-evidence" aria-labelledby="document-evidence-heading">
        <div class="document-section-header">
          <h2 id="document-evidence-heading">段落检查</h2>
          <span class="document-count">{{ paragraphs.length }} 个段落</span>
        </div>
        <div
          v-if="malicious || incomplete"
          class="document-filters"
          role="group"
          aria-label="筛选段落"
        >
          <button type="button" :aria-pressed="filter === 'all'" @click="filterParagraphs('all')">
            全部
          </button>
          <button
            v-if="malicious"
            type="button"
            :aria-pressed="filter === 'risk'"
            @click="filterParagraphs('risk')"
          >
            风险 {{ malicious }}
          </button>
          <button
            v-if="incomplete"
            type="button"
            :aria-pressed="filter === 'issue'"
            @click="filterParagraphs('issue')"
          >
            异常 {{ incomplete }}
          </button>
        </div>
        <div class="document-paragraphs">
          <div
            v-for="paragraph in visibleParagraphs"
            :key="paragraph.index"
            class="paragraph document-paragraph"
            :class="'tone-' + paragraphTone(paragraph)"
          >
            <button
              type="button"
              class="paragraph-heading"
              @click="
                activeParagraph = activeParagraph === paragraph.index ? null : paragraph.index
              "
              :aria-expanded="activeParagraph === paragraph.index"
              :aria-controls="
                activeParagraph === paragraph.index
                  ? 'document-paragraph-' + paragraph.index
                  : undefined
              "
            >
              <span class="document-paragraph-title">段落 {{ paragraph.index + 1 }}</span>
              <span class="document-paragraph-status">
                <Icon :name="paragraphLabels[paragraphTone(paragraph)][0]" :size="14" />
                {{ paragraphLabels[paragraphTone(paragraph)][1] }}
              </span>
              <Icon class="document-chevron" name="chevrondown" :size="16" />
              <span
                v-if="activeParagraph !== paragraph.index"
                class="document-paragraph-preview"
                aria-hidden="true"
                >{{ paragraph.text }}</span
              >
            </button>
            <div
              v-if="activeParagraph === paragraph.index"
              :id="'document-paragraph-' + paragraph.index"
              class="document-paragraph-detail"
            >
              <p>{{ paragraph.text }}</p>
              <LayerResults :detection="paragraph.detection" />
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
<style scoped>
.document-page {
  display: grid;
  gap: 20px;
}
.document-page :is(button, a):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}
.document-page .panel {
  margin-bottom: 0;
  padding: clamp(16px, 2.1vw, 26px);
  border-radius: 16px;
}
.document-upload {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(235px, 0.47fr);
  gap: clamp(16px, 2vw, 28px);
}
.document-input {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 14px;
  min-width: 0;
}
.document-protection,
.document-section-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.document-section-header {
  justify-content: space-between;
  flex-wrap: wrap;
}
.document-upload h2,
.document-workspace h2 {
  margin: 0;
  color: var(--ink);
  font-size: 18px;
  font-weight: 700;
  line-height: 1.4;
}
.document-heading p,
.document-count {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}
.document-file-icon {
  display: grid;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  place-items: center;
  border-radius: 12px;
  background: var(--accent-soft);
  color: var(--accent);
}
.document-protection {
  gap: 8px;
  padding: 4px 0;
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
.document-protection > svg {
  color: var(--muted);
}
.document-protection :deep(.el-switch) {
  margin-left: auto;
}
.document-dropzone {
  display: grid;
  overflow: hidden;
  border: 1px dashed #aebdf4;
  border-radius: 12px;
  background: #f8faff;
  color: var(--ink);
}
.document-dropzone.has-file {
  border: 1px solid var(--line);
  background: var(--canvas);
}
.document-dropzone.is-dragging {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.document-drop-button {
  display: grid;
  width: 100%;
  min-height: 156px;
  place-content: center;
  justify-items: center;
  gap: 10px;
  padding: 20px;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: center;
}
.document-drop-button:hover {
  background: var(--accent-soft);
}
.document-page .document-drop-button:focus-visible {
  outline-offset: -4px;
}
.document-drop-copy {
  display: grid;
  gap: 4px;
}
.document-drop-button strong {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.45;
}
.document-drop-copy > span,
.document-file-meta > span {
  color: var(--muted);
  font-size: 13px;
}
.document-picker-label {
  color: var(--accent);
  font-weight: 600;
}
.document-file-meta > span {
  margin-top: 4px;
}
.document-file,
.document-file-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.document-file {
  min-height: 86px;
  padding: 14px 16px;
}
.document-file-meta {
  display: grid;
  flex: 1;
  min-width: 0;
  line-height: 1.45;
}
.document-file-meta strong {
  overflow-wrap: anywhere;
  color: inherit;
  font-size: 14px;
  font-weight: 650;
}
.document-file-actions {
  flex-shrink: 0;
  gap: 8px;
}
.document-file-actions button,
.document-filters button {
  display: inline-grid;
  min-height: 36px;
  min-width: 36px;
  place-items: center;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--ink);
  font: inherit;
  font-size: 13px;
}
.document-file-actions button:hover:not(:disabled),
.document-filters button:hover {
  border-color: #aebdf4;
  color: var(--accent);
}
.document-file-actions button:disabled {
  opacity: 0.55;
}
.document-control-rail {
  display: grid;
  min-width: 0;
  padding: 9px;
  border: 1px solid #dee7f7;
  border-radius: 16px;
  background:
    radial-gradient(ellipse at 92% 12%, #b4c7fa 0%, transparent 64%),
    radial-gradient(ellipse at 6% 100%, #dce7fe 0%, transparent 75%), #f0f4ff;
}
.document-controls {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  padding: 15px;
  border: 1px solid #fff;
  border-radius: 12px;
  background: #f7f9ff;
  box-shadow:
    inset 0 1px 0 #fff,
    0 3px 10px #23427612;
}
@supports (backdrop-filter: blur(12px)) or (-webkit-backdrop-filter: blur(12px)) {
  .document-controls {
    background: #ffffffa3;
    backdrop-filter: blur(12px) saturate(115%);
    -webkit-backdrop-filter: blur(12px) saturate(115%);
  }
}
.document-upload .document-controls h2 {
  font-size: 15px;
}
.document-mode {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
}
.document-mode > span {
  white-space: nowrap;
}
.document-detector-select {
  width: 100%;
}
.document-detector-select :deep(.el-select__wrapper),
.document-action {
  min-height: 40px;
  border-radius: 10px;
}
.document-action {
  width: 100%;
  padding-inline: 10px;
  font-weight: 650;
}
.document-action-row {
  margin-top: auto;
  padding-top: 1px;
}
.document-progress {
  margin: 7px 0 0;
  color: var(--ink);
  font-size: 13px;
}
.document-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(300px, 1fr);
  align-items: start;
  gap: 20px;
}
.document-workspace > .panel {
  min-width: 0;
  scroll-margin-top: 75px;
}
.document-section-header {
  margin-bottom: 16px;
}
.document-count {
  margin: 0;
}
.document-log-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding-block: 3px;
  color: var(--accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}
.document-log-link:hover {
  text-decoration: underline;
}
.document-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.document-filters button[aria-pressed='true'] {
  border-color: #aebdf4;
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.document-paragraphs {
  display: grid;
  gap: 8px;
}
.document-paragraph {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: transparent;
}
.document-paragraph .paragraph-heading {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  min-height: 48px;
  align-items: center;
  gap: 7px 8px;
  padding: 10px 12px;
  border-radius: 11px;
  text-align: left;
}
.document-paragraph .paragraph-heading:hover {
  background: var(--canvas);
}
.document-paragraph .paragraph-heading:focus-visible {
  outline-offset: -2px;
}
.document-paragraph-title {
  color: var(--ink);
  font-size: 14px;
  font-weight: 700;
}
.document-paragraph-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 6px;
  background: #edf8f2;
  color: #28634a;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.tone-risk .document-paragraph-status {
  background: #fef0ef;
  color: #a83439;
}
.tone-issue .document-paragraph-status {
  background: #fff6e5;
  color: #815219;
}
.document-chevron {
  color: var(--muted);
}
.paragraph-heading[aria-expanded='true'] .document-chevron {
  transform: rotate(180deg);
}
.document-paragraph .paragraph-heading > .document-paragraph-preview {
  display: -webkit-box;
  grid-column: 1 / -1;
  overflow: hidden;
  color: var(--muted);
  font-size: 13px;
  font-weight: 400;
  line-height: 1.5;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.document-paragraph-detail {
  display: grid;
  gap: 12px;
  padding: 0 12px 12px;
}
.document-paragraph-detail > p {
  margin: 0;
  color: var(--ink);
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
@media (max-width: 1050px) {
  .document-workspace {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 940px) {
  .document-upload {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 540px) {
  .document-page,
  .document-workspace {
    gap: 14px;
  }
  .document-drop-button {
    min-height: 136px;
  }
  .document-file {
    flex-wrap: wrap;
    gap: 8px;
  }
  .document-file-meta strong {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }
  .document-file-actions {
    flex: 0 0 100%;
    justify-content: flex-end;
  }
}
@media (prefers-reduced-transparency: reduce) {
  .document-control-rail {
    background: #edf1ff;
  }
  .document-controls {
    background: var(--panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
