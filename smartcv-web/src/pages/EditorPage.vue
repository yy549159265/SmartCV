<script setup lang="ts">
/**
 * 页面 1 · 编辑简历：三栏布局（宽度可拖动调整）
 *   左：组件库（ComponentLibrary） ｜ 中：编辑画布（EditCanvas） ｜ 右：实时预览（ResumePreview）
 *
 * 列宽调整：两列之间各有一条分隔条（ColumnDivider），按住左右拖动即可改变列宽；
 * 双击分隔条恢复默认。列宽用 VueUse 的 useStorage 记忆在浏览器本地。
 * 三栏读写的是同一个 Pinia store（stores/resume.ts）—— 单一数据源。
 */
import { computed } from 'vue'
import { useStorage } from '@vueuse/core'
import ComponentLibrary from '@/components/ComponentLibrary.vue'
import EditCanvas from '@/components/EditCanvas.vue'
import ResumePreview from '@/components/ResumePreview.vue'
import ColumnDivider from '@/components/ColumnDivider.vue'

/* ---------- 三栏列宽（useStorage：自动记忆到 localStorage） ---------- */

/** 各列的默认宽度（px） */
const DEFAULTS = { library: 268, preview: 872 }
/** 各列的宽度范围（px） */
const LIMITS = { library: { min: 200, max: 460 }, preview: { min: 500, max: 1100 } }

const libraryWidth = useStorage('smartcv-layout-library', DEFAULTS.library)
const previewWidth = useStorage('smartcv-layout-preview', DEFAULTS.preview)

/** 把宽度变化限制在合理范围内 */
function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function onResizeLibrary(dx: number) {
  libraryWidth.value = clamp(libraryWidth.value + dx, LIMITS.library.min, LIMITS.library.max)
}
function onResizePreview(dx: number) {
  // 预览在右边：向右拖 = 变窄
  previewWidth.value = clamp(previewWidth.value - dx, LIMITS.preview.min, LIMITS.preview.max)
}
function onResetLibrary() {
  libraryWidth.value = DEFAULTS.library
}
function onResetPreview() {
  previewWidth.value = DEFAULTS.preview
}

/** 三栏布局样式：左右两列固定宽度，中间弹性占满剩余空间 */
const mainStyle = computed(() => ({
  gridTemplateColumns: `${libraryWidth.value}px 8px minmax(0, 1fr) 8px ${previewWidth.value}px`,
}))
</script>

<template>
  <main class="app-main" :style="mainStyle">
    <ComponentLibrary />
    <ColumnDivider @resize="onResizeLibrary" @reset="onResetLibrary" />
    <EditCanvas />
    <ColumnDivider @resize="onResizePreview" @reset="onResetPreview" />
    <ResumePreview />
  </main>
</template>

<style scoped>
.app-main {
  flex: 1;
  min-height: 0;
  display: grid;
  /* 列：组件库 | 分隔条 | 画布(弹性) | 分隔条 | 预览 —— 宽度由 JS 控制 */
  grid-template-columns: 268px 8px minmax(0, 1fr) 8px 872px;
}
.app-main > * {
  min-width: 0;
  min-height: 0;
}
</style>
