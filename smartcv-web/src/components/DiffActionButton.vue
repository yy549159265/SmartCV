<script setup lang="ts">
import { computed } from 'vue'
import IconGlyph from './IconGlyph.vue'
import type { ChangeView } from '@/utils/resumeDiff'

const props = defineProps<{ view: ChangeView }>()

const icon = computed(() => (props.view.reverted ? '↻' : '↺'))

const tooltip = computed(() =>
  props.view.reverted ? '恢复 AI 修改（↻）' : '还原为修改前的内容（↺）',
)
</script>

<template>
  <span class="diff-actions">
    <button
      v-if="view.jumpToDiagnosis"
      type="button"
      class="diff-action diff-action-jump"
      title="查看这条诊断"
      aria-label="查看这条诊断"
      @click.stop="view.jumpToDiagnosis()"
      @mousedown.stop
    >
      <IconGlyph name="file-text" :size="11" :stroke-width="2.2" />
    </button>
    <button
      type="button"
      class="diff-action"
      :class="{ reverted: view.reverted }"
      :title="tooltip"
      :aria-label="tooltip"
      @click.stop="view.toggle()"
      @mousedown.stop
    >
      {{ icon }}
    </button>
  </span>
</template>

<style scoped>
.diff-actions {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transform: translateX(calc(-100% + 20px));
}

.diff-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 1.5px solid currentColor;
  border-radius: 50%;
  background: var(--panel-bg, #fff);
  color: var(--diff-color, #a6763f);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  user-select: none;
  box-shadow:
    0 1px 2px rgba(28, 33, 48, 0.12),
    0 4px 10px -6px rgba(28, 33, 48, 0.28);
  transition:
    transform 0.16s var(--ease),
    background-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.diff-action.reverted {
  border-style: dashed;
  background: var(--diff-bg, rgba(0, 0, 0, 0.04));
}
.diff-action:hover {
  transform: scale(1.12);
  background: var(--panel-bg, #fff);
  box-shadow:
    0 1px 2px rgba(28, 33, 48, 0.12),
    0 6px 14px -6px rgba(28, 33, 48, 0.32);
}
.diff-action:active {
  transform: scale(0.94);
}

.diff-action-jump {
  color: var(--primary, #4753c7);
  border-width: 1px;
  font-weight: 400;
}
.diff-action-jump:hover {
  background: var(--primary-soft, #eceffb);
  color: var(--primary-hover, #3c46b2);
}
</style>
