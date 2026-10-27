<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, dateTime, errorText } from '../api'
import { auth } from '../auth'
import Icon from '../components/Icon.vue'

const router = useRouter()
const accounts = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const listError = ref('')
const creating = ref(false)
const createError = ref('')
const changing = ref(false)
const passwordError = ref('')
const newAccount = reactive({ username: '', password: '', confirm: '', role: 'user' })
const password = reactive({ old: '', next: '', confirm: '' })
const editing = ref(null)
const resetting = ref(null)
const managing = ref(false)
const manageError = ref('')
const accountUpdate = reactive({ role: 'user', is_active: true })
const resetPassword = reactive({ password: '', confirm: '' })

function editAccount(account) {
  editing.value = account
  manageError.value = ''
  Object.assign(accountUpdate, { role: account.role, is_active: account.is_active })
}
function openReset(account) {
  resetting.value = account
  manageError.value = ''
  Object.assign(resetPassword, { password: '', confirm: '' })
}
async function manageAccount(reset = false) {
  manageError.value = reset ? validatePassword(resetPassword.password, resetPassword.confirm) : ''
  if (manageError.value) return
  const account = reset ? resetting.value : editing.value
  managing.value = true
  try {
    if (reset) await api.post(`/users/${account.id}/password`, { password: resetPassword.password })
    else await api.patch(`/users/${account.id}`, accountUpdate)
    editing.value = null
    resetting.value = null
    Object.assign(resetPassword, { password: '', confirm: '' })
    if (account.id === auth.state.user?.id) {
      auth.logout()
      await router.replace('/login')
    } else {
      ElMessage.success(reset ? '密码已重置，旧登录会话已失效。' : '账号已更新，旧登录会话已失效。')
      await loadAccounts()
    }
  } catch (e) {
    manageError.value = errorText(e)
  } finally {
    managing.value = false
  }
}

function validatePassword(value, confirm) {
  const bytes = new TextEncoder().encode(value).length
  if (bytes < 8 || bytes > 72) return '密码长度需为 8–72 字节（中文通常占 3 字节）。'
  if (value !== confirm) return '两次输入的密码不一致。'
  return ''
}

