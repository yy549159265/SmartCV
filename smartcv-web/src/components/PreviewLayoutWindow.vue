<script setup lang="ts">
/**
 * 布局窗口的"只读渲染版"（递归组件，右侧预览 / 隐藏测量层共用）
 *
 * 叶子窗口：渲染内容列表；容器窗口：递归渲染子窗口。
 * 只做展示，高度与 A4 成品一致（测量层靠它算分页）。
 */
import { computed, type CSSProperties } from 'vue'
import PreviewContent from './PreviewContent.vue'
import { computeTableCols, spanForIndex } from '@/utils/layout'
import type { Section, LayoutWindow } from '@/types'

const props = defineProps<{
  section: Section
  row: LayoutWindow
  /** 父级"纵向堆叠"列表算出的全局列数（表格行对齐用）；不传则自己算 */
  tableCols?: number
}>()

/** 是否为容器窗口（有 rows 字段就算，即使还是空的） */
const isContainer = (row: LayoutWindow) => Array.isArray(row.rows)

/** 本窗口所在"纵向堆叠"里的全局列数（横向容器用来均分格子宽度，与画布一致） */
const cols = computed(() => props.tableCols ?? computeTableCols(props.row.rows ?? []))

/** 横向容器里第 index 个子窗口占几列 */
function childGridStyle(index: number): CSSProperties | undefined {
  if (props.row.layout !== 'horizontal') return undefined
  return { gridColumn: `span ${spanForIndex(index, props.row.rows?.length ?? 0, cols.value)}` }
}
</script>

<template>
  <div class="preview-row" :data-row-id="row.id">
    <!-- 容器窗口：子窗口按方向排列（横向容器用网格均分列数，与编辑画布一致） -->
    <div
      v-if="isContainer(row)"
      class="row-children"
      :class="row.layout === 'horizontal' ? 'children-h' : 'children-v'"
      :style="row.layout === 'horizontal' ? { '--cols': cols } : undefined"
    >
      <PreviewLayoutWindow
        v-for="(child, i) in row.rows"
        :key="child.id"
        :section="section"
        :row="child"
        :table-cols="cols"
        :style="childGridStyle(i)"
      />
    </div>

    <!-- 叶子窗口：内容 -->
    <div
      v-else
      class="row-body"
      :class="row.layout === 'horizontal' ? 'row-h' : 'row-v'"
    >
      <PreviewContent
        v-for="b in row.contents"
        :key="b.id"
        :section="section"
        :row="row"
        :content="b"
        :data-content-id="b.id"
      />
    </div>
  </div>
</template>

<style scoped>
.preview-row {
  min-width: 0;
}

/* 子窗口排列 */
.row-children {
  display: flex;
}
.children-v {
  flex-direction: column;
  gap: 10px;
}
/* 横向容器：网格均分全局列数（与画布一致），保持文档式间距、不画边框 */
.children-h {
  display: grid;
  grid-template-columns: repeat(var(--cols, 1), minmax(0, 1fr));
  gap: 10px;
  align-items: flex-start;
}
.children-h > .preview-row {
  min-width: 0;
}

/* 叶子窗口内的内容排列 */
.row-body {
  display: flex;
}
.row-v {
  flex-direction: column;
}
.row-h {
  flex-direction: row;
  align-items: flex-start;
  flex-wrap: wrap;
}
.row-h > :deep(.preview-content) {
  flex: 1 1 0;
}
/* 开了紧贴的内容：横向窗口里不再被拉伸成均分宽度，按内容宽排列，
   这样排在它后面的组件才能真的挨着它的内容（而不只是去掉 12px 间距） */
.row-h > :deep(.preview-content.tight) {
  flex: 0 1 auto;
}
.row-body > :deep(.preview-content:last-child) {
  margin-right: 0;
  margin-bottom: 0;
}
</style>
