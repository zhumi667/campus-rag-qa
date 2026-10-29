<template>
  <div class="app">
    <header class="topbar">
      <button
        class="nav-toggle"
        type="button"
        aria-label="会话列表"
        @click="sidebarOpen = !sidebarOpen"
      >☰</button>
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
        <span class="user-name">{{ currentUser.display_name || currentUser.username }}</span>
        <el-button v-if="currentUser.role === 'admin'" class="admin-link" text type="primary" @click="$router.push('/admin')">
          管理后台
        </el-button>
        <el-button text type="primary" @click="openDocs">已收录资料</el-button>
        <el-button text @click="doLogout">退出登录</el-button>
      </div>
    </header>

    <div class="main">
      <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false"></div>
      <SessionSidebar
        :open="sidebarOpen"
        :sessions="sessions"
        :current-session-id="currentSessionId"
        @select="selectSession"
        @create="createNewSession"
        @delete="removeSession"
        @close="sidebarOpen = false"
      />
      <ChatPanel
        :messages="messages"
        :streaming="streaming"
        @send="sendQuestion"
        @stop="stopGeneration"
      />
    </div>

    <!-- size 用 min() 而非写死 420px：Element Plus 把 size 原样作为 CSS width
         （见 element-plus/es/components/drawer 中 style 绑定 width: size），
         因此窄屏（375px）下不会超出视口。 -->
    <el-drawer v-model="docsOpen" title="已收录资料" size="min(420px, 92vw)" direction="rtl">
      <div v-if="docsLoading" class="docs-loading">正在加载…</div>
      <div v-else class="docs-list">
        <!-- key 用 title + version：库里可能出现同名文档（如两年同名通知），
             仅用 title 会触发 Vue 的重复 key 警告并导致渲染复用错乱 -->
        <div v-for="d in docsList" :key="`${d.title}|${d.version}`" class="docs-item">
          <div class="docs-title">{{ d.title }}</div>
          <div class="docs-meta">
            <template v-if="d.effective_date">{{ d.effective_date }} 起施行</template>
            <template v-else>未标注生效日期</template>
            <template v-if="d.version">　·　版本 {{ d.version }}</template>
            <template v-if="d.chars">　·　{{ d.chars }} 字</template>
          </div>
        </div>
        <div v-if="!docsList.length" class="docs-empty">暂无已收录资料</div>
        <div class="docs-note">
          以上为当前有效的资料。未收录的问题系统会明确提示“未找到依据”，不会编造答案。
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watchEffect, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import SessionSidebar from '../components/SessionSidebar.vue'
import ChatPanel from '../components/ChatPanel.vue'
import { fetchHealth, listSessions, createSession, getMessages, deleteSession, fetchCorpusDocs } from '../api/client'
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

// 窄屏会话抽屉开关（桌面端不显示按钮，此值恒为 false，无副作用）
const sidebarOpen = ref(false)

// 「已收录资料」抽屉：懒加载，点开时才请求
const docsOpen = ref(false)
const docsLoading = ref(false)
const docsList = ref([])

async function openDocs() {
  docsOpen.value = true
  if (docsList.value.length) return      // 已加载过就不重复请求
  docsLoading.value = true
  try {
    docsList.value = await fetchCorpusDocs()
  } catch (e) {
    docsList.value = []
  } finally {
    docsLoading.value = false
  }
}

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
  height: 100dvh;
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

/* ── 窄屏适配 ──────────────────────────────────────── */
/* 默认（桌面）不显示，保持原样 */
.nav-toggle {
  display: none;
}

.sidebar-mask {
  display: none;
}

@media (max-width: 768px) {
  .nav-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    margin-right: var(--sp-2, 8px);
    border: 1px solid var(--c-border, #dcdfe6);
    border-radius: var(--r-sm, 4px);
    background: var(--c-bg-card, #fff);
    color: var(--c-text-2, #606266);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    flex-shrink: 0;
  }

  .sidebar-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 999;
    background: rgba(0, 0, 0, 0.4);
  }

  /* 顶栏在窄屏允许换行，避免溢出 */
  .topbar {
    flex-wrap: wrap;
    row-gap: 4px;
    padding-top: 6px;
    padding-bottom: 6px;
    /* ★ 必须放开固定高度：原 .topbar 是 height: 56px，
       允许换行后第二行会溢出到 56px 盒子外、压住下面的聊天区。 */
    height: auto;
    min-height: 56px;
  }

  .brand-title {
    font-size: 14px;
  }
}

/* 更窄（≤560px）时隐藏顶栏的状态标签，防止挤成一团 */
@media (max-width: 560px) {
  .chip {
    display: none;
  }

  .user-name {
    display: none;
  }
}

/* ── 已收录资料抽屉 ───────────────────────────────── */
.docs-loading {
  padding: var(--sp-4);
  font-size: 13px;
  color: var(--c-text-3);
}

.docs-item {
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--c-border);
}

.docs-item:last-of-type {
  border-bottom: none;
}

.docs-title {
  font-size: 13.5px;
  color: var(--c-text-1);
  line-height: 1.6;
  margin-bottom: 2px;
}

.docs-meta {
  font-size: 12px;
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.docs-empty {
  padding: var(--sp-4);
  font-size: 13px;
  color: var(--c-text-3);
  text-align: center;
}

.docs-note {
  margin-top: var(--sp-4);
  padding: var(--sp-3);
  background: var(--c-bg-page);
  border-radius: var(--r-md);
  font-size: 12px;
  line-height: 1.7;
  color: var(--c-text-3);
}
</style>
