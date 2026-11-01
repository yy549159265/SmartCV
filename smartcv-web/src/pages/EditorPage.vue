<script setup lang="ts">
/**
 * 页面 1 · 编辑简历：顶部工具栏 + 两栏布局（宽度可拖动调整）
 *   左：组件库（ComponentLibrary，横向面板）+ 编辑画布（EditCanvas）
 *   右：实时预览（ResumePreview）
 *
 * 顶部工具栏：简历名字、撤销/重做、预览缩放、纸面宽度。
 * 列宽：两栏之间有一条分隔条（ColumnDivider），按住左右拖动改变列宽；
 * 双击恢复默认，宽度用 VueUse 的 useStorage 记忆在浏览器本地。
 * 两栏读写的是同一个 Pinia store（stores/resume.ts）—— 单一数据源。
 */
import { computed, ref, watchEffect } from 'vue'
import { useStorage, useWindowSize } from '@vueuse/core'
import ComponentLibrary from '@/components/ComponentLibrary.vue'
import EditCanvas from '@/components/EditCanvas.vue'
import ResumePreview from '@/components/ResumePreview.vue'
import ColumnDivider from '@/components/ColumnDivider.vue'
import IconGlyph from '@/components/IconGlyph.vue'
import { previewZoom, ZOOM_LEVELS } from '@/composables/usePreviewZoom'
import {
  PAGE_WIDTH_MAX,
  PAGE_WIDTH_MIN,
  PAGE_WIDTH_PRESETS,
  pageHeight,
  pageWidth,
} from '@/composables/usePageSize'
import { resumeName } from '@/composables/useResumeName'
import { useResumeStore } from '@/stores/resume'

const store = useResumeStore()

/* ---------- 左列宽度（useStorage：自动记忆到 localStorage） ---------- */

const DEFAULTS = { editor: 640 }
const LIMITS = { editor: { min: 440, max: 1200 } }

const editorWidth = useStorage('smartcv-layout-editor', DEFAULTS.editor)

/** 把宽度变化限制在合理范围内 */
function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function onResizeEditor(dx: number) {
  editorWidth.value = clamp(editorWidth.value + dx, LIMITS.editor.min, LIMITS.editor.max)
}
function onResetEditor() {
  editorWidth.value = DEFAULTS.editor
}

/* ---------- 窗口变窄时自动收缩编辑列（只缩不放，用户拖过的宽度永远优先） ---------- */

const { width: viewportWidth } = useWindowSize()

watchEffect(() => {
  // 给预览至少留 480px；窗口更窄时按最小编辑列宽处理
  const max = viewportWidth.value - 480
  if (max < editorWidth.value) {
    editorWidth.value = Math.max(LIMITS.editor.min, max)
  }
})

/** 两栏布局样式：左列固定宽度，预览弹性占满剩余空间 */
const mainStyle = computed(() => ({
  gridTemplateColumns: `${editorWidth.value}px 8px minmax(0, 1fr)`,
}))

/* ---------- 顶部工具栏 ---------- */

/** 撤销/重做是否可用（看两个历史栈） */
const canUndo = computed(() => store.undoStack.length > 0)
const canRedo = computed(() => store.redoStack.length > 0)

/** 纸面宽度弹层是否展开 */
const widthMenuShow = ref(false)
</script>

<template>
  <main class="editor-page">
    <!-- 顶部工具栏：简历名字 + 撤销/重做 + 预览缩放 + 纸面宽度 -->
    <header class="editor-toolbar">
      <div class="editor-name-box">
        <span class="editor-name-label">简历名字：</span>
        <input v-model="resumeName" class="editor-name" placeholder="给简历起个名字" title="简历名字：导出的 PDF / JSON 文件会以这个名字命名" />
      </div>

      <span class="editor-toolbar-spacer" />

      <div class="editor-history">
        <button class="editor-tool-btn" :disabled="!canUndo" title="撤销（Ctrl+Z）" @click="store.undo()">
          <IconGlyph name="undo-2" :size="14" />
        </button>
        <button class="editor-tool-btn" :disabled="!canRedo" title="重做（Ctrl+Shift+Z）" @click="store.redo()">
          <IconGlyph name="redo-2" :size="14" />
        </button>
      </div>

      <span class="editor-toolbar-divider" />

      <!-- 预览缩放（与诊断页共用 previewZoom，两边始终一致） -->
      <div class="editor-zoom">
        <button
          v-for="z in ZOOM_LEVELS"
          :key="z"
          class="editor-zoom-btn"
          :class="{ active: previewZoom === z }"
          @click="previewZoom = z"
        >
          {{ Math.round(z * 100) }}%
        </button>
      </div>

      <span class="editor-toolbar-divider" />

      <!-- 纸面宽度：简历成品的页面宽度（快捷档 + 滑块），预览与导出 PDF 同步生效 -->
      <n-popover v-model:show="widthMenuShow" trigger="click" placement="bottom-end" :width="272">
        <template #trigger>
          <button
            type="button"
            class="editor-width-btn"
            :class="{ open: widthMenuShow }"
            :aria-expanded="widthMenuShow"
            title="纸面宽度：预览与导出 PDF 的页面宽度"
          >
            <IconGlyph name="scan-line" :size="13" />
            <span class="editor-width-text">纸面 {{ pageWidth }}×{{ pageHeight }}</span>
            <IconGlyph name="chevron-down" :size="12" />
          </button>
        </template>
        <div class="width-menu">
          <div class="width-menu-label">纸面宽度：预览与导出 PDF 同步生效</div>
          <div class="width-presets">
            <button
              v-for="p in PAGE_WIDTH_PRESETS"
              :key="p.value"
              type="button"
              class="width-preset"
              :class="{ active: pageWidth === p.value }"
              @click="pageWidth = p.value"
            >
              <span class="width-preset-name">{{ p.label }}</span>
              <span class="width-preset-value">{{ p.size }}</span>
            </button>
          </div>
          <div class="width-slider-row">
            <n-slider
              v-model:value="pageWidth"
              class="width-slider"
              :min="PAGE_WIDTH_MIN"
              :max="PAGE_WIDTH_MAX"
              :step="10"
              :tooltip="false"
            />
            <span class="width-slider-value">{{ pageWidth }}×{{ pageHeight }}</span>
          </div>
        </div>
      </n-popover>
    </header>

    <!-- 两栏：左（组件库 + 画布）｜ 分隔条 ｜ 右（实时预览） -->
    <div class="editor-columns" :style="mainStyle">
      <div class="editor-left">
        <ComponentLibrary />
        <EditCanvas />
      </div>
      <ColumnDivider @resize="onResizeEditor" @reset="onResetEditor" />
      <ResumePreview />
    </div>
  </main>
