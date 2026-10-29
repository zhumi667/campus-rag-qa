<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <span class="brand-mark">?</span>
        <span class="brand-title">校园领域智能问答系统</span>
      </div>
      <div class="login-sub">基于校园公开文档的检索增强问答</div>

      <el-input
        v-model="username"
        class="field"
        placeholder="用户名"
        autocomplete="username"
        @keydown.enter="submit"
      />
      <el-input
        v-model="password"
        class="field"
        type="password"
        placeholder="密码"
        autocomplete="current-password"
        show-password
        @keydown.enter="submit"
      />

      <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

      <el-button
        class="login-btn"
        type="primary"
        :loading="loading"
        @click="submit"
      >登 录</el-button>

      <div class="demo-hint">
        <div class="demo-line">演示账号：管理员 <b>admin / admin123</b></div>
        <div class="demo-line">　　　　　学生　<b>student / student123</b></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { login } from '../api/auth'

const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function submit() {
  if (loading.value) return
  errorMsg.value = ''

  // ★ 原实现是 `if (!username || !password) return` —— 什么都不做也不提示。
  //   浏览器自动填充（或首次进入时字段还没同步到 v-model）会让第一次点击
  //   静默失败，用户以为"点了没反应"，再点一次才进去。这里改为明确提示。
  if (!username.value || !password.value) {
    errorMsg.value = '请输入用户名和密码'
    return
  }

  loading.value = true
  try {
    // 用户名去除首尾空格：从浏览器自动填充或粘贴时经常带进不可见空格，
    // 后端按原样比对会导致"密码明明对却返回 401"。
    // 密码不做 trim —— 空格可能是密码的一部分。
    await login(username.value.trim(), password.value)

    // 只接受站内相对路径，避免 redirect 参数被用来跳出站点
    const q = route.query.redirect
    const redirect = typeof q === 'string' && q.startsWith('/') ? q : '/'

    // ★ await：确保跳转完成后才结束 loading 状态，
    //   否则按钮会先恢复可点、页面还停在登录页，用户容易重复点击。
    await router.push(redirect)
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || '登录失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--c-bg-page);
  padding: var(--sp-4);
}
.login-card {
  width: min(380px, 92vw);
  background: var(--c-bg-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  padding: var(--sp-6);
  box-shadow: var(--sh-2);
}
.login-brand {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
}
.brand-mark {
  width: 24px;
  height: 24px;
  border-radius: var(--r-sm);
  background: var(--c-primary);
  color: var(--c-white);
  font-size: 16px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.brand-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--c-text-1);
}
.login-sub {
  font-size: 13px;
  color: var(--c-text-3);
  margin-bottom: var(--sp-5);
}
.field {
  margin-bottom: var(--sp-3);
}
.error-msg {
  color: var(--c-danger);
  font-size: 13px;
  margin-bottom: var(--sp-3);
}
.login-btn {
  width: 100%;
  height: 38px;
  border-radius: var(--r-md);
  margin-bottom: var(--sp-4);
}
.demo-hint {
  border-top: 1px solid var(--c-border);
  padding-top: var(--sp-3);
  font-size: 12px;
  color: var(--c-text-3);
  line-height: 1.9;
}
.demo-line b {
  color: var(--c-text-2);
  font-weight: 500;
}
</style>
