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
  <main class="access-screen">
    <header class="access-header">
      <a href="/" class="access-brand">
        <span class="access-mark"><Icon name="shield" :size="22" /></span>
        <span class="access-brand-copy">
          <strong>Prompt Sentinel</strong>
          <small>AI 安全控制台</small>
        </span>
      </a>
    </header>
    <div class="access-layout">
      <section class="access-form" aria-labelledby="login-heading">
        <h1 id="login-heading">登录控制台</h1>
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
        <form class="access-fields" @submit.prevent="submit">
          <div class="access-field">
            <label for="username">用户名</label>
            <el-input
              id="username"
              v-model="form.username"
              placeholder="输入用户名"
              autocomplete="username"
              size="large"
              :disabled="loading"
            />
          </div>
          <div class="access-field">
            <label for="password">密码</label>
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
          </div>
          <el-button
            native-type="submit"
            type="primary"
            size="large"
            :loading="loading"
            class="access-submit"
          >
            登录<Icon name="arrow" :size="18" />
          </el-button>
        </form>
        <el-popover placement="bottom-start" :width="252" trigger="click">
          <template #reference>
            <button type="button" class="access-help">无法登录？</button>
          </template>
          <p class="context-help">请联系管理员获取账号或重置密码。</p>
        </el-popover>
      </section>
    </div>
    <div class="access-art" aria-hidden="true"></div>
  </main>
</template>

<style scoped>
.access-screen {
  --access-ink: #192439;
  --access-muted: #5d6b82;
  --access-accent: #2849d8;
  --access-line: #e1e7f0;
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-rows: auto minmax(min-content, 1fr);
  gap: clamp(1.5rem, 5vh, 3.75rem);
  min-height: 100dvh;
  padding: clamp(1.5rem, 4.5vh, 3rem) clamp(2.6rem, 8vw, 9.5rem);
  background: radial-gradient(ellipse at 25% 40%, #fbfcff, #edf2fa 74%);
  color: var(--access-ink);
}

.access-layout {
  display: grid;
  align-items: center;
}

.access-form {
  min-width: 0;
  width: min(100%, 31rem);
  padding: clamp(1.8rem, 3.8vw, 3.4rem);
  margin-block-end: min(5vh, 3rem);
  border: 1px solid #fff;
  border-radius: 22px;
  background: #fafdff;
  box-shadow:
    0 20px 64px #45689e1c,
    0 2px 10px #2945710b;
}

@supports (backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)) {
  .access-form {
    background: #ffffffbc;
    -webkit-backdrop-filter: blur(20px) saturate(130%);
    backdrop-filter: blur(20px) saturate(130%);
  }
}

.access-brand {
  display: inline-flex;
  align-items: center;
  gap: 0.9rem;
  color: var(--access-ink);
  line-height: 1.35;
}

.access-brand:hover {
  color: var(--access-ink);
}

.access-brand-copy {
  display: grid;
  gap: 2px;
}

.access-brand-copy strong {
  font-size: 1.15rem;
  font-weight: 750;
  letter-spacing: -0.025em;
}

.access-brand-copy small {
  color: var(--access-muted);
  font-size: 0.85rem;
}

.access-mark {
  display: grid;
  width: 3rem;
  height: 3rem;
  flex: none;
  place-items: center;
  border-radius: 10px;
  background: #eef2ff;
  color: var(--access-accent);
}

.access-form h1 {
  margin: 0 0 2rem;
  font-size: clamp(1.9rem, 2.7vw, 2.6rem);
  font-weight: 750;
  line-height: 1.22;
  letter-spacing: -0.02em;
}

.access-fields {
  display: grid;
  gap: 1.25rem;
}

.access-field label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 600;
}

.access-field :deep(.el-input__wrapper) {
  min-height: 3.4rem;
  padding-inline: 0.9rem;
  border-radius: 10px;
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--access-line);
}

.access-field :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    inset 0 0 0 1px var(--access-accent),
    0 0 0 3px #2849d81f;
}

.access-field :deep(.el-input__inner) {
  color: var(--access-ink);
  font-size: 1rem;
}

.access-field :deep(.el-input__inner::placeholder) {
  color: #65738c;
}

.access-fields .access-submit {
  width: 100%;
  height: 3.5rem;
  margin-top: 0.45rem;
  border: 1px solid var(--access-accent);
  border-radius: 10px;
  background: var(--access-accent);
  color: #fff;
  font-size: 1rem;
  font-weight: 750;
}

.access-submit:not(.is-loading, :disabled):hover {
  border-color: #203bb6;
  background: #203bb6;
}

.access-submit svg {
  margin-left: 0.25rem;
}

.access-help {
  min-height: 2.75rem;
  margin-top: 0.8rem;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--access-accent);
}

.access-help:hover {
  text-decoration: underline;
  text-underline-offset: 0.25em;
}

.access-art {
  position: absolute;
  z-index: -1;
  inset: 0 0 0 min(24vw, 36rem);
  background: #eaf0fb url('../assets/sentinel-prism.webp') center 53% / cover no-repeat;
  mask-image: linear-gradient(to right, transparent, #000 min(21vw, 20rem));
}

@media (prefers-reduced-transparency: reduce) {
  .access-form {
    background: #fafdff;
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
}

@media (max-width: 800px) {
  .access-screen {
    grid-template-rows: auto auto auto;
    align-content: center;
    gap: 1.15rem;
    padding: 1.3rem max(1.1rem, calc((100% - 33rem) / 2));
    background: radial-gradient(ellipse at 60% 65%, #e6edff, #f8fafe 75%);
  }

  .access-form {
    width: 100%;
    padding: clamp(1.45rem, 5vw, 2.2rem);
    margin-block-end: 0;
    border-radius: 16px;
  }

  .access-art {
    position: relative;
    z-index: auto;
    inset: auto;
    height: clamp(7.75rem, 27vw, 12rem);
    border-radius: 16px;
    background-position: center 50%;
    mask-image: none;
  }
}

@media (max-width: 480px) {
  .access-form h1 {
    margin-bottom: 1.5rem;
  }
}
</style>