</template>

<style scoped>
.editor-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* ============================================================
 * 顶部工具栏
 * ============================================================ */
.editor-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 44px;
  padding: 0 14px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
}

/* 简历名字：固定标签 + 输入框，空的时候也不会显得"空白一块" */
.editor-name-box {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.editor-name-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
}
.editor-name {
  width: 170px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  padding: 4px 8px;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease);
}
.editor-name:hover {
  background: var(--surface-soft);
}
.editor-name:focus {
  border-color: var(--primary);
  background: var(--panel-bg);
  outline: none;
  box-shadow: 0 0 0 2px rgba(71, 83, 199, 0.12);
}

.editor-toolbar-spacer {
  flex: 1;
}

.editor-history {
  display: flex;
  gap: 4px;
}
.editor-tool-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    border-color 0.14s var(--ease),
    color 0.14s var(--ease);
}
.editor-tool-btn:hover:not(:disabled) {
  background: var(--surface-soft);
  border-color: var(--border);
  color: var(--text);
}
.editor-tool-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.editor-toolbar-divider {
  flex: none;
  width: 1px;
  height: 18px;
  background: var(--border);
}

.editor-zoom {
  display: flex;
  gap: 2px;
  flex: none;
  padding: 2px;
  border-radius: 8px;
  background: var(--surface-soft);
}
.editor-zoom-btn {
  height: 24px;
  padding: 0 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.editor-zoom-btn:hover {
  color: var(--text);
}
.editor-zoom-btn.active {
  background: var(--panel-bg);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.08);
}

/* ---- 纸面宽度：触发按钮 ---- */
.editor-width-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  height: 24px;
  padding: 0 9px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.editor-width-btn:hover,
.editor-width-btn.open {
  background: var(--surface-soft);
  color: var(--text);
}
.editor-width-btn :deep(.icon-glyph) {
  color: var(--text-tertiary);
}
.editor-width-btn:hover :deep(.icon-glyph),
.editor-width-btn.open :deep(.icon-glyph) {
  color: var(--text-secondary);
}

/* ---- 纸面宽度：弹层 ---- */
.width-menu {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.width-menu-label {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.width-presets {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.width-preset {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 7px 0 6px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-bg);
  cursor: pointer;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease);
}
.width-preset:hover {
  border-color: var(--primary);
}
.width-preset.active {
  border-color: var(--primary);
  background: var(--primary-faint);
}
.width-preset-name {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text);
}
.width-preset-value {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text-tertiary);
}
.width-preset.active .width-preset-name,
.width-preset.active .width-preset-value {
  color: var(--primary);
}
.width-slider-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.width-slider {
  flex: 1;
  min-width: 0;
}
.width-slider-value {
  flex: none;
  width: 76px;
  text-align: right;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}

/* ============================================================
 * 两栏布局
 * ============================================================ */
.editor-columns {
  flex: 1;
  min-height: 0;
  display: grid;
  /* 列：编辑区 | 分隔条 | 预览 —— 宽度由 JS 控制 */
  grid-template-columns: 640px 8px minmax(0, 1fr);
}
.editor-columns > * {
  min-width: 0;
  min-height: 0;
}

/* 左列：组件库在上、画布在下 */
.editor-left {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-right: 1px solid var(--border);
}

/* 窄屏：工具栏压缩名称宽度 */
@media (max-width: 760px) {
  .editor-name {
    width: 100px;
  }
}
</style>
