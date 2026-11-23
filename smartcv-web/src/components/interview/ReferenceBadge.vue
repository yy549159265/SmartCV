<script setup lang="ts">
/**
 * 引用角标：贴在字段右上角，点击在右侧简历原文里定位并高亮。
 * 多条引用只显示一个角标，数量标在图标后面。
 */

import type { Coord } from '@/api/interview'
import IconGlyph from '@/components/IconGlyph.vue'

const props = defineProps<{ coords: Coord[] }>()

const emit = defineEmits<{ open: [coords: Coord[]] }>()

function label(): string {
  return props.coords.length > 1
    ? `在简历原文中查看 ${props.coords.length} 处引用`
    : '在简历原文中查看'
}
</script>

<template>
  <button
    class="ref-badge"
    type="button"
    :title="label()"
    :aria-label="label()"
    draggable="false"
    @click.stop="emit('open', coords)"
    @pointerdown.stop
  >
    <IconGlyph name="target" :size="11" />
    <span v-if="coords.length > 1" class="ref-badge-count">{{ coords.length }}</span>
  </button>
</template>

<style scoped>
.ref-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-width: 19px;
  height: 19px;
  padding: 0 4px;
  border: 1px solid var(--panel-bg);
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(23, 29, 43, 0.2);
  transition:
    background-color var(--dur-2) var(--ease),
    transform var(--dur-2) var(--ease);
}
.ref-badge:hover {
  background: var(--primary-strong, var(--primary));
  transform: scale(1.08);
}
.ref-badge:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
.ref-badge-count {
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
</style>
