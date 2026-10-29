<script setup>
import { onMounted, ref, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, dateTime, errorText, attackName } from '../api'
import { useUnsavedChanges } from '../composables/useUnsavedChanges'

const document = ref({ version: 1, items: [] })
const ruleHistory = ref([])
const policyHistory = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const tab = ref('rules')
const detail = ref(null),
  snapshot = ref(''),
  search = ref(''),
  editor = ref(false),
  editing = ref(null),
  formError = ref('')
const form = reactive({ id: '', category: 'goal_hijacking', pattern: '', enabled: true })
const dirty = computed(() => !!snapshot.value && JSON.stringify(document.value) !== snapshot.value)
const filtered = computed(() =>
  document.value.items.filter((row) =>
    [row.id, row.category, row.pattern].some((value) =>
      value.toLowerCase().includes(search.value.toLowerCase())
    )
  )
)
useUnsavedChanges(dirty)
function editRule(row = null) {
  editing.value = row
  Object.assign(form, row || { id: '', category: 'goal_hijacking', pattern: '', enabled: true })
  formError.value = ''
  editor.value = true
}
function applyRule() {
  if (!form.id.trim() || !form.category.trim() || !form.pattern.trim()) {
    formError.value = '请填写规则 ID、类别和表达式'
    return
  }
  if (document.value.items.some((row) => row !== editing.value && row.id === form.id.trim())) {
    formError.value = '规则 ID 已存在'
    return
  }
  const value = { ...form, id: form.id.trim(), category: form.category.trim() }
  if (editing.value) Object.assign(editing.value, value)
  else document.value.items.push(value)
  editor.value = false
}
async function reload() {
  if (dirty.value) {
    try {
      await ElMessageBox.confirm('重新载入将丢弃尚未保存的规则更改。', '重新载入？', {
        confirmButtonText: '重新载入',
        cancelButtonText: '继续编辑',
      })
    } catch {
      return
    }
  }
  await load()
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [rules, history, policies] = await Promise.all([
      api.get('/admin/rules'),
      api.get('/admin/rules/history'),
      api.get('/admin/policy/history'),
    ])
    document.value = rules.data
    snapshot.value = JSON.stringify(document.value)
    ruleHistory.value = history.data.items
    policyHistory.value = policies.data.items
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
    document.value = (await api.put('/admin/rules', document.value)).data
    ElMessage.success('规则已保存，后续检测使用新版本。')
    await load()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}
