<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { auth } from '../auth'
import { errorText } from '../api'
import Icon from '../components/Icon.vue'
const router = useRouter(),
  route = useRoute(),
  form = reactive({ username: '', password: '' }),
  loading = ref(false),
  error = ref('')
async function submit() {
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
  <div class="login-page">
    <section class="login-art">
      <a class="brand login-brand" href="/"
        ><span class="brand-mark"><Icon name="shield" :size="28" /></span
        ><span><strong>Prompt Sentinel</strong><small>提示词安全研究平台</small></span></a
      >
      <div class="login-intro">
        <div class="eyebrow light">LOCAL AI SECURITY LAB</div>
        <h1>让模型专注任务，<br /><span>让安全有迹可循。</span></h1>
        <p>从输入识别到输出审查，探索提示词注入攻击的边界，验证每一道防线。</p>
        <div
          class="defense-illustration"
          aria-label="五层防御：规则过滤、分类检测、输入审核、提示加固、输出检测"
        >
          <div class="shield-orbit">
            <Icon name="shield" :size="74" /><span class="orbit-dot d1"></span
            ><span class="orbit-dot d2"></span><span class="orbit-dot d3"></span>
          </div>
          <div class="defense-stack">
            <div
              v-for="(name, index) in ['规则过滤', '语义分类', '输入审核', '提示加固', '输出检测']"
              :key="name"
            >
              <span>L{{ index + 1 }}</span
              ><strong>{{ name }}</strong
              ><Icon name="check" :size="15" />
            </div>
          </div>
        </div>
      </div>
      <div class="login-art-footer">
        <span class="live-dot"></span> 五层防护架构 <span>本地模型推理 / 可复现实验</span>
      </div>
    </section>
    <section class="login-form-area">
      <div class="login-card">
        <div class="login-greeting">欢迎回来</div>
        <h2>登录研究工作台</h2>
        <p class="login-subtitle">使用你的账号，开始安全研究。</p>
        <el-alert
          v-if="route.query.expired"
          title="登录已过期，请重新登录。"
          type="warning"
          :closable="false"
          show-icon
          class="mb20"
        /><el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
          class="mb20"
          role="alert"
        />
        <form @submit.prevent="submit">
          <label class="field-label" for="username">用户名</label
          ><el-input
            id="username"
            v-model="form.username"
            placeholder="请输入用户名"
            autocomplete="username"
            size="large"
            :disabled="loading"
            ><template #prefix><Icon name="user" :size="18" /></template></el-input
          ><label class="field-label login-password-label" for="password">密码</label
          ><el-input
            id="password"
            v-model="form.password"
            placeholder="请输入密码"
            type="password"
            show-password
            autocomplete="current-password"
            size="large"
            :disabled="loading"
            ><template #prefix><Icon name="lock" :size="18" /></template></el-input
          ><el-button
            native-type="submit"
            type="primary"
            size="large"
            :loading="loading"
            class="login-submit"
            >{{ loading ? '验证账号中' : '登录工作台'
            }}<Icon v-if="!loading" name="arrow" :size="18"
          /></el-button>
        </form>
        <div class="login-help">
          <Icon name="info" :size="18" />
          <div>
            <strong>首次使用？</strong>
            <p>
              启动后端后，在项目
              <code>.runtime/credentials.json</code> 中查看初始账号密码。安装与账号说明请参阅
              README。
            </p>
          </div>
        </div>
        <p class="login-access"><Icon name="lock" :size="13" /> 管理员可配置防护策略与启动评测</p>
      </div>
      <div class="login-copyright">Prompt Sentinel · 本地安全研究环境</div>
    </section>
  </div>
</template>
