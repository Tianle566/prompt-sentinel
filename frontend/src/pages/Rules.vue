<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, dateTime, errorText } from '../api'

const document = ref({ version: 1, items: [] })
const ruleHistory = ref([])
const policyHistory = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const tab = ref('rules')
const detail = ref(null)
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
      `确认恢复此记录${side === 'before' ? '修改前' : '修改后'}的${kind === 'rules' ? '规则' : '策略'}？此次恢复也会留存记录。`,
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
        <div class="admin-toolbar">
          <p class="helper">
            当前版本 {{ document.version }} ·
            {{ document.items.length }} 条规则。保存后生效；已运行的评测保留自己的规则快照。
          </p>
          <div>
            <el-button @click="load" :disabled="saving">重新加载</el-button
            ><el-button
              @click="
                document.items.push({
                  id: '',
                  category: 'goal_hijacking',
                  pattern: '',
                  enabled: true,
                })
              "
              :disabled="saving"
              >新增规则</el-button
            ><el-button type="primary" :loading="saving" @click="save">保存规则</el-button>
          </div>
        </div>
        <TableScroll
          ><el-table :data="document.items">
            <el-table-column label="规则 ID" min-width="160"
              ><template #default="{ row, $index }"
                ><el-input
                  v-model="row.id"
                  :aria-label="`规则 ID ${$index + 1}`"
                  maxlength="80" /></template
            ></el-table-column>
            <el-table-column label="类别" min-width="175"
              ><template #default="{ row, $index }"
                ><el-input
                  v-model="row.category"
                  :aria-label="`规则类别 ${$index + 1}`"
                  maxlength="80" /></template
            ></el-table-column>
            <el-table-column label="正则表达式" min-width="300"
              ><template #default="{ row, $index }"
                ><el-input
                  v-model="row.pattern"
                  type="textarea"
                  :rows="2"
                  :aria-label="`规则表达式 ${$index + 1}`"
                  maxlength="2000" /></template
            ></el-table-column>
            <el-table-column label="启用" width="80"
              ><template #default="{ row, $index }"
                ><el-switch
                  v-model="row.enabled"
                  :aria-label="`启用规则 ${$index + 1}`" /></template
            ></el-table-column>
            <el-table-column label="操作" width="80"
              ><template #default="{ $index }"
                ><el-button
                  type="danger"
                  link
                  @click="document.items.splice($index, 1)"
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
