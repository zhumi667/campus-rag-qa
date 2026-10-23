<template>
  <div class="chat-panel">
    <!-- 消息列表 -->
    <div ref="listRef" class="message-list">
      <div class="list-inner">
        <div v-if="!messages.length" class="empty-hint">
          <div class="empty-title">校园领域智能问答系统</div>
          <div class="empty-sub">
            基于校园公开文档的检索增强问答，回答均附原文出处。
          </div>
          <div class="empty-try">
            试试问：<code @click="fillExample">考试不及格可以补考吗</code>
          </div>
        </div>
        <MessageItem v-for="m in messages" :key="m.id" :message="m" />
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <div class="input-inner">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          :autosize="{ minRows: 2, maxRows: 5 }"
          placeholder="输入问题…"
          :disabled="streaming"
          @keydown="onKeydown"
        />
        <div class="input-actions">
          <span v-if="streaming" class="streaming-hint">正在生成…</span>
          <span v-else class="input-tip">Enter 发送 · Shift+Enter 换行</span>
          <div class="input-btns">
            <el-button v-if="streaming" type="danger" plain @click="$emit('stop')">停止</el-button>
            <el-button v-else type="primary" :disabled="!canSend" @click="send">发送</el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import MessageItem from './MessageItem.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
})

const emit = defineEmits(['send', 'stop'])

const input = ref('')
const listRef = ref(null)

const canSend = computed(() => input.value.trim() && !props.streaming)

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function send() {
  if (!canSend.value) return
  const q = input.value.trim()
  input.value = ''
  emit('send', q)
}

/** 点击空状态示例问题：填入输入框（不自动发送，让用户可先修改） */
function fillExample() {
  if (props.streaming) return
  input.value = '考试不及格可以补考吗'
}

watch(() => props.messages.length, async () => {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
})
</script>

<style scoped>
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
}
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4) 0;
}
.list-inner {
  max-width: 820px;
  margin: 0 auto;
  padding: 0 var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.empty-hint {
  text-align: center;
  color: var(--c-text-3);
  margin-top: 15vh;
}
.empty-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--c-text-1);
  margin-bottom: var(--sp-2);
}
.empty-sub {
  font-size: 13px;
}
.empty-try {
  margin-top: var(--sp-3);
  font-size: 13px;
}
.empty-try code {
  display: inline-block;
  padding: 3px 10px;
  border-radius: var(--r-md);
  border: 1px solid var(--c-primary-border);
  background: var(--c-primary-light);
  color: var(--c-primary);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
}
.empty-try code:hover {
  background: var(--c-white);
}
.input-area {
  border-top: 1px solid var(--c-border);
  padding: var(--sp-4);
  background: var(--c-bg-card);
  flex-shrink: 0;
}
.input-inner {
  max-width: 820px;
  margin: 0 auto;
}
.input-inner :deep(.el-textarea__inner) {
  border-radius: var(--r-md);
  border-color: var(--c-border);
  box-shadow: none;
  font-size: 14px;
  line-height: 1.7;
  padding: var(--sp-3);
}
.input-inner :deep(.el-textarea__inner:focus) {
  border-color: var(--c-primary);
  box-shadow: 0 0 0 2px var(--c-primary-light);
}
.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--sp-2);
}
.streaming-hint {
  color: var(--c-primary);
  font-size: 12px;
}
.input-tip {
  color: var(--c-text-3);
  font-size: 12px;
}
.input-btns {
  display: flex;
  gap: var(--sp-2);
}
</style>
