<script setup lang="ts">
/**
 * 列分隔条：放在两列之间，按住左右拖动可以改变两侧列宽。
 *
 * 用法（在 App.vue 里）：
 *   <ColumnDivider @resize="(dx) => libraryWidth = clamp(libraryWidth + dx, ...)" @reset="..." />
 *
 * 实现要点：
 *  - pointerdown 时用 setPointerCapture 把后续 move/up 事件"钉"在本元素上，
 *    拖出元素范围也能继续收到事件，松手自然结束；
 *  - 拖动期间给 body 加 col-resize 光标 + 禁止选中文本，避免拖出选区；
 *  - 双击分隔条 = 恢复默认宽度（父组件处理 reset 事件）。
 */
import { ref } from 'vue'

const emit = defineEmits<{
  /** 拖动中：水平位移增量（px，向右为正） */
  resize: [deltaX: number]
  /** 拖动结束 */
  resizeEnd: []
  /** 双击：请求恢复默认宽度 */
  reset: []
}>()

const dragging = ref(false)
let lastX = 0

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  lastX = e.clientX
  // 把后续 pointermove/pointerup 都锁定到本元素
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
  touch-action: none; /* 触屏上也不让浏览器接管手势 */
}
/* 视觉分隔线：平时细灰线，悬停/拖动时变主题色 */
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
  border-radius: 2px;
  background: #c6ccd8;
  opacity: 0;
  transition: opacity 0.12s, background 0.12s;
  pointer-events: none;
}
.column-divider:hover .divider-grip,
.column-divider.dragging .divider-grip {
  opacity: 1;
  background: var(--primary);
}
</style>
