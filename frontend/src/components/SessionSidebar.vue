<template>
  <div class="sidebar" :class="{ open }">
    <div class="sidebar-head">
      <el-button class="new-btn" type="primary" @click="onCreate">＋ 新建会话</el-button>
    </div>
    <div class="sidebar-list">
      <div
        v-for="s in sessions"
        :key="s.session_id"
        class="session-item"
        :class="{ active: s.session_id === currentSessionId }"
        @click="onSelect(s.session_id)"
      >
        <div class="session-info">
          <div class="session-name">{{ s.title || '未命名会话' }}</div>
          <div class="session-time">{{ shortTime(s.updated_at) }}</div>
        </div>
        <span class="session-del" title="删除" @click.stop="confirmDelete(s)">✕</span>
      </div>
      <div v-if="!sessions.length" class="sidebar-empty">暂无会话</div>
    </div>
  </div>
</template>

<script setup>
import { ElMessageBox } from 'element-plus'

defineProps({
  sessions: { type: Array, default: () => [] },
  currentSessionId: { type: String, default: null },
  // 窄屏抽屉是否打开（桌面端忽略）
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'create', 'delete', 'close'])

// 选中会话后，窄屏要自动收起抽屉
function onSelect(id) {
  emit('select', id)
  emit('close')
}

function onCreate() {
  emit('create')
  emit('close')
}

function shortTime(iso) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 16)
}

async function confirmDelete(s) {
  try {
    await ElMessageBox.confirm(`删除会话「${s.title || '未命名会话'}」？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    emit('delete', s.session_id)
  } catch (e) {
    // 取消
  }
}
</script>

<style scoped>
.sidebar {
  width: 260px;
  flex-shrink: 0;
  height: 100%;
  border-right: 1px solid var(--c-border);
  display: flex;
  flex-direction: column;
  background: var(--c-bg-card);
}
.sidebar-head {
  padding: var(--sp-3);
  border-bottom: 1px solid var(--c-border);
}
.new-btn {
  width: 100%;
  height: 36px;
  border-radius: var(--r-md);
}
.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-2);
}
.session-item {
  position: relative;
  display: flex;
  align-items: center;
  height: 40px;
  padding: 0 var(--sp-3);
  border-radius: var(--r-md);
  cursor: pointer;
  margin: 2px var(--sp-2);
}
.session-item:hover {
  background: var(--c-bg-hover);
}
.session-item.active {
  background: var(--c-primary-light);
}
.session-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: var(--c-primary);
}
.session-info {
  flex: 1;
  min-width: 0;
}
.session-name {
  font-size: 14px;
  color: var(--c-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-item.active .session-name {
  color: var(--c-primary);
}
.session-time {
  font-size: 11px;
  color: var(--c-text-3);
  margin-top: 2px;
}
.session-del {
  display: none;
  color: var(--c-danger);
  font-size: 14px;
  line-height: 1;
  padding: 4px;
  flex-shrink: 0;
}
.session-item:hover .session-del {
  display: inline;
}
.session-del:hover {
  opacity: 0.7;
}
.sidebar-empty {
  text-align: center;
  color: var(--c-text-3);
  font-size: 13px;
  padding: 20px 0;
}

/* ── 窄屏：侧栏改为抽屉（桌面端不受影响）──────────────── */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 1000;
    width: min(280px, 82vw);
    height: 100%;
    transform: translateX(-100%);
    transition: transform 0.22s ease;
    /* ★ 阴影只放在打开态：关闭时元素虽移出屏幕，阴影仍会从屏幕左侧
       漏出一条灰边（x 偏移 2px + 16px 模糊），在窄屏上很显眼。 */
  }

  .sidebar.open {
    transform: translateX(0);
    box-shadow: 2px 0 16px rgba(0, 0, 0, 0.12);
  }
}
</style>
