<template>
  <div ref="rootEl" class="msg" :class="message.role" @click="onCiteClick">
    <!-- 用户消息：右侧蓝色气泡 -->
    <div v-if="message.role === 'user'" class="user-bubble">{{ message.content }}</div>

    <!-- 助手消息：左侧白卡片 -->
    <div v-else class="assistant-card">
      <div v-if="message.streaming && !message.content && !message.refused" class="loading">
        <span class="loading-dots"><i></i><i></i><i></i></span>
        <span>{{ message.sources.length ? '正在生成…' : '正在检索…' }}</span>
      </div>

      <RefuseNotice
        v-if="message.refused"
        :text="message.content || defaultRefuseText"
        :stage="message.judge?.stage || ''"
        :retrieved="message.retrieved || []"
      />

      <div v-else-if="message.content" class="assistant-text markdown" v-html="rendered"></div>

      <span v-if="message.streaming && message.content && !message.refused" class="cursor"></span>

      <div v-if="message.error" class="msg-error">出错了：{{ message.error }}</div>

      <div v-if="!message.refused && message.sources && message.sources.length" class="sources">
        <div class="sources-title">引用来源（{{ message.sources.length }}）</div>
        <div class="sources-list">
          <SourceCard v-for="s in message.sources" :key="s.chunk_id" :source="s" />
        </div>
      </div>

      <!-- ★ 检索候选（未采用）：让用户/演示者看到"系统还找到了什么、相关度多少"，
           也为"为什么这么答"提供依据。默认收起，不干扰正常阅读。 -->
      <div
        v-if="!message.streaming && !message.refused && extraCandidates.length"
        class="cand"
      >
        <div class="cand-toggle" @click="showCandidates = !showCandidates">
          检索候选（未采用 {{ extraCandidates.length }} 条）{{ showCandidates ? '▲' : '▼' }}
        </div>
        <div v-if="showCandidates" class="cand-list">
          <div v-for="c in extraCandidates" :key="c.chunk_id" class="cand-item">
            <span class="cand-idx">{{ c.idx }}</span>
            <span class="cand-title">{{ c.doc_title }}</span>
            <span v-if="c.heading_path" class="cand-heading">{{ tailHeading(c.heading_path) }}</span>
            <span class="cand-score">{{ c.score.toFixed(4) }}</span>
          </div>
          <div class="cand-note">
            相关度分数为稠密向量相似度；低于阈值或未被判定采用的不计入引用。
          </div>
        </div>
      </div>

      <div v-if="!message.streaming && message.timing" class="timing">
        检索 {{ fmt(message.timing.retrieve) }}s · 判定 {{ fmt(message.timing.judge) }}s · 生成 {{ fmt(message.timing.generate) }}s · 合计 {{ fmt(message.timing.total) }}s
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { marked } from 'marked'
import SourceCard from './SourceCard.vue'
import RefuseNotice from './RefuseNotice.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const defaultRefuseText = '知识库中未找到相关依据。建议咨询学校相关部门获取准确信息。'
const rootEl = ref(null)

const rendered = computed(() => {
  let html
  try {
    html = marked.parse(props.message.content || '')
  } catch (e) {
    html = props.message.content || ''
  }
  // 把正文里的 [1][2] 渲染成可点击的引用标签
  return html.replace(/\[(\d+)\]/g, '<span class="cite-ref" data-idx="$1">[$1]</span>')
})

function onCiteClick(e) {
  const el = e.target.closest('.cite-ref')
  if (!el || !rootEl.value) return
  const idx = el.dataset.idx
  const card = rootEl.value.querySelector(`.source-card[data-idx="${idx}"]`)
  if (card) {
    card.scrollIntoView({ behavior: 'smooth', block: 'center' })
    card.classList.add('flash')
    setTimeout(() => card.classList.remove('flash'), 1500)
  }
}

function fmt(v) {
  return (v ?? 0).toFixed(2)
}

const showCandidates = ref(false)

/** 检索候选中【未被引用】的部分（后端 retrieved 与 sources 结构相同，按 chunk_id 差集） */
const extraCandidates = computed(() => {
  const ret = props.message.retrieved || []
  if (!ret.length) return []
  const used = new Set((props.message.sources || []).map((s) => s.chunk_id))
  return ret.filter((c) => !used.has(c.chunk_id))
})

