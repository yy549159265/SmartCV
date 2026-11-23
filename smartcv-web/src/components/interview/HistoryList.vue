<script setup lang="ts">
/** 左侧栏的最近面试：进行中的一场置顶，再列最近的对话与清单记录。 */

import type { SessionRecord } from '@/utils/interviewDb'
import { SCENE_LABEL, formatDateTime } from '@/utils/interview'
import IconGlyph from '@/components/IconGlyph.vue'

defineProps<{
  items: SessionRecord[]
  currentId?: string
  disabled?: boolean
}>()

const emit = defineEmits<{ open: [threadId: string] }>()

function title(item: SessionRecord): string {
  if (item.projectNames.length) return item.projectNames.join('、')
  return SCENE_LABEL[item.scene] ?? '面试'
}

function modeLabel(item: SessionRecord): string {
  return item.useMode === 'checklist' ? '清单' : '对话'
}

function subtitle(item: SessionRecord): string {
  const scene = SCENE_LABEL[item.scene] ?? ''
  if (item.status === 'active') {
    return `${scene} · 第 ${item.currentIndex || 1} 题`
  }
  const count = item.useMode === 'checklist' ? item.checklistCards?.length : 0
  const detail = count ? `${count} 道题 · ` : ''
  return `${scene} · ${detail}${formatDateTime(item.endedAt || item.startedAt)}`
}
</script>

<template>
  <section class="history">
    <h3 class="history-title">
      <IconGlyph name="history" :size="14" />
      最近面试
    </h3>
    <p v-if="!items.length" class="history-empty">
      还没有面试记录。完成一场对话面试或生成清单后，这里会保留最近 5 场记录。
    </p>
    <ul v-else class="history-list">
      <li v-for="item in items" :key="item.threadId">
        <button
          type="button"
          class="history-item"
          :class="{ current: item.threadId === currentId, active: item.status === 'active' }"
          :disabled="disabled"
          @click="emit('open', item.threadId)"
        >
          <span class="item-top">
            <span class="item-title">{{ title(item) }}</span>
            <span class="item-badge">{{ modeLabel(item) }}</span>
            <span v-if="item.status === 'active'" class="item-badge item-live">进行中</span>
            <span v-else class="item-badge">已结束</span>
          </span>
          <span class="item-sub">{{ subtitle(item) }}</span>
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.history {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
.history-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 10px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--text-tertiary);
}
.history-empty {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-tertiary);
}
.history-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.history-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    border-color 0.16s var(--ease);
}
.history-item:hover:not(:disabled) {
  background: var(--panel-bg);
  border-color: var(--border);
}
.history-item.current {
  background: var(--panel-bg);
  border-color: var(--border);
}
.history-item.active {
  background: var(--primary-faint);
  border-color: #d9ddf5;
}
.history-item:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.item-top {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.item-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--text);
  word-break: break-word;
}
.item-badge {
  flex: none;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 11.5px;
  line-height: 17px;
  white-space: nowrap;
}
.item-live {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.item-sub {
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-tertiary);
  word-break: break-word;
}
</style>
