<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, attackName, errorText } from '../api'
const items = ref([]),
  total = ref(0),
  page = ref(1),
  origin = ref('all'),
  search = ref('')
const loading = ref(false),
  saving = ref(false),
  error = ref(''),
  formError = ref(''),
  visible = ref(false),
  editing = ref(null)
const fresh = () => ({
  text: '',
  lang: 'zh',
  attack_type: 'goal_hijacking',
  source: '自定义测试',
  label: 1,
  enabled: true,
  oracleType: 'marker',
  marker: '',
})
const form = reactive(fresh())
async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/admin/samples', {
      params: { origin: origin.value, q: search.value, page: page.value },
    })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
function edit(row = null) {
  editing.value = row
  formError.value = ''
  Object.assign(form, fresh())
  if (row)
    Object.assign(form, {
      text: row.text,
      lang: row.lang,
      attack_type: row.attack_type,
      source: row.source,
      label: row.label,
      enabled: row.enabled,
      oracleType: row.oracle?.type || 'marker',
      marker: row.oracle?.marker || '',
    })
  visible.value = true
}
async function save() {
  saving.value = true
  formError.value = ''
  const { oracleType, marker, ...body } = form
  body.label = body.attack_type === 'benign' ? 0 : 1
  body.oracle = body.label
    ? { type: oracleType, ...(oracleType === 'marker' ? { marker } : {}) }
    : {}
  try {
    if (editing.value) await api.put(`/admin/samples/${editing.value.id}`, body)
    else await api.post('/admin/samples', body)
    visible.value = false
    ElMessage.success('自定义样本已保存，可在攻击测试台选择。')
    await load(true)
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}
async function remove(row) {
  try {
    await ElMessageBox.confirm('确认移除此自定义样本？已保存的历史测试记录会保留。', '移除样本', {
      confirmButtonText: '确认移除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await api.delete(`/admin/samples/${row.id}`)
    await load(true)
  } catch (e) {
    if (!['cancel', 'close'].includes(e)) error.value = errorText(e)
  }
}
onMounted(() => load())
</script>
<template>
  <section class="panel">
    <div class="section-title">
      <div>
        <h2>攻击与正常测试样本</h2>
        <p>内置论文样本只读。自定义样本不会改变论文数据或历史实验的分母。</p>
      </div>
      <el-button type="primary" @click="edit()">新增样本</el-button>
    </div>
    <div class="admin-toolbar">
      <el-select v-model="origin" aria-label="样本来源" @change="load(true)"
        ><el-option label="全部样本" value="all" /><el-option
          label="自定义样本"
          value="custom" /><el-option label="内置论文样本（只读）" value="builtin" /></el-select
      ><el-input
        v-model="search"
        placeholder="搜索内容、来源或 ID"
        aria-label="搜索样本"
        clearable
        @keyup.enter="load(true)"
      /><el-button @click="load(true)" :loading="loading">查询样本</el-button>
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb20"
      role="alert"
    />
    <TableScroll
      ><el-table :data="items" v-loading="loading" empty-text="暂无符合条件的样本">
        <el-table-column label="样本内容" min-width="280" show-overflow-tooltip
          ><template #default="{ row }">{{ row.text }}</template></el-table-column
        >
        <el-table-column label="类别 / 标签" min-width="150"
          ><template #default="{ row }"
            >{{ attackName(row.attack_type)
            }}<small class="table-subtitle"
              >{{ row.label ? '攻击' : '正常' }} · {{ row.lang }}</small
            ></template
          ></el-table-column
        >
        <el-table-column label="来源" min-width="180" show-overflow-tooltip
          ><template #default="{ row }"
            >{{ row.source
            }}<small class="table-subtitle">{{
              row.origin === 'builtin' ? '论文样本 · 只读' : '自定义样本'
            }}</small></template
          ></el-table-column
        >
        <el-table-column label="状态" width="90"
          ><template #default="{ row }"
            ><el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{
              row.enabled ? '启用' : '停用'
            }}</el-tag></template
          ></el-table-column
        >
        <el-table-column label="操作" min-width="160"
          ><template #default="{ row }"
            ><template v-if="row.origin === 'custom'"
              ><el-button size="small" @click="edit(row)">编辑</el-button
              ><el-button size="small" type="danger" @click="remove(row)">移除</el-button></template
            ><span v-else class="helper">只读</span></template
          ></el-table-column
        >
      </el-table></TableScroll
    >
    <el-pagination
      v-if="total > 20"
      v-model:current-page="page"
      :total="total"
      :page-size="20"
      layout="prev, pager, next"
      class="admin-pagination"
      @current-change="load()"
    />
    <el-dialog
      v-model="visible"
      :title="editing ? '编辑自定义样本' : '新增自定义样本'"
      width="650px"
      :close-on-click-modal="false"
    >
      <el-alert
        v-if="formError"
        :title="formError"
        type="error"
        :closable="false"
        class="mb20"
        role="alert"
      />
      <el-form label-position="top" :disabled="saving" @submit.prevent="save">
        <el-form-item label="样本内容" for="sample-text"
          ><el-input
            id="sample-text"
            v-model="form.text"
            type="textarea"
            :rows="5"
            maxlength="30000"
            required
        /></el-form-item>
        <div class="admin-form-grid">
          <el-form-item label="语言"
            ><el-select v-model="form.lang" aria-label="样本语言"
              ><el-option label="中文" value="zh" /><el-option
                label="英文"
                value="en" /></el-select></el-form-item
          ><el-form-item label="类别与标签"
            ><el-select v-model="form.attack_type" aria-label="样本类别"
              ><el-option
                v-for="kind in [
                  'goal_hijacking',
                  'prompt_leaking',
                  'role_play',
                  'encoded',
                  'indirect',
                  'benign',
                ]"
                :key="kind"
                :value="kind"
                :label="attackName(kind)" /></el-select
          ></el-form-item>
        </div>
        <el-form-item label="来源说明" for="sample-source"
          ><el-input id="sample-source" v-model="form.source" maxlength="200" required
        /></el-form-item>
        <template v-if="form.attack_type !== 'benign'"
          ><el-form-item label="攻击成功判据"
            ><el-select v-model="form.oracleType" aria-label="攻击成功判据"
              ><el-option label="回复包含指定标记" value="marker" /><el-option
                label="泄露会话金丝雀"
                value="canary" /><el-option
                label="审核模型判定回复 Unsafe"
                value="guard_unsafe" /></el-select></el-form-item
          ><el-form-item v-if="form.oracleType === 'marker'" label="预期标记" for="sample-marker"
            ><el-input
              id="sample-marker"
              v-model="form.marker"
              maxlength="100"
              required /></el-form-item
        ></template>
        <el-form-item label="在攻击测试台启用"
          ><el-switch v-model="form.enabled" aria-label="启用自定义样本"
        /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="saving">保存样本</el-button>
      </el-form>
    </el-dialog>
  </section>
</template>
