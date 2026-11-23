<script setup lang="ts">
import type { PlanGroup } from '@/types/market'

defineProps<{
  group: PlanGroup | null
  running: boolean
  highlightKey: string
}>()
</script>

<template>
  <div class="plan-list glass-surface">
    <Transition name="mod-swap" mode="out-in">
      <div v-if="group" :key="group.kind" class="plan-group">
        <div class="plan-list-head">
          <span class="qgroup-badge" :class="group.source">
            {{ group.source === 'ai' ? '关键词' : '默认检索' }}
          </span>
          <span class="plan-count">{{ group.queries.length }} 条</span>
        </div>
        <div class="qgroup-body">
          <div
            v-for="item in group.queries"
            :key="`q${item.index}`"
            class="qrow glass-item"
            :class="{ hl: highlightKey === `q${item.index}` }"
          >
            <span class="idx">{{ item.index }}</span>
            <span class="q">{{ item.q }}</span>
          </div>
        </div>
        <div v-if="running" class="plan-caret">生成中</div>
      </div>
      <div v-else key="plan-empty" class="pane-empty">
        规划检索完成后，这里会按调研维度列出本次的检索词。
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.plan-list {
  margin-top: 2px;
  padding: 10px 11px 12px;
}
.plan-group {
  display: flex;
  flex-direction: column;
}
.plan-list-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 7px;
  padding: 0 2px;
}
.plan-count {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.qgroup-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.qgroup-badge {
  flex: none;
  font-size: 11px;
  line-height: 16px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--primary-faint);
  color: var(--primary);
}
.qgroup-badge.fallback {
  background: var(--surface);
  color: var(--text-3);
}
.qrow {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 8px;
  font-size: 12.5px;
  color: var(--text-2);
}
.qrow .idx {
  flex: none;
  width: 16px;
  font-size: 11.5px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.qrow .q {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qrow .site {
  flex: none;
  font-size: 11.5px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--surface);
  color: var(--text-3);
}
.plan-caret {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 12.5px;
}
.plan-caret::after {
  content: '';
  width: 6px;
  height: 12px;
  background: var(--primary);
  opacity: 0.6;
  animation: caret 0.9s step-end infinite;
}
@keyframes caret {
  50% {
    opacity: 0;
  }
}
</style>

<style scoped src="./pane-shared.css"></style>
