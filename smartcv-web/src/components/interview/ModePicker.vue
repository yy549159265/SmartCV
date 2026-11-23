<script setup lang="ts">
/**
 * 第 4 步：选择对话面试或清单自测。
 * 两种方式都复用第 3 步的问题包；对话面试建场，清单自测直接展开同一套题。
 */

import { computed } from 'vue'

import type { UseMode } from '@/api/interview'
import IconGlyph from '@/components/IconGlyph.vue'

const props = defineProps<{
  useMode: UseMode
  starting?: boolean
  hasThread?: boolean
  finished?: boolean
}>()

const emit = defineEmits<{
  back: []
  select: [mode: UseMode]
  start: []
}>()

const MODES: { key: UseMode; title: string; icon: 'compass' | 'book-open'; summary: string }[] = [
  {
    key: 'dialog',
    title: '对话面试',
    icon: 'compass',
    summary: '逐题作答，即时反馈与追问，可请 AI 讲解',
  },
  {
    key: 'checklist',
    title: '清单自测',
    icon: 'book-open',
    summary: '一次展开全部题目与参考答案，不逐题反馈',
  },
]

const startLabel = computed(() => {
  if (props.hasThread) return props.finished ? '查看面试复盘' : '继续面试'
  return props.useMode === 'checklist' ? '开始清单自测' : '开始面试'
})

const startingLabel = computed(() =>
  props.useMode === 'checklist' ? '正在准备清单…' : '正在创建面试…',
)
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <h2 class="panel-title">选择面试方式</h2>
    </header>

    <p v-if="hasThread" class="thread-state">这场面试已经开始。</p>

    <div v-else class="mode-grid">
      <button
        v-for="mode in MODES"
        :key="mode.key"
        type="button"
        class="mode-item"
        :class="{ on: useMode === mode.key }"
        :disabled="starting"
        @click="emit('select', mode.key)"
      >
        <span class="mode-icon">
          <IconGlyph :name="mode.icon" :size="19" />
        </span>
        <span class="mode-copy">
          <span class="mode-title">{{ mode.title }}</span>
          <span class="mode-desc">{{ mode.summary }}</span>
        </span>
        <span class="mode-check" :class="{ on: useMode === mode.key }">
          <IconGlyph v-if="useMode === mode.key" name="check" :size="12" />
        </span>
      </button>
    </div>

    <footer class="panel-foot">
      <button class="btn ghost" type="button" :disabled="starting" @click="emit('back')">
        <IconGlyph name="chevron-left" :size="15" />
        上一步
      </button>
      <button class="btn primary" type="button" :disabled="starting" @click="emit('start')">
        <span v-if="starting" class="spinner" aria-hidden="true"></span>
        <template v-else>
          {{ startLabel }}
          <IconGlyph name="arrow-right" :size="15" />
        </template>
        <template v-if="starting">{{ startingLabel }}</template>
      </button>
    </footer>
  </section>
</template>

<style scoped>
.panel {
  padding: 26px 30px 30px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-paper);
}
.panel-title {
  margin: 0 0 18px;
  font-size: 19px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.thread-state {
  margin: 0;
  padding: 18px 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-soft);
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-secondary);
}

.mode-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.mode-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.mode-item:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
}
.mode-item.on {
  border-color: var(--primary);
  background: var(--primary-faint);
  box-shadow: 0 0 0 1px var(--primary);
}
.mode-item:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}
.mode-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 9px;
  background: var(--primary-soft);
  color: var(--primary);
}
.mode-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mode-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.mode-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  word-break: break-word;
}
.mode-check {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-top: 2px;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: var(--panel-bg);
  color: #fff;
}
.mode-check.on {
  border-color: var(--primary);
  background: var(--primary);
}

.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 760px) {
  .panel {
    padding: 20px 18px 24px;
  }
  .mode-grid {
    grid-template-columns: 1fr;
  }
  .panel-foot {
    flex-direction: column-reverse;
    align-items: stretch;
  }
  .btn {
    justify-content: center;
  }
}
</style>
