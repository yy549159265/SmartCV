<script setup lang="ts">
import { computed, type CSSProperties } from 'vue'
import PreviewContent from './PreviewContent.vue'
import DiffActionButton from './DiffActionButton.vue'
import { computeTableCols, spanForIndex } from '@/utils/layout'
import { diffAttr as resolveDiffAttr, type DiffControls, type DiffMarks } from '@/utils/resumeDiff'
import type { Section, LayoutWindow } from '@/types'

const props = defineProps<{
  section: Section
  row: LayoutWindow
  tableCols?: number
  marks?: DiffMarks
  controls?: DiffControls
  unitDiffs?: Record<string, Record<number, string>>
}>()

const isContainer = (row: LayoutWindow) => Array.isArray(row.rows)

const cols = computed(() => props.tableCols ?? computeTableCols(props.row.rows ?? []))

function childGridStyle(index: number): CSSProperties | undefined {
  if (props.row.layout !== 'horizontal') return undefined
  return { gridColumn: `span ${spanForIndex(index, props.row.rows?.length ?? 0, cols.value)}` }
}

const rowMark = computed(() => props.marks?.rows[props.row.id])

const rowView = computed(() => props.controls?.rows[props.row.id])

const rowAttr = computed(() => resolveDiffAttr(rowMark.value, rowView.value))

const contentMark = (id: string) => props.marks?.contents[id]

const contentView = (id: string) => props.controls?.contents[id]

const unitMarks = (id: string) => props.marks?.units[id]
const unitViews = (id: string) => props.controls?.units[id]

const unitDiffsOf = (id: string) => props.unitDiffs?.[id]
</script>

<template>
  <div
    class="preview-row"
    :class="{ 'diff-action-host': !!rowView }"
    :data-row-id="row.id"
    :data-diff="rowAttr"
    :data-diff-key="rowView ? `row:${row.id}` : undefined"
  >
    <DiffActionButton v-if="rowView" class="diff-action-float" :view="rowView" />

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
        :marks="marks"
        :controls="controls"
        :unit-diffs="unitDiffs"
        :style="childGridStyle(i)"
      />
    </div>

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
        :diff-mark="contentMark(b.id)"
        :diff-view="contentView(b.id)"
        :diff-units="unitMarks(b.id)"
        :diff-unit-views="unitViews(b.id)"
        :unit-diffs="unitDiffsOf(b.id)"
        :data-content-id="b.id"
      />
    </div>
  </div>
</template>

<style scoped>
.preview-row {
  min-width: 0;
}

.diff-action-host {
  position: relative;
}
.diff-action-float {
  position: absolute;
  top: -2px;
  left: -20px;
  z-index: 6;
}

.row-children {
  display: flex;
}
.children-v {
  flex-direction: column;
  gap: 6px;
}
.children-h {
  display: grid;
  grid-template-columns: repeat(var(--cols, 1), minmax(0, 1fr));
  gap: 10px;
  align-items: flex-start;
}
.children-h > .preview-row {
  min-width: 0;
}

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
.row-h > :deep(.preview-content.tight) {
  flex: 0 1 auto;
}
.row-body > :deep(.preview-content:last-child) {
  margin-right: 0;
  margin-bottom: 0;
}
</style>
