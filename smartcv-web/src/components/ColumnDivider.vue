<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  resize: [deltaX: number]
  resizeEnd: []
  reset: []
}>()

const dragging = ref(false)
let lastX = 0

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  lastX = e.clientX
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  const dx = e.clientX - lastX
  if (dx !== 0) {
    lastX = e.clientX
    emit('resize', dx)
  }
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value) return
  dragging.value = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  emit('resizeEnd')
}
</script>

<template>
  <div
    class="column-divider"
    :class="{ dragging }"
    title="拖动调整列宽，双击恢复默认"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @dblclick="emit('reset')"
  >
    <span class="divider-grip" />
  </div>
</template>

<style scoped>
.column-divider {
  flex: none;
  width: 8px;
  cursor: col-resize;
  position: relative;
  z-index: 8;
  display: flex;
  align-items: center;
  justify-content: center;
  touch-action: none;
}
.column-divider::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  transform: translateX(-50%);
  background: var(--border);
  transition: width 0.12s, background 0.12s;
}
.column-divider:hover::before,
.column-divider.dragging::before {
  width: 3px;
  background: var(--primary);
}
.divider-grip {
  width: 3px;
  height: 42px;
  border-radius: 999px;
  background: var(--primary);
  opacity: 0;
  transition: opacity 0.14s var(--ease);
  pointer-events: none;
}
.column-divider:hover .divider-grip,
.column-divider.dragging .divider-grip {
  opacity: 0.5;
}
.column-divider.dragging .divider-grip {
  opacity: 1;
}
</style>
