<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">?</span>
        <span class="brand-title">校园领域智能问答系统</span>
      </div>
      <div v-if="healthError" class="health-error">⚠ 服务未连接：请确认后端已启动（127.0.0.1:8000）</div>
      <div v-else-if="health" class="health-ok">
        <span class="chip"><span class="chip-label">模型</span><span class="chip-val">{{ modelName }}</span></span>
        <span class="chip"><span class="chip-label">索引</span><span class="chip-val">{{ health.index.size }} 块 / {{ health.index.dim }} 维</span></span>
        <span class="chip"><span class="chip-label">语料</span><span class="chip-val">{{ health.corpus.docs }} 份 / {{ health.corpus.chunks }} 块</span></span>
        <span class="chip" :class="health.ollama.ok ? 'chip-ok' : 'chip-err'">
          <span class="chip-label">Ollama</span><span class="chip-val">{{ health.ollama.ok ? '正常' : '异常' }}</span>
        </span>
      </div>
      <div v-else class="health-loading">正在连接后端…</div>

      <div class="topbar-spacer"></div>

      <!-- 用户区 -->
      <div v-if="currentUser" class="user-area">
        <span class="role-badge" :class="currentUser.role === 'admin' ? 'role-admin' : 'role-student'">
          {{ currentUser.role === 'admin' ? '管理员' : '学生' }}
        </span>
        <span class="user-name">{{ currentUser.display_name || currentUser.username }}</span>
        <el-button v-if="currentUser.role === 'admin'" class="admin-link" text type="primary" @click="$router.push('/admin')">
          管理后台
        </el-button>
        <el-button text @click="doLogout">退出登录</el-button>
      </div>
    </header>

    <div class="main">
      <SessionSidebar
        :sessions="sessions"
        :current-session-id="currentSessionId"
        @select="selectSession"
        @create="createNewSession"
        @delete="removeSession"
      />
      <ChatPanel
        :messages="messages"
        :streaming="streaming"
        @send="sendQuestion"
        @stop="stopGeneration"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watchEffect, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import SessionSidebar from '../components/SessionSidebar.vue'
import ChatPanel from '../components/ChatPanel.vue'
import { fetchHealth, listSessions, createSession, getMessages, deleteSession } from '../api/client'
import { fetchMe, logout } from '../api/auth'
import { useChatStream } from '../composables/useChatStream'

const router = useRouter()

const {
  streaming, answer, sources, retrieved, refused, judge, timing, error, ask, abort,
} = useChatStream()

const messages = ref([])
const sessions = ref([])
const currentSessionId = ref(null)
const health = ref(null)
const healthError = ref('')
const currentUser = ref(null)

const modelName = computed(() => {
  const models = health.value?.ollama?.models || []
  if (!models.length) return '未知'
  return models[0].replace(/:latest$/, '')
})

async function loadHealth() {
  try {
    health.value = await fetchHealth()
    healthError.value = ''
  } catch (e) {
    health.value = null
    healthError.value = '后端未连接'
  }
}

async function loadSessions() {
  try {
    sessions.value = await listSessions()
  } catch (e) {
    sessions.value = []
  }
}

async function selectSession(sid) {
  currentSessionId.value = sid
  messages.value = []
  try {
    const msgs = await getMessages(sid)
    messages.value = msgs.map((m, i) => ({
      id: `${sid}-${i}`,
      role: m.role,
      content: m.content,
      sources: m.sources || [],
      retrieved: [],
      refused: false,
      judge: null,
      timing: null,
      streaming: false,
      error: '',
    }))
  } catch (e) {
    messages.value = []
  }
}

async function createNewSession() {
  try {
    const s = await createSession()
    sessions.value.unshift(s)
    currentSessionId.value = s.session_id
    messages.value = []
  } catch (e) {
    healthError.value = '创建会话失败'
  }
}

async function removeSession(sid) {
  try {
    await deleteSession(sid)
    sessions.value = sessions.value.filter((s) => s.session_id !== sid)
    if (currentSessionId.value === sid) {
      currentSessionId.value = null
      messages.value = []
    }
  } catch (e) {
    healthError.value = '删除会话失败'
  }
}

async function sendQuestion(question) {
  if (streaming.value) return

  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: question })

  const assistantMsg = reactive({
    id: `a-${Date.now()}`,
    role: 'assistant',
    content: '',
    sources: [],
    retrieved: [],
    refused: false,
    judge: null,
    timing: { retrieve: 0, judge: 0, generate: 0, total: 0 },
    streaming: true,
    error: '',
  })
  messages.value.push(assistantMsg)

  const stop = watchEffect(() => {
    assistantMsg.content = answer.value
    assistantMsg.sources = sources.value
    assistantMsg.retrieved = retrieved.value
    assistantMsg.refused = refused.value
    assistantMsg.judge = judge.value
    assistantMsg.timing = { ...timing.value }
    assistantMsg.error = error.value
  })

  await ask(question, currentSessionId.value)

  assistantMsg.streaming = false
  stop()

  loadSessions()
}

function stopGeneration() {
  abort()
}

async function doLogout() {
  await logout()
  router.push('/login')
}

onMounted(async () => {
  loadHealth()
  loadSessions()
  try {
    currentUser.value = await fetchMe()
  } catch (e) {
    currentUser.value = null
  }
})
</script>

<style scoped>
.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg-page);
}
.topbar {
  height: 56px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: 0 var(--sp-5);
  background: var(--c-bg-card);
  border-bottom: 1px solid var(--c-border);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-right: var(--sp-2);
}
.brand-mark {
  width: 20px;
  height: 20px;
  border-radius: var(--r-sm);
  background: var(--c-primary);
  color: var(--c-white);
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.brand-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
  white-space: nowrap;
}
.health-ok {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--r-sm);
  background: var(--c-bg-hover);
}
.chip-label {
  color: var(--c-text-3);
}
.chip-val {
  color: var(--c-text-2);
  font-weight: 500;
}
.chip-ok {
  background: var(--c-success-bg);
}
.chip-ok .chip-val {
  color: var(--c-success);
}
.chip-err {
  background: var(--c-danger-bg);
}
.chip-err .chip-val {
  color: var(--c-danger);
}
.health-error {
  font-size: 13px;
  color: var(--c-danger);
  font-weight: 600;
}
.health-loading {
  font-size: 13px;
  color: var(--c-text-3);
}
.topbar-spacer {
  flex: 1;
}
.user-area {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}
.role-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: var(--r-sm);
}
.role-admin {
  background: var(--c-primary-light);
  color: var(--c-primary);
}
.role-student {
  background: var(--c-bg-hover);
  color: var(--c-text-2);
}
.user-name {
  font-size: 14px;
  color: var(--c-text-1);
  font-weight: 500;
}
.admin-link {
  margin-left: var(--sp-1);
}
.main {
  flex: 1;
  display: flex;
  min-height: 0;
  gap: 0;
}
</style>