/** heading_path 通常以文档标题开头，列表里只显示末段章节名 */
function tailHeading(hp) {
  const parts = String(hp || '').split('>')
  return parts[parts.length - 1].trim()
}
</script>

<style scoped>
.msg {
  display: flex;
}
.msg.user {
  justify-content: flex-end;
}
.msg.assistant {
  justify-content: flex-start;
}
/* 用户气泡 */
.user-bubble {
  max-width: 70%;
  background: var(--c-primary);
  color: var(--c-white);
  padding: 10px 14px;
  border-radius: var(--r-lg);
  border-top-right-radius: var(--r-sm);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
/* 助手卡片 */
.assistant-card {
  position: relative;
  width: 100%;
  background: var(--c-bg-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  border-top-left-radius: var(--r-sm);
  padding: var(--sp-4);
  box-shadow: var(--sh-1);
}
.assistant-card::before {
  content: '';
  position: absolute;
  left: -1px;
  top: var(--sp-3);
  bottom: var(--sp-3);
  width: 3px;
  border-radius: 2px;
  background: var(--c-primary);
}
.assistant-text {
  font-size: 14px;
  line-height: 1.75;
  color: var(--c-text-2);
  word-break: break-word;
}
.markdown :deep(p) {
  margin: 0 0 8px;
}
.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 0 0 8px;
  padding-left: 20px;
}
.markdown :deep(li) {
  margin: 2px 0;
}
.markdown :deep(strong) {
  font-weight: 600;
  color: var(--c-text-1);
}
.markdown :deep(code) {
  background: var(--c-bg-hover);
  border-radius: var(--r-sm);
  padding: 1px 5px;
  font-size: 13px;
}
.markdown :deep(.cite-ref) {
  background: var(--c-primary-light);
  color: var(--c-primary);
  border-radius: var(--r-sm);
  padding: 0 4px;
  font-size: 12px;
  vertical-align: super;
  cursor: pointer;
}
.markdown :deep(.cite-ref:hover) {
  text-decoration: underline;
}
.loading {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--c-text-3);
  font-size: 13px;
  padding: var(--sp-2) 0;
}
.loading-dots {
  display: inline-flex;
  gap: 3px;
}
.loading-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--c-text-3);
  animation: bounce 1s infinite;
}
.loading-dots i:nth-child(2) {
  animation-delay: 0.15s;
}
.loading-dots i:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes bounce {
  0%, 100% { transform: translateY(0); opacity: 0.4; }
  50% { transform: translateY(-3px); opacity: 1; }
}
.cursor {
  display: inline-block;
  width: 1px;
  height: 1em;
  background: var(--c-primary);
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
.sources {
  margin-top: var(--sp-4);
}
.sources-title {
  font-size: 13px;
  color: var(--c-text-3);
  margin-bottom: var(--sp-2);
}
.sources-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
/* 检索候选（未采用） */
.cand {
  margin-top: var(--sp-3);
  border-top: 1px dashed var(--c-border);
  padding-top: var(--sp-2);
}
.cand-toggle {
  font-size: 12px;
  color: var(--c-text-3);
  cursor: pointer;
}
.cand-toggle:hover {
  color: var(--c-primary);
}
.cand-list {
  margin-top: var(--sp-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cand-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 12px;
  padding: 3px var(--sp-2);
  background: var(--c-bg-page);
  border-radius: var(--r-sm);
}
.cand-idx {
  width: 16px;
  height: 16px;
  border-radius: var(--r-sm);
  background: var(--c-text-4);
  color: var(--c-white);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.cand-title {
  color: var(--c-text-2);
  flex-shrink: 0;
  max-width: 42%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cand-heading {
  color: var(--c-text-4);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cand-score {
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.cand-note {
  margin-top: var(--sp-1);
  font-size: 11px;
  color: var(--c-text-4);
  line-height: 1.6;
}
.timing {
  margin-top: var(--sp-3);
  font-size: 11px;
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}
.msg-error {
  color: var(--c-danger);
  font-size: 13px;
  margin-top: var(--sp-2);
}
</style>

<style>
/* 引用卡片点击高亮（跨组件） */
.source-card.flash {
  animation: cite-flash 1.5s ease;
}
@keyframes cite-flash {
  0%, 100% { border-color: var(--c-primary-border); }
  50% { border-color: var(--c-primary); }
}
</style>
