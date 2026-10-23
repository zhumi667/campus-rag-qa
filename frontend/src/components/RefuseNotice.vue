<template>
  <div class="refuse-notice">
    <div class="refuse-main">
      <span class="refuse-icon">!</span>
      <span class="refuse-text">{{ text }}</span>
    </div>
    <div v-if="stage === 'threshold'" class="refuse-hint">未在知识库中找到足够相关的内容</div>
    <div class="refuse-foot">未调用生成模型</div>
    <div v-if="retrieved.length" class="refuse-retrieved">
      <div class="refuse-toggle" @click="showRetrieved = !showRetrieved">
        查看检索到的相关内容（未采用）{{ showRetrieved ? '▲' : '▼' }}
      </div>
      <div v-if="showRetrieved" class="refuse-list">
        <div v-for="item in retrieved" :key="item.chunk_id" class="refuse-item">
          <span class="r-idx">{{ item.idx }}</span>
          <span class="r-title">{{ item.doc_title }}</span>
          <span class="r-unused">未采用</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  text: { type: String, default: '知识库中未找到相关依据。建议咨询学校相关部门获取准确信息。' },
  stage: { type: String, default: '' },
  retrieved: { type: Array, default: () => [] },
})

const showRetrieved = ref(false)
</script>

<style scoped>
.refuse-notice {
  background: var(--c-warn-bg);
  border: 1px solid var(--c-warn-border);
  border-left: 3px solid var(--c-warn);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
}
.refuse-main {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
}
.refuse-icon {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--c-warn);
  color: var(--c-white);
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.refuse-text {
  font-size: 14px;
  line-height: 1.6;
  color: var(--c-text-2);
}
.refuse-hint {
  margin-top: var(--sp-1);
  margin-left: 26px;
  font-size: 12px;
  color: var(--c-text-3);
}
.refuse-foot {
  margin-top: var(--sp-2);
  margin-left: 26px;
  font-size: 11px;
  color: var(--c-text-4);
  font-variant-numeric: tabular-nums;
}
.refuse-retrieved {
  margin-top: var(--sp-3);
  border-top: 1px solid var(--c-warn-border);
  padding-top: var(--sp-2);
}
.refuse-toggle {
  font-size: 12px;
  color: var(--c-text-3);
  cursor: pointer;
}
.refuse-toggle:hover {
  color: var(--c-primary);
}
.refuse-list {
  margin-top: var(--sp-2);
  opacity: 0.75;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.refuse-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 12px;
  padding: var(--sp-1) var(--sp-2);
  background: var(--c-bg-card);
  border-radius: var(--r-sm);
}
.r-idx {
  width: 16px;
  height: 16px;
  border-radius: var(--r-sm);
  background: var(--c-warn);
  color: var(--c-white);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.r-title {
  flex: 1;
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.r-unused {
  color: var(--c-text-4);
  font-size: 11px;
  flex-shrink: 0;
}
</style>