async function loadAccounts() {
  loading.value = true
  listError.value = ''
  try {
    const { data } = await api.get('/users', { params: { page: page.value, page_size: 10 } })
    accounts.value = data.items
    total.value = data.total
  } catch (e) {
    listError.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function createAccount() {
  createError.value = validatePassword(newAccount.password, newAccount.confirm)
  if (createError.value) return
  const username = newAccount.username.trim()
  if (!username || username.length > 80 || !/^[\p{L}\p{N}_.-]+$/u.test(username)) {
    createError.value = '用户名限 1–80 位，可使用中文、字母、数字、下划线、点和短横线。'
    return
  }
  creating.value = true
  try {
    await api.post('/users', {
      username,
      password: newAccount.password,
      role: newAccount.role,
    })
    Object.assign(newAccount, { username: '', password: '', confirm: '', role: 'user' })
    ElMessage.success('账号已建立，可使用新账号登录。')
    page.value = Math.max(1, Math.ceil((total.value + 1) / 10))
    await loadAccounts()
  } catch (e) {
    createError.value = errorText(e)
  } finally {
    creating.value = false
  }
}

async function changePassword() {
  passwordError.value = validatePassword(password.next, password.confirm)
  if (passwordError.value) return
  changing.value = true
  try {
    await api.post('/auth/password', { old_password: password.old, new_password: password.next })
    Object.assign(password, { old: '', next: '', confirm: '' })
    auth.logout()
    await router.replace({ path: '/login', query: { password_changed: '1' } })
  } catch (e) {
    passwordError.value = errorText(e)
  } finally {
    changing.value = false
  }
}

onMounted(() => {
  if (auth.isAdmin.value) loadAccounts()
})
</script>

<template>
  <div class="accounts-page">
    <section v-if="auth.isAdmin.value" class="panel" aria-labelledby="accounts-heading">
      <div class="section-title">
        <div>
          <h2 id="accounts-heading">登录账号</h2>
          <p>共 {{ total }} 个账号 · 密码保存后不可查看</p>
        </div>
        <el-button :loading="loading" @click="loadAccounts">
          <Icon name="refresh" :size="16" />刷新列表
        </el-button>
      </div>
      <el-alert
        v-if="listError"
        :title="listError"
        type="error"
        :closable="false"
        show-icon
        class="mb20"
        role="alert"
      />
      <el-table v-loading="loading" :data="accounts" empty-text="暂无账号">
        <el-table-column prop="username" label="用户名" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.username }}
            <el-tag v-if="row.id === auth.state.user?.id" size="small" type="info">当前账号</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="120">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'success' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="95">
          <template #default="{ row }"
            ><el-tag :type="row.is_active ? 'success' : 'danger'" size="small">{{
              row.is_active ? '已启用' : '已停用'
            }}</el-tag></template
          >
        </el-table-column>
        <el-table-column label="创建时间" min-width="190">
          <template #default="{ row }">{{ dateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="185">
          <template #default="{ row }">
            <el-button size="small" @click="editAccount(row)">权限与状态</el-button>
            <el-button size="small" @click="openReset(row)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="total > 10"
        v-model:current-page="page"
        :page-size="10"
        :total="total"
        layout="prev, pager, next"
        class="accounts-pagination"
        @current-change="loadAccounts"
      />
    </section>

    <div class="account-forms" :class="{ 'personal-only': !auth.isAdmin.value }">
      <section v-if="auth.isAdmin.value" class="panel" aria-labelledby="create-heading">
        <div class="section-title">
          <div>
            <h2 id="create-heading">新增账号</h2>
            <p>创建后即可登录，账号和密码会持续保存。</p>
          </div>
          <Icon name="user" />
        </div>
        <el-alert
          v-if="createError"
          :title="createError"
          type="error"
          :closable="false"
          show-icon
          class="mb20"
          role="alert"
        />
        <el-form label-position="top" :disabled="creating" @submit.prevent="createAccount">
          <el-form-item label="新账号用户名" for="new-username">
            <el-input
              id="new-username"
              v-model="newAccount.username"
              maxlength="80"
              autocomplete="off"
              placeholder="中文、字母、数字、下划线、点或短横线"
              required
            />
          </el-form-item>
          <el-form-item label="账号角色" for="new-role">
            <el-select id="new-role" v-model="newAccount.role">
              <el-option label="普通用户" value="user" />
              <el-option label="管理员" value="admin" />
            </el-select>
          </el-form-item>
          <p class="helper role-help">
            {{
              newAccount.role === 'admin'
                ? '管理员可管理账号、修改防护策略和启动评测。'
                : '普通用户可进行安全测试，并查看自己的记录。'
            }}
          </p>
          <el-form-item label="初始密码" for="new-password">
            <el-input
              id="new-password"
              v-model="newAccount.password"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="建议使用 8 位以上字母、数字与符号组合"
              required
            />
          </el-form-item>
          <el-form-item label="确认初始密码" for="new-confirm">
            <el-input
              id="new-confirm"
              v-model="newAccount.confirm"
              type="password"
              show-password
              autocomplete="new-password"
              required
            />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="creating">建立账号</el-button>
        </el-form>
      </section>

      <section class="panel" aria-labelledby="password-heading">
        <div class="section-title">
          <div>
            <h2 id="password-heading">修改我的密码</h2>
            <p>当前账号：{{ auth.state.user?.username }}</p>
          </div>
          <Icon name="lock" />
        </div>
        <el-alert
          v-if="passwordError"
          :title="passwordError"
          type="error"
          :closable="false"
          show-icon
          class="mb20"
          role="alert"
        />
        <el-form label-position="top" :disabled="changing" @submit.prevent="changePassword">
          <el-form-item label="当前密码" for="current-password">
            <el-input
              id="current-password"
              v-model="password.old"
              type="password"
              show-password
              autocomplete="current-password"
              required
            />
          </el-form-item>
          <el-form-item label="新密码" for="change-password">
            <el-input
              id="change-password"
              v-model="password.next"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="建议使用 8 位以上字母、数字与符号组合"
              required
            />
          </el-form-item>
          <el-form-item label="确认新密码" for="change-confirm">
            <el-input
              id="change-confirm"
              v-model="password.confirm"
              type="password"
              show-password
              autocomplete="new-password"
              required
            />
          </el-form-item>
          <p class="helper password-help">保存后需重新登录，其他已登录的窗口也会退出。</p>
          <el-button type="primary" native-type="submit" :loading="changing">更新密码</el-button>
        </el-form>
      </section>
    </div>
    <el-dialog
      :model-value="!!editing"
      title="调整账号权限与状态"
      width="480px"
      :close-on-click-modal="false"
      @close="editing = null"
    >
      <p class="helper mb20">
        账号：{{ editing?.username }}。保存变更后，该账号的旧登录会话失效；历史记录保留。
      </p>
      <el-alert
        v-if="manageError"
        :title="manageError"
        type="error"
        :closable="false"
        class="mb20"
        role="alert"
      />
      <el-form label-position="top" :disabled="managing" @submit.prevent="manageAccount(false)">
        <el-form-item label="角色"
          ><el-select v-model="accountUpdate.role" aria-label="调整账号角色"
            ><el-option label="普通用户" value="user" /><el-option
              label="管理员"
              value="admin" /></el-select
        ></el-form-item>
        <el-form-item label="允许登录"
          ><el-switch v-model="accountUpdate.is_active" aria-label="允许账号登录"
        /></el-form-item>
        <p class="helper mb20">最后一个有效管理员不能被停用或降级。</p>
        <el-button native-type="submit" type="primary" :loading="managing">保存账号设置</el-button>
      </el-form>
    </el-dialog>
    <el-dialog
      :model-value="!!resetting"
      title="重置账号密码"
      width="480px"
      :close-on-click-modal="false"
      @close="resetting = null"
    >
      <p class="helper mb20">
        账号：{{ resetting?.username }}。原密码不可查看，重置后需使用新密码重新登录。
      </p>
      <el-alert
        v-if="manageError"
        :title="manageError"
        type="error"
        :closable="false"
        class="mb20"
        role="alert"
      />
      <el-form label-position="top" :disabled="managing" @submit.prevent="manageAccount(true)">
        <el-form-item label="重置后的密码" for="reset-password"
          ><el-input
            id="reset-password"
            v-model="resetPassword.password"
            type="password"
            show-password
            autocomplete="new-password"
            required
        /></el-form-item>
        <el-form-item label="再次确认密码" for="reset-confirm"
          ><el-input
            id="reset-confirm"
            v-model="resetPassword.confirm"
            type="password"
            show-password
            autocomplete="new-password"
            required
        /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="managing">确认重置密码</el-button>
      </el-form>
    </el-dialog>
  </div>
</template>

<style scoped>
.account-forms {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  align-items: start;
}
.account-forms.personal-only {
  grid-template-columns: minmax(0, 620px);
}
.account-forms .el-select {
  width: 100%;
}
.role-help {
  margin: -8px 0 20px;
}
.password-help {
  margin-bottom: 20px;
}
.accounts-pagination {
  margin-top: 20px;
  justify-content: flex-end;
}
@media (max-width: 1000px) {
  .account-forms {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
}
</style>
