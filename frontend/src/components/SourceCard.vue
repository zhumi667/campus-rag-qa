<template>
  <div class="source-card" :class="{ expanded }" :data-idx="source.idx">
    <div class="source-card-head" @click="expanded = !expanded">
      <span class="source-idx">{{ source.idx }}</span>
      <span class="source-title">{{ source.doc_title }}</span>
      <!-- 版本文档（有 version 字段时展示），便于核对引用的是哪一版 -->
      <span v-if="source.version" class="source-ver">v{{ source.version }}</span>
      <span v-if="isDeprecated" class="source-dep">已失效</span>
      <span class="source-toggle">{{ expanded ? '收起 ▴' : '查看原文 ▾' }}</span>
    </div>
    <div class="source-detail" :class="{ open: expanded }">
      <div class="source-detail-inner">
        <div v-if="source.heading_path" class="source-heading">{{ source.heading_path }}</div>
        <div class="source-snippet">{{ source.snippet }}</div>
        <div class="source-foot">
          <span class="source-pos">原文位置 char {{ source.char_start }}-{{ source.char_end }}</span>
          <span v-if="source.effective_date" class="source-date">
            生效 {{ source.effective_date }}
          </span>
          <span v-if="source.is_truncated" class="source-trunc">片段已省略</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  source: { type: Object, required: true },
})

const expanded = ref(false)

/** status 非 active 视为已失效（正常情况下检索期已被过滤，此处作兜底提示） */
const isDeprecated = computed(() => {
  const s = props.source.status
  return !!s && s !== 'active'
})
</script>

<style scoped>
.source-card {
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: var(--c-primary-light);
  cursor: pointer;
  transition: border-color 0.15s;
}
.source-card.expanded {
  border-color: var(--c-primary-border);
}
.source-card:hover {
  border-color: var(--c-primary);
}
.source-card-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
}
.source-idx {
  width: 16px;
  height: 16px;
  border-radius: var(--r-sm);
  background: var(--c-primary);
  color: var(--c-white);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.source-title {
  font-size: 14px;
  color: var(--c-text-1);
  font-weight: 500;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-toggle {
  color: var(--c-primary);
  font-size: 12px;
  flex-shrink: 0;
}
/* 版本标记：有 version 字段时展示，便于核对引用的是哪一版 */
.source-ver {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--c-primary-dark);
  background: var(--c-bg-card);
  border: 1px solid var(--c-primary-border);
  border-radius: var(--r-sm);
  padding: 0 5px;
  line-height: 16px;
}
/* 失效标记：status 非 active 时的兜底提示（检索期通常已过滤） */
.source-dep {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--c-danger);
  background: var(--c-danger-bg);
  border-radius: var(--r-sm);
  padding: 0 5px;
  line-height: 16px;
}
.source-date {
  font-variant-numeric: tabular-nums;
}
.source-card:not(.expanded) .source-toggle {
  color: var(--c-text-3);
}
.source-detail {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.15s;
}
.source-detail.open {
  max-height: 1000px;
}
.source-detail-inner {
  padding: 0 var(--sp-3) var(--sp-3) var(--sp-5);
}
.source-heading {
  font-size: 12px;
  color: var(--c-text-3);
  margin-bottom: var(--sp-2);
  line-height: 1.6;
  word-break: break-all;
}
.source-snippet {
  font-size: 13px;
  color: var(--c-text-2);
  line-height: 1.85;
  /* 后端已移除被折行劈开的汉字间空白；保留换行以便并列条目各自成行 */
  white-space: pre-wrap;
  word-break: break-word;
  border-left: 2px solid var(--c-primary-border);
  padding-left: var(--sp-3);
}
.source-foot {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
  font-size: 12px;
  color: var(--c-text-4);
}
.source-pos {
  font-variant-numeric: tabular-nums;
}
.source-trunc {
  color: var(--c-text-3);
}
</style>