async function restore(kind, row, side) {
  try {
    await ElMessageBox.confirm(
      `${dirty.value ? '未保存的更改将丢失。' : ''}确认恢复此记录${side === 'before' ? '修改前' : '修改后'}的${kind === 'rules' ? '规则' : '策略'}？此次恢复也会留存记录。`,
      '恢复历史配置',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )
    saving.value = true
    await api.post(`/admin/${kind}/history/${row.id}/restore`, { side })
    ElMessage.success('历史配置已恢复，后续请求生效。')
    await load()
  } catch (e) {
    if (!['cancel', 'close'].includes(e)) error.value = errorText(e)
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>
<template>
  <section class="panel" v-loading="loading">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb20"
      role="alert"
    />
    <el-tabs v-model="tab">
      <el-tab-pane label="检测规则" name="rules">
        <div class="admin-toolbar rules-toolbar">
          <div class="toolbar-actions">
            <el-input
              v-model="search"
              placeholder="搜索规则"
              aria-label="搜索规则"
              clearable
            /><span class="subtle-label"
              >v{{ document.version }} · {{ document.items.length }} 条</span
            ><span v-if="dirty" class="unsaved-dot">未保存</span>
          </div>
          <div class="toolbar-actions">
            <el-button @click="reload" :disabled="saving">重新载入</el-button
            ><el-button @click="editRule()" :disabled="saving">新建规则</el-button
            ><el-button type="primary" :loading="saving" :disabled="!dirty" @click="save"
              >保存规则</el-button
            >
          </div>
        </div>
        <TableScroll
          ><el-table :data="filtered" class="compact-table" empty-text="没有匹配的规则">
            <el-table-column label="规则 ID" min-width="170"
              ><template #default="{ row }"
                ><span class="mono">{{ row.id }}</span></template
              ></el-table-column
            >
            <el-table-column label="类别" min-width="150"
              ><template #default="{ row }">{{
                attackName(row.category)
              }}</template></el-table-column
            >
            <el-table-column label="表达式" min-width="300"
              ><template #default="{ row }"
                ><span class="rule-pattern">{{ row.pattern }}</span></template
              ></el-table-column
            >
            <el-table-column label="启用" width="80"
              ><template #default="{ row }"
                ><el-switch
                  v-model="row.enabled"
                  :aria-label="`启用规则 ${row.id}`"
                  :disabled="saving" /></template
            ></el-table-column>
            <el-table-column label="操作" width="130" fixed="right"
              ><template #default="{ row }"
                ><el-button text size="small" @click="editRule(row)" :disabled="saving"
                  >编辑</el-button
                ><el-button
                  text
                  size="small"
                  type="danger"
                  @click="document.items.splice(document.items.indexOf(row), 1)"
                  :disabled="saving"
                  >移除</el-button
                ></template
              ></el-table-column
            >
          </el-table></TableScroll
        >
      </el-tab-pane>
      <el-tab-pane label="规则历史" name="rules-history">
        <TableScroll
          ><el-table :data="ruleHistory" empty-text="保存规则后会在此记录历史版本">
            <el-table-column label="时间" min-width="180"
              ><template #default="{ row }">{{
                dateTime(row.created_at)
              }}</template></el-table-column
            >
            <el-table-column label="版本变更" min-width="130"
              ><template #default="{ row }"
                >{{ row.before.version }} → {{ row.after.version }}</template
              ></el-table-column
            >
            <el-table-column label="操作" min-width="300"
              ><template #default="{ row }"
                ><el-button size="small" @click="detail = row">查看变化</el-button
                ><el-button size="small" :disabled="saving" @click="restore('rules', row, 'before')"
                  >恢复修改前</el-button
                ><el-button size="small" :disabled="saving" @click="restore('rules', row, 'after')"
                  >恢复修改后</el-button
                ></template
              ></el-table-column
            >
          </el-table></TableScroll
        >
      </el-tab-pane>
      <el-tab-pane label="策略历史" name="policy-history">
        <TableScroll
          ><el-table :data="policyHistory" empty-text="保存防护策略后会在此记录历史配置">
            <el-table-column label="时间" min-width="180"
              ><template #default="{ row }">{{
                dateTime(row.created_at)
              }}</template></el-table-column
            >
            <el-table-column prop="username" label="操作人" min-width="140" />
            <el-table-column label="操作" min-width="300"
              ><template #default="{ row }"
                ><el-button size="small" @click="detail = row">查看变化</el-button
                ><el-button
                  size="small"
                  :disabled="saving"
                  @click="restore('policy', row, 'before')"
                  >恢复修改前</el-button
                ><el-button size="small" :disabled="saving" @click="restore('policy', row, 'after')"
                  >恢复修改后</el-button
                ></template
              ></el-table-column
            >
          </el-table></TableScroll
        >
      </el-tab-pane>
    </el-tabs>
    <el-dialog
      v-model="editor"
      :title="editing ? '编辑规则' : '新建规则'"
      width="min(580px, calc(100% - 24px))"
      :close-on-click-modal="false"
    >
      <el-alert v-if="formError" :title="formError" type="error" :closable="false" class="mb20" />
      <el-form label-position="top" @submit.prevent="applyRule"
        ><el-form-item label="规则 ID"
          ><el-input v-model="form.id" maxlength="80" aria-label="规则 ID" /></el-form-item
        ><el-form-item label="风险类别"
          ><el-input v-model="form.category" maxlength="80" aria-label="规则类别" /></el-form-item
        ><el-form-item label="正则表达式"
          ><el-input
            v-model="form.pattern"
            type="textarea"
            :rows="6"
            maxlength="2000"
            aria-label="规则表达式" /></el-form-item
        ><el-form-item label="启用"
          ><el-switch v-model="form.enabled" aria-label="启用编辑规则" /></el-form-item
      ></el-form>
      <template #footer
        ><el-button @click="editor = false">取消</el-button
        ><el-button type="primary" @click="applyRule">应用更改</el-button></template
      >
    </el-dialog>
    <el-dialog :model-value="!!detail" title="配置变更详情" width="900px" @close="detail = null"
      ><div class="admin-diff">
        <div>
          <h3>修改前</h3>
          <pre>{{ JSON.stringify(detail?.before, null, 2) }}</pre>
        </div>
        <div>
          <h3>修改后</h3>
          <pre>{{ JSON.stringify(detail?.after, null, 2) }}</pre>
        </div>
      </div></el-dialog
    >
  </section>
</template>
