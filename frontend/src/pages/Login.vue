<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { auth } from '../auth'
import { errorText } from '../api'
import Icon from '../components/Icon.vue'
const router = useRouter(),
  route = useRoute()
const form = reactive({ username: '', password: '' }),
  loading = ref(false),
  error = ref('')
async function submit() {
  if (loading.value) return
  if (!form.username.trim() || !form.password) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await auth.login(form)
    const next = route.query.redirect
    router.replace(
      typeof next === 'string' && next.startsWith('/') && !next.startsWith('//')
        ? next
        : '/dashboard'
    )
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
</script>
<template>
  <main class="login-surface">
    <a href="/" class="login-identity"
      ><span class="brand-mark"><Icon name="shield" :size="25" /></span
      ><strong>Prompt Sentinel</strong></a
    >
    <section class="login-auth-card">
      <h1>登录控制台</h1>
      <p class="login-intro-copy">欢迎回来</p>
      <el-alert
        v-if="route.query.password_changed"
        title="密码已更新，请重新登录"
        type="success"
        :closable="false"
        show-icon
        class="mb20"
      />
      <el-alert
        v-if="route.query.expired"
        title="登录已过期，请重新登录"
        type="warning"
        :closable="false"
        show-icon
        class="mb20"
      />
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
        show-icon
        class="mb20"
        role="alert"
      />
      <form @submit.prevent="submit">
        <label class="field-label" for="username">用户名</label>
        <el-input
          id="username"
          v-model="form.username"
          placeholder="输入用户名"
          autocomplete="username"
          size="large"
          :disabled="loading"
        />
        <label class="field-label login-password-label" for="password">密码</label>
        <el-input
          id="password"
          v-model="form.password"
          type="password"
          placeholder="输入密码"
          show-password
          autocomplete="current-password"
          size="large"
          :disabled="loading"
        />
        <el-button
          native-type="submit"
          type="primary"
          size="large"
          :loading="loading"
          class="login-submit"
          >登录</el-button
        >
      </form>
      <el-popover placement="bottom" :width="270" trigger="click">
        <template #reference><button class="login-support">无法登录？</button></template>
        <p class="context-help">请联系管理员获取账号或重置密码。</p>
      </el-popover>
    </section>
    <footer class="login-legal">Prompt Sentinel · AI 安全控制台</footer>
  </main>
</template>
